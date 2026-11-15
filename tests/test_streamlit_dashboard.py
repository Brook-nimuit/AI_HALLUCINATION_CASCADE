import json
import tempfile
import unittest
from pathlib import Path

from streamlit_dashboard import load_trials


class StreamlitDashboardTests(unittest.TestCase):
    def test_includes_audited_replay_only_trials_without_counting_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            results = root / "results"
            results.mkdir()
            run = {
                "game": "chess",
                "run_id": "20261111T123456789012",
                "configuration": {"white_model": "gpt-4o", "black_model": "random"},
                "trials": [
                    {
                        "trial_id": 1,
                        "failed": False,
                        "audit": {
                            "game": "chess",
                            "run_id": "20261111T123456789012",
                            "trial_id": 1,
                            "moves": [{"ply": 1, "status": "LEGAL", "san": "e4"}],
                        },
                    }
                ],
            }
            (results / "chess_test.json").write_text(
                json.dumps(run), encoding="utf-8"
            )

            duplicate = root / "replays" / (
                "gpt-4o_20261111T123456789012_trial_01"
            )
            duplicate.mkdir(parents=True)
            (duplicate / "match_audit.json").write_text(
                json.dumps(run["trials"][0]["audit"]), encoding="utf-8"
            )
            replay_only = root / "replays" / "gpt-6-astra_trial_01"
            replay_only.mkdir(parents=True)
            (replay_only / "match_audit.json").write_text(
                json.dumps(
                    {
                        "trial_id": 1,
                        "white_bot": "gpt-6-astra (White)",
                        "black_bot": "gpt-6-astra (Black)",
                        "failed": False,
                        "failure_reason": "Completed (Max Plies Reached)",
                        "plies_survived": 80,
                        "moves": [{"ply": 1, "actor": "White", "san": "e4", "status": "LEGAL"}],
                    }
                ),
                encoding="utf-8",
            )

            rows = load_trials(root)

            self.assertEqual(len(rows), 2)
            self.assertEqual({row["model"] for row in rows}, {"gpt-4o", "gpt-6-astra"})
            self.assertEqual(sum(row["run_id"] == run["run_id"] for row in rows), 1)


if __name__ == "__main__":
    unittest.main()
