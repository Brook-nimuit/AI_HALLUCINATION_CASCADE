"""One-time migration of local UNO turn-by-turn replays into Supabase trial_replays."""

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

from cloud_logger import classify_uno_outcome, slim_uno_audit

DATA_DIR = PROJECT_ROOT / "data" / "local"


def load_local_uno_audits(data_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Indexes local UNO match_audit dicts by (run_id, str(trial_id)) and (model, str(trial_id))."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    # 1. Check results/uno_*.json batch files
    for json_file in sorted((data_dir / "results").glob("uno_*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            run_id = str(data.get("run_id", ""))
            for trial in data.get("trials", []):
                audit = trial.get("match_log")
                if isinstance(audit, dict) and audit.get("turns"):
                    t_id = str(trial.get("trial_id", audit.get("trial_id", "")))
                    model = str(trial.get("model", audit.get("model", "")))
                    by_key[(run_id, t_id)] = audit
                    by_key[(model, f"{run_id}_{t_id}")] = audit
        except Exception as err:
            print(f"Skipping {json_file.name}: {err}")

    # 2. Check snapshots/uno/**/match_audit.json
    uno_snap_dir = data_dir / "snapshots" / "uno"
    if uno_snap_dir.exists():
        for audit_path in uno_snap_dir.rglob("match_audit.json"):
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                if isinstance(audit, dict) and audit.get("turns"):
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

    headers = {
        "apikey": secret_key,
        "Content-Type": "application/json",
    }

    # Fetch existing UNO catalog rows from Supabase
    resp = requests.get(
        f"{supabase_url}/rest/v1/trials_catalog?game=eq.uno&select=*&limit=500",
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    uno_rows = resp.json()
    print(f"Found {len(uno_rows)} UNO rows in Supabase trials_catalog.")

    audits_index = load_local_uno_audits(DATA_DIR)
    print(f"Indexed {len(audits_index)} local UNO audit logs.")

    replay_batch = []
    catalog_updates = []

    for row in uno_rows:
        full_id = row["trial_id"]
        parts = full_id.split("__")
        # Format: uno__<model>__<run_tag>__<local_trial>__<index>
        run_tag = parts[2] if len(parts) > 2 else ""
        local_trial = parts[3].replace("Trial_", "") if len(parts) > 3 else ""

        audit = audits_index.get((run_tag, local_trial))
        if not audit:
            continue

        slimmed = slim_uno_audit(audit)
        turns = slimmed.get("turns", [])
        last_turn = turns[-1] if turns else {}
        last_raw = last_turn.get("raw_response", "")

        status, clean_reason = classify_uno_outcome(
            failed=bool(slimmed.get("failed")),
            failure_reason=str(slimmed.get("failure_reason", "")),
            raw_response=str(last_raw),
            culprit_model=row["white_model"],
        )

        exact_prompt = slimmed.get("system_prompt") or ""
        if last_turn.get("user_prompt"):
            exact_prompt = f"System:\n{exact_prompt}\n\nUser (Turn {last_turn.get('turn')}):\n{last_turn.get('user_prompt')}"

        replay_batch.append(
            {
                "trial_id": full_id,
                "game": "uno",
                "replay_data": slimmed,
            }
        )

        row["status"] = status
        row["failure_reason"] = clean_reason
        row["has_replay"] = True
        row["exact_prompt"] = exact_prompt
        catalog_updates.append(row)

    upsert_headers = {
        **headers,
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    if replay_batch:
        r_url = f"{supabase_url}/rest/v1/trial_replays?on_conflict={quote('trial_id')}"
        for i in range(0, len(replay_batch), 50):
            chunk = replay_batch[i : i + 50]
            r_resp = requests.post(r_url, headers=upsert_headers, json=chunk, timeout=30)
            r_resp.raise_for_status()
            print(f"Uploaded UNO replays {i + 1}..{i + len(chunk)} / {len(replay_batch)}")

    if catalog_updates:
        c_url = f"{supabase_url}/rest/v1/trials_catalog?on_conflict={quote('trial_id')}"
        for i in range(0, len(catalog_updates), 50):
            chunk = catalog_updates[i : i + 50]
            c_resp = requests.post(c_url, headers=upsert_headers, json=chunk, timeout=30)
            c_resp.raise_for_status()

    print(f"Done! Linked and uploaded {len(replay_batch)} UNO turn-by-turn replays.")


if __name__ == "__main__":
    main()