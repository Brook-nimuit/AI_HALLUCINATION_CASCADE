import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

from local_website import make_handler


class LocalWebsiteTests(unittest.TestCase):
    def test_api_serves_current_gameplay_backed_trials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            results_dir = data_dir / "results"
            results_dir.mkdir(parents=True)
            run = {
                "game": "chess",
                "run_id": "test-run",
                "configuration": {"white_model": "gpt-4o", "black_model": "random"},
                "trials": [
                    {
                        "trial_id": 1,
                        "audit": {
                            "moves": [{"ply": 1, "san": "e4", "status": "LEGAL"}]
                        },
                    }
                ],
            }
            (results_dir / "chess_test-run.json").write_text(
                json.dumps(run), encoding="utf-8"
            )
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(data_dir, Path(temp_dir))
            )
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/api/trials"
                with urlopen(url, timeout=5) as response:
                    payload = json.loads(response.read())
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(payload["trial_count"], 1)
                self.assertEqual(payload["trials"][0]["game"], "chess")
                self.assertEqual(payload["trials"][0]["replay_url"], "/chess-replay/")

                run["trials"].append(
                    {
                        "trial_id": 2,
                        "audit": {
                            "moves": [{"ply": 1, "san": "d4", "status": "LEGAL"}]
                        },
                    }
                )
                (results_dir / "chess_test-run.json").write_text(
                    json.dumps(run), encoding="utf-8"
                )
                with urlopen(url, timeout=5) as response:
                    updated_payload = json.loads(response.read())
                self.assertEqual(updated_payload["trial_count"], 2)
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def test_api_reports_data_loading_errors_as_server_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                make_handler(Path(temp_dir), Path(temp_dir)),
            )
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                with patch("local_website.load_trials", side_effect=OSError("locked")):
                    try:
                        urlopen(
                            f"http://127.0.0.1:{server.server_port}/api/trials",
                            timeout=5,
                        )
                    except HTTPError as error:
                        self.assertEqual(error.code, 500)
                        error.close()
                    else:
                        self.fail("Data loading failure should return HTTP 500.")
            finally:
                server.shutdown()
                thread.join()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
