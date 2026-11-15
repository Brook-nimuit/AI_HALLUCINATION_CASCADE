import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "experiments" / "connect-four"))

import run_connect_four_trials


class ConnectFourTests(unittest.TestCase):
    def test_provider_routing_and_column_parser(self):
        self.assertEqual(
            run_connect_four_trials.provider_for_model("gpt-4o"), "openai"
        )
        self.assertEqual(
            run_connect_four_trials.provider_for_model("gpt-oss-120b"), "groq"
        )
        self.assertEqual(run_connect_four_trials.parse_column("column d"), 4)
        self.assertEqual(run_connect_four_trials.parse_column("G."), 7)
        self.assertIsNone(run_connect_four_trials.parse_column("A or B"))
        self.assertIsNone(run_connect_four_trials.parse_column("H"))

    def test_gravity_and_full_column_rejection(self):
        game = run_connect_four_trials.ConnectFour()
        for expected_row, mark in zip(range(1, 7), ("R", "Y", "R", "Y", "R", "Y")):
            valid, _, row = game.play(mark, 1)
            self.assertTrue(valid)
            self.assertEqual(row, expected_row)
        valid, reason, row = game.play("R", 1)
        self.assertFalse(valid)
        self.assertIn("full", reason)
        self.assertIsNone(row)

    def test_detects_horizontal_vertical_and_diagonal_wins(self):
        game = run_connect_four_trials.ConnectFour()
        for mark, column in (
            ("R", 1), ("Y", 7), ("R", 2), ("Y", 7),
            ("R", 3), ("Y", 6), ("R", 4),
        ):
            valid, _, _ = game.play(mark, column)
            self.assertTrue(valid)
        self.assertEqual(game.winner, "R")

        game = run_connect_four_trials.ConnectFour()
        for mark, column in (
            ("R", 1), ("Y", 2), ("R", 1), ("Y", 2),
            ("R", 1), ("Y", 2), ("R", 1),
        ):
            valid, _, _ = game.play(mark, column)
            self.assertTrue(valid)
        self.assertEqual(game.winner, "R")

        game = run_connect_four_trials.ConnectFour()
        game.board[5][0] = "R"
        game.board[4][1] = "R"
        game.board[3][2] = "R"
        game.board[2][3] = "R"
        self.assertTrue(game._has_four(2, 3, "R"))
        game.board = [[None for _ in range(7)] for _ in range(6)]
        game.board[2][2] = "R"
        game.board[3][3] = "R"
        game.board[4][4] = "R"
        game.board[5][5] = "R"
        self.assertTrue(game._has_four(2, 2, "R"))

    def test_model_request_keeps_per_player_context_and_move_only_prompt(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="D"),
                    finish_reason="stop",
                )
            ],
            model_dump=lambda mode: {"choices": [{"message": {"content": "D"}}]},
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **request: response
                )
            )
        )
        conversation = [
            {"role": "user", "content": "Game start. Board is empty."},
            {"role": "assistant", "content": "B"},
        ]
        raw_response, prompt, metadata = run_connect_four_trials.query_model(
            "R",
            "gpt-test",
            {"openai": client},
            "Opponent played: Y in column C. Your move:",
            conversation,
        )
        self.assertEqual(raw_response, "D")
        self.assertEqual(prompt, "Opponent played: Y in column C. Your move:")
        self.assertEqual(
            metadata["request"]["messages"][1:],
            [
                {"role": "user", "content": "Game start. Board is empty."},
                {"role": "assistant", "content": "B"},
                {"role": "user", "content": "Opponent played: Y in column C. Your move:"},
            ],
        )
        self.assertIn("one column letter from A to G", metadata["request"]["messages"][0]["content"])

    def test_random_trial_writes_match_audit_and_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            csv_path = output_dir / "results" / "summary.csv"
            run_connect_four_trials.execute_batch(
                "random", "random", 1, output_dir, csv_path, {}, "test-run"
            )

            results_path = output_dir / "results" / "connect_four_test-run.json"
            results = json.loads(results_path.read_text(encoding="utf-8"))
            trial = results["trials"][0]
            audit = trial["match_log"]
            self.assertIn(audit["result"], ("R wins", "Y wins", "Draw"))
            self.assertGreaterEqual(audit["moves_played"], 7)
            self.assertEqual(len(audit["snapshots"]), audit["moves_played"] + 1)
            self.assertEqual(
                len(list((output_dir / "snapshots" / "connect-four" / "test-run")
                         .rglob("state_*.png"))),
                audit["moves_played"] + 1,
            )
            self.assertTrue(
                next((output_dir / "snapshots" / "connect-four" / "test-run")
                     .rglob("match_audit.json")).exists()
            )

    def test_scripted_game_records_latest_opponent_move_and_win(self):
        scripted_columns = iter(("A", "G", "B", "G", "C", "F", "D"))
        seen_prompts = []

        def fake_query(mark, model_name, clients, prompt, conversation):
            seen_prompts.append(prompt)
            return next(scripted_columns), prompt, {"provider": "mock"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                run_connect_four_trials, "query_model", side_effect=fake_query
            ):
                trial = run_connect_four_trials.run_trial(
                    1,
                    "red-model",
                    "yellow-model",
                    {},
                    Path(temp_dir),
                    "scripted",
                )

            self.assertEqual(trial["winner"], "R")
            self.assertEqual(trial["moves_played"], 7)
            self.assertEqual(seen_prompts[1], "Opponent played: R in column A. Your move:")
            self.assertEqual(seen_prompts[2], "Opponent played: Y in column G. Your move:")
            audit_path = (
                Path(temp_dir)
                / "snapshots"
                / "connect-four"
                / "scripted"
                / "red-model_trial_001"
                / "match_audit.json"
            )
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["moves"][-1]["column"], "D")
            self.assertEqual(audit["moves"][-1]["status"], "LEGAL")

    def test_model_can_print_board_then_continue_with_a_move(self):
        prompts = []
        responses = iter(("PRINT OUT BOARD", "A", "G", "B", "G", "C", "F", "D"))

        def fake_query(mark, model_name, clients, prompt, conversation):
            prompts.append(prompt)
            response = next(responses)
            return response, prompt, {"provider": "mock"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                run_connect_four_trials, "query_model", side_effect=fake_query
            ):
                result = run_connect_four_trials.run_trial(
                    1,
                    "red-model",
                    "yellow-model",
                    {},
                    Path(temp_dir),
                    "test",
                )

        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["moves_played"], 7)
        self.assertEqual(result["winner"], "R")
        self.assertEqual(result["board_print_requests"], 1)
        self.assertEqual(result["match_log"]["board_print_requests"], 1)
        self.assertIn("Current board", prompts[1])
        self.assertIn(
            run_connect_four_trials.board_text(
                [[None for _ in range(7)] for _ in range(6)]
            ),
            prompts[1],
        )
        self.assertIn("still your turn as Red (R)", prompts[1])
        self.assertEqual(
            prompts[2], "Opponent played: R in column A. Your move:"
        )


if __name__ == "__main__":
    unittest.main()
