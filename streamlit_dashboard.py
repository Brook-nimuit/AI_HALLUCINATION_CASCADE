"""Data loading and replay rendering shared by the Streamlit research pages."""

import json
import re
from pathlib import Path
from typing import Any

import streamlit as st

from experiments.prepare_visualization_data import (
    canonical_game,
    failure_detail,
    models_for_trial,
    trial_audit,
    trial_events,
    trial_row,
)
from experiments.trial_artifacts import trial_has_gameplay


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data" / "local"


def _model_label(value: Any) -> str:
    return re.sub(r"\s+\((?:White|Black|X|O|Red|Yellow)\)$", "", str(value or ""))


def _display_result(row: dict[str, Any]) -> str:
    result = row.get("result") or ""
    winner = row.get("winner") or ""
    if result:
        return str(result)
    if winner:
        return f"{winner} wins"
    status = row.get("trial_status")
    if status == "partial_api_error":
        return "Partial game; stopped after gameplay began"
    if status == "invalid_or_illegal":
        return "Invalid/illegal move recorded"
    completion = row.get("completion")
    if completion == "max_turns":
        return "Stopped at turn limit"
    return "No terminal result recorded"


def _make_row(
    game: str,
    run_id: str,
    trial: dict[str, Any],
    configuration: dict[str, Any],
    source_file: str,
    audit_path: Path | None,
) -> dict[str, Any] | None:
    audit = trial_audit(trial)
    if not trial_has_gameplay(trial):
        return None
    row = trial_row(game, run_id, trial, configuration, source_file)
    row["game"] = canonical_game(game)
    row["audit"] = audit
    row["events"] = trial_events(audit)
    row["wrong_response"] = str(
        trial.get("wrong_response")
        or next(
            (
                event.get("raw_response")
                for event in row["events"]
                if event.get("valid") is False
                and not str(event.get("raw_response") or "").upper().startswith(
                    "API_ERROR"
                )
            ),
            "",
        )
        if row["game"] == "tic-tac-toe"
        else ""
    )
    row["audit_path"] = str(audit_path) if audit_path else ""
    row["trial_key"] = f"{row['game']}|{run_id}|{row['trial_id']}|{source_file}"
    row["display_result"] = _display_result(row)
    row["reason"] = (
        row.get("failure_reason") or failure_detail(trial)
        if row["trial_status"] != "complete"
        else ""
    )
    row["moves"] = len(
        [
            event
            for event in row["events"]
            if str(event.get("status", "")).upper() != "API_ERROR"
        ]
    )
    return row


def _replay_only_trial(audit_path: Path, data_dir: Path) -> dict[str, Any] | None:
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(audit, dict):
        return None

    relative = audit_path.relative_to(data_dir)
    path_parts = relative.parts
    if path_parts[0] == "replays":
        game = "chess"
        legacy_id = audit_path.parent.name
    elif len(path_parts) > 1 and path_parts[0] == "snapshots":
        game = canonical_game(audit.get("game") or path_parts[1])
        legacy_id = audit_path.parent.name
    else:
        return None
    if game not in {"chess", "checkers"}:
        return None

    trial_id = audit.get("trial_id")
    if trial_id is None:
        match = re.search(r"trial[_-](\d+)", audit_path.parent.name, re.IGNORECASE)
        if not match:
            return None
        trial_id = int(match.group(1))

    players = audit.get("players") or {}
    white_model = _model_label(
        players.get("White") or audit.get("white_bot") or audit.get("white_model")
    )
    black_model = _model_label(
        players.get("Black") or audit.get("black_bot") or audit.get("black_model")
    )
    if not white_model:
        white_model = "Unknown model"
    if not black_model:
        black_model = "Unknown opponent"

    folder_run_id = re.search(r"(20\d{6}T\d{12,})", legacy_id)
    run_id = str(
        audit.get("run_id")
        or (folder_run_id.group(1) if folder_run_id else f"replay:{legacy_id}")
    )
    trial = {
        "trial_id": trial_id,
        "white_model": white_model,
        "black_model": black_model,
        "model": white_model,
        "winner": audit.get("winner", ""),
        "result": audit.get("result", ""),
        "failed": audit.get("failed", False),
        "failure_reason": audit.get("failure_reason", ""),
        "plies_survived": audit.get("plies_survived", audit.get("plies_played", 0)),
        "audit": audit,
    }
    if game == "checkers":
        trial["white_model"] = players.get("White") or white_model
        trial["black_model"] = players.get("Black") or black_model
    if game == "chess":
        completed = re.search(r"Completed \((1-0|0-1|1/2-1/2)\)", str(audit.get("failure_reason", "")))
        if completed:
            trial["result"] = completed.group(1)
            trial["audit"]["result"] = completed.group(1)

    configuration = {
        "white_model": trial["white_model"],
        "black_model": trial["black_model"],
        "x_model": trial["white_model"],
        "o_model": trial["black_model"],
    }
    return _make_row(
        game,
        run_id,
        trial,
        configuration,
        audit_path.name,
        audit_path,
    )


