"""Shared Supabase cloud logger and Tic-Tac-Toe response classifier."""

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Optional
from urllib.parse import quote

from dotenv import load_dotenv
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def classify_tictactoe_outcome(
    completed: bool,
    raw_response: Optional[str] = None,
    occupied_square: bool = False,
) -> tuple[str, str]:
    """
    Applies the 3-way Tic-Tac-Toe classification rule:
    1. Full valid trial -> ('completed', 'Complete trial')
    2. Is a number (not between 1-9, or occupied square) -> ('illegal_move', exact response)
    3. Isn't a number (or API_ERROR / truncated) -> ('api_error', 'RUN OUT OF TIME')
    """
    if completed:
        return "completed", "Complete trial"

    cleaned = (raw_response or "").strip()
    if cleaned.upper().startswith("API_ERROR"):
        return "api_error", "RUN OUT OF TIME"

    # Check if the response is a number (e.g. "0", "12", "-3", or an occupied square "5")
    if re.fullmatch(r"[-+]?\d+", cleaned):
        num = int(cleaned)
        if num < 1 or num > 9:
            return (
                "illegal_move",
                f"Chose number outside 1-9. Exact response: {cleaned}",
            )
        if occupied_square:
            return (
                "illegal_move",
                f"Chose already-occupied square. Exact response: {cleaned}",
            )

    # Not a number -> classify as RUN OUT OF TIME
    return "api_error", "RUN OUT OF TIME"


