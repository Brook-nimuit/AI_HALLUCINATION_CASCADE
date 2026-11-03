"""Run chess state-tracking trials against OpenAI-compatible chat models."""

import argparse
import csv
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path

import chess
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from openai import APIError, OpenAI, RateLimitError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "local"
CONFIG_PARAMS = {
    "temperature": 0.7,
    "max_tokens_standard": 150,
    "max_completion_tokens_astra": 2500,
}
SYSTEM_PROMPT = """You are an engine playing headless chess.
You will receive the chronological move history in standard algebraic notation (SAN).
Determine the board state and output ONLY your next move in valid standard algebraic notation.
Do not write explanations, commentary, sentences, punctuation, or move numbers.
Output exactly ONE move token (e.g. e4, Nf3, Bxc6, O-O, Qh4#)."""
PIECE_SYMBOLS = {
    "P": "♙",
    "N": "♘",
    "B": "♗",
    "R": "♖",
    "Q": "♕",
    "K": "♔",
    "p": "♟",
    "n": "♞",
    "b": "♝",
    "r": "♜",
    "q": "♛",
    "k": "♚",
}


def clean_api_key(value: str | None) -> str | None:
    if not value:
        return None
    return (
        value.strip()
        .strip('"')
        .strip("'")
        .replace("\u201c", "")
        .replace("\u201d", "")
        .replace("\u2018", "")
        .replace("\u2019", "")
    )


def provider_for_model(model_name: str) -> str:
    lowered = model_name.lower()
    if lowered.startswith("gpt-") or "astra" in lowered:
        return "openai"
    return "groq"


def create_clients(
    model_names: list[str],
    openai_api_key: str | None = None,
    groq_api_key: str | None = None,
) -> dict[str, OpenAI]:
    required_providers = {
        provider_for_model(name)
        for name in model_names
        if name.lower() not in {"random", "self"}
    }
    keys = {
        "openai": clean_api_key(openai_api_key or os.getenv("OPENAI_API_KEY")),
        "groq": clean_api_key(groq_api_key or os.getenv("GROQ_API_KEY")),
    }
    clients: dict[str, OpenAI] = {}
    for provider in required_providers:
        if not keys[provider]:
            env_name = f"{provider.upper()}_API_KEY"
            raise ValueError(
                f"Set {env_name} or pass the corresponding --{provider}-api-key option."
            )
        if provider == "groq":
            clients[provider] = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=keys[provider],
            )
        else:
            clients[provider] = OpenAI(api_key=keys[provider])
    return clients


def get_match_folder(
    model_name: str, trial_id: int, output_dir: Path, run_id: str
) -> Path:
    safe_model = re.sub(r"[^a-zA-Z0-9_-]", "_", model_name)
    folder = output_dir / "replays" / f"{safe_model}_{run_id}_trial_{trial_id:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _draw_board(
    ax: plt.Axes,
    board: chess.Board,
    highlight: chess.Square | None = None,
    move_squares: tuple[chess.Square | None, chess.Square | None] = (None, None),
) -> None:
    light_square, dark_square = "#f0d9b5", "#b58863"
    from_square, to_square = move_squares
    for row in range(8):
        for column in range(8):
            square = chess.square(column, 7 - row)
            color = light_square if (row + column) % 2 == 0 else dark_square
            if square == highlight:
                color = "#f4a261"
            elif square == to_square:
                color = "#e63946"
            elif square == from_square:
                color = "#e9c46a"
            ax.add_patch(
                plt.Rectangle(
                    (column, 7 - row), 1, 1, facecolor=color, edgecolor="none"
                )
            )
            if column == 0:
                ax.text(
                    -0.35,
                    7 - row + 0.5,
                    str(8 - row),
                    va="center",
                    ha="center",
                    fontsize=10,
                    fontweight="bold",
                    color="#aaaaaa",
                )
            if row == 7:
                ax.text(
                    column + 0.5,
                    -0.35,
                    chr(ord("a") + column),
                    va="center",
                    ha="center",
                    fontsize=10,
                    fontweight="bold",
                    color="#aaaaaa",
                )
            piece = board.piece_at(square)
            if piece:
                ax.text(
                    column + 0.5,
                    7 - row + 0.45,
                    PIECE_SYMBOLS[piece.symbol()],
                    fontfamily="DejaVu Sans",
                    va="center",
                    ha="center",
                    fontsize=28,
                    color="#ffffff" if piece.color == chess.WHITE else "#111111",
                    fontweight="bold",
                )
    ax.set_xlim(-0.7, 8.5)
    ax.set_ylim(-0.7, 8.5)
    ax.set_aspect("equal")
    ax.axis("off")


