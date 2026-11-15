"""Run chess state-tracking trials and log directly to Supabase Cloud."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any

import chess
import chess.pgn
from openai import APIError, OpenAI, RateLimitError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "experiments"))
from cloud_logger import (
    classify_chess_outcome,
    log_trial_to_supabase,
    slim_chess_audit,
)

CONFIG_PARAMS = {
    "temperature": 0.7,
    "max_tokens_standard": 150,
    "max_completion_tokens_reasoning": 2500,
}
REASONING_COMPLETION_TOKEN_BUDGETS = (2500, 5000)
ANTHROPIC_COMPLETION_TOKEN_BUDGET = 8192

SYSTEM_PROMPT = """You are playing standard chess. The game starts from the standard
initial position. Maintain the game state across this conversation: your prior
move replies are your moves, and each new user message gives the opponent's
latest move in standard algebraic notation (SAN). PRINT OUT BOARD replies only
request the current board and do not advance the game. Apply legal chess rules
and choose one legal move for the side to move, or reply exactly PRINT OUT BOARD
to request the current board. For a move, reply with exactly one SAN move token
(for example e4, Nf3, Bxc6, O-O, or Qh4#), with no move number, explanation,
commentary, or other text."""

PRINT_BOARD_RESPONSE = "PRINT OUT BOARD"
PIECE_SYMBOLS = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
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


def clean_model_name(model_name: str) -> str:
    for prefix in ("ollama/", "local/"):
        if model_name.lower().startswith(prefix):
            return model_name[len(prefix) :]
    return model_name


def provider_for_model(model_name: str) -> str:
    lowered = model_name.lower()
    if lowered.startswith("ollama/") or lowered.startswith("local/") or "deepseek" in lowered:
        return "ollama"
    if "claude" in lowered:
        return "anthropic"
    if "gpt-oss" in lowered:
        return "groq"
    if lowered.startswith("gpt-") or "astra" in lowered:
        return "openai"
    return "groq"


def create_clients(
    model_names: list[str],
    openai_api_key: str | None = None,
    groq_api_key: str | None = None,
    anthropic_api_key: str | None = None,
) -> dict[str, OpenAI]:
    required_providers = {
        provider_for_model(name)
        for name in model_names
        if name.lower() not in {"random", "self"}
    }
    keys = {
        "openai": clean_api_key(openai_api_key or os.getenv("OPENAI_API_KEY")),
        "groq": clean_api_key(groq_api_key or os.getenv("GROQ_API_KEY")),
        "anthropic": clean_api_key(anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")),
    }
    clients: dict[str, OpenAI] = {}
    for provider in required_providers:
        if provider == "ollama":
            clients["ollama"] = OpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
            )
            continue
        if not keys[provider]:
            env_name = f"{provider.upper()}_API_KEY"
            raise ValueError(f"Set {env_name} or pass --{provider}-api-key.")
        if provider == "groq":
            clients[provider] = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=keys[provider],
            )
        elif provider == "anthropic":
            clients[provider] = OpenAI(
                base_url="https://api.anthropic.com/v1/",
                api_key=keys[provider],
            )
        else:
            clients[provider] = OpenAI(api_key=keys[provider])
    return clients


def diagnose_illegal_move(
    board: chess.Board, attempted_san: str
) -> tuple[str, str | None, str | None]:
    """Infers the intended squares and failure archetype without Matplotlib."""
    turn_color = board.turn
    color_name = "White" if turn_color == chess.WHITE else "Black"
    clean = attempted_san.replace("+", "").replace("#", "").strip()
    king_home = chess.E1 if turn_color == chess.WHITE else chess.E8
    rank = 0 if turn_color == chess.WHITE else 7

    if clean in {"O-O", "0-0", "O-O-O", "0-0-0"}:
        king_to_file = 6 if clean in {"O-O", "0-0"} else 2
        king_to = chess.square(king_to_file, rank)
        castle = "O-O" if king_to_file == 6 else "O-O-O"
        return (
            f"Illegal {color_name} Castling ({castle})",
            chess.square_name(king_home),
            chess.square_name(king_to),
        )

    destination_match = re.search(r"([a-h][1-8])", clean)
    if not destination_match:
        return f"Unparseable Token: '{attempted_san}'", None, None

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
            sq for sq in candidates if chess.square_file(sq) == origin_file
        ]
        if same_file:
            from_square = min(
                same_file, key=lambda sq: chess.square_distance(sq, to_square)
            )
    elif candidates:
        prefix = clean[: destination_match.start()].replace("x", "")
        if prefix and prefix[0] in piece_types:
            prefix = prefix[1:]
        if len(prefix) == 1 and prefix in "abcdefgh":
            file_index = ord(prefix) - ord("a")
            candidates = [
                sq for sq in candidates if chess.square_file(sq) == file_index
            ] or candidates
        elif len(prefix) == 1 and prefix in "12345678":
            rank_index = int(prefix) - 1
            candidates = [
                sq for sq in candidates if chess.square_rank(sq) == rank_index
            ] or candidates
        from_square = min(
            candidates, key=lambda sq: chess.square_distance(sq, to_square)
        )

    occupant = board.piece_at(to_square)
    if from_square is not None and from_square != to_square:
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
        description = f"Phantom Spawn: Created {piece_symbol} on {chess.square_name(to_square)}"

    return (
        description,
        chess.square_name(from_square) if from_square is not None else None,
        chess.square_name(to_square),
    )


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


def is_print_board_response(raw_response: str) -> bool:
    return raw_response.strip().casefold() == PRINT_BOARD_RESPONSE.casefold()


def board_text(board: chess.Board) -> str:
    rows = []
    for rank in range(7, -1, -1):
        pieces = []
        for file_index in range(8):
            piece = board.piece_at(chess.square(file_index, rank))
            pieces.append(PIECE_SYMBOLS[piece.symbol()] if piece else ".")
        rows.append(f"{rank + 1} {' '.join(pieces)}")
    rows.append("  a b c d e f g h")
    return "\n".join(rows)


def query_model(
    user_prompt: str,
    model_name: str,
    board: chess.Board,
    clients: dict[str, OpenAI],
    conversation: list[dict[str, str]] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *(conversation or []),
        {"role": "user", "content": user_prompt},
    ]
    lowered_model_name = model_name.lower()
    uses_completion_tokens = (
        "astra" in lowered_model_name
        or re.match(r"^gpt-6(?:[.-]|$)", lowered_model_name) is not None
    )
    provider = provider_for_model(model_name)
    client = clients[provider]
    metadata: dict[str, Any] = {"model_name": model_name, "provider": provider}

    budget_attempt = 0
    for _ in range(6):
        try:
            request_options = (
                {
                    "max_completion_tokens": REASONING_COMPLETION_TOKEN_BUDGETS[budget_attempt],
                    "reasoning_effort": "low",
                }
                if uses_completion_tokens
                else (
                    {"max_tokens": ANTHROPIC_COMPLETION_TOKEN_BUDGET}
                    if provider == "anthropic"
                    else {
                        "temperature": CONFIG_PARAMS["temperature"],
                        "max_tokens": CONFIG_PARAMS["max_tokens_standard"],
                    }
                )
            )
            response = client.chat.completions.create(
                model=clean_model_name(model_name),
                messages=messages,
                **request_options,
            )
            choice = response.choices[0]
            if uses_completion_tokens and getattr(choice, "finish_reason", None) == "length":
                if budget_attempt < len(REASONING_COMPLETION_TOKEN_BUDGETS) - 1:
                    budget_attempt += 1
                    continue
                metadata["error"] = "Model response was truncated."
                return f"API_ERROR: {metadata['error']}", user_prompt, metadata

            if provider == "anthropic" and getattr(choice, "finish_reason", None) in {"length", "max_tokens"}:
                metadata["error"] = "Claude response was truncated."
                return f"API_ERROR: {metadata['error']}", user_prompt, metadata

            message = choice.message
            content = message.content or getattr(message, "reasoning", "") or ""
            metadata["raw_response"] = content
            move = (
                PRINT_BOARD_RESPONSE
                if is_print_board_response(content)
                else extract_move(content, board)
            )
            if conversation is not None:
                conversation.extend(
                    [
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": move},
                    ]
                )
            return move, user_prompt, metadata
        except RateLimitError as error:
            wait_match = re.search(r"try again in (\d+(?:\.\d+)?)s", str(error))
            wait_seconds = float(wait_match.group(1)) + 2 if wait_match else 12
            print(f"Rate limit: waiting {wait_seconds:.1f}s before retry.")
            time.sleep(wait_seconds)
        except APIError as error:
            metadata["error"] = str(error)
            return f"API_ERROR: {error}", user_prompt, metadata
    return "API_ERROR: Maximum rate-limit retries exceeded.", user_prompt, metadata


def build_pgn_string(audit_data: dict[str, Any], board: chess.Board) -> str:
    pgn_game = chess.pgn.Game.from_board(board)
    pgn_game.headers["Event"] = "Weird Index State-Tracking Trial"
    pgn_game.headers["White"] = audit_data["white_bot"]
    pgn_game.headers["Black"] = audit_data["black_bot"]
    pgn_game.headers["Result"] = board.result() if board.is_game_over() else "*"

    illegal_move = next(
        (move for move in reversed(audit_data["moves"]) if move["status"] == "ILLEGAL"),
        None,
    )
    if illegal_move:
        pgn_game.end().comment = (
            f"Illegal move attempted by {illegal_move['actor']}: {illegal_move['san']}"
        )
    return pgn_game.accept(
        chess.pgn.StringExporter(headers=True, variations=False, comments=True)
    )


def run_trial(
    trial_id: int,
    white_model: str,
    black_model: str,
    max_plies: int,
    clients: dict[str, OpenAI],
    run_id: str,
) -> dict[str, Any]:
    if black_model == "self":
        black_model = white_model

    board = chess.Board()
    plies_survived = 0
    board_print_requests = 0
    white_label = f"{white_model} (White)" if white_model == black_model else white_model
    black_label = f"{black_model} (Black)" if white_model == black_model else black_model

    audit_data: dict[str, Any] = {
        "trial_id": trial_id,
        "white_bot": white_label,
        "black_bot": black_label,
        "system_prompt": SYSTEM_PROMPT,
        "failed": False,
        "failure_reason": "",
        "plies_survived": 0,
        "board_print_requests": 0,
        "moves": [],
        "prompts": [],
        "started_at": datetime.now().astimezone().isoformat(),
        "max_plies": max_plies,
    }
    conversations: dict[str, list[dict[str, str]]] = {"White": [], "Black": []}

    def finalize_and_upload(failed_flag: bool, reason_text: str, raw_resp: str, culprit: str) -> dict[str, Any]:
        audit_data["plies_survived"] = plies_survived
        audit_data["board_print_requests"] = board_print_requests
        audit_data["failed"] = failed_flag
        audit_data["failure_reason"] = reason_text
        audit_data["completed_at"] = datetime.now().astimezone().isoformat()
        audit_data["pgn"] = build_pgn_string(audit_data, board)

        slimmed = slim_chess_audit(audit_data)
        status, clean_reason = classify_chess_outcome(
            failed=failed_flag,
            failure_reason=reason_text,
            raw_response=raw_resp,
            culprit_label=culprit,
        )

        last_move = slimmed["moves"][-1] if slimmed["moves"] else {}
        exact_prompt = SYSTEM_PROMPT
        if last_move.get("prompt"):
            exact_prompt = (
                f"System:\n{SYSTEM_PROMPT}\n\n"
                f"User (Ply {last_move.get('ply')}):\n{last_move.get('prompt')}"
            )

        cloud_trial_id = (
            f"chess__{white_model}__{run_id}__Trial_{trial_id:03d}"
            .replace(" ", "_")
            .replace("/", "-")
        )

        log_trial_to_supabase(
            game="chess",
            white_model=white_model,
            black_model=black_model,
            status=status,
            plies_survived=plies_survived,
            failure_reason=clean_reason,
            board_print_requests=board_print_requests,
            exact_prompt=exact_prompt,
            trial_id=cloud_trial_id,
            replay_data=slimmed,
        )

        return {
            "trial_id": cloud_trial_id,
            "status": status,
            "plies_survived": plies_survived,
            "board_print_requests": board_print_requests,
            "failure_reason": clean_reason,
        }

    while not board.is_game_over() and plies_survived < max_plies:
        is_white = board.turn == chess.WHITE
        active_model = white_model if is_white else black_model
        active_label = white_label if is_white else black_label
        side_name = "White" if is_white else "Black"

        if not is_white and black_model.lower() == "random":
            random_move = random.choice(list(board.legal_moves))
            san = board.san(random_move)
            pre_fen = board.fen()
            board.push(random_move)
            plies_survived += 1
            audit_data["moves"].append(
                {
                    "ply": plies_survived,
                    "actor": side_name,
                    "bot": active_label,
                    "san": san,
                    "raw_response": san,
                    "status": "LEGAL",
                    "pre_fen": pre_fen,
                    "post_fen": board.fen(),
                    "prompt": "Random baseline move",
                }
            )
            continue

        if audit_data["moves"]:
            previous_move = audit_data["moves"][-1]["san"]
            user_prompt = f"Opponent played: {previous_move}. You play {side_name}. Your move:"
        else:
            user_prompt = "Game start. You are White; the standard starting position is in effect. Your move:"

        while True:
            move_text, user_prompt, metadata = query_model(
                user_prompt,
                active_model,
                board,
                clients,
                conversations[side_name],
            )
            if not is_print_board_response(move_text):
                break
            board_print_requests += 1
            user_prompt = (
                f"Current board:\n{board_text(board)}\n"
                f"It is still {side_name}'s turn. Choose a legal move, or reply "
                f"exactly {PRINT_BOARD_RESPONSE} to display the board again."
            )

        if move_text.startswith("API_ERROR"):
            audit_data["moves"].append(
                {
                    "ply": plies_survived + 1,
                    "actor": side_name,
                    "bot": active_label,
                    "san": "",
                    "raw_response": move_text,
                    "status": "API_ERROR",
                    "pre_fen": board.fen(),
                    "post_fen": board.fen(),
                    "reason": move_text,
                    "prompt": user_prompt,
                }
            )
            return finalize_and_upload(True, move_text, move_text, f"{side_name} / {active_model}")

        san = move_text.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
        try:
            move = board.parse_san(san)
        except ValueError as error:
            pre_fen = board.fen()
            description, from_square, to_square = diagnose_illegal_move(board, move_text)
            reason = f"[{side_name} / {active_model}] Illegal Move: '{move_text}' — {description} ({error})"
            audit_data["moves"].append(
                {
                    "ply": plies_survived + 1,
                    "actor": side_name,
                    "bot": active_label,
                    "san": move_text,
                    "raw_response": str(metadata.get("raw_response", move_text)),
                    "status": "ILLEGAL",
                    "reason": reason,
                    "pre_fen": pre_fen,
                    "post_fen": pre_fen,
                    "prompt": user_prompt,
                    "illegal_move": {
                        "san": move_text,
                        "from_square": from_square,
                        "to_square": to_square,
                    },
                }
            )
            return finalize_and_upload(True, reason, move_text, f"{side_name} / {active_model}")

        pre_fen = board.fen()
        board.push(move)
        plies_survived += 1
        audit_data["moves"].append(
            {
                "ply": plies_survived,
                "actor": side_name,
                "bot": active_label,
                "san": san,
                "raw_response": str(metadata.get("raw_response", move_text)),
                "status": "LEGAL",
                "pre_fen": pre_fen,
                "post_fen": board.fen(),
                "prompt": user_prompt,
            }
        )

    done_reason = f"Completed ({board.result() if board.is_game_over() else 'Max Plies Reached'})"
    return finalize_and_upload(False, done_reason, "", "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--white-model", required=True, help="Model to test as White.")
    parser.add_argument("--black-model", default="self", help="Black model, 'self', or 'random'.")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--max-plies", type=int, default=80)
    parser.add_argument("--openai-api-key")
    parser.add_argument("--groq-api-key")
    parser.add_argument("--anthropic-api-key")
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

    run_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    try:
        clients = create_clients(
            [args.white_model, args.black_model],
            args.openai_api_key,
            args.groq_api_key,
            args.anthropic_api_key,
        )
        for trial_num in range(1, args.trials + 1):
            res = run_trial(
                trial_num,
                args.white_model,
                args.black_model,
                args.max_plies,
                clients,
                run_id,
            )
            print(
                f"[Cloud Logged] Trial {trial_num:02d}/{args.trials:02d} | "
                f"Status: {res['status']} | Plies: {res['plies_survived']} | "
                f"Note: {res['failure_reason']}"
            )
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
