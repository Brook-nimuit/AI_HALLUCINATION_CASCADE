import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