def load_trials(data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    known_keys: set[tuple[str, str, str]] = set()
    results_dir = data_dir / "results"

    for source in sorted(results_dir.glob("*.json")):
        try:
            run = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(run, dict) or not isinstance(run.get("trials"), list):
            continue
        game = canonical_game(
            str(run.get("game") or source.stem.split("_")[0])
        )
        run_id = str(run.get("run_id") or source.stem)
        configuration = run.get("configuration") or {}
        for trial in run["trials"]:
            if not isinstance(trial, dict):
                continue
            row = _make_row(
                game,
                run_id,
                trial,
                configuration,
                source.name,
                None,
            )
            if row is None:
                continue
            key = (row["game"], str(run_id), str(row["trial_id"]))
            known_keys.add(key)
            row["trial_key"] = f"{game}|{run_id}|{row['trial_id']}"
            rows.append(row)

    for root in (data_dir / "snapshots", data_dir / "replays"):
        if not root.exists():
            continue
        for audit_path in sorted(root.rglob("match_audit.json")):
            row = _replay_only_trial(audit_path, data_dir)
            if row is None:
                continue
            key = (row["game"], str(row["run_id"]), str(row["trial_id"]))
            if key in known_keys:
                continue
            known_keys.add(key)
            rows.append(row)

    return sorted(
        rows,
        key=lambda row: (
            row["game"],
            row["model"],
            row["run_id"],
            str(row["trial_id"]),
        ),
    )


def _format_trial(row: dict[str, Any]) -> str:
    return (
        f"{row['run_id']} · Trial {row['trial_id']} · "
        f"{row['model']} vs {row['opponent_model']} · {row['trial_status']}"
    )


def _chess_snapshot_path(row: dict[str, Any], ply: int) -> Path | None:
    if row.get("audit_path"):
        audit_path = Path(row["audit_path"])
        if audit_path.parent.name and audit_path.parent.exists():
            matches = sorted(audit_path.parent.glob(f"ply_{ply:02d}_*.png"))
            if matches:
                return matches[0]

    safe_model = re.sub(r"[^a-zA-Z0-9_-]", "_", str(row["model"]))
    trial_id = int(row["trial_id"])
    folder = DATA_DIR / "replays" / f"{safe_model}_{row['run_id']}_trial_{trial_id:02d}"
    matches = sorted(folder.glob(f"ply_{ply:02d}_*.png"))
    return matches[0] if matches else None


def _chess_position(events: list[dict[str, Any]], selected_ply: int):
    import chess

    board = chess.Board()
    for event in events:
        if int(event.get("ply", 0) or 0) > selected_ply:
            break
        if str(event.get("status", "")).upper() != "LEGAL":
            continue
        san = str(event.get("san") or "")
        if san:
            try:
                board.push_san(san)
            except ValueError:
                break
    return board


def render_replay_page(game: str) -> None:
    rows = [row for row in load_trials() if row["game"] == game]
    st.title(f"{game.replace('-', ' ').title()} replays")
    if not rows:
        st.info("No gameplay-backed replay audits are available yet.")
        return

    preferred = st.session_state.get("selected_trial_key")
    labels = {_format_trial(row): row for row in rows}
    preferred_label = next(
        (label for label, row in labels.items() if row["trial_key"] == preferred),
        next(iter(labels)),
    )
    selected_label = st.selectbox(
        "Select a trial",
        list(labels),
        index=list(labels).index(preferred_label),
    )
    row = labels[selected_label]
    st.session_state["selected_trial_key"] = row["trial_key"]
    st.caption(
        f"Result: {row['display_result']} · Status: {row['trial_status']} · "
        f"Recorded turns: {row['turns']}"
    )
    if row.get("reason"):
        st.warning(row["reason"])

    events = row["events"]
    max_ply = max(
        (int(event.get("ply", index + 1) or index + 1) for index, event in enumerate(events)),
        default=0,
    )
    selected_ply = st.slider("Ply / turn", 0, max_ply, max_ply, key=f"{game}-ply")
    current_event = next(
        (
            event
            for index, event in enumerate(events)
            if int(event.get("ply", index + 1) or index + 1) == selected_ply
        ),
        None,
    )

    if current_event:
        st.write(
            f"**{current_event.get('actor') or current_event.get('player') or 'Turn'}** "
            f"· {current_event.get('san') or current_event.get('move') or 'No move'} "
            f"· {current_event.get('status') or ('valid' if current_event.get('valid') else 'invalid')}"
        )
        if current_event.get("reason"):
            st.caption(current_event["reason"])

    if game == "chess":
        board = _chess_position(events, selected_ply)
        image_path = _chess_snapshot_path(row, selected_ply)
        left, right = st.columns(2)
        with left:
            st.subheader("Board position")
            st.code(board.unicode(empty_square="·", borders=True), language=None)
            st.caption(f"FEN: {board.fen()}")
        with right:
            if image_path and image_path.is_file():
                st.image(str(image_path), caption=image_path.name, use_container_width=True)
            st.subheader("Move history")
            st.code(
                board.variation_san(list(board.move_stack))
                if board.move_stack
                else "(starting position)"
            )
    else:
        state = {}
        if current_event:
            state = current_event.get("post_board") or current_event.get("pre_board") or {}
        if not state:
            state = row["audit"].get("final_state") or row["audit"].get("initial_state") or {}
            if isinstance(state, dict):
                state = state.get("board", state)
        st.subheader("Recorded board state")
        if isinstance(state, dict):
            st.dataframe(
                [{"Square": square, "Piece": piece} for square, piece in sorted(
                    state.items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else 0
                )],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.json(state)

    st.subheader("Move / turn audit")
    if events:
        st.dataframe(
            [
                {
                    "Ply": event.get("ply", index + 1),
                    "Player": event.get("actor") or event.get("player"),
                    "Model": event.get("bot") or event.get("model"),
                    "Move": event.get("san") or event.get("move") or event.get("raw_response"),
                    "Status": event.get("status") or ("VALID" if event.get("valid") else "INVALID"),
                    "Reason": event.get("reason", ""),
                }
                for index, event in enumerate(events)
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("This replay has no per-turn event list.")
