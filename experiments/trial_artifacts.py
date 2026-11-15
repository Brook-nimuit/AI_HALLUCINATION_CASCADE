"""Shared helpers for durable, machine-readable experiment artifacts."""

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any


API_ERROR_PREFIXES = ("API_ERROR:", "API ERROR:")
API_ERROR_STATUS = "API_ERROR"


def trial_events(trial: dict[str, Any]) -> list[dict[str, Any]]:
    audit = trial.get("audit") or trial.get("match_log") or {}
    if not isinstance(audit, dict):
        return []
    events = audit.get("moves") or audit.get("turns") or audit.get("actions") or []
    return [event for event in events if isinstance(event, dict)]


def trial_has_gameplay(trial: dict[str, Any]) -> bool:
    events = trial_events(trial)
    if events:
        return any(
            str(event.get("status", "")).upper() != API_ERROR_STATUS
            and not str(event.get("raw_response") or "").strip().upper().startswith(
                API_ERROR_PREFIXES
            )
            for event in events
        )
    return any(
        int(trial.get(field) or 0) > 0
        for field in ("plies_survived", "plies_played", "moves_played", "turns_survived")
    )


def trial_has_api_error(trial: dict[str, Any]) -> bool:
    if any(
        str(event.get("status", "")).upper() == API_ERROR_STATUS
        or str(event.get("raw_response") or "").strip().upper().startswith(
            API_ERROR_PREFIXES
        )
        for event in trial_events(trial)
    ):
        return True
    return str(trial.get("failure_reason") or "").strip().upper().startswith(
        API_ERROR_PREFIXES
    )


def trial_csv_row(trial: dict[str, Any]) -> dict[str, Any] | None:
    """Return a research CSV row; omit failures before gameplay and redact API errors."""
    if not trial_has_gameplay(trial):
        return None

    row = dict(trial)
    api_error = trial_has_api_error(trial)
    row["trial_status"] = "partial_api_error" if api_error else (
        "invalid_or_illegal" if trial.get("failed") else "complete"
    )
    if api_error:
        row["failure_reason"] = "Stopped after gameplay began because of an API/provider error."
        row["raw_response"] = ""
    return row


def write_json(path: Path, payload: Any) -> None:
    """Atomically write JSON, retrying transient file locks from sync clients."""
    write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_text(path: Path, content: str) -> None:
    """Atomically write UTF-8 text, retrying transient file locks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        for attempt in range(8):
            try:
                temporary_path.replace(path)
                return
            except PermissionError as error:
                if attempt == 7:
                    raise PermissionError(
                        f"Could not replace {path} after 8 attempts; "
                        "another process may be holding the file open."
                    ) from error
                time.sleep(min(0.1 * (2**attempt), 1.0))
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_state_snapshot(directory: Path, step: int, state: dict[str, Any]) -> Path:
    path = directory / f"state_{step:03d}.json"
    write_json(path, state)
    return path
