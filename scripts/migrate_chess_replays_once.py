"""One-time migration of local Chess replays into Supabase trial_replays."""

import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT / "experiments"))

from cloud_logger import classify_chess_outcome, slim_chess_audit

DATA_DIR = PROJECT_ROOT / "data" / "local"


def load_local_chess_audits(data_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    # 1. Check results/chess_*.json batch files
    for json_file in sorted((data_dir / "results").glob("chess_*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            run_id = str(data.get("run_id", ""))
            for trial in data.get("trials", []):
                audit = trial.get("audit") or trial.get("match_log")
                if isinstance(audit, dict) and (audit.get("moves") or audit.get("ply_log")):
                    t_id = str(trial.get("trial_id", audit.get("trial_id", "")))
                    by_key[(run_id, t_id)] = audit
        except Exception as err:
            print(f"Skipping {json_file.name}: {err}")

    # 2. Check snapshots/chess/**/match_audit.json and replays/**/match_audit.json
    for root_folder in (data_dir / "snapshots" / "chess", data_dir / "replays"):
        if not root_folder.exists():
            continue
        for audit_path in root_folder.rglob("match_audit.json"):
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                if not isinstance(audit, dict):
                    continue
                t_id = str(audit.get("trial_id", ""))
                # Extract timestamp run_id from folder path if not inside JSON
                m = re.search(r"(\d{8}T\d{6,})", audit_path.as_posix())
                run_id = str(audit.get("run_id") or (m.group(1) if m else ""))
                if run_id and t_id:
                    by_key[(run_id, t_id)] = audit
                # Also index by parent folder name
                by_key[("folder", audit_path.parent.name)] = audit
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
        f"{supabase_url}/rest/v1/trials_catalog?game=eq.chess&select=*&limit=500",
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    chess_rows = resp.json()
    print(f"Found {len(chess_rows)} Chess rows in Supabase trials_catalog.")

    audits_index = load_local_chess_audits(DATA_DIR)
    print(f"Indexed {len(audits_index)} local Chess audit logs.")

    replay_batch = []
    catalog_updates = []

    for row in chess_rows:
        full_id = row["trial_id"]
        parts = full_id.split("__")
        run_tag = parts[2] if len(parts) > 2 else ""
        local_trial = parts[3].replace("Trial_", "") if len(parts) > 3 else ""

        audit = audits_index.get((run_tag, local_trial))
        if not audit and local_trial.isdigit():
            audit = audits_index.get((run_tag, str(int(local_trial))))
        if not audit:
            continue

        slimmed = slim_chess_audit(audit)
        moves = slimmed.get("moves", [])
        last_move = moves[-1] if moves else {}
        last_raw = str(last_move.get("raw_response") or last_move.get("san") or "")
        culprit_actor = str(last_move.get("actor", "White"))
        culprit_bot = str(last_move.get("bot") or row["white_model"])

        status, clean_reason = classify_chess_outcome(
            failed=bool(slimmed.get("failed")),
            failure_reason=str(slimmed.get("failure_reason", "")),
            raw_response=last_raw,
            culprit_label=f"{culprit_actor} / {culprit_bot}",
        )

        exact_prompt = slimmed.get("system_prompt") or ""
        if last_move.get("prompt"):
            exact_prompt = (
                f"System:\n{exact_prompt}\n\n"
                f"User (Ply {last_move.get('ply')}):\n{last_move.get('prompt')}"
            )

        replay_batch.append(
            {
                "trial_id": full_id,
                "game": "chess",
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
            print(f"Uploaded Chess replays {i + 1}..{i + len(chunk)} / {len(replay_batch)}")

    if catalog_updates:
        c_url = f"{supabase_url}/rest/v1/trials_catalog?on_conflict={quote('trial_id')}"
        for i in range(0, len(catalog_updates), 50):
            chunk = catalog_updates[i : i + 50]
            c_resp = requests.post(c_url, headers=upsert_headers, json=chunk, timeout=30)
            c_resp.raise_for_status()

    print(f"Done! Linked and uploaded {len(replay_batch)} Chess replays.")


if __name__ == "__main__":
    main()
