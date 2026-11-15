import json
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "experiments" / "tic-tac-toe"))

import run_tttoe_trials


class TicTacToeTrialTests(unittest.TestCase):
    def test_routes_gpt_oss_to_groq(self):
        self.assertEqual(
            run_tttoe_trials.provider_for_model("gpt-oss-120b"), "groq"
        )
        self.assertEqual(
            run_tttoe_trials.provider_for_model("openai/gpt-oss-120b"), "groq"
        )
        self.assertEqual(run_tttoe_trials.provider_for_model("gpt-4o"), "openai")
        self.assertEqual(run_tttoe_trials.provider_for_model("astra-model"), "openai")

    def test_astra_request_uses_low_reasoning_effort(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="5"))],
            model_dump=lambda mode: {},
        )
        client = run_tttoe_trials.OpenAI(api_key="test-key")
        with patch.object(
            client.chat.completions, "create", return_value=response
        ) as create:
            raw_response, _, metadata = run_tttoe_trials.query_model(
                "X",
                "astra-model",
                {"openai": client},
                "Game start. You are X; the board is empty. Your move:",
            )

        self.assertEqual(raw_response, "5")
        self.assertEqual(create.call_args.kwargs["reasoning_effort"], "low")
        self.assertEqual(metadata["request"]["reasoning_effort"], "low")
        self.assertEqual(metadata["request"]["max_completion_tokens"], 512)
        self.assertNotIn("temperature", create.call_args.kwargs)
        self.assertNotIn("temperature", metadata["request"])
        self.assertNotIn("max_tokens", create.call_args.kwargs)
        self.assertNotIn("max_tokens", metadata["request"])

    def test_non_astra_tic_tac_toe_request_keeps_default_reasoning(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="5"))],
            model_dump=lambda mode: {},
        )
        client = run_tttoe_trials.OpenAI(api_key="test-key")
        with patch.object(
            client.chat.completions, "create", return_value=response
        ) as create:
            raw_response, _, metadata = run_tttoe_trials.query_model(
                "X",
                "gpt-4o",
                {"openai": client},
                "Opponent played: O in square 4. Your move:",
            )

        self.assertEqual(raw_response, "5")
        self.assertNotIn("reasoning_effort", create.call_args.kwargs)
        self.assertNotIn("reasoning_effort", metadata["request"])
        self.assertEqual(create.call_args.kwargs["temperature"], 0.2)

    def test_model_request_uses_move_only_context_and_small_output_budget(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="5"))],
            model_dump=lambda mode: {},
        )
        create = lambda **request: response
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        conversation = [
            {"role": "user", "content": "Game start. You are X; the board is empty."},
            {"role": "assistant", "content": "5"},
        ]

        raw_response, user_prompt, metadata = run_tttoe_trials.query_model(
            "X",
            "gpt-test",
            {"openai": client},
            "Opponent played: O in square 4. Your move:",
            conversation,
        )

        self.assertEqual(raw_response, "5")
        self.assertEqual(user_prompt, "Opponent played: O in square 4. Your move:")
        self.assertEqual(
            metadata["request"]["messages"][1:],
            [
                {"role": "user", "content": "Game start. You are X; the board is empty."},
                {"role": "assistant", "content": "5"},
                {"role": "user", "content": "Opponent played: O in square 4. Your move:"},
            ],
        )
        self.assertEqual(metadata["request"]["max_tokens"], 16)

    def test_gpt_oss_request_allows_low_effort_reasoning_before_its_move(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="5"))],
            model_dump=lambda mode: {},
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **request: response)
            )
        )

        raw_response, _, metadata = run_tttoe_trials.query_model(
            "X",
            "openai/gpt-oss-120b",
            {"groq": client},
            "Game start. You are X; the board is empty. Your move:",
        )

        self.assertEqual(raw_response, "5")
        self.assertEqual(metadata["provider"], "groq")
        self.assertEqual(metadata["request"]["reasoning_effort"], "low")
        self.assertEqual(metadata["request"]["max_completion_tokens"], 512)
        self.assertEqual(
            metadata["request"]["extra_body"], {"reasoning_format": "hidden"}
        )
        self.assertNotIn("max_tokens", metadata["request"])
        from openai.resources.chat.completions import Completions

        inspect.signature(Completions.create).bind(
            object(), **metadata["request"]
        )

    def test_gpt_oss_retries_truncated_responses_with_larger_budget(self):
        requests = []

        def make_response(content, finish_reason, reasoning):
            payload = {
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": {"content": content, "reasoning": reasoning},
                    }
                ]
            }
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=finish_reason,
                        message=SimpleNamespace(content=content),
                    )
                ],
                usage=SimpleNamespace(completion_tokens=512),
                model_dump=lambda mode: payload,
            )

        responses = [
            make_response("", "length", "incomplete reasoning"),
            make_response("5", "stop", ""),
        ]

        def create(**request):
            requests.append(dict(request))
            return responses.pop(0)

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        raw_response, _, metadata = run_tttoe_trials.query_model(
            "X",
            "openai/gpt-oss-120b",
            {"groq": client},
            "Game start. You are X; the board is empty. Your move:",
        )

        self.assertEqual(raw_response, "5")
        self.assertEqual(
            [request["max_completion_tokens"] for request in requests], [512, 1024]
        )
        self.assertEqual(metadata["truncated_attempts"][0]["completion_tokens"], 512)
        self.assertNotIn(
            "reasoning",
            metadata["response"]["choices"][0]["message"],
        )

    def test_gpt_oss_reports_truncation_after_budget_retries(self):
        def create(**request):
            payload = {"choices": [{"finish_reason": "length", "message": {}}]}
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="length",
                        message=SimpleNamespace(content=""),
                    )
                ],
                usage=SimpleNamespace(completion_tokens=request["max_completion_tokens"]),
                model_dump=lambda mode: payload,
            )

        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        )
        raw_response, _, metadata = run_tttoe_trials.query_model(
            "X",
            "openai/gpt-oss-120b",
            {"groq": client},
            "Game start. You are X; the board is empty. Your move:",
        )

        self.assertTrue(raw_response.startswith("API_ERROR:"))
        self.assertIn("truncated at 2048 completion tokens", raw_response)
        self.assertEqual(len(metadata["truncated_attempts"]), 3)

    def test_detects_win_and_rejects_occupied_square(self):
        game = run_tttoe_trials.TicTacToe()
        for mark, position in (("X", 1), ("O", 4), ("X", 2), ("O", 5)):
            self.assertTrue(game.play(mark, position)[0])

        valid, reason = game.play("X", 4)
        self.assertFalse(valid)
        self.assertIn("occupied", reason)
        self.assertTrue(game.play("X", 3)[0])
        self.assertEqual(game.winner, "X")
        self.assertTrue(game.finished)

    def test_writes_full_run_results_and_state_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            csv_path = output_dir / "results" / "summary.csv"
            responses = [("1", "prompt X", {}), ("4", "prompt O", {}),
                         ("2", "prompt X", {}), ("5", "prompt O", {}),
                         ("3", "prompt X", {})]
            with patch.object(
                run_tttoe_trials, "query_model", side_effect=responses
            ):
                run_tttoe_trials.execute_batch(
                    "test-model",
                    "self",
                    1,
                    output_dir,
                    csv_path,
                    {},
                    "test-run",
                )

            results_path = output_dir / "results" / "tic_tac_toe_test-run.json"
            results = json.loads(results_path.read_text(encoding="utf-8"))
            trial = results["trials"][0]
            self.assertEqual(trial["winner"], "X")
            self.assertEqual(len(trial["match_log"]["moves"]), 5)
            self.assertEqual(
                [move["position"] for move in trial["match_log"]["moves"]],
                [1, 4, 2, 5, 3],
            )
            match_dir = (
                output_dir
                / "snapshots"
                / "tic-tac-toe"
                / "test-run"
                / "test-model_trial_001"
            )
            self.assertEqual(len(list(match_dir.glob("state_*.json"))), 6)
            self.assertEqual(len(list(match_dir.glob("state_*.png"))), 6)
            self.assertTrue((match_dir / "match_audit.json").exists())

    def test_model_can_print_board_then_continue_with_a_move(self):
        prompts = []
        responses = iter(("PRINT OUT BOARD", "1", "4", "2", "5", "3"))

        def fake_query(mark, model_name, clients, prompt, conversation):
            prompts.append(prompt)
            response = next(responses)
            return response, prompt, {"provider": "mock"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(run_tttoe_trials, "query_model", side_effect=fake_query):
                result = run_tttoe_trials.run_trial(
                    1,
                    "x-model",
                    "o-model",
                    {},
                    Path(temp_dir),
                    "test",
                )

        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["moves_played"], 5)
        self.assertEqual(result["board_print_requests"], 1)
        self.assertEqual(result["match_log"]["board_print_requests"], 1)
        self.assertIn("Current board", prompts[1])
        self.assertIn(run_tttoe_trials.board_text([None] * 9), prompts[1])
        self.assertIn("still X's turn", prompts[1])
        self.assertEqual(
            prompts[2], "Opponent played: X in square 1. Your move:"
        )


if __name__ == "__main__":
    unittest.main()
