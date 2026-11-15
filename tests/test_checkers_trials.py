import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "experiments" / "checkers"))

import run_checkers_trials as checkers


def square_at(row, column):
    return checkers.coordinate_to_square(row, column)


class InternationalDraughtsTests(unittest.TestCase):
    def test_provider_selection_supports_anthropic_gemini_groq_openai_and_ollama(self):
        self.assertEqual(
            checkers.provider_for_model("claude-sonnet-4-5"), "anthropic"
        )
        self.assertEqual(checkers.provider_for_model("gemini-2.5-flash"), "gemini")
        self.assertEqual(checkers.provider_for_model("gpt-oss-120b"), "groq")
        self.assertEqual(checkers.provider_for_model("gpt-6-astra"), "openai")
        self.assertEqual(checkers.provider_for_model("o4-mini"), "openai")
        self.assertEqual(
            checkers.provider_for_model("llama-3.3-70b", "groq"),
            "groq",
        )
        self.assertEqual(checkers.provider_for_model("deepseek-r1"), "ollama")

    def test_client_creation_uses_selected_provider_keys(self):
        with (
            patch.object(checkers.genai, "Client") as gemini_client,
            patch.object(checkers, "OpenAI") as openai_client,
        ):
            clients = checkers.create_clients(
                [
                    "gemini-2.5-flash",
                    "llama-3.3-70b",
                    "local-model",
                    "claude-sonnet-4-5",
                ],
                groq_api_key="groq-test-key",
                providers=["gemini", "groq", "ollama", "anthropic"],
                gemini_api_key="gemini-test-key",
                anthropic_api_key="anthropic-test-key",
            )

        self.assertEqual(
            set(clients), {"gemini", "groq", "ollama", "anthropic"}
        )
        gemini_client.assert_called_once_with(api_key="gemini-test-key")
        self.assertEqual(openai_client.call_count, 3)
        calls_by_url = {
            call.kwargs["base_url"]: call.kwargs
            for call in openai_client.call_args_list
        }
        self.assertEqual(
            calls_by_url["https://api.groq.com/openai/v1"]["api_key"],
            "groq-test-key",
        )
        self.assertEqual(
            calls_by_url["http://localhost:11434/v1"]["api_key"],
            "ollama",
        )
        self.assertEqual(
            calls_by_url["https://api.anthropic.com/v1/"]["api_key"],
            "anthropic-test-key",
        )

    def test_claude_request_uses_8192_response_token_limit(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="31-26"),
                )
            ],
            model_dump=lambda mode: {"choices": [{"message": {"content": "31-26"}}]},
        )
        create = Mock(return_value=response)

        class FakeOpenAIClient:
            def __init__(self):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=create)
                )

        with patch.object(checkers, "OpenAI", FakeOpenAIClient):
            raw_response, _, metadata = checkers.query_model(
                "Game start. You are White. Your move:",
                "claude-sonnet-4-5",
                {"anthropic": FakeOpenAIClient()},
                "auto",
            )

        self.assertEqual(raw_response, "31-26")
        self.assertEqual(metadata["provider"], "anthropic")
        self.assertEqual(create.call_args.kwargs["max_tokens"], 8192)
        self.assertNotIn("temperature", create.call_args.kwargs)

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
        create = Mock(return_value=response)

        class FakeOpenAIClient:
            def __init__(self):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=create)
                )

        with patch.object(checkers, "OpenAI", FakeOpenAIClient):
            raw_response, _, _ = checkers.query_model(
                "Game start. You are White. Your move:",
                "claude-sonnet-4-5",
                {"anthropic": FakeOpenAIClient()},
                "auto",
            )

        self.assertIn("API_ERROR: Claude response was truncated", raw_response)

    def test_gemini_request_uses_pdn_move_and_conversation_context(self):
        class FakeGeminiClient:
            def __init__(self):
                self.models = SimpleNamespace(
                    generate_content=Mock(
                        return_value=SimpleNamespace(
                            text="31-26",
                            model_dump=lambda mode: (
                                {"text": "31-26"} if mode == "json" else {}
                            ),
                        )
                    )
                )

        client = FakeGeminiClient()
        conversation = [
            {"role": "user", "content": "Game start. You are White."},
            {"role": "assistant", "content": "31-26"},
        ]
        with patch.object(checkers.genai, "Client", FakeGeminiClient):
            raw_response, prompt, metadata = checkers.query_model(
                "Opponent played: 20-25. You play White. Your move:",
                "gemini-2.5-flash",
                {"gemini": client},
                "medium",
                conversation=conversation,
            )

        self.assertEqual(raw_response, "31-26")
        self.assertIn("Opponent played: 20-25", prompt)
        request = client.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], "gemini-2.5-flash")
        self.assertEqual(request["config"].system_instruction, checkers.SYSTEM_PROMPT)
        self.assertIn("latest complete PDN move", checkers.SYSTEM_PROMPT)
        self.assertNotIn("Current board", checkers.SYSTEM_PROMPT)
        self.assertEqual(
            [content.role for content in request["contents"]],
            ["user", "model", "user"],
        )
        self.assertEqual(
            request["contents"][-1].parts[0].text,
            "Opponent played: 20-25. You play White. Your move:",
        )
        self.assertEqual(metadata["provider"], "gemini")

    def test_initial_position_uses_ten_by_ten_international_setup(self):
        game = checkers.InternationalDraughts()

        self.assertEqual(len(game.board), 40)
        self.assertEqual(sum(piece.lower() == "w" for piece in game.board.values()), 20)
        self.assertEqual(sum(piece.lower() == "b" for piece in game.board.values()), 20)
        self.assertEqual(game.turn, "White")
        self.assertEqual(len(game.legal_moves()), 9)

    def test_square_numbering_round_trips_all_playable_squares(self):
        for square in range(1, 51):
            self.assertEqual(
                square_at(*checkers.square_to_coordinate(square)),
                square,
            )

    def test_men_move_forward_but_capture_in_all_diagonal_directions(self):
        forward = checkers.InternationalDraughts({31: "w"}, turn="White")
        self.assertEqual(
            {move.path for move in forward.legal_moves()},
            {(31, 26), (31, 27)},
        )

        backward_capture = checkers.InternationalDraughts(
            {26: "w", 31: "b"}, turn="White"
        )
        self.assertIn(
            (26, 37),
            {move.path for move in backward_capture.legal_moves()},
        )

    def test_mandatory_capture_and_global_maximum_capture(self):
        board = {
            31: "w",
            33: "w",
            27: "b",
            18: "b",
            29: "b",
            36: "b",
        }
        game = checkers.InternationalDraughts(board, turn="White")

        moves = game.legal_moves()

        self.assertTrue(moves)
        self.assertTrue(all(move.is_capture for move in moves))
        self.assertEqual(
            {move.notation for move in moves},
            {"31x22x13"},
        )

    def test_flying_king_can_choose_any_empty_landing_beyond_enemy(self):
        king_square = square_at(6, 1)
        enemy_square = square_at(4, 3)
        game = checkers.InternationalDraughts(
            {king_square: "W", enemy_square: "b"}, turn="White"
        )

        capture_moves = [
            move for move in game.legal_moves() if move.path[0] == king_square
        ]

        self.assertGreaterEqual(len(capture_moves), 3)
        self.assertTrue(all(move.captured == (enemy_square,) for move in capture_moves))

    def test_captured_piece_remains_a_blocker_during_capture_sequence(self):
        king_square = square_at(6, 1)
        first_enemy = square_at(4, 3)
        blocked_enemy = square_at(5, 2)
        game = checkers.InternationalDraughts(
            {king_square: "W", first_enemy: "b", blocked_enemy: "b"},
            turn="White",
        )

        self.assertFalse(
            any(
                blocked_enemy in move.captured
                for move in game.legal_moves()
                if move.path[0] == king_square
            )
        )

    def test_move_removes_captures_after_sequence_and_promotes_at_turn_end(self):
        game = checkers.InternationalDraughts(
            {31: "w", 27: "b", 18: "b"}, turn="White"
        )
        valid, reason, move = game.play((31, 22, 13))

        self.assertTrue(valid, reason)
        self.assertEqual(move.notation, "31x22x13")
        self.assertEqual(game.board, {13: "w"})
        self.assertEqual(game.turn, "Black")

        promotion = checkers.InternationalDraughts(
            {square_at(2, 1): "w", square_at(1, 2): "b"},
            turn="White",
        )
        promotion_move = next(iter(promotion.legal_moves()))
        self.assertEqual(promotion_move.path[-1], square_at(0, 3))
        self.assertTrue(promotion.play(promotion_move.path)[0])
        self.assertEqual(promotion.board[square_at(0, 3)], "W")

    def test_parser_reads_pdn_style_moves_and_rejects_ambiguous_responses(self):
        self.assertEqual(checkers.parse_move("31-26"), (31, 26))
        self.assertEqual(checkers.parse_move("31x22x13"), (31, 22, 13))
        self.assertEqual(checkers.parse_move("31×22×13"), (31, 22, 13))
        self.assertIsNone(checkers.parse_move("Move 31-26 and 16-21"))
        self.assertIsNone(checkers.parse_move("move not found"))

    def test_pdn_formats_full_turns_with_international_result_codes(self):
        audit = {
            "started_at": "2026-11-05T20:00:00-05:00",
            "trial_id": 2,
            "players": {"White": "gpt-6-astra", "Black": "random"},
            "winner": "White",
            "draw": False,
            "turns": [
                {"player": "White", "move": "31-26", "valid": True},
                {"player": "Black", "move": "16-21", "valid": True},
                {"player": "White", "move": "26x17", "valid": True},
            ],
        }

        pdn = checkers.build_pdn(audit)

        self.assertIn('[GameType "20"]', pdn)
        self.assertIn('[Variant "International"]', pdn)
        self.assertIn('[Result "2-0"]', pdn)
        self.assertTrue(pdn.endswith("1. 31-26 16-21 2. 26x17 2-0\n"))

    def test_astra_request_uses_medium_effort_and_latest_pdn_move(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="31-26"),
                )
            ],
            model_dump=lambda mode: {"choices": [{"message": {"content": "31-26"}}]},
        )
        create = Mock(return_value=response)
        class FakeOpenAIClient:
            def __init__(self):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=create)
                )

        client = FakeOpenAIClient()
        conversation = [
            {"role": "user", "content": "Game start. You are White."},
            {"role": "assistant", "content": "31-26"},
        ]

        with patch.object(checkers, "OpenAI", FakeOpenAIClient):
            raw_response, prompt, metadata = checkers.query_model(
                "Opponent played: 20-25. You play White. Your move:",
                "gpt-6-astra",
                {"openai": client},
                "medium",
                conversation=conversation,
            )

        self.assertEqual(raw_response, "31-26")
        self.assertIn("Opponent played: 20-25", prompt)
        self.assertEqual(
            create.call_args.kwargs["messages"][1:],
            [
                {"role": "user", "content": "Game start. You are White."},
                {"role": "assistant", "content": "31-26"},
                {
                    "role": "user",
                    "content": "Opponent played: 20-25. You play White. Your move:",
                },
            ],
        )
        self.assertEqual(metadata["request"]["reasoning_effort"], "medium")
        self.assertEqual(metadata["request"]["max_completion_tokens"], 1024)
        self.assertNotIn("temperature", metadata["request"])
        self.assertNotIn("max_tokens", metadata["request"])
        self.assertNotIn("temperature", create.call_args.kwargs)

    def test_gpt_oss_defaults_to_low_reasoning_to_avoid_token_exhaustion(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="31-26"),
                )
            ],
            model_dump=lambda mode: {"choices": [{"message": {"content": "31-26"}}]},
        )
        create = Mock(return_value=response)

        class FakeOpenAIClient:
            def __init__(self):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=create)
                )

        with patch.object(checkers, "OpenAI", FakeOpenAIClient):
            raw_response, _, metadata = checkers.query_model(
                "Game start. You are White. Your move:",
                "openai/gpt-oss-120b",
                {"groq": FakeOpenAIClient()},
                "auto",
            )

        self.assertEqual(raw_response, "31-26")
        self.assertEqual(metadata["provider"], "groq")
        self.assertEqual(metadata["request"]["reasoning_effort"], "low")
        self.assertNotIn("temperature", metadata["request"])
        self.assertEqual(
            checkers.effective_reasoning_effort("gpt-6-astra", "auto"),
            "medium",
        )
        self.assertEqual(
            checkers.effective_reasoning_effort("openai/gpt-oss-120b", "high"),
            "high",
        )

    def test_random_two_trial_batch_saves_incremental_pdn_audits_and_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            csv_path = output_dir / "results" / "summary.csv"

            checkers.execute_batch(
                "random",
                "random",
                2,
                6,
                "medium",
                output_dir,
                csv_path,
                {},
                "test-run",
            )

            with csv_path.open(encoding="utf-8", newline="") as result_file:
                rows = list(csv.DictReader(result_file))
            self.assertEqual(len(rows), 2)
            for trial_id in (1, 2):
                match_dir = (
                    output_dir
                    / "snapshots"
                    / "checkers"
                    / "test-run"
                    / f"random_trial_{trial_id:03d}"
                )
                audit = json.loads(
                    (match_dir / "match_audit.json").read_text(encoding="utf-8")
                )
                pdn_text = (match_dir / "match.pdn").read_text(encoding="utf-8")
                self.assertEqual(audit["game"], "international-draughts")
                self.assertGreater(len(audit["turns"]), 0)
                self.assertLessEqual(len(audit["turns"]), 6)
                self.assertTrue(all(turn["valid"] for turn in audit["turns"]))
                self.assertIn("[GameType \"20\"]", pdn_text)
                self.assertEqual(audit["pdn"], pdn_text)
                self.assertEqual(
                    len(list(match_dir.glob("state_*.json"))),
                    len(audit["turns"]) + 1,
                )

    def test_model_can_print_board_then_continue_with_a_move(self):
        prompts = []
        responses = iter(("PRINT OUT BOARD", "31-26", "20-25"))

        def fake_query(prompt, model_name, clients, reasoning_effort, provider, conversation):
            prompts.append(prompt)
            response = next(responses)
            return response, prompt, {"provider": "mock"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(checkers, "query_model", side_effect=fake_query):
                result = checkers.run_trial(
                    1,
                    "white-model",
                    "black-model",
                    2,
                    {},
                    "auto",
                    Path(temp_dir),
                    "test",
                )

        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["plies_played"], 2)
        self.assertEqual(result["board_print_requests"], 1)
        self.assertEqual(result["match_log"]["board_print_requests"], 1)
        self.assertIn("Current board (numbered playable squares)", prompts[1])
        self.assertIn(checkers.InternationalDraughts().board_text(), prompts[1])
        self.assertIn("still White's turn", prompts[1])
        self.assertEqual(
            prompts[2], "Opponent played: 31-26. You play Black. Your move:"
        )


if __name__ == "__main__":
    unittest.main()
