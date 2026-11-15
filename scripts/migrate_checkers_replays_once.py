"""One-time migration of local Checkers replays into Supabase trial_replays."""

import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT / "experiments"))

from cloud_logger import classify_checkers_outcome, slim_checkers_audit

DATA_DIR = PROJECT_ROOT / "data" / "local"


def load_local_checkers_audits(data_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for json_file in sorted((data_dir / "results").glob("checkers_*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            run_id = str(data.get("run_id", ""))
            for trial in data.get("trials", []):
                audit = trial.get("match_log")
                if isinstance(audit, dict) and audit.get("turns") is not None:
                    t_id = str(trial.get("trial_id", audit.get("trial_id", "")))
                    by_key[(run_id, t_id)] = audit
        except Exception as err:
            print(f"Skipping {json_file.name}: {err}")

    snap_dir = data_dir / "snapshots" / "checkers"
    if snap_dir.exists():
        for audit_path in snap_dir.rglob("match_audit.json"):
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                if isinstance(audit, dict) and audit.get("turns") is not None:
                    run_id = str(audit.get("run_id", ""))
                    t_id = str(audit.get("trial_id", ""))
                    by_key[(run_id, t_id)] = audit
            except Exception:
                pass

    return by_key


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    secret_key = os.getenv("SUPABASE_SECRET_KEY", "")
    if not supabase_url or not secret_key:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")

    headers = {"apikey": secret_key, "Content-Type": "application/json"}
    resp = requests.get(
        f"{supabase_url}/rest/v1/trials_catalog?game=eq.checkers&select=*&limit=500",
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    checkers_rows = resp.json()
    print(f"Found {len(checkers_rows)} Checkers rows in Supabase trials_catalog.")

    audits_index = load_local_checkers_audits(DATA_DIR)
    print(f"Indexed {len(audits_index)} local Checkers audit logs.")

    replay_batch = []
    catalog_updates = []

    for row in checkers_rows:
        full_id = row["trial_id"]
        parts = full_id.split("__")
        run_tag = parts[2] if len(parts) > 2 else ""
        local_trial = parts[3].replace("Trial_", "") if len(parts) > 3 else ""

        audit = audits_index.get((run_tag, local_trial))
        if not audit:
            continue

        slimmed = slim_checkers_audit(audit)
        turns = slimmed.get("turns", [])
        last_turn = turns[-1] if turns else {}
        last_raw = str(last_turn.get("raw_response", ""))
        culprit_player = str(last_turn.get("player", "White"))
        culprit_model = str(last_turn.get("model", row["white_model"]))

        status, clean_reason = classify_checkers_outcome(
            failed=bool(slimmed.get("failed")),
            failure_reason=str(slimmed.get("failure_reason", "")),
            raw_response=last_raw,
            culprit_label=f"{culprit_player} / {culprit_model}",
        )

        exact_prompt = slimmed.get("system_prompt") or ""
        if last_turn.get("user_prompt"):
            exact_prompt = (
                f"System:\n{exact_prompt}\n\n"
                f"User (Ply {last_turn.get('ply')}):\n{last_turn.get('user_prompt')}"
            )

        replay_batch.append(
            {
                "trial_id": full_id,
                "game": "checkers",
                "replay_data": slimmed,
            }
        )

        row["status"] = status
        row["failure_reason"] = clean_reason
        row["has_replay"] = True
        row["exact_prompt"] = exact_prompt
        catalog_updates.append(row)

    upsert_headers = {**headers, "Prefer": "resolution=merge-duplicates,return=minimal"}

    if replay_batch:
        r_url = f"{supabase_url}/rest/v1/trial_replays?on_conflict={quote('trial_id')}"
        for i in range(0, len(replay_batch), 50):
            chunk = replay_batch[i : i + 50]
            r_resp = requests.post(r_url, headers=upsert_headers, json=chunk, timeout=30)
            r_resp.raise_for_status()
            print(f"Uploaded Checkers replays {i + 1}..{i + len(chunk)} / {len(replay_batch)}")

    if catalog_updates:
        c_url = f"{supabase_url}/rest/v1/trials_catalog?on_conflict={quote('trial_id')}"
        for i in range(0, len(catalog_updates), 50):
            chunk = catalog_updates[i : i + 50]
            c_resp = requests.post(c_url, headers=upsert_headers, json=chunk, timeout=30)
            c_resp.raise_for_status()

    print(f"Done! Linked and uploaded {len(replay_batch)} Checkers replays.")


if __name__ == "__main__":
    main()