def log_trial_to_supabase(
    game: str,
    white_model: str,
    black_model: str,
    status: str,
    plies_survived: int,
    failure_reason: str = "Complete trial",
    board_print_requests: int = 0,
    exact_prompt: Optional[str] = None,
    trial_id: Optional[str] = None,
    replay_data: Optional[dict[str, Any]] = None,
) -> str:
    """Upserts a single trial record directly to Supabase."""
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    secret_key = os.getenv("SUPABASE_SECRET_KEY", "")

    if not supabase_url or not secret_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_trial_id = (
        trial_id or f"{game}__{white_model}__{timestamp}".replace(" ", "_").replace("/", "-")
    )

    headers = {
        "apikey": secret_key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    catalog_row: dict[str, Any] = {
        "trial_id": final_trial_id,
        "game": game.lower().strip(),
        "white_model": white_model.strip(),
        "black_model": black_model.strip(),
        "status": status,
        "plies_survived": int(plies_survived),
        "board_print_requests": int(board_print_requests),
        "failure_reason": failure_reason,
        "exact_prompt": exact_prompt,
        "has_replay": replay_data is not None,
        "source": "official",
    }

    catalog_url = f"{supabase_url}/rest/v1/trials_catalog?on_conflict={quote('trial_id')}"
    resp = requests.post(catalog_url, headers=headers, json=[catalog_row], timeout=20)
    if not resp.ok:
        raise RuntimeError(f"Supabase catalog insert failed ({resp.status_code}): {resp.text}")

    if replay_data is not None:
        replay_row = {
            "trial_id": final_trial_id,
            "game": game.lower().strip(),
            "replay_data": replay_data,
        }
        replay_url = f"{supabase_url}/rest/v1/trial_replays?on_conflict={quote('trial_id')}"
        r_resp = requests.post(replay_url, headers=headers, json=[replay_row], timeout=20)
        if not r_resp.ok:
            raise RuntimeError(f"Supabase replay insert failed ({r_resp.status_code}): {r_resp.text}")

    return final_trial_id

def classify_connect_four_outcome(
    completed: bool,
    raw_response: Optional[str] = None,
    column_full: bool = False,
    culprit_label: str = "",
) -> tuple[str, str]:
    """
    Applies the 3-way Connect Four classification rule:
    1. Full valid trial -> ('completed', 'Complete trial')
    2. Single letter outside A-G, or a valid column A-G that is full -> ('illegal_move', exact response)
    3. Non-letter / multi-word / API_ERROR / truncated -> ('api_error', 'RUN OUT OF TIME')
    """
    if completed:
        return "completed", "Complete trial"

    cleaned = (raw_response or "").strip()
    if not cleaned or cleaned.upper().startswith("API_ERROR"):
        return "api_error", "RUN OUT OF TIME"

    prefix = f"[{culprit_label}] " if culprit_label else ""

    # Check if the model returned a single letter (or "Column X")
    match = re.fullmatch(r"(?:column\s+)?([A-Za-z])\.?", cleaned, flags=re.IGNORECASE)
    if match:
        letter = match.group(1).upper()
        if letter < "A" or letter > "G":
            return (
                "illegal_move",
                f"{prefix}Out-of-bounds column '{letter}' (Next to A-G). Exact response: {cleaned!r}",
            )
        if column_full:
            return (
                "illegal_move",
                f"{prefix}Column {letter} is full (Gravity / Column Overflow Drift). Exact response: {cleaned!r}",
            )

    # Also catch if the model replied with a single digit (e.g. "4" instead of "D")
    if re.fullmatch(r"[-+]?\d+", cleaned):
        return (
            "illegal_move",
            f"{prefix}Replied with number instead of column letter A-G (Coordinate Format Drift). Exact response: {cleaned!r}",
        )

    # Otherwise, response was truncated or timed out
    return "api_error", "RUN OUT OF TIME"
def classify_uno_outcome(
    failed: bool,
    failure_reason: str = "",
    raw_response: str = "",
    culprit_model: str = "",
) -> tuple[str, str]:
    """
    3-way UNO classification rule:
    1. Valid completion (Game Won Legally / Max Turns Reached) -> ('completed', reason)
    2. API_ERROR or empty/truncated response -> ('api_error', 'RUN OUT OF TIME')
    3. Inventory Amnesia, Rule Mismatch, or Syntax Error -> ('illegal_move', exact reason + response)
    """
    if not failed:
        return "completed", failure_reason or "Game Won Legally"

    cleaned_raw = (raw_response or "").strip()
    cleaned_reason = (failure_reason or "").strip()

    if (
        not cleaned_raw
        or cleaned_raw.upper().startswith("API_ERROR")
        or cleaned_reason.upper().startswith("API_ERROR")
        or "truncated" in cleaned_reason.lower()
    ):
        return "api_error", "RUN OUT OF TIME"

    prefix = f"[{culprit_model}] " if culprit_model else ""
    if "Inventory Amnesia" in cleaned_reason:
        archetype = "(Inventory Amnesia)"
    elif "Rule Mismatch" in cleaned_reason:
        archetype = "(Rule Mismatch)"
    else:
        archetype = "(Syntax / Format Drift)"

    return (
        "illegal_move",
        f"{prefix}{cleaned_reason} {archetype} — Exact response: {cleaned_raw!r}",
    )


def slim_uno_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Strips heavy API metadata and deck arrays so the UNO replay JSON is ~3 KB."""
    slim_turns = []
    for t in audit.get("turns", []):
        pre = t.get("pre_state") or {}
        post = t.get("post_state") or {}
        slim_turns.append(
            {
                "turn": t.get("turn"),
                "player": t.get("player"),
                "model": t.get("model"),
                "user_prompt": t.get("user_prompt", ""),
                "raw_response": t.get("raw_response", ""),
                "action": t.get("action", t.get("raw_response", "")),
                "status": t.get("status", ""),
                "valid": bool(t.get("valid", False)),
                "reason": t.get("reason", ""),
                "top_card_before": pre.get("top_card", ""),
                "top_card_after": post.get("top_card", pre.get("top_card", "")),
                "hands_before": pre.get("hands", {}),
                "hands_after": post.get("hands", pre.get("hands", {})),
            }
        )

    init_state = audit.get("initial_state") or {}
    init_discard = init_state.get("discard_pile") or []

    return {
        "game": "uno",
        "model": audit.get("model", ""),
        "system_prompt": audit.get("system_prompt", ""),
        "turns_survived": audit.get("turns_survived", len(slim_turns)),
        "failed": bool(audit.get("failed", False)),
        "failure_reason": audit.get("failure_reason", ""),
        "winner": audit.get("winner"),
        "initial_top_card": init_discard[-1] if init_discard else "",
        "initial_hands": init_state.get("hands", {}),
        "turns": slim_turns,
    }
def classify_checkers_outcome(
    failed: bool,
    failure_reason: str = "",
    raw_response: str = "",
    culprit_label: str = "",
) -> tuple[str, str]:
    """
    3-way Checkers classification rule:
    1. Valid completion (Win / Draw / Max Plies Reached) -> ('completed', reason)
    2. API_ERROR or truncated/non-PDN response -> ('api_error', 'RUN OUT OF TIME')
    3. Parsed a 1-50 PDN move that violates Draughts rules -> ('illegal_move', reason + exact response)
    """
    if not failed:
        return "completed", failure_reason or "Max Plies Reached"

    cleaned_raw = (raw_response or "").strip()
    cleaned_reason = (failure_reason or "").strip()

    if (
        not cleaned_raw
        or cleaned_raw.upper().startswith("API_ERROR")
        or cleaned_reason.upper().startswith("API_ERROR")
        or "truncated" in cleaned_reason.lower()
    ):
        return "api_error", "RUN OUT OF TIME"

    # Check if the response contains a 1-50 PDN move like "31-26" or "31x22"
    has_pdn_move = bool(
        re.search(
            r"(?<!\d)(?:50|[1-4]\d|[1-9])(?!\d)(?:\s*[-xX×]\s*(?:50|[1-4]\d|[1-9])(?!\d))+",
            cleaned_raw,
        )
    )
    if not has_pdn_move:
        # Check if they tried algebraic chess notation like "e3-d4" or out-of-range numbers like "55-60"
        if re.search(r"\b\d+\s*[-xX×]\s*\d+\b", cleaned_raw) or re.search(
            r"\b[a-j][1-9]\b", cleaned_raw, flags=re.I
        ):
            prefix = f"[{culprit_label}] " if culprit_label else ""
            return (
                "illegal_move",
                f"{prefix}Invalid square range or notation (Coordinate Drift). Exact response: {cleaned_raw!r}",
            )
        return "api_error", "RUN OUT OF TIME"

    prefix = f"[{culprit_label}] " if culprit_label else ""
    return (
        "illegal_move",
        f"{prefix}{cleaned_reason} (Mandatory Capture / Illegal Trajectory) — Exact response: {cleaned_raw!r}",
    )


def slim_checkers_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Strips heavy API metadata and duplicate pre_boards so a 100-ply Checkers replay is ~6 KB."""
    slim_turns = []
    for t in audit.get("turns", []):
        slim_turns.append(
            {
                "ply": t.get("ply"),
                "player": t.get("player"),
                "model": t.get("model"),
                "user_prompt": t.get("user_prompt", ""),
                "raw_response": t.get("raw_response", ""),
                "parsed_path": t.get("parsed_path"),
                "move": t.get("move"),
                "captured_squares": t.get("captured_squares", []),
                "valid": bool(t.get("valid", False)),
                "status": t.get("status", ""),
                "reason": t.get("reason", ""),
                "post_board": t.get("post_board", {}),
            }
        )

    init_state = audit.get("initial_state") or {}
    return {
        "game": "international-draughts",
        "variant": audit.get("variant", "International Draughts (10x10)"),
        "run_id": audit.get("run_id", ""),
        "trial_id": audit.get("trial_id", ""),
        "players": audit.get("players", {}),
        "system_prompt": audit.get("system_prompt", ""),
        "winner": audit.get("winner"),
        "draw": bool(audit.get("draw", False)),
        "result": audit.get("result", ""),
        "failed": bool(audit.get("failed", False)),
        "failure_reason": audit.get("failure_reason", ""),
        "pdn": audit.get("pdn", ""),
        "initial_board": init_state.get("board", {}),
        "turns": slim_turns,
    }

def classify_chess_outcome(
    failed: bool,
    failure_reason: str = "",
    raw_response: str = "",
    culprit_label: str = "",
) -> tuple[str, str]:
    """
    3-way Chess classification rule:
    1. Valid completion (Checkmate / Draw / Max Plies Reached) -> ('completed', reason)
    2. API_ERROR or empty/truncated response -> ('api_error', 'RUN OUT OF TIME')
    3. Illegal SAN / trajectory / pin / phantom spawn -> ('illegal_move', reason)
    """
    if not failed:
        return "completed", failure_reason or "Completed (Max Plies Reached)"

    cleaned_raw = (raw_response or "").strip()
    cleaned_reason = (failure_reason or "").strip()

    if (
        not cleaned_raw
        or cleaned_raw.upper().startswith("API_ERROR")
        or cleaned_reason.upper().startswith("API_ERROR")
        or "truncated" in cleaned_reason.lower()
    ):
        return "api_error", "RUN OUT OF TIME"

    # Strip local snapshot file suffixes like "[Snapshot: snapshots/chess/...]"
    clean_desc = cleaned_reason.split("[Snapshot:")[0].strip()
    if clean_desc.startswith("["):
        return "illegal_move", clean_desc

    prefix = f"[{culprit_label}] " if culprit_label else ""
    return "illegal_move", f"{prefix}{clean_desc} — Exact response: {cleaned_raw!r}"


def slim_chess_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Strips heavy API metadata and snapshot paths so a Chess replay JSON is ~5 KB."""
    prompts_by_ply = {}
    for p in audit.get("prompts", []):
        if isinstance(p, dict) and p.get("ply") is not None:
            prompts_by_ply[int(p["ply"])] = p.get("user_prompt", "")

    raw_moves = audit.get("moves") or audit.get("ply_log") or []
    slim_moves = []
    for idx, m in enumerate(raw_moves):
        ply_num = int(m.get("ply") or (idx + 1))
        slim_moves.append(
            {
                "ply": ply_num,
                "actor": m.get("actor", "White" if ply_num % 2 == 1 else "Black"),
                "bot": m.get("bot", ""),
                "san": m.get("san", ""),
                "raw_response": m.get("raw_response", ""),
                "status": m.get("status", "LEGAL"),
                "reason": m.get("reason", ""),
                "pre_fen": m.get("pre_fen", ""),
                "post_fen": m.get("post_fen", ""),
                "prompt": m.get("prompt") or prompts_by_ply.get(ply_num, ""),
                "illegal_move": m.get("illegal_move"),
            }
        )

    return {
        "game": "chess",
        "trial_id": audit.get("trial_id"),
        "white_bot": audit.get("white_bot", ""),
        "black_bot": audit.get("black_bot", ""),
        "system_prompt": audit.get("system_prompt", ""),
        "failed": bool(audit.get("failed", False)),
        "failure_reason": str(audit.get("failure_reason", "")).split("[Snapshot:")[0].strip(),
        "plies_survived": int(audit.get("plies_survived", 0)),
        "board_print_requests": int(audit.get("board_print_requests", 0)),
        "result": audit.get("result", ""),
        "pgn": audit.get("pgn", ""),
        "moves": slim_moves,
    }
