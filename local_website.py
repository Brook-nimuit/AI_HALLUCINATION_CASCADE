"""Serve the local research website and a live, read-only trial-data endpoint."""

import argparse
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
from typing import Any

from experiments.web_trial_data import public_trial
from streamlit_dashboard import DATA_DIR, load_trials


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"
LOGGER = logging.getLogger(__name__)


def trials_payload(data_dir: Path) -> dict[str, Any]:
    trials = [public_trial(row) for row in load_trials(data_dir)]
    return {
        "updated_at": datetime.now().astimezone().isoformat(),
        "trial_count": len(trials),
        "trials": trials,
    }


def make_handler(data_dir: Path, web_root: Path) -> type[SimpleHTTPRequestHandler]:
    class LocalWebsiteHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_root), **kwargs)

        def do_GET(self) -> None:
            if self.path.split("?", 1)[0].rstrip("/") == "/api/trials":
                self._send_trials()
                return
            super().do_GET()

        def _send_trials(self) -> None:
            try:
                body = json.dumps(
                    trials_payload(data_dir),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            except Exception:
                LOGGER.exception("Could not load local research trial data")
                body = json.dumps(
                    {"error": "Could not load local research trial data."}
                ).encode("utf-8")
                self.send_response(500)
            else:
                self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return LocalWebsiteHandler


def serve(port: int, data_dir: Path = DATA_DIR, web_root: Path = WEB_ROOT) -> None:
    handler = make_handler(data_dir, web_root)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Local research website: http://127.0.0.1:{port}")
    print(f"Live trials endpoint:    http://127.0.0.1:{port}/api/trials")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local research website.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--web-root", type=Path, default=WEB_ROOT)
    args = parser.parse_args()
    serve(args.port, args.data_dir, args.web_root)


if __name__ == "__main__":
    main()
