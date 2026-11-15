"""Prepare visualization exports, optionally pruning no-gameplay source data."""

import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "experiments"))
from trial_artifacts import (
    trial_has_api_error,
    trial_has_gameplay,
    write_json,
)

DEFAULT_INPUT = PROJECT_ROOT / "data" / "local"
DEFAULT_OUTPUT = DEFAULT_INPUT / "visualization-ready"
MODEL_RATES = {
    "gpt-4o": (2.50, 10.00),
    "gpt-6-astra": (10.00, 50.00),
    "gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-120b": (0.15, 0.60),
}
TARGET_VALID_TRIALS = 25
CSV_FIELDS = [
    "game",
    "run_id",
    "trial_id",
    "model",
    "opponent_model",
    "provider",
    "result",
    "winner",
    "outcome_for_model",
    "completion",
    "trial_status",
    "failure_reason",
    "turns",
    "board_print_requests",
    "input_tokens",
    "output_tokens",
    "estimated_cost_usd",
    "source_file",
    "wrong_response",
]
EXCLUDED_FIELDS = [
    "game",
    "run_id",
    "trial_id",
    "model",
    "opponent_model",
    "reason",
    "failure_detail",
    "input_tokens",
    "output_tokens",
    "estimated_cost_usd",
    "source_file",
]


def canonical_game(game: str) -> str:
    if game == "international-draughts":
        return "checkers"
    return game


def trial_audit(trial: dict[str, Any]) -> dict[str, Any]:
    audit = trial.get("match_log") or trial.get("audit") or {}
    return audit if isinstance(audit, dict) else {}


def trial_events(audit: dict[str, Any]) -> list[dict[str, Any]]:
    events = audit.get("moves") or audit.get("turns") or []
    return [event for event in events if isinstance(event, dict)]


