import sys
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "experiments" / "uno"))

import run_simulations


class UnoRefereeTests(unittest.TestCase):
    def setUp(self):
        self.game = run_simulations.UnoReferee.__new__(run_simulations.UnoReferee)
        self.game.hands = {
            "Agent_A": [
                run_simulations.Card("Red", "5"),
                run_simulations.Card("Green", "3"),
            ],
            "Agent_B": [],
        }
        self.game.discard_pile = [run_simulations.Card("Blue", "5")]
        self.game.deck = [run_simulations.Card("Yellow", "1")]

    def test_valid_card_is_removed_and_discarded(self):
        valid, reason = self.game.validate_and_play("Agent_A", "PLAY red 5")

        self.assertTrue(valid)
        self.assertEqual(reason, "Valid Move")
        self.assertEqual(self.game.hands["Agent_A"], [run_simulations.Card("Green", "3")])
        self.assertEqual(self.game.top_card, run_simulations.Card("Red", "5"))

    def test_rejects_card_that_does_not_match_top_card(self):
        valid, reason = self.game.validate_and_play("Agent_A", "PLAY Green 3")

        self.assertFalse(valid)
        self.assertIn("Rule Mismatch", reason)
        self.assertEqual(len(self.game.hands["Agent_A"]), 2)

    def test_draw_adds_one_card_to_hand(self):
        valid, reason = self.game.validate_and_play("Agent_A", "DRAW")

        self.assertTrue(valid)
        self.assertEqual(reason, "Valid Draw")
        self.assertEqual(self.game.hands["Agent_A"][-1], run_simulations.Card("Yellow", "1"))

    def test_provider_inference(self):
        self.assertEqual(run_simulations.infer_provider("openai/gpt-oss-120b"), "groq")
        self.assertEqual(run_simulations.infer_provider("gemini-2.0-flash"), "gemini")
        self.assertEqual(run_simulations.infer_provider("deepseek-r1:7b"), "ollama")

    def test_main_rejects_unreplaced_angle_bracket_model_placeholder(self):
        with patch("sys.argv", [
            "run_simulations.py",
            "--model",
            "<gemini-3.8-flash>",
            "--provider",
            "gemini",
            "--trials",
            "15",
        ]), patch.object(run_simulations, "create_client") as create_client:
            with self.assertRaises(SystemExit) as error:
                run_simulations.main()

        self.assertEqual(error.exception.code, 2)
        create_client.assert_not_called()

    def test_astra_uses_completion_token_limit_and_low_reasoning(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="DRAW"))],
            model_dump=lambda mode: {},
        )
        client = run_simulations.OpenAI(api_key="test-key")
        with patch.object(
            client.chat.completions, "create", return_value=response
        ) as create:
            result = run_simulations.query_model(
                "system",
                "user",
                "astra-model",
                "openai",
                client,
            )

        self.assertEqual(result, "DRAW")
        self.assertEqual(create.call_args.kwargs["reasoning_effort"], "low")
        self.assertEqual(create.call_args.kwargs["max_completion_tokens"], 300)
        self.assertNotIn("temperature", create.call_args.kwargs)
        self.assertNotIn("max_tokens", create.call_args.kwargs)

    def test_non_astra_requests_keep_default_token_limit(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="DRAW"))],
            model_dump=lambda mode: {},
        )
        client = run_simulations.OpenAI(api_key="test-key")
        with patch.object(
            client.chat.completions, "create", return_value=response
        ) as create:
            result = run_simulations.query_model(
                "system",
                "user",
                "gpt-4o",
                "openai",
                client,
            )

        self.assertEqual(result, "DRAW")
        self.assertNotIn("reasoning_effort", create.call_args.kwargs)
        self.assertEqual(create.call_args.kwargs["temperature"], 0.2)
        self.assertEqual(create.call_args.kwargs["max_tokens"], 300)
        self.assertNotIn("max_completion_tokens", create.call_args.kwargs)

    def test_request_keeps_private_turn_history_and_sends_only_latest_action(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="PLAY Red 5"))],
            model_dump=lambda mode: {},
        )
        client = run_simulations.OpenAI(api_key="test-key")
        conversation = [
            {"role": "user", "content": "Game start. Initial discard: Blue 5."},
            {"role": "assistant", "content": "PLAY Red 5"},
        ]
        user_prompt = (
            "Opponent played: Green 7. Your hand: [Red 7, Green 3]. "
            "Choose a legal action."
        )
        with patch.object(
            client.chat.completions, "create", return_value=response
        ) as create:
            result = run_simulations.query_model(
                "system",
                user_prompt,
                "gpt-4o",
                "openai",
                client,
                conversation=conversation,
            )

        self.assertEqual(result, "PLAY Red 5")
        messages = create.call_args.kwargs["messages"]
        self.assertEqual(messages[1:4], conversation[:2] + [
            {"role": "user", "content": user_prompt}
        ])
        self.assertEqual(
            conversation[-2:],
            [
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": "PLAY Red 5"},
            ],
        )

    def test_trial_writes_turn_log_and_full_state_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            csv_path = output_dir / "results" / "summary.csv"
            with patch.object(run_simulations, "query_model", return_value="DRAW"):
                run_simulations.execute_batch(
                    "test-model",
                    "openai",
                    object(),
                    csv_path,
                    1,
                    1,
                    output_dir=output_dir,
                    run_id="test-run",
                )

            match_dir = output_dir / "snapshots" / "uno" / "test-run" / "test-model_trial_001"
            audit = json.loads((match_dir / "match_audit.json").read_text(encoding="utf-8"))
            results = json.loads(
                (output_dir / "results" / "uno_test-run.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                results["trials"][0]["match_log"]["turns"][0]["raw_response"],
                "DRAW",
            )
            self.assertEqual(len(audit["turns"]), 1)
            self.assertEqual(len(list(match_dir.glob("state_*.json"))), 2)

    def test_trial_retries_malformed_play_response_with_format_feedback(self):
        responses = iter(("PLAY", "DRAW"))
        prompts = []

        def fake_query(
            system_prompt,
            user_prompt,
            model_name,
            provider,
            client,
            response_details,
            conversation,
        ):
            prompts.append(user_prompt)
            return next(responses)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with patch.object(run_simulations, "query_model", side_effect=fake_query):
                result = run_simulations.run_trial(
                    1,
                    "test-model",
                    "openai",
                    object(),
                    max_turns=1,
                    output_dir=output_dir,
                    run_id="format-retry",
                )

            match_dir = (
                output_dir
                / "snapshots"
                / "uno"
                / "format-retry"
                / "test-model_trial_001"
            )
            audit = json.loads(
                (match_dir / "match_audit.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(prompts), 2)
        self.assertIn("invalid syntax", prompts[1])
        self.assertIn("Your hand:", prompts[1])
        self.assertEqual(
            [attempt["raw_response"] for attempt in audit["turns"][0]["response_attempts"]],
            ["PLAY", "DRAW"],
        )
        self.assertEqual(audit["turns"][0]["raw_response"], "DRAW")


if __name__ == "__main__":
    unittest.main()
