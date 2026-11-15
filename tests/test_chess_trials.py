import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import chess
import chess.pgn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "experiments" / "chess"))

import run_chess_trials


class ChessTrialTests(unittest.TestCase):
    def test_routes_gpt_oss_to_groq(self):
        self.assertEqual(
            run_chess_trials.provider_for_model("gpt-oss-120b"), "groq"
        )
        self.assertEqual(
            run_chess_trials.provider_for_model("openai/gpt-oss-120b"), "groq"
        )
        self.assertEqual(run_chess_trials.provider_for_model("gpt-4o"), "openai")
        self.assertEqual(
            run_chess_trials.provider_for_model("claude-sonnet-4-5"), "anthropic"
        )

    def test_anthropic_client_uses_claude_api_compatibility_endpoint(self):
        with patch.object(run_chess_trials, "OpenAI") as openai_client:
            clients = run_chess_trials.create_clients(
                ["claude-sonnet-4-5"],
                anthropic_api_key="anthropic-test-key",
            )

        self.assertEqual(set(clients), {"anthropic"})
        openai_client.assert_called_once_with(
            base_url="https://api.anthropic.com/v1/",
            api_key="anthropic-test-key",
        )

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

    def test_model_request_uses_conversation_and_latest_opponent_san(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Nf3"))],
            model_dump=lambda mode: {},
        )
        requests = []

        def create(**request):
            requests.append(request)
            return response

        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        )
        board = chess.Board()
        board.push_san("e4")
        board.push_san("e5")
        conversation = [
            {"role": "user", "content": "Game start. You are White."},
            {"role": "assistant", "content": "e4"},
        ]

        move, user_prompt, _ = run_chess_trials.query_model(
            "Opponent played: e5. You play White. Your move:",
            "gpt-4o",
            board,
            {"openai": client},
            conversation,
        )

        self.assertEqual(move, "Nf3")
        self.assertEqual(user_prompt, "Opponent played: e5. You play White. Your move:")
        self.assertEqual(
            conversation[-2:],
            [
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": "Nf3"},
            ],
        )
        self.assertEqual(
            requests[0]["messages"][1:],
            [
                {"role": "user", "content": "Game start. You are White."},
                {"role": "assistant", "content": "e4"},
                {"role": "user", "content": user_prompt},
            ],
        )

    def test_gpt6_model_uses_low_reasoning_and_completion_tokens(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="e4"))],
            model_dump=lambda mode: {},
        )
        requests = []
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **request: requests.append(request) or response
                )
            )
        )

        for model_name in ("gpt-6-luna", "gpt-6.1-terra"):
            with self.subTest(model_name=model_name):
                requests.clear()
                move, _, _ = run_chess_trials.query_model(
                    "Game start. You are White. Your move:",
                    model_name,
                    chess.Board(),
                    {"openai": client},
                )

                self.assertEqual(move, "e4")
                self.assertEqual(requests[0]["max_completion_tokens"], 2500)
                self.assertEqual(requests[0]["reasoning_effort"], "low")
                self.assertNotIn("max_tokens", requests[0])
                self.assertNotIn("temperature", requests[0])

    def test_gpt6_retries_truncated_response_with_larger_budget(self):
        requests = []
        responses = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="length",
                        message=SimpleNamespace(content=""),
                    )
                ],
                usage=SimpleNamespace(completion_tokens=2500),
                model_dump=lambda mode: {"choices": [{"finish_reason": "length"}]},
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="e5"),
                    )
                ],
                model_dump=lambda mode: {"choices": [{"finish_reason": "stop"}]},
            ),
        ]

        def create(**request):
            requests.append(dict(request))
            return responses.pop(0)

        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        )

        move, _, metadata = run_chess_trials.query_model(
            "Opponent played: e4. You play Black. Your move:",
            "gpt-6-luna",
            chess.Board(),
            {"openai": client},
        )

        self.assertEqual(move, "e5")
        self.assertEqual(
            [request["max_completion_tokens"] for request in requests],
            [2500, 5000],
        )
        self.assertEqual(metadata["truncated_attempts"][0]["completion_tokens"], 2500)

    def test_claude_request_uses_8192_response_token_limit(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="e4"),
                )
            ],
            model_dump=lambda mode: {},
        )
        requests = []
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **request: requests.append(request) or response
                )
            )
        )

        move, _, metadata = run_chess_trials.query_model(
            "Game start. You are White. Your move:",
            "claude-sonnet-4-5",
            chess.Board(),
            {"anthropic": client},
        )

        self.assertEqual(move, "e4")
        self.assertEqual(requests[0]["max_tokens"], 8192)
        self.assertNotIn("temperature", requests[0])
        self.assertEqual(metadata["provider"], "anthropic")

    def test_truncated_claude_response_is_reported_as_api_error(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content=""),
                )
            ],
            model_dump=lambda mode: {"choices": [{"finish_reason": "length"}]},
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **request: response
                )
            )
        )

        move, _, _ = run_chess_trials.query_model(
            "Game start. You are White. Your move:",
            "claude-sonnet-4-5",
            chess.Board(),
            {"anthropic": client},
        )

        self.assertIn("API_ERROR: Claude response was truncated", move)

    def test_gpt6_exhausted_response_is_reported_as_api_error(self):
        requests = []

        def create(**request):
            requests.append(dict(request))
            budget = request["max_completion_tokens"]
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="length",
                        message=SimpleNamespace(content=""),
                    )
                ],
                usage=SimpleNamespace(completion_tokens=budget),
                model_dump=lambda mode: {"choices": [{"finish_reason": "length"}]},
            )

        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        )

        response, _, metadata = run_chess_trials.query_model(
            "Game start. You are White. Your move:",
            "gpt-6-luna",
            chess.Board(),
            {"openai": client},
        )

        self.assertTrue(response.startswith("API_ERROR:"))
        self.assertIn("truncated at 5000 completion tokens", response)
        self.assertEqual(
            [request["max_completion_tokens"] for request in requests],
            [2500, 5000],
        )
        self.assertEqual(len(metadata["truncated_attempts"]), 2)

    def test_model_board_request_is_not_parsed_as_a_chess_move(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="PRINT OUT BOARD"))
            ],
            model_dump=lambda mode: {},
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **request: response
                )
            )
        )
        conversation = []

        move, _, _ = run_chess_trials.query_model(
            "Game start. You are White. Your move:",
            "gpt-4o",
            chess.Board(),
            {"openai": client},
            conversation,
        )

        self.assertEqual(move, "PRINT OUT BOARD")
        self.assertEqual(
            conversation[-1],
            {"role": "assistant", "content": "PRINT OUT BOARD"},
        )

    def test_model_can_print_board_then_continue_with_a_move(self):
        prompts = []
        responses = iter(("PRINT OUT BOARD", "e4", "e5"))

        def fake_query(prompt, model_name, board, clients, conversation):
            prompts.append(prompt)
            response = next(responses)
            return response, prompt, {"raw_response": response}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(run_chess_trials, "query_model", side_effect=fake_query):
                result = run_chess_trials.run_trial(
                    1,
                    "white-model",
                    "black-model",
                    2,
                    {},
                    Path(temp_dir),
                    "test",
                )

        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["plies_survived"], 2)
        self.assertEqual(result["board_print_requests"], 1)
        self.assertEqual(result["audit"]["board_print_requests"], 1)
        self.assertIn(run_chess_trials.board_text(chess.Board()), prompts[1])
        self.assertIn("still White's turn", prompts[1])
        self.assertEqual(
            prompts[2], "Opponent played: e4. You play Black. Your move:"
        )

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
            self.assertEqual(
                illegal_move["illegal_move"],
                {"san": "e5", "from_square": "e2", "to_square": "e5"},
            )
            with (folder / "match.pgn").open(encoding="utf-8") as pgn_file:
                game = chess.pgn.read_game(pgn_file)
            self.assertIsNotNone(game)
            self.assertEqual(list(game.mainline_moves()), [])
            self.assertIn("Illegal move attempted by White: e5", game.end().comment)
            self.assertEqual(audit["pgn"], (folder / "match.pgn").read_text().strip())

    def test_batch_writes_structured_results_and_json_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            csv_path = output_dir / "results" / "summary.csv"
            with patch.object(
                run_chess_trials,
                "query_model",
                return_value=("e4", "start prompt", {"raw_response": "e4"}),
            ):
                run_chess_trials.execute_batch(
                    "gpt-4o",
                    "random",
                    1,
                    1,
                    output_dir,
                    csv_path,
                    {},
                    "test-run",
                )

            results_path = output_dir / "results" / "chess_gpt-4o_test-run.json"
            result = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(result["trials"][0]["audit"]["moves"][0]["raw_response"], "e4")
            self.assertEqual(result["trials"][0]["board_print_requests"], 0)
            with csv_path.open(encoding="utf-8", newline="") as result_file:
                csv_rows = list(csv.DictReader(result_file))
            self.assertEqual(csv_rows[0]["board_print_requests"], "0")
            snapshot_dir = (
                output_dir
                / "snapshots"
                / "chess"
                / "test-run"
                / "gpt-4o_test-run_trial_01"
            )
            self.assertEqual(len(list(snapshot_dir.glob("state_*.json"))), 2)
            pgn_path = (
                output_dir
                / "replays"
                / "gpt-4o_test-run_trial_01"
                / "match.pgn"
            )
            with pgn_path.open(encoding="utf-8") as pgn_file:
                game = chess.pgn.read_game(pgn_file)
            self.assertIsNotNone(game)
            self.assertEqual(len(list(game.mainline_moves())), 1)
            self.assertIn("1. e4", result["trials"][0]["audit"]["pgn"])


if __name__ == "__main__":
    unittest.main()