def contains_api_error(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.upper()
        return "API_ERROR" in normalized or "API ERROR" in normalized
    if isinstance(value, dict):
        return any(contains_api_error(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_api_error(item) for item in value)
    return False


def exclusion_reason(trial: dict[str, Any]) -> str:
    return "" if trial_has_gameplay(trial) else "No model moves recorded"


def failure_detail(trial: dict[str, Any]) -> str:
    if trial_has_api_error(trial) and trial_has_gameplay(trial):
        return "Trial stopped after gameplay began because of an API/provider error."
    audit = trial_audit(trial)
    detail = trial.get("failure_reason") or audit.get("failure_reason")
    if detail:
        return str(detail).replace("\r", " ").replace("\n", " ")
    for event in trial_events(audit):
        response = str(event.get("raw_response") or "")
        if contains_api_error(response):
            return response.replace("\r", " ").replace("\n", " ")
        if event.get("valid") is False or str(event.get("status", "")).upper() in {
            "INVALID",
            "ILLEGAL",
        }:
            return str(event.get("reason") or response).replace("\r", " ").replace(
                "\n", " "
            )
    return "No recorded turns"


def models_for_trial(
    game: str, trial: dict[str, Any], configuration: dict[str, Any]
) -> tuple[str, str, str]:
    fields = {
        "chess": ("white_model", "black_model", "White"),
        "checkers": ("white_model", "black_model", "White"),
        "tic-tac-toe": ("x_model", "o_model", "X"),
        "connect-four": ("red_model", "yellow_model", "R"),
        "uno": ("model", "model", "Agent_A"),
    }
    main_key, opponent_key, main_seat = fields[game]
    model = (
        trial.get(main_key)
        or configuration.get(main_key)
        or trial.get("model")
        or configuration.get("model")
        or ""
    )
    opponent = (
        trial.get(opponent_key)
        or configuration.get(opponent_key)
        or (model if game == "uno" else "")
    )
    return str(model), str(opponent), main_seat


def event_usage(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata") or event.get("request_metadata") or {}
    if not isinstance(metadata, dict):
        return {}
    response = metadata.get("response") or metadata.get("provider_response") or {}
    if not isinstance(response, dict):
        return {}
    usage = response.get("usage")
    return usage if isinstance(usage, dict) else {}


def trial_result(
    game: str,
    trial: dict[str, Any],
    audit: dict[str, Any],
    main_seat: str,
    model: str,
    opponent: str,
) -> tuple[str, str, str]:
    winner = str(trial.get("winner") or audit.get("winner") or "")
    result = str(trial.get("result") or audit.get("result") or "")
    if game == "chess":
        result = str(audit.get("result") or result)
        winner = {"1-0": "White", "0-1": "Black", "1/2-1/2": "Draw"}.get(
            result, winner
        )
        outcome = {
            "1-0": "win" if main_seat == "White" else "loss",
            "0-1": "loss" if main_seat == "White" else "win",
            "1/2-1/2": "draw",
        }.get(result, "unfinished")
    elif game == "uno":
        if winner:
            outcome = f"{winner} wins"
        elif audit.get("turns_survived", trial.get("turns_survived", 0)) >= audit.get(
            "max_turns", 0
        ):
            outcome = "censored at max turns"
        else:
            outcome = "unfinished"
    elif winner:
        outcome = "win" if winner == main_seat else "loss"
    elif trial.get("draw") or audit.get("draw") or "draw" in result.lower():
        outcome = "draw"
    else:
        outcome = "unfinished"

    if model and model == opponent:
        outcome_for_model = f"self-play: {outcome}"
    else:
        outcome_for_model = outcome
    return result, winner, outcome_for_model


def trial_row(
    game: str,
    run_id: str,
    trial: dict[str, Any],
    configuration: dict[str, Any],
    source_file: str,
) -> dict[str, Any]:
    audit = trial_audit(trial)
    events = trial_events(audit)
    model, opponent, main_seat = models_for_trial(game, trial, configuration)
    result, winner, outcome = trial_result(
        game, trial, audit, main_seat, model, opponent
    )
    input_tokens = output_tokens = 0
    provider = str(audit.get("provider") or "")
    for event in events:
        metadata = event.get("metadata") or event.get("request_metadata") or {}
        if isinstance(metadata, dict) and not provider:
            provider = str(metadata.get("provider") or "")
        usage = event_usage(event)
        input_tokens += int(usage.get("prompt_tokens") or 0)
        output_tokens += int(usage.get("completion_tokens") or 0)
    rates = MODEL_RATES.get(model)
    estimated_cost = (
        (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
        if rates
        else None
    )
    board_requests = trial.get("board_print_requests", audit.get("board_print_requests"))
    turns = len(events)
    max_turns = audit.get("max_turns")
    completion = "max_turns" if (
        game == "uno"
        and max_turns
        and audit.get("turns_survived", trial.get("turns_survived", 0)) >= max_turns
    ) else "api_error_partial" if trial_has_api_error(trial) else (
        "terminal" if winner or trial.get("draw") or audit.get("draw") else "stopped"
    )
    invalid_events = any(
        event.get("valid") is False
        or str(event.get("status", "")).upper() in {"INVALID", "ILLEGAL"}
        for event in events
    )
    trial_status = (
        "partial_api_error"
        if trial_has_api_error(trial)
        else "invalid_or_illegal"
        if invalid_events or trial.get("failed")
        else "complete"
    )
    return {
        "game": game,
        "run_id": run_id,
        "trial_id": trial.get("trial_id", ""),
        "model": model,
        "opponent_model": opponent,
        "provider": provider,
        "result": result,
        "winner": winner,
        "outcome_for_model": outcome,
        "completion": completion,
        "trial_status": trial_status,
        "failure_reason": failure_detail(trial) if trial_status != "complete" else "",
        "wrong_response": (
            next(
                (
                    str(event.get("raw_response") or "")
                    for event in events
                    if event.get("valid") is False
                    and not str(event.get("raw_response") or "")
                    .upper()
                    .startswith("API_ERROR")
                ),
                "",
            )
            if game == "tic-tac-toe"
            else ""
        ),
        "turns": sum(
            str(event.get("status", "")).upper() != "API_ERROR"
            for event in events
        ),
        "board_print_requests": board_requests,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimated_cost,
        "source_file": source_file,
        "raw_trial": trial,
    }


def trial_key(game: str, run_id: str, trial_id: Any) -> tuple[str, str, int]:
    return canonical_game(game), str(run_id), int(trial_id)


def estimated_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    rates = MODEL_RATES.get(model)
    if not rates:
        return None
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def prune_unplayed_trials(input_dir: Path) -> dict[str, int]:
    """Remove only trial records and artifact folders with no model gameplay."""
    results_dir = input_dir / "results"
    removed_trials = 0
    removed_run_files = 0
    removed_csv_rows = 0
    removed_csv_files = 0
    removed_artifact_dirs = 0
    rejected_by_run: dict[str, set[str]] = {}

    for source in sorted(results_dir.glob("*.json")):
        try:
            run = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(run, dict) or not isinstance(run.get("trials"), list):
            continue
        rejected = [
            trial
            for trial in run["trials"]
            if isinstance(trial, dict) and not trial_has_gameplay(trial)
        ]
        if not rejected:
            continue
        run_id = str(run.get("run_id") or source.stem)
        rejected_ids = {str(trial.get("trial_id", "")) for trial in rejected}
        rejected_by_run[run_id] = rejected_ids
        run["trials"] = [
            trial
            for trial in run["trials"]
            if not isinstance(trial, dict) or trial not in rejected
        ]
        removed_trials += len(rejected)
        if run["trials"]:
            write_json(source, run)
        else:
            source.unlink()
            removed_run_files += 1

    for run_id, rejected_ids in rejected_by_run.items():
        for csv_path in results_dir.glob("*.csv"):
            if run_id not in csv_path.name:
                continue
            try:
                with csv_path.open(encoding="utf-8-sig", newline="") as file:
                    reader = csv.DictReader(file)
                    fieldnames = reader.fieldnames or []
                    rows = list(reader)
            except OSError:
                continue
            kept_rows = [
                row
                for row in rows
                if str(row.get("trial_id", "")) not in rejected_ids
            ]
            removed_csv_rows += len(rows) - len(kept_rows)
            if kept_rows:
                write_csv(csv_path, fieldnames, kept_rows)
            else:
                csv_path.unlink(missing_ok=True)
                removed_csv_files += 1

    gameplay_by_run: dict[str, set[str]] = {}
    for source in results_dir.glob("*.json"):
        try:
            run = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(run, dict) or not isinstance(run.get("trials"), list):
            continue
        run_id = str(run.get("run_id") or source.stem)
        gameplay_by_run[run_id] = {
            str(trial.get("trial_id", ""))
            for trial in run["trials"]
            if isinstance(trial, dict) and trial_has_gameplay(trial)
        }

    for csv_path in results_dir.glob("*.csv"):
        try:
            with csv_path.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                fieldnames = reader.fieldnames or []
                rows = list(reader)
        except OSError:
            continue
        matching_run = next(
            (run_id for run_id in gameplay_by_run if run_id in csv_path.name),
            None,
        )
        gameplay_trials = (
            gameplay_by_run.get(matching_run, set()) if matching_run else set()
        )

        retained_rows = []
        has_partial_errors = False
        csv_changed = False
        for row in rows:
            error_fields = [
                key
                for key, value in row.items()
                if key != "trial_status" and contains_api_error(value)
            ]
            if not error_fields:
                retained_rows.append(row)
                continue
            if str(row.get("trial_id", "")) not in gameplay_trials:
                removed_csv_rows += 1
                csv_changed = True
                continue
            for key in error_fields:
                row[key] = (
                    "Stopped after gameplay began because of an API/provider error."
                    if key == "failure_reason"
                    else ""
                )
            row["trial_status"] = "partial_api_error"
            has_partial_errors = True
            csv_changed = True
            retained_rows.append(row)

        if has_partial_errors and "trial_status" not in fieldnames:
            fieldnames.append("trial_status")
        if retained_rows and csv_changed:
            write_csv(csv_path, fieldnames, retained_rows)
        if not retained_rows:
            csv_path.unlink(missing_ok=True)
            removed_csv_files += 1

    for artifact_root in (input_dir / "snapshots", input_dir / "replays"):
        if not artifact_root.exists():
            continue
        for audit_path in list(artifact_root.rglob("match_audit.json")):
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(audit, dict) and not trial_has_gameplay({"audit": audit}):
                shutil.rmtree(audit_path.parent)
                removed_artifact_dirs += 1

    return {
        "removed_trials": removed_trials,
        "removed_run_files": removed_run_files,
        "removed_csv_rows": removed_csv_rows,
        "removed_csv_files": removed_csv_files,
        "removed_artifact_dirs": removed_artifact_dirs,
    }


def summarize_groups(
    all_trials: list[dict[str, Any]], excluded: list[dict[str, Any]]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0,
            "clean": 0,
            "excluded": 0,
            "outcomes": Counter(),
            "clean_input": 0,
            "clean_output": 0,
            "clean_cost": 0.0,
            "rated_clean": 0,
            "all_cost": 0.0,
            "rated_trials": 0,
        }
    )
    for row in all_trials:
        key = (row["game"], row["model"], row["opponent_model"])
        group = groups[key]
        group["total"] += 1
        group["clean"] += 1
        group["outcomes"][row["outcome_for_model"]] += 1
        group["clean_input"] += row["input_tokens"]
        group["clean_output"] += row["output_tokens"]
        if row["estimated_cost_usd"] is not None:
            group["all_cost"] += row["estimated_cost_usd"]
            group["clean_cost"] += row["estimated_cost_usd"]
            group["rated_clean"] += 1
            group["rated_trials"] += 1
    for row in excluded:
        key = (row["game"], row["model"], row["opponent_model"])
        group = groups[key]
        group["total"] += 1
        group["excluded"] += 1
        group["all_cost"] += row.get("estimated_cost_usd") or 0.0
        if row.get("estimated_cost_usd") is not None:
            group["rated_trials"] += 1
    return groups


def report_markdown(
    input_dir: Path,
    run_files: int,
    empty_runs: int,
    rows: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    groups: dict[tuple[str, str, str], dict[str, Any]],
    snapshot_dirs: int,
    replay_dirs: int,
    skipped_temps: int,
) -> str:
    statuses = Counter(row["trial_status"] for row in rows)
    lines = [
        "# Local Trial Results and Research Status",
        "",
        f"Generated: {datetime.now().astimezone().isoformat()}",
        "",
        "## Research data export",
        "",
        f"- Source: `{input_dir}`.",
        f"- Run JSON files inspected: {run_files}; empty run files: {empty_runs}.",
        f"- Research trials retained: {len(rows)}.",
        f"- Trial statuses: {', '.join(f'{name}={count}' for name, count in sorted(statuses.items())) or 'none'}.",
        f"- Snapshot trial folders copied: {snapshot_dirs}; replay folders copied: "
        f"{replay_dirs}; temporary files skipped: {skipped_temps}.",
        "- Trials are retained when a model attempted at least one move/action, "
        "including invalid/illegal moves. Partial games remain when an API/provider "
        "error occurs after gameplay begins. No-play attempts are omitted.",
        "- `board_print_requests` is included when present in the source audit; "
        "blank values mean that older runs did not record the count, not zero.",
        "",
        "Files: `results/clean_trials.csv`, `results/clean_trials.json`, "
        "`results/filtered_runs/`, filtered `snapshots/`, and gameplay-backed "
        "Chess `replays/`. The `clean_trials` filename is retained for compatibility; "
        "it includes invalid/illegal moves and partial matches.",
        "",
        "## Results by matchup",
        "",
        "| Game | Model | Opponent | Trials | Outcomes | Mean input/output tokens per trial | Estimated cost per trial |",
        "|---|---|---|---:|---|---:|---:|",
    ]
    for (game, model, opponent), group in sorted(groups.items()):
        trial_count = group["total"]
        if not group["total"]:
            continue
        means = (
            f"{group['clean_input'] / trial_count:.0f}/"
            f"{group['clean_output'] / trial_count:.0f}"
            if trial_count
            else "n/a"
        )
        cost = (
            f"${group['clean_cost'] / group['rated_clean']:.4f}"
            if group["rated_clean"]
            else "unknown"
        )
        outcome_counts = ", ".join(
            f"{name}: {count}"
            for name, count in sorted(group["outcomes"].items())
        ) or "none"
        lines.append(
            f"| {game} | {model} | {opponent or '—'} | "
            f"{trial_count} | {outcome_counts} | {means} | {cost} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation notes",
            "",
            "- Invalid/illegal moves are included as model-behavior data, but should "
            "be separated from legal outcomes when evaluating win rates.",
            "- Partial API-error trials are included only if gameplay had already "
            "begun; their result is incomplete.",
            "- Treat turn/ply-limited games as censored, not decisive wins/losses.",
            "- Token-derived cost estimates are approximate and are not invoices.",
        ]
    )
    return "\n".join(lines) + "\n"


def projected_budget(
    rows: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    groups: dict[tuple[str, str, str], dict[str, Any]],
) -> float:
    plans = [
        ("chess", "gpt-4o", "random", "clean_average"),
        ("checkers", "gpt-6-astra", "random", "observed_attempts"),
        ("tic-tac-toe", "gpt-6-astra", "random", "clean_average"),
        ("connect-four", "gpt-4o", "random", "clean_average"),
        ("uno", "gpt-4o", "gpt-4o", "clean_average"),
    ]
    total = 0.0
    for game, model, opponent, basis in plans:
        group = groups.get((game, model, opponent))
        if not group or group["clean"] >= TARGET_VALID_TRIALS or not group["clean"]:
            continue
        gap = TARGET_VALID_TRIALS - group["clean"]
        if basis == "observed_attempts" and group["total"]:
            success_rate = group["clean"] / group["total"]
            if success_rate:
                total += gap / success_rate * group["all_cost"] / group["total"]
            continue
        mean_cost = (
            group["clean_cost"] / group["rated_clean"]
            if group["rated_clean"]
            else 0
        )
        total += gap * mean_cost
    return total


def copy_artifacts(
    input_dir: Path,
    output_dir: Path,
    clean_keys: set[tuple[str, str, int]],
) -> tuple[int, int, int]:
    snapshot_dirs = replay_dirs = skipped_temps = 0
    supported_names = {"match_audit.json", "match.pgn", "match.pdn"}

    for audit_path in (input_dir / "snapshots").rglob("match_audit.json"):
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            key = trial_key(
                audit.get("game", audit_path.parents[2].name),
                audit.get("run_id") or audit_path.parent.parent.name,
                audit["trial_id"],
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if key not in clean_keys:
            continue
        game, run_id, _ = key
        target = output_dir / "snapshots" / game / run_id / audit_path.parent.name
        target.mkdir(parents=True, exist_ok=True)
        for source in audit_path.parent.iterdir():
            if not source.is_file():
                continue
            if source.suffix == ".tmp":
                skipped_temps += 1
                continue
            if (
                source.name in supported_names
                or (source.name.startswith("state_") and source.suffix in {".json", ".png"})
                or source.name.startswith("ply_") and source.suffix == ".png"
            ):
                shutil.copy2(source, target / source.name)
        snapshot_dirs += 1

    replay_source = input_dir / "replays"
    copied_replay_dirs: set[str] = set()
    for source in replay_source.rglob("*"):
        if not source.is_file():
            continue
        if source.suffix == ".tmp":
            skipped_temps += 1
            continue
        relative_path = source.relative_to(replay_source)
        audit_path = source.parent / "match_audit.json"
        if audit_path.is_file():
            try:
                replay_audit = json.loads(audit_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                replay_audit = None
            if isinstance(replay_audit, dict) and not trial_has_gameplay(
                {"audit": replay_audit}
            ):
                continue
        target = output_dir / "replays" / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if len(relative_path.parts) > 1:
            copied_replay_dirs.add(relative_path.parts[0])
    replay_dirs = len(copied_replay_dirs)
    return snapshot_dirs, replay_dirs, skipped_temps


def prepare(
    input_dir: Path,
    output_dir: Path,
    *,
    raw_data_modified: bool = False,
) -> dict[str, Any]:
    results_dir = input_dir / "results"
    run_files = sorted(results_dir.glob("*.json"))
    if not run_files:
        raise FileNotFoundError(f"No run JSON files found in {results_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Refusing to overwrite non-empty output directory: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    clean_runs: list[dict[str, Any]] = []
    clean_keys: set[tuple[str, str, int]] = set()
    empty_runs = 0

    for source in run_files:
        try:
            run = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(run, dict) or not isinstance(run.get("trials"), list):
            continue
        game = canonical_game(str(run.get("game") or source.stem.split("_")[0]))
        run_id = str(run.get("run_id") or source.stem)
        configuration = run.get("configuration") or {}
        accepted_trials = []
        if not run["trials"]:
            empty_runs += 1
        for trial in run["trials"]:
            if not isinstance(trial, dict):
                continue
            model, opponent, _ = models_for_trial(game, trial, configuration)
            reason = exclusion_reason(trial)
            if reason:
                continue
            row = trial_row(game, run_id, trial, configuration, source.name)
            clean_rows.append(row)
            accepted_trials.append(trial)
            clean_keys.add(trial_key(game, run_id, trial.get("trial_id")))
        if accepted_trials:
            filtered_run = dict(run)
            filtered_run["trials"] = accepted_trials
            filtered_run["visualization_filter"] = "passed validity/error filter"
            clean_runs.append({"file": source.name, "data": filtered_run})

    clean_csv_rows = [
        {field: row.get(field) for field in CSV_FIELDS}
        for row in clean_rows
    ]
    write_csv(output_dir / "results" / "clean_trials.csv", CSV_FIELDS, clean_csv_rows)
    write_csv(
        output_dir / "results" / "excluded_trials.csv",
        EXCLUDED_FIELDS,
        excluded_rows,
    )
    (output_dir / "results" / "clean_trials.json").write_text(
        json.dumps(
            [{key: value for key, value in row.items() if key != "raw_trial"} for row in clean_rows],
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    filtered_runs_dir = output_dir / "results" / "filtered_runs"
    filtered_runs_dir.mkdir(parents=True, exist_ok=True)
    for entry in clean_runs:
        (filtered_runs_dir / entry["file"]).write_text(
            json.dumps(entry["data"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    snapshot_dirs, replay_dirs, _ = copy_artifacts(
        input_dir, output_dir, clean_keys
    )
    skipped_temps = sum(
        1
        for folder in (input_dir / "snapshots", input_dir / "replays")
        for path in folder.rglob("*.tmp")
    )
    groups = summarize_groups(clean_rows, excluded_rows)
    report = report_markdown(
        input_dir,
        len(run_files),
        empty_runs,
        clean_rows,
        excluded_rows,
        groups,
        snapshot_dirs,
        replay_dirs,
        skipped_temps,
    )
    (output_dir / "research_status.md").write_text(report, encoding="utf-8")
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_directory": str(input_dir),
        "raw_data_modified": raw_data_modified,
        "run_json_files": len(run_files),
        "empty_run_files": empty_runs,
        "clean_trials": len(clean_rows),
        "research_trials": len(clean_rows),
        "excluded_trials": len(excluded_rows),
        "clean_snapshot_directories": snapshot_dirs,
        "chess_replay_directories": replay_dirs,
        "temporary_files_skipped": skipped_temps,
        "clean_games": dict(Counter(row["game"] for row in clean_rows)),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--prune-unplayed",
        action="store_true",
        help="Delete run records and trial artifact folders where no model move was played.",
    )
    parser.add_argument(
        "--replace-output",
        action="store_true",
        help="Replace the generated visualization-ready exports.",
    )
    args = parser.parse_args()
    if args.replace_output and args.output_dir.exists():
        generated_names = {
            "results",
            "snapshots",
            "replays",
            "manifest.json",
            "research_status.md",
        }
        unexpected = {
            path.name for path in args.output_dir.iterdir()
        } - generated_names
        if unexpected:
            parser.error(
                "Refusing to replace output directory with unexpected contents: "
                + ", ".join(sorted(unexpected))
            )
        for name in generated_names:
            target = args.output_dir / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
    if args.prune_unplayed:
        print(json.dumps(prune_unplayed_trials(args.input_dir), indent=2))
    manifest = prepare(
        args.input_dir,
        args.output_dir,
        raw_data_modified=args.prune_unplayed,
    )
    print(json.dumps(manifest, indent=2))
    report_path = str(args.output_dir / "research_status.md")
    safe_report_path = report_path.encode("ascii", "backslashreplace").decode("ascii")
    print(f"Research report: {safe_report_path}")


if __name__ == "__main__":
    main()
