"""Shape local trial records for display in the research website."""

from typing import Any


def public_trial(row: dict[str, Any]) -> dict[str, Any]:
    game = str(row["game"])
    status = str(row["trial_status"])
    reason = (
        "Stopped after gameplay began because of an API/provider error."
        if status == "partial_api_error"
        else str(row.get("reason") or "")
    )
    return {
        "game": game,
        "run_id": str(row["run_id"]),
        "trial_id": row["trial_id"],
        "model": str(row["model"]),
        "opponent_model": str(row["opponent_model"]),
        "result": str(row.get("display_result") or "No terminal result recorded"),
        "outcome": str(row.get("outcome_for_model") or "unfinished"),
        "status": status,
        "turns": int(row.get("turns") or 0),
        "wrong_response": str(row.get("wrong_response") or ""),
        "reason": reason[:400],
        "replay_url": {
            "chess": "/chess-replay/",
            "checkers": "/checkers-replay/",
        }.get(game),
    }