def save_board_snapshot(
    board: chess.Board,
    folder: Path,
    plies: int,
    actor: str,
    bot_name: str,
    last_move_str: str = "",
) -> Path:
    safe_move = re.sub(r"[^a-zA-Z0-9_+#=-]", "", last_move_str)
    suffix = f"_{safe_move}" if safe_move else ""
    save_path = folder / f"ply_{plies:02d}_{actor.lower()}{suffix}.png"

    fig, ax = plt.subplots(figsize=(6, 6), facecolor="#1e1e1e")
    ax.set_facecolor("#1e1e1e")
    _draw_board(ax, board)
    title = f"Ply {plies:02d} ({actor}) | {bot_name}"
    if last_move_str:
        title += f" - Move: {last_move_str}"
    ax.set_title(title, fontsize=11, fontweight="bold", color="#ffffff", pad=12)
    plt.tight_layout()
    fig.savefig(save_path, dpi=140, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return save_path


def simulate_illegal_board(
    board: chess.Board, attempted_san: str
) -> tuple[chess.Board, chess.Square | None, chess.Square | None, str]:
    after_board = board.copy(stack=False)
    turn_color = board.turn
    color_name = "White" if turn_color == chess.WHITE else "Black"
    clean = attempted_san.replace("+", "").replace("#", "").strip()
    king_home = chess.E1 if turn_color == chess.WHITE else chess.E8
    rank = 0 if turn_color == chess.WHITE else 7

    if clean in {"O-O", "0-0", "O-O-O", "0-0-0"}:
        king_to_file, rook_from_file, rook_to_file = (
            (6, 7, 5) if clean in {"O-O", "0-0"} else (2, 0, 3)
        )
        king_to = chess.square(king_to_file, rank)
        rook_from = chess.square(rook_from_file, rank)
        rook_to = chess.square(rook_to_file, rank)
        after_board.remove_piece_at(king_home)
        after_board.remove_piece_at(rook_from)
        after_board.set_piece_at(king_to, chess.Piece(chess.KING, turn_color))
        after_board.set_piece_at(rook_to, chess.Piece(chess.ROOK, turn_color))
        castle = "O-O" if king_to_file == 6 else "O-O-O"
        return after_board, king_home, king_to, f"Illegal {color_name} Castling ({castle})"

    destination_match = re.search(r"([a-h][1-8])", clean)
    if not destination_match:
        return after_board, None, None, f"Unparseable Token: '{attempted_san}'"

    to_square = chess.parse_square(destination_match.group(1))
    piece_types = {
        "N": chess.KNIGHT,
        "B": chess.BISHOP,
        "R": chess.ROOK,
        "Q": chess.QUEEN,
        "K": chess.KING,
    }
    piece_type = piece_types.get(clean[0], chess.PAWN)
    piece_symbol = chess.Piece(piece_type, turn_color).symbol()
    candidates = list(board.pieces(piece_type, turn_color))
    from_square = None

    if piece_type == chess.PAWN and clean[0] in "abcdefgh":
        origin_file = ord(clean[0]) - ord("a")
        same_file = [
            square for square in candidates if chess.square_file(square) == origin_file
        ]
        if same_file:
            from_square = min(
                same_file, key=lambda square: chess.square_distance(square, to_square)
            )
    elif candidates:
        prefix = clean[: destination_match.start()].replace("x", "")
        if prefix and prefix[0] in piece_types:
            prefix = prefix[1:]
        if len(prefix) == 1 and prefix in "abcdefgh":
            file_index = ord(prefix) - ord("a")
            candidates = [
                square
                for square in candidates
                if chess.square_file(square) == file_index
            ] or candidates
        elif len(prefix) == 1 and prefix in "12345678":
            rank_index = int(prefix) - 1
            candidates = [
                square
                for square in candidates
                if chess.square_rank(square) == rank_index
            ] or candidates
        from_square = min(
            candidates, key=lambda square: chess.square_distance(square, to_square)
        )

    occupant = board.piece_at(to_square)
    if from_square is not None and from_square != to_square:
        after_board.remove_piece_at(from_square)
        after_board.set_piece_at(to_square, chess.Piece(piece_type, turn_color))
        if occupant:
            description = (
                f"Forced {piece_symbol}: {chess.square_name(from_square)} → "
                f"{chess.square_name(to_square)} (Overwrote '{occupant.symbol()}')"
            )
        else:
            description = (
                f"Forced {piece_symbol}: {chess.square_name(from_square)} → "
                f"{chess.square_name(to_square)} (Illegal Trajectory / Pin)"
            )
    elif from_square == to_square:
        description = (
            f"Self-Collision: {color_name} {piece_symbol} is ALREADY on "
            f"{chess.square_name(to_square)}"
        )
    else:
        after_board.set_piece_at(to_square, chess.Piece(piece_type, turn_color))
        description = f"Phantom Spawn: Created {piece_symbol} on {chess.square_name(to_square)}"
    return after_board, from_square, to_square, description


def save_before_after_snapshot(
    board: chess.Board,
    attempted_san: str,
    folder: Path,
    trial_id: int,
    plies: int,
    model_name: str,
) -> tuple[Path, str]:
    safe_move = re.sub(r"[^a-zA-Z0-9_+-]", "", attempted_san) or "illegal"
    save_path = folder / f"ply_{plies:02d}_FAIL_{safe_move}.png"
    after_board, from_square, to_square, description = simulate_illegal_board(
        board, attempted_san
    )
    fig, (before_ax, after_ax) = plt.subplots(
        1, 2, figsize=(11.5, 5.8), facecolor="#1e1e1e"
    )
    for ax in (before_ax, after_ax):
        ax.set_facecolor("#1e1e1e")
    _draw_board(before_ax, board, highlight=to_square)
    _draw_board(after_ax, after_board, move_squares=(from_square, to_square))
    before_ax.set_title(
        f"BEFORE (Valid State at Ply {plies})\n"
        f"{'White' if board.turn == chess.WHITE else 'Black'} ({model_name}) to Move",
        fontsize=12,
        fontweight="bold",
        color="#ffffff",
        pad=12,
    )
    after_ax.set_title(
        f"AFTER (Forced Illegal Move: '{attempted_san}')\n{description}",
        fontsize=12,
        fontweight="bold",
        color="#ff6b6b",
        pad=12,
    )
    fig.suptitle(
        f"Trial {trial_id:02d} Spatial Drift Snapshot | White: {model_name}",
        fontsize=14,
        fontweight="bold",
        color="#e0e0e0",
        y=0.98,
    )
    plt.tight_layout()
    fig.savefig(save_path, dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return save_path, description


def extract_move(raw_text: str, board: chess.Board) -> str:
    text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned_text = re.sub(r"\b\d+\.+", " ", text).strip()
    pattern = (
        r"\b(O-O-O|O-O|0-0-0|0-0|[KQRBN][a-h]?[1-8]?x?[a-h][1-8][+#]?|"
        r"[a-h](?:x[a-h])?[2-7][+#]?|[a-h](?:x[a-h])?[18]=[QRBN][+#]?)\b"
    )
    candidates = [
        move.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
        for move in re.findall(pattern, cleaned_text)
    ]
    for candidate in reversed(candidates):
        try:
            board.parse_san(candidate)
            return candidate
        except ValueError:
            continue
    if candidates:
        return candidates[-1]
    tokens = cleaned_text.split()
    return tokens[-1] if tokens else ""


def query_model(
    transcript: str,
    model_name: str,
    board: chess.Board,
    clients: dict[str, OpenAI],
) -> tuple[str, str, dict[str, str | int | float]]:
    side = "White" if board.turn == chess.WHITE else "Black"
    user_prompt = (
        f"Move history:\n{transcript}\n\nYou play {side}. Your move:"
        if transcript
        else "The board is in the starting position. You play White. Your move:"
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    is_astra = "astra" in model_name.lower()
    provider = provider_for_model(model_name)
    client = clients[provider]
    metadata: dict[str, str | int | float] = {
        "model_name": model_name,
        "temperature": (
            "model default" if is_astra else CONFIG_PARAMS["temperature"]
        ),
        "max_tokens": (
            CONFIG_PARAMS["max_completion_tokens_astra"]
            if is_astra
            else CONFIG_PARAMS["max_tokens_standard"]
        ),
    }

    for _ in range(6):
        try:
            request_options = (
                {"max_completion_tokens": CONFIG_PARAMS["max_completion_tokens_astra"]}
                if is_astra
                else {
                    "temperature": CONFIG_PARAMS["temperature"],
                    "max_tokens": CONFIG_PARAMS["max_tokens_standard"],
                }
            )
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                **request_options,
            )
            message = response.choices[0].message
            content = message.content or getattr(message, "reasoning", "") or ""
            return extract_move(content, board), user_prompt, metadata
        except RateLimitError as error:
            wait_match = re.search(r"try again in (\d+(?:\.\d+)?)s", str(error))
            wait_seconds = float(wait_match.group(1)) + 2 if wait_match else 12
            print(f"Rate limit: waiting {wait_seconds:.1f}s before retry.")
            time.sleep(wait_seconds)
        except APIError as error:
            return f"API_ERROR: {error}", user_prompt, metadata
    return "API_ERROR: Maximum rate-limit retries exceeded.", user_prompt, metadata


def format_transcript(board: chess.Board) -> str:
    replay_board = chess.Board()
    transcript_parts: list[str] = []
    for index, move in enumerate(board.move_stack):
        san = replay_board.san(move)
        replay_board.push(move)
        if index % 2 == 0:
            transcript_parts.append(f"{index // 2 + 1}. {san}")
        else:
            transcript_parts[-1] += f" {san}"
    return " ".join(transcript_parts)


def write_audit(folder: Path, audit_data: dict) -> None:
    with (folder / "match_audit.json").open("w", encoding="utf-8") as audit_file:
        json.dump(audit_data, audit_file, indent=2)


def run_trial(
    trial_id: int,
    white_model: str,
    black_model: str,
    max_plies: int,
    clients: dict[str, OpenAI],
    output_dir: Path,
    run_id: str,
) -> dict[str, str | int]:
    if black_model == "self":
        black_model = white_model

    board = chess.Board()
    plies_survived = 0
    folder = get_match_folder(white_model, trial_id, output_dir, run_id)
    white_label = f"{white_model} (White)" if white_model == black_model else white_model
    black_label = f"{black_model} (Black)" if white_model == black_model else black_model
    audit_data = {
        "trial_id": trial_id,
        "white_bot": white_label,
        "black_bot": black_label,
        "system_prompt": SYSTEM_PROMPT,
        "failed": False,
        "failure_reason": "",
        "plies_survived": 0,
        "moves": [],
        "prompts": [],
    }
    save_board_snapshot(board, folder, 0, "Start", "Initial")

    while not board.is_game_over() and plies_survived < max_plies:
        is_white = board.turn == chess.WHITE
        active_model = white_model if is_white else black_model
        active_label = white_label if is_white else black_label
        side_name = "White" if is_white else "Black"

        if not is_white and black_model.lower() == "random":
            random_move = random.choice(list(board.legal_moves))
            san = board.san(random_move)
            board.push(random_move)
            plies_survived += 1
            save_board_snapshot(board, folder, plies_survived, side_name, active_label, san)
            audit_data["moves"].append(
                {
                    "ply": plies_survived,
                    "actor": side_name,
                    "bot": active_label,
                    "san": san,
                    "status": "LEGAL",
                }
            )
            continue

        user_prompt = ""
        transcript = format_transcript(board)
        move_text, user_prompt, metadata = query_model(
            transcript, active_model, board, clients
        )
        if move_text.startswith("API_ERROR"):
            audit_data.update(
                failed=True,
                failure_reason=move_text,
                plies_survived=plies_survived,
            )
            audit_data["prompts"].append(
                {
                    "ply": plies_survived + 1,
                    "actor": side_name,
                    "bot": active_label,
                    "user_prompt": user_prompt,
                    "extracted_move": move_text,
                    "status": "API_ERROR",
                    "metadata": metadata,
                }
            )
            write_audit(folder, audit_data)
            return {
                "trial_id": trial_id,
                "model": f"{white_label} vs {black_label}",
                "plies_survived": plies_survived,
                "failed": 1,
                "failure_reason": move_text,
                "raw_response": move_text,
            }

        san = move_text.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
        try:
            move = board.parse_san(san)
        except ValueError as error:
            image_path, description = save_before_after_snapshot(
                board, move_text, folder, trial_id, plies_survived + 1, active_label
            )
            reason = (
                f"[{side_name} / {active_label}] Illegal Move: '{move_text}' — "
                f"{description} ({error})"
            )
            audit_data.update(
                failed=True,
                failure_reason=reason,
                plies_survived=plies_survived,
            )
            audit_data["moves"].append(
                {
                    "ply": plies_survived + 1,
                    "actor": side_name,
                    "bot": active_label,
                    "san": move_text,
                    "status": "ILLEGAL",
                    "reason": reason,
                }
            )
            audit_data["prompts"].append(
                {
                    "ply": plies_survived + 1,
                    "actor": side_name,
                    "bot": active_label,
                    "user_prompt": user_prompt,
                    "extracted_move": move_text,
                    "status": "ILLEGAL",
                    "metadata": metadata,
                }
            )
            write_audit(folder, audit_data)
            return {
                "trial_id": trial_id,
                "model": f"{white_label} vs {black_label}",
                "plies_survived": plies_survived,
                "failed": 1,
                "failure_reason": f"{reason} [Snapshot: {image_path}]",
                "raw_response": move_text,
            }

        board.push(move)
        plies_survived += 1
        save_board_snapshot(board, folder, plies_survived, side_name, active_label, san)
        audit_data["moves"].append(
            {
                "ply": plies_survived,
                "actor": side_name,
                "bot": active_label,
                "san": san,
                "status": "LEGAL",
            }
        )
        audit_data["prompts"].append(
            {
                "ply": plies_survived,
                "actor": side_name,
                "bot": active_label,
                "user_prompt": user_prompt,
                "extracted_move": san,
                "status": "LEGAL",
                "metadata": metadata,
            }
        )

    audit_data["plies_survived"] = plies_survived
    audit_data["failure_reason"] = (
        f"Completed ({board.result() if board.is_game_over() else 'Max Plies Reached'})"
    )
    write_audit(folder, audit_data)
    return {
        "trial_id": trial_id,
        "model": f"{white_label} vs {black_label}",
        "plies_survived": plies_survived,
        "failed": 0,
        "failure_reason": audit_data["failure_reason"],
        "raw_response": "",
    }


def execute_batch(
    white_model: str,
    black_model: str,
    num_trials: int,
    max_plies: int,
    output_dir: Path,
    csv_path: Path,
    clients: dict[str, OpenAI],
    run_id: str,
    append: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists() and not append:
        raise FileExistsError(f"{csv_path} already exists; use --append to add rows.")

    black_label = white_model if black_model == "self" else black_model
    print(f"Starting {num_trials} trials | {white_model} (White) vs {black_label} (Black)")
    print(f"Results: {csv_path}")
    print(f"Replay data: {output_dir / 'replays'}")

    fieldnames = [
        "trial_id",
        "model",
        "plies_survived",
        "failed",
        "failure_reason",
        "raw_response",
    ]
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0
    mode = "a" if append else "x"
    with csv_path.open(mode, newline="", encoding="utf-8") as results_file:
        writer = csv.DictWriter(results_file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for trial_id in range(1, num_trials + 1):
            result = run_trial(
                trial_id,
                white_model,
                black_model,
                max_plies,
                clients,
                output_dir,
                run_id,
            )
            writer.writerow(result)
            results_file.flush()
            status = "FAILED" if result["failed"] else "SURVIVED"
            print(
                f"Trial {trial_id:02d}/{num_trials:02d} | "
                f"Plies: {result['plies_survived']} | {status} | "
                f"{result['failure_reason']}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--white-model", required=True, help="Model to test as White.")
    parser.add_argument(
        "--black-model",
        default="self",
        help="Black model, 'self' for self-play, or 'random' for a legal random baseline.",
    )
    parser.add_argument("--trials", type=int, default=1, help="Number of trials to run.")
    parser.add_argument("--max-plies", type=int, default=80)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated replays and results.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="CSV destination. Defaults to a timestamped file under data/local/results/.",
    )
    parser.add_argument("--append", action="store_true", help="Append rows to an existing CSV.")
    parser.add_argument("--openai-api-key", help="OpenAI key (OPENAI_API_KEY is preferred).")
    parser.add_argument("--groq-api-key", help="Groq key (GROQ_API_KEY is preferred).")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be at least 1.")
    if args.max_plies < 1:
        parser.error("--max-plies must be at least 1.")
    if args.white_model.lower() == "random":
        parser.error("The White player must be an API-backed model.")

    black_model = args.black_model
    run_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    safe_model = re.sub(r"[^a-zA-Z0-9_-]", "_", args.white_model)
    csv_path = args.output_csv or (
        args.output_dir
        / "results"
        / f"chess_{safe_model}_{run_id}.csv"
    )
    if args.append and args.output_csv is None:
        parser.error("--append requires --output-csv.")
    try:
        clients = create_clients(
            [args.white_model, black_model],
            args.openai_api_key,
            args.groq_api_key,
        )
        execute_batch(
            args.white_model,
            black_model,
            args.trials,
            args.max_plies,
            args.output_dir,
            csv_path,
            clients,
            run_id,
            args.append,
        )
    except (FileExistsError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
