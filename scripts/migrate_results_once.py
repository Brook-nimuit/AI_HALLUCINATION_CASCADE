"""One-time migration of local trial results into Supabase trials_catalog."""

from collections import defaultdict
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

from experiments.web_trial_data import public_trial
from streamlit_dashboard import DATA_DIR, load_trials


def first_present(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        val = row.get(key)
        if val is not None and str(val).strip() != "":
            return val
    return default


def normalize_status(row: dict[str, Any]) -> str:
    raw = str(first_present(row, ["status", "result", "outcome"], "")).lower()
    reason = str(first_present(row, ["failure_reason", "reason", "notes"], "")).lower()
    failed = row.get("failed")

    if "api" in raw or "api" in reason or "partial" in raw:
        return "api_error"
    if failed is True or "illegal" in raw or "invalid" in raw or "fail" in raw:
        return "illegal_move"
    if failed is False or "complete" in raw or "valid" in raw or "max turns" in reason:
        return "completed"
    return "illegal_move"


def build_unique_trial_id(raw_row: dict[str, Any], pub_row: dict[str, Any], index: int) -> str:
    game = str(first_present(pub_row, ["game", "game_name", "experiment"], "unknown")).lower().strip()
    white = str(first_present(pub_row, ["white_model", "model", "model_a", "agent_a"], "model")).strip()

    # Pull batch/run timestamp or source path so "Trial 1" from two runs never collide
    run_tag = str(
        first_present(
            raw_row,
            ["run_id", "batch_id", "timestamp", "completed_at", "source_file", "path", "audit_path"],
            "",
        )
        or first_present(
            pub_row,
            ["run_id", "batch_id", "timestamp", "completed_at", "trial_label"],
            "",
        )
    ).strip()

    local_trial = str(
        first_present(pub_row, ["trial_id", "trial", "id", "match_id"], f"row_{index:04d}")
    ).strip()

    # Clean characters so it makes a safe URL/database key
    combined = f"{game}__{white}__{run_tag}__{local_trial}__{index:04d}"
    return combined.replace(" ", "_").replace("/", "-")


def to_catalog_record(raw_row: dict[str, Any], index: int) -> dict[str, Any]:
    row = public_trial(raw_row)

    game = str(first_present(row, ["game", "game_name", "experiment"], "unknown")).lower().strip()
    white = str(first_present(row, ["white_model", "model", "model_a", "agent_a", "x_model"], "unknown")).strip()
    black = str(
        first_present(row, ["black_model", "opponent_model", "model_b", "agent_b", "o_model", "opponent"], white)
    ).strip()

    trial_id = build_unique_trial_id(raw_row, row, index)

    plies = int(first_present(row, ["plies_survived", "turns_survived", "turns", "plies", "move_count"], 0) or 0)
    prints = int(first_present(row, ["board_print_requests", "print_requests", "tool_calls"], 0) or 0)
    reason = str(first_present(row, ["failure_reason", "reason", "terminal_reason", "notes"], "Completed")).strip()

    return {
        "trial_id": trial_id,
        "game": game,
        "white_model": white,
        "black_model": black,
        "status": normalize_status(row),
        "plies_survived": plies,
        "board_print_requests": prints,
        "failure_reason": reason,
        "has_replay": False,
        "source": "official",
    }


def assign_round_robin_page_order(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        by_game[rec["game"]].append(rec)

    ordered: list[dict[str, Any]] = []
    game_names = sorted(by_game.keys())

    while any(by_game.values()):
        for game in game_names:
            bucket = by_game[game]
            ordered.extend(bucket[:5])
            by_game[game] = bucket[5:]

    for page_idx, rec in enumerate(ordered, start=1):
        rec["page_order"] = page_idx

    return ordered


def clear_existing_official_rows(url: str, secret_key: str) -> None:
    endpoint = f"{url.rstrip('/')}/rest/v1/trials_catalog?source=eq.official"
    headers = {"apikey": secret_key}
    requests.delete(endpoint, headers=headers, timeout=30)


def upload_in_batches(url: str, secret_key: str, records: list[dict[str, Any]]) -> None:
    endpoint = f"{url.rstrip('/')}/rest/v1/trials_catalog?on_conflict={quote('trial_id')}"
    headers = {
        "apikey": secret_key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    batch_size = 100
    for start in range(0, len(records), batch_size):
        chunk = records[start : start + batch_size]
        response = requests.post(endpoint, headers=headers, json=chunk, timeout=30)
        if not response.ok:
            raise RuntimeError(f"Batch {start} failed ({response.status_code}): {response.text}")
        print(f"Uploaded rows {start + 1}..{start + len(chunk)} / {len(records)}")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    supabase_url = os.getenv("SUPABASE_URL")
    secret_key = os.getenv("SUPABASE_SECRET_KEY")

    if not supabase_url or not secret_key:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")

    raw_trials = list(load_trials(DATA_DIR))
    print(f"Loaded {len(raw_trials)} local trials from {DATA_DIR}")

    records = [to_catalog_record(raw, idx) for idx, raw in enumerate(raw_trials, start=1)]
    catalog_rows = assign_round_robin_page_order(records)

    # Print breakdown by game so we can verify before uploading
    counts_by_game: dict[str, int] = defaultdict(int)
    for r in catalog_rows:
        counts_by_game[r["game"]] += 1
    print("Breakdown by game:", dict(counts_by_game))

    clear_existing_official_rows(supabase_url, secret_key)
    upload_in_batches(supabase_url, secret_key, catalog_rows)
    print(f"One-time catalog migration complete! All {len(catalog_rows)} rows uploaded.")


if __name__ == "__main__":
    main()