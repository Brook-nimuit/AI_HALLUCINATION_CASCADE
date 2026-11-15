import csv
import json
import tempfile
import unittest
from pathlib import Path

from experiments.prepare_visualization_data import (
    copy_artifacts,
    exclusion_reason,
    models_for_trial,
    prepare,
    prune_unplayed_trials,
    projected_budget,
    trial_row,
)


class PrepareVisualizationDataTests(unittest.TestCase):
    def test_copies_all_chess_replays_even_when_not_clean_or_run_scoped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "input"
            output_dir = Path(temp_dir) / "output"
            legacy_replay = input_dir / "replays" / "gpt-4o_trial_01"
            run_replay = (
                input_dir
                / "replays"
                / "gpt-4o_20261105T184046539972_trial_02"
            )
            legacy_replay.mkdir(parents=True)
            run_replay.mkdir(parents=True)
            (legacy_replay / "match_audit.json").write_text(
                '{"moves":[{"status":"ILLEGAL"}]}', encoding="utf-8"
            )
            (run_replay / "ply_01_white_e4.png").write_bytes(b"frame")
            (run_replay / "unfinished.tmp").write_text("temporary", encoding="utf-8")

            _, replay_dirs, skipped_temps = copy_artifacts(
                input_dir, output_dir, set()
            )

            self.assertEqual(replay_dirs, 2)
            self.assertEqual(skipped_temps, 1)
            self.assertTrue(
                (
                    output_dir
                    / "replays"
                    / "gpt-4o_trial_01"
                    / "match_audit.json"
                ).exists()
            )
            self.assertTrue(
                (
                    output_dir
                    / "replays"
                    / "gpt-4o_20261105T184046539972_trial_02"
                    / "ply_01_white_e4.png"
                ).exists()
            )
            self.assertFalse(
                (
                    output_dir
                    / "replays"
                    / "gpt-4o_20261105T184046539972_trial_02"
                    / "unfinished.tmp"
                ).exists()
            )

    def test_keeps_valid_turn_limited_trial(self):
        trial = {
            "trial_id": 1,
            "model": "gpt-4o",
            "turns_survived": 50,
            "match_log": {
                "game": "uno",
                "model": "gpt-4o",
                "provider": "openai",
                "max_turns": 50,
                "turns_survived": 50,
                "turns": [{"valid": True, "status": "VALID"}],
            },
        }

        self.assertEqual(exclusion_reason(trial), "")
        row = trial_row("uno", "test-run", trial, {"model": "gpt-4o"}, "run.json")
        self.assertEqual(row["completion"], "max_turns")
        self.assertEqual(row["outcome_for_model"], "self-play: censored at max turns")

    def test_omits_api_errors_before_play_and_keeps_illegal_attempts(self):
        api_error = {
            "failed": 1,
            "failure_reason": "API_ERROR: model unavailable",
            "match_log": {"turns": [{"valid": False, "status": "API_ERROR"}]},
        }
        invalid_move = {
            "failed": 1,
            "match_log": {"turns": [{"valid": False, "status": "INVALID"}]},
        }

        self.assertEqual(exclusion_reason(api_error), "No model moves recorded")
        self.assertEqual(exclusion_reason(invalid_move), "")

    def test_excludes_trials_without_recorded_turns(self):
        self.assertEqual(
            exclusion_reason({"match_log": {"turns": []}}),
            "No model moves recorded",
        )

    def test_prunes_only_no_gameplay_trials_and_their_audited_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            results = root / "results"
            results.mkdir()
            run = {
                "game": "chess",
                "run_id": "test-run",
                "configuration": {"white_model": "gpt-4o", "black_model": "random"},
                "trials": [
                    {
                        "trial_id": 1,
                        "failed": 1,
                        "failure_reason": "API_ERROR: invalid model",
                        "audit": {
                            "moves": [{"status": "API_ERROR", "raw_response": "API_ERROR"}]
                        },
                    },
                    {
                        "trial_id": 2,
                        "failed": 1,
                        "failure_reason": "Illegal move",
                        "audit": {"moves": [{"status": "ILLEGAL", "san": "e5"}]},
                    },
                    {
                        "trial_id": 3,
                        "failed": 1,
                        "failure_reason": "API_ERROR: provider unavailable",
                        "audit": {
                            "moves": [
                                {"status": "LEGAL", "san": "e4"},
                                {
                                    "status": "API_ERROR",
                                    "raw_response": "API_ERROR: provider unavailable",
                                },
                            ]
                        },
                    },
                ],
            }
            (results / "chess_test-run.json").write_text(
                json.dumps(run), encoding="utf-8"
            )
            csv_path = results / "chess_test-run.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "trial_id",
                        "failed",
                        "failure_reason",
                        "raw_response",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "trial_id": 1,
                            "failed": 1,
                            "failure_reason": "API_ERROR: model unavailable",
                            "raw_response": "API_ERROR: model unavailable",
                        },
                        {"trial_id": 2, "failed": 1},
                        {
                            "trial_id": 3,
                            "failed": 1,
                            "failure_reason": "API_ERROR: provider unavailable",
                            "raw_response": "API_ERROR: provider unavailable",
                        },
                    ]
                )

            for root_name, trial_id, status in (
                ("snapshots", 1, "API_ERROR"),
                ("snapshots", 2, "ILLEGAL"),
                ("replays", 1, "API_ERROR"),
            ):
                folder = root / root_name / f"trial_{trial_id:02}"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "match_audit.json").write_text(
                    json.dumps(
                        {
                            "game": "chess",
                            "run_id": "test-run",
                            "trial_id": trial_id,
                            "moves": [{"status": status}],
                        }
                    ),
                    encoding="utf-8",
                )

            summary = prune_unplayed_trials(root)

            updated = json.loads((results / "chess_test-run.json").read_text())
            with csv_path.open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(
                [trial["trial_id"] for trial in updated["trials"]], [2, 3]
            )
            self.assertEqual([row["trial_id"] for row in rows], ["2", "3"])
            partial_row = rows[1]
            self.assertEqual(partial_row["trial_status"], "partial_api_error")
            self.assertEqual(
                partial_row["failure_reason"],
                "Stopped after gameplay began because of an API/provider error.",
            )
            self.assertEqual(partial_row["raw_response"], "")
            self.assertFalse((root / "snapshots" / "trial_01").exists())
            self.assertTrue((root / "snapshots" / "trial_02").exists())
            self.assertFalse((root / "replays" / "trial_01").exists())
            self.assertEqual(summary["removed_trials"], 1)
            self.assertEqual(summary["removed_csv_rows"], 1)
            self.assertEqual(summary["removed_artifact_dirs"], 2)

    def test_prefers_configured_chess_model_over_legacy_combined_label(self):
        model, opponent, main_seat = models_for_trial(
            "chess",
            {"model": "gpt-4o vs random"},
            {"white_model": "gpt-4o", "black_model": "random"},
        )

        self.assertEqual((model, opponent, main_seat), ("gpt-4o", "random", "White"))

    def test_budget_uses_clean_trial_cost_not_unbilled_api_failures(self):
        groups = {
            ("tic-tac-toe", "gpt-6-astra", "random"): {
                "clean": 5,
                "total": 15,
                "all_cost": 0.05151,
                "rated_trials": 15,
                "clean_cost": 0.05151,
                "rated_clean": 5,
            }
        }

        self.assertAlmostEqual(
            projected_budget([], [], groups),
            20 * (0.05151 / 5),
        )

    def test_manifest_reports_when_source_data_was_pruned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            results_dir = input_dir / "results"
            results_dir.mkdir(parents=True)
            (results_dir / "chess_test.json").write_text(
                json.dumps(
                    {
                        "game": "chess",
                        "run_id": "test-run",
                        "configuration": {"white_model": "gpt-4o"},
                        "trials": [
                            {
                                "trial_id": 1,
                                "audit": {"moves": [{"status": "LEGAL"}]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            manifest = prepare(
                input_dir,
                root / "output",
                raw_data_modified=True,
            )

            self.assertTrue(manifest["raw_data_modified"])


if __name__ == "__main__":
    unittest.main()
