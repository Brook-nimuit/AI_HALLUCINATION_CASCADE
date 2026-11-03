import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "experiments" / "chess"))

import run_chess_trials


class ChessTrialTests(unittest.TestCase):
    def test_extracts_a_legal_move_from_notation(self):
        board = chess.Board()
        for san in ("e4", "e5", "Nf3", "Nc6"):
            board.push_san(san)

        self.assertEqual(
            run_chess_trials.extract_move("1. e4 e5 2. Nf3 Nc6 3. Bb5", board),
            "Bb5",
        )

    def test_transcript_preserves_full_move_numbers(self):
        board = chess.Board()
        board.push_san("e4")
        board.push_san("e5")
        board.push_san("Nf3")

        self.assertEqual(run_chess_trials.format_transcript(board), "1. e4 e5 2. Nf3")

    def test_random_opponent_records_its_own_san(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                run_chess_trials,
                "query_model",
                return_value=("e4", "start prompt", {}),
            ):
                result = run_chess_trials.run_trial(
                    trial_id=1,
                    white_model="gpt-4o",
                    black_model="random",
                    max_plies=2,
                    clients={},
                    output_dir=Path(temp_dir),
                    run_id="test",
                )

            folder = next((Path(temp_dir) / "replays").iterdir())
            audit = json.loads((folder / "match_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(result["failed"], 0)
            self.assertEqual(len(audit["moves"]), 2)
            self.assertEqual(audit["moves"][1]["actor"], "Black")
            self.assertTrue(audit["moves"][1]["san"])

    def test_self_play_only_requires_the_white_provider(self):
        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True),
            patch.object(run_chess_trials, "OpenAI", return_value=object()) as client,
        ):
            clients = run_chess_trials.create_clients(["gpt-4o", "self"])

        self.assertEqual(set(clients), {"openai"})
        client.assert_called_once_with(api_key="test-key")

    def test_illegal_move_is_recorded_in_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                run_chess_trials,
                "query_model",
                return_value=("e5", "start prompt", {}),
            ):
                result = run_chess_trials.run_trial(
                    trial_id=1,
                    white_model="gpt-4o",
                    black_model="random",
                    max_plies=1,
                    clients={},
                    output_dir=Path(temp_dir),
                    run_id="test",
                )

            folder = next((Path(temp_dir) / "replays").iterdir())
            audit = json.loads((folder / "match_audit.json").read_text(encoding="utf-8"))
            illegal_move = next(move for move in audit["moves"] if move["status"] == "ILLEGAL")
            self.assertEqual(result["failed"], 1)
            self.assertEqual(illegal_move["san"], "e5")


if __name__ == "__main__":
    unittest.main()
