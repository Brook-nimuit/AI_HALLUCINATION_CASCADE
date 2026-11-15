import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "experiments"))

from trial_artifacts import trial_csv_row, trial_has_gameplay, write_json


class WriteJsonTests(unittest.TestCase):
    def test_retries_transient_replace_permission_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "audit.json"
            target.write_text('{"old": true}\n', encoding="utf-8")
            path_type = type(target)
            real_replace = path_type.replace
            attempts = 0

            def replace_with_transient_lock(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("Temporary sync-client lock")
                return real_replace(source, destination)

            with (
                patch.object(path_type, "replace", replace_with_transient_lock),
                patch("trial_artifacts.time.sleep"),
            ):
                write_json(target, {"new": "value"})

            self.assertEqual(attempts, 3)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")), {"new": "value"}
            )
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])
            self.assertEqual(list(Path(temp_dir).glob(".*.tmp")), [])

    def test_reports_persistent_replace_permission_error_and_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "audit.json"
            target.write_text('{"old": true}\n', encoding="utf-8")
            path_type = type(target)
            attempts = 0

            def replace_with_persistent_lock(source, destination):
                nonlocal attempts
                attempts += 1
                raise PermissionError("Persistent sync-client lock")

            with (
                patch.object(path_type, "replace", replace_with_persistent_lock),
                patch("trial_artifacts.time.sleep"),
                self.assertRaisesRegex(
                    PermissionError, "Could not replace .* after 8 attempts"
                ),
            ):
                write_json(target, {"new": "value"})

            self.assertEqual(attempts, 8)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")), {"old": True}
            )
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])
            self.assertEqual(list(Path(temp_dir).glob(".*.tmp")), [])

    def test_api_error_before_gameplay_is_not_a_csv_trial(self):
        trial = {
            "failed": 1,
            "failure_reason": "API_ERROR: invalid model",
            "raw_response": "API_ERROR: invalid model",
            "audit": {
                "moves": [{"status": "API_ERROR", "raw_response": "API_ERROR: invalid model"}]
            },
        }

        self.assertFalse(trial_has_gameplay(trial))
        self.assertIsNone(trial_csv_row(trial))

    def test_partial_game_is_retained_and_api_error_text_is_redacted_from_csv(self):
        trial = {
            "failed": 1,
            "failure_reason": "API_ERROR: rate limit",
            "raw_response": "API_ERROR: rate limit",
            "audit": {
                "moves": [
                    {"status": "ILLEGAL", "raw_response": "not a legal move"},
                    {"status": "API_ERROR", "raw_response": "API_ERROR: rate limit"},
                ]
            },
        }

        row = trial_csv_row(trial)

        self.assertIsNotNone(row)
        self.assertEqual(row["trial_status"], "partial_api_error")
        self.assertNotIn("API_ERROR", row["failure_reason"])
        self.assertEqual(row["raw_response"], "")
        self.assertTrue(trial_has_gameplay(trial))


if __name__ == "__main__":
    unittest.main()
