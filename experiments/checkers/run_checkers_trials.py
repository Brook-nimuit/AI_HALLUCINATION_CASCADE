"""Run logged trials using the 10x10 International Draughts rules (Supabase Cloud)."""

import argparse
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from openai import APIError, OpenAI, RateLimitError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "experiments"))
from cloud_logger import (
    classify_checkers_outcome,
    log_trial_to_supabase,
    slim_checkers_audit,
)

PLAYERS = ("White", "Black")
MAX_COMPLETION_TOKENS = (1024, 2048, 4096)
PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
SUPPORTED_PROVIDERS = ("auto", "openai", "groq", "gemini", "anthropic", "ollama")
ModelClient = OpenAI | genai.Client
ANTHROPIC_MAX_TOKENS = 8192
SYSTEM_PROMPT = """You are playing International Draughts (10x10 checkers).
The game starts from the standard initial position. Use numbered dark squares:
White men (w) move toward square 1; Black men (b) move toward square 50. Men
move one diagonal square forward when not capturing and may capture in any
diagonal direction. Captures are mandatory; choose a complete turn capturing
the maximum possible number of opposing pieces. Kings (W/B) fly diagonally
and may land on any empty square beyond a captured piece. Captured pieces stay
on the board and block movement until the capture sequence ends. A man is
crowned only when its turn ends on the far edge. Maintain the game state across
this conversation: your prior move replies are your moves, and each new user
message gives the opponent's latest complete PDN move. PRINT OUT BOARD replies
only request the current board and do not advance the game. Choose one legal
complete turn, or reply exactly PRINT OUT BOARD to request the current board.
For a move, reply with exactly one PDN move (for example 31-26 or 31x22x13),
with no history, explanation, or other text."""
PRINT_BOARD_RESPONSE = "PRINT OUT BOARD"


@dataclass(frozen=True)
class DraughtsMove:
    path: tuple[int, ...]
    captured: tuple[int, ...] = ()

    @property
    def is_capture(self) -> bool:
        return bool(self.captured)

    @property
    def notation(self) -> str:
        separator = "x" if self.is_capture else "-"
        return separator.join(str(square) for square in self.path)


def square_to_coordinate(square: int) -> tuple[int, int]:
    if not 1 <= square <= 50:
        raise ValueError(f"Square must be between 1 and 50: {square}")
    index = square - 1
    row, offset = divmod(index, 5)
    column = 2 * offset + (1 if row % 2 == 0 else 0)
    return row, column


def coordinate_to_square(row: int, column: int) -> int | None:
    if not (0 <= row < 10 and 0 <= column < 10):
        return None
    if (row + column) % 2 != 1:
        return None
    return row * 5 + column // 2 + 1


def parse_move(raw_response: str) -> tuple[int, ...] | None:
    candidates = re.findall(
        r"(?<!\d)(?:50|[1-4]\d|[1-9])(?!\d)"
        r"(?:\s*[-xX×]\s*(?:50|[1-4]\d|[1-9])(?!\d))+",
        raw_response,
    )
    if len(candidates) != 1:
        return None
    path_text = candidates[0].replace("×", "x").replace("X", "x")
    try:
        path = tuple(int(square.strip()) for square in re.split(r"[-x]", path_text))
    except ValueError:
        return None
    return path if len(path) >= 2 else None


def is_print_board_response(raw_response: str) -> bool:
    return raw_response.strip().casefold() == PRINT_BOARD_RESPONSE.casefold()


def pdn_result(audit: dict[str, Any]) -> str:
    if audit.get("winner") == "White":
        return "2-0"
    if audit.get("winner") == "Black":
        return "0-2"
    if audit.get("draw"):
        return "1-1"
    return "*"


def escape_pdn_tag(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def build_pdn(audit: dict[str, Any], result: str | None = None) -> str:
    started_at = str(audit.get("started_at", ""))
    date_match = re.match(r"(\d{4})-(\d{2})-(\d{2})", started_at)
    date = ".".join(date_match.groups()) if date_match else "????.??.??"
    players = audit.get("players", {})
    game_result = result or pdn_result(audit)
    tags = (
        ("Event", "International Draughts State-Tracking Trial"),
        ("Site", "Supabase Cloud"),
        ("Date", date),
        ("Round", str(audit.get("trial_id", "?"))),
        ("White", str(players.get("White", "?"))),
        ("Black", str(players.get("Black", "?"))),
        ("GameType", "20"),
        ("Variant", "International"),
        ("Result", game_result),
    )
    lines = [f'[{name} "{escape_pdn_tag(value)}"]' for name, value in tags]

    move_tokens: list[str] = []
    move_number = 1
    previous_player: str | None = None
    for event in audit.get("turns", []):
        if not event.get("valid") or not event.get("move"):
            continue
        notation = str(event["move"])
        player = event.get("player")
        if player == "White":
            move_tokens.append(f"{move_number}. {notation}")
        elif player == "Black" and previous_player == "White" and move_tokens:
            move_tokens[-1] += f" {notation}"
            move_number += 1
        elif player == "Black":
            move_tokens.append(f"{move_number}... {notation}")
            move_number += 1
        previous_player = player

    invalid_event = next(
        (
            event
            for event in reversed(audit.get("turns", []))
            if not event.get("valid")
        ),
        None,
    )
    if invalid_event:
        detail = (
            f"Rejected move by {invalid_event.get('player', 'unknown')}: "
            f"{invalid_event.get('raw_response', '')} "
            f"({invalid_event.get('reason', '')})"
        )
        move_tokens.append(
            "{" + detail.replace("{", "(").replace("}", ")").replace("\n", " ") + "}"
        )
    lines.append("")
    lines.append(" ".join(move_tokens + [game_result]))
    return "\n".join(lines) + "\n"


class InternationalDraughts:
    """International Draughts rules and position state for one match."""

    def __init__(
        self,
        board: dict[int, str] | None = None,
        turn: str = "White",
    ) -> None:
        if turn not in PLAYERS:
            raise ValueError(f"Unknown player: {turn}")
        self.board = dict(board) if board is not None else self._initial_board()
        if any(square_to_coordinate(square) is None for square in self.board):
            raise ValueError("Board contains an invalid square.")
        if any(piece not in {"w", "W", "b", "B"} for piece in self.board.values()):
            raise ValueError("Board contains an invalid piece.")
        self.turn = turn
        self.no_progress_plies = 0
        self.repetitions: dict[tuple[Any, ...], int] = {}
        self.draw = False
        self._record_position()

    @staticmethod
    def _initial_board() -> dict[int, str]:
        board = {square: "b" for square in range(1, 21)}
        board.update({square: "w" for square in range(31, 51)})
        return board

    @staticmethod
    def _owner(piece: str) -> str:
        return "White" if piece.lower() == "w" else "Black"

    @staticmethod
    def _other(player: str) -> str:
        return "Black" if player == "White" else "White"

    def _position_key(self) -> tuple[Any, ...]:
        return (
            self.turn,
            tuple(sorted(self.board.items())),
        )

    def _record_position(self) -> None:
        key = self._position_key()
        self.repetitions[key] = self.repetitions.get(key, 0) + 1
        if self.repetitions[key] >= 3:
            self.draw = True

    @staticmethod
    def _directions() -> tuple[tuple[int, int], ...]:
        return ((-1, -1), (-1, 1), (1, -1), (1, 1))

    def _capture_options(
        self,
        square: int,
        piece: str,
        captured: frozenset[int],
        board: dict[int, str],
    ) -> list[tuple[int, int]]:
        row, column = square_to_coordinate(square)
        options: list[tuple[int, int]] = []
        if piece.islower():
            for row_delta, column_delta in self._directions():
                jumped = coordinate_to_square(
                    row + row_delta, column + column_delta
                )
                landing = coordinate_to_square(
                    row + 2 * row_delta, column + 2 * column_delta
                )
                if (
                    jumped is not None
                    and landing is not None
                    and jumped in board
                    and jumped not in captured
                    and self._owner(board[jumped]) != self._owner(piece)
                    and landing not in board
                ):
                    options.append((jumped, landing))
            return options

        for row_delta, column_delta in self._directions():
            scan_row = row + row_delta
            scan_column = column + column_delta
            enemy: int | None = None
            while True:
                square_on_ray = coordinate_to_square(scan_row, scan_column)
                if square_on_ray is None:
                    break
                blocking_piece = board.get(square_on_ray)
                if blocking_piece is not None:
                    if enemy is not None:
                        break
                    if (
                        square_on_ray in captured
                        or self._owner(blocking_piece) == self._owner(piece)
                    ):
                        break
                    enemy = square_on_ray
                elif enemy is not None:
                    options.append((enemy, square_on_ray))
                scan_row += row_delta
                scan_column += column_delta
        return options

    def _capture_sequences(
        self,
        square: int,
        piece: str,
        board: dict[int, str],
        captured: tuple[int, ...] = (),
        path: tuple[int, ...] = (),
    ) -> list[DraughtsMove]:
        current_path = path or (square,)
        options = self._capture_options(
            square, piece, frozenset(captured), board
        )
        if not options:
            return [DraughtsMove(current_path, captured)] if captured else []

        sequences: list[DraughtsMove] = []
        for jumped, landing in options:
            next_board = board.copy()
            next_board.pop(square)
            next_board[landing] = piece
            sequences.extend(
                self._capture_sequences(
                    landing,
                    piece,
                    next_board,
                    captured + (jumped,),
                    current_path + (landing,),
                )
            )
        return sequences

    def legal_moves(self) -> list[DraughtsMove]:
        if self.draw:
            return []

        captures: list[DraughtsMove] = []
        for square, piece in self.board.items():
            if self._owner(piece) == self.turn:
                captures.extend(
                    self._capture_sequences(square, piece, self.board)
                )
        if captures:
            most_captured = max(len(move.captured) for move in captures)
            return [
                move for move in captures if len(move.captured) == most_captured
            ]

        moves: list[DraughtsMove] = []
        for square, piece in self.board.items():
            if self._owner(piece) != self.turn:
                continue
            row, column = square_to_coordinate(square)
            if piece.islower():
                direction = -1 if self.turn == "White" else 1
                for column_delta in (-1, 1):
                    destination = coordinate_to_square(
                        row + direction, column + column_delta
                    )
                    if destination is not None and destination not in self.board:
                        moves.append(DraughtsMove((square, destination)))
            else:
                for row_delta, column_delta in self._directions():
                    scan_row = row + row_delta
                    scan_column = column + column_delta
                    while True:
                        destination = coordinate_to_square(
                            scan_row, scan_column
                        )
                        if destination is None or destination in self.board:
                            break
                        moves.append(DraughtsMove((square, destination)))
                        scan_row += row_delta
                        scan_column += column_delta
        return moves

    @property
    def winner(self) -> str | None:
        if self.draw:
            return None
        if not any(self._owner(piece) == self.turn for piece in self.board.values()):
            return self._other(self.turn)
        if not self.legal_moves():
            return self._other(self.turn)
        return None

    @property
    def finished(self) -> bool:
        return self.draw or self.winner is not None

    def play(self, path: tuple[int, ...]) -> tuple[bool, str, DraughtsMove | None]:
        move = next((candidate for candidate in self.legal_moves() if candidate.path == path), None)
        if move is None:
            return False, "Move is illegal or violates the mandatory maximum-capture rule.", None

        piece = self.board[move.path[0]]
        self.board.pop(move.path[0])
        for captured_square in move.captured:
            self.board.pop(captured_square)

        destination = move.path[-1]
        destination_row, _ = square_to_coordinate(destination)
        moving_was_king = piece.isupper()
        if piece == "w" and destination_row == 0:
            piece = "W"
        elif piece == "b" and destination_row == 9:
            piece = "B"
        self.board[destination] = piece

        if moving_was_king and not move.is_capture:
            self.no_progress_plies += 1
        else:
            self.no_progress_plies = 0

        self.turn = self._other(self.turn)
        self._record_position()
        if self.no_progress_plies >= 50:
            self.draw = True
        return True, "Legal move.", move

    def board_text(self) -> str:
        rows = []
        for row in range(10):
            squares = []
            for offset in range(5):
                square = row * 5 + offset + 1
                piece = self.board.get(square, ".")
                squares.append(f"{square:02d}:{piece}")
            rows.append(" ".join(squares))
        return "\n".join(rows)

    def state(self, ply: int, last_move: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "ply": ply,
            "active_player": None if self.finished else self.turn,
            "board": {str(square): piece for square, piece in sorted(self.board.items())},
            "board_text": self.board_text(),
            "piece_counts": {
                player: sum(
                    self._owner(piece) == player for piece in self.board.values()
                )
                for player in PLAYERS
            },
            "winner": self.winner,
            "draw": self.draw,
            "no_progress_plies": self.no_progress_plies,
            "last_move": last_move,
            "captured_at": datetime.now().astimezone().isoformat(),
        }


def clean_model_name(model_name: str) -> str:
    for prefix in ("ollama/", "local/"):
        if model_name.lower().startswith(prefix):
            return model_name[len(prefix) :]
    return model_name


def provider_for_model(model_name: str, provider: str = "auto") -> str:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    if provider != "auto":
        return provider
    lowered = model_name.lower()
    if lowered.startswith("ollama/") or lowered.startswith("local/") or "deepseek" in lowered:
        return "ollama"
    if "claude" in lowered:
        return "anthropic"
    if "gemini" in lowered:
        return "gemini"
    if "gpt-oss" in lowered:
        return "groq"
    if (
        lowered.startswith("gpt-")
        or re.match(r"o[134](?:-|$)", lowered)
        or "astra" in lowered
    ):
        return "openai"
    if "groq" in lowered:
        return "groq"
    return "groq"


def effective_reasoning_effort(model_name: str, requested: str) -> str:
    if requested != "auto":
        return requested
    return "low" if "gpt-oss" in model_name.lower() else "medium"


def create_clients(
    model_names: list[str],
    openai_api_key: str | None = None,
    groq_api_key: str | None = None,
    providers: list[str] | None = None,
    gemini_api_key: str | None = None,
    anthropic_api_key: str | None = None,
) -> dict[str, ModelClient]:
    selected_providers = providers or ["auto"] * len(model_names)
    if len(selected_providers) != len(model_names):
        raise ValueError("Provide exactly one provider selection per model.")
    required = {
        provider_for_model(name, selected_provider)
        for name, selected_provider in zip(model_names, selected_providers)
        if name.lower() not in {"random", "self"}
    }
    keys = {
        "openai": (openai_api_key or os.getenv("OPENAI_API_KEY") or "").strip(),
        "groq": (groq_api_key or os.getenv("GROQ_API_KEY") or "").strip(),
        "gemini": (gemini_api_key or os.getenv("GEMINI_API_KEY") or "").strip(),
        "anthropic": (
            anthropic_api_key or os.getenv("ANTHROPIC_API_KEY") or ""
        ).strip(),
    }
    clients: dict[str, ModelClient] = {}
    for provider in required:
        if provider == "ollama":
            clients[provider] = OpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
            )
            continue
        if not keys[provider]:
            env_name = PROVIDER_ENV_VARS[provider]
            option = f"--{provider}-api-key"
            raise ValueError(f"Set {env_name} or pass {option}.")
        if provider == "gemini":
            clients[provider] = genai.Client(api_key=keys[provider])
        elif provider == "groq":
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


def query_model(
    user_prompt: str,
    model_name: str,
    clients: dict[str, ModelClient],
    reasoning_effort: str,
    provider: str = "auto",
    conversation: list[dict[str, str]] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    system_prompt = SYSTEM_PROMPT
    provider = provider_for_model(model_name, provider)
    if provider == "gemini":
        client = clients[provider]
        if not isinstance(client, genai.Client):
            raise TypeError("Gemini provider requires a Google GenAI client.")
        return query_gemini(
            system_prompt, user_prompt, clean_model_name(model_name), client, provider, conversation
        )
    client = clients[provider]
    if not isinstance(client, OpenAI):
        raise TypeError("OpenAI-compatible providers require an OpenAI client.")
    request: dict[str, Any] = {
        "model": clean_model_name(model_name),
        "messages": [
            {"role": "system", "content": system_prompt},
            *(conversation or []),
            {"role": "user", "content": user_prompt},
        ],
    }
    lowered = model_name.lower()
    is_openai_reasoning = provider == "openai" and (
        "astra" in lowered
        or "terra" in lowered
        or "luna" in lowered
        or lowered.startswith("gpt-6")
    )
    is_gpt_oss = provider == "groq" and "gpt-oss" in lowered
    uses_reasoning_effort = is_openai_reasoning or is_gpt_oss
    if uses_reasoning_effort:
        request["max_completion_tokens"] = MAX_COMPLETION_TOKENS[0]
        request["reasoning_effort"] = effective_reasoning_effort(
            model_name, reasoning_effort
        )
        if is_gpt_oss:
            request["extra_body"] = {"reasoning_format": "hidden"}
    else:
        request["max_tokens"] = (
            ANTHROPIC_MAX_TOKENS if provider == "anthropic" else 128
        )
        if provider != "anthropic":
            request["temperature"] = 0.2

    metadata: dict[str, Any] = {"provider": provider}
    budget_attempt = 0
    rate_limit_retries = 0
    while True:
        if uses_reasoning_effort:
            request["max_completion_tokens"] = MAX_COMPLETION_TOKENS[budget_attempt]
        try:
            response = client.chat.completions.create(**request)
            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if uses_reasoning_effort and finish_reason == "length":
                if budget_attempt < len(MAX_COMPLETION_TOKENS) - 1:
                    budget_attempt += 1
                    continue
                metadata["error"] = (
                    "Model response was truncated at "
                    f"{request['max_completion_tokens']} completion tokens."
                )
                return f"API_ERROR: {metadata['error']}", user_prompt, metadata

            if provider == "anthropic" and finish_reason in {"length", "max_tokens"}:
                metadata["error"] = (
                    f"Claude response was truncated at {ANTHROPIC_MAX_TOKENS} "
                    "output tokens."
                )
                return f"API_ERROR: {metadata['error']}", user_prompt, metadata

            raw_response = (choice.message.content or "").strip()
            if conversation is not None:
                conversation.extend(
                    [
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": raw_response},
                    ]
                )
            return raw_response, user_prompt, metadata
        except RateLimitError as error:
            if rate_limit_retries < 2:
                rate_limit_retries += 1
                time.sleep(10)
                continue
            metadata["error"] = str(error)
            return f"API_ERROR: {error}", user_prompt, metadata
        except APIError as error:
            metadata["error"] = str(error)
            return f"API_ERROR: {error}", user_prompt, metadata


def query_gemini(
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    client: genai.Client,
    provider: str,
    conversation: list[dict[str, str]] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.2,
        max_output_tokens=128,
    )
    metadata: dict[str, Any] = {"provider": provider}
    contents = [
        types.Content(
            role="user" if message["role"] == "user" else "model",
            parts=[types.Part(text=message["content"])],
        )
        for message in (conversation or [])
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            raw_response = (response.text or "").strip()
            if conversation is not None:
                conversation.extend(
                    [
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": raw_response},
                    ]
                )
            return raw_response, user_prompt, metadata
        except genai_errors.APIError as error:
            message = str(error)
            metadata["error"] = message
            retryable = any(
                marker in message.upper()
                for marker in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")
            )
            if retryable and attempt < 2:
                time.sleep(10)
                continue
            return f"API_ERROR: {message}", user_prompt, metadata
    return "API_ERROR: Maximum retries exceeded.", user_prompt, metadata


def run_trial(
    trial_id: int,
    white_model: str,
    black_model: str,
    max_plies: int,
    clients: dict[str, ModelClient],
    reasoning_effort: str,
    run_id: str,
    white_provider: str = "auto",
    black_provider: str = "auto",
) -> dict[str, Any]:
    black_provider_was_auto = black_provider == "auto"
    if black_model == "self":
        black_model = white_model
        if black_provider_was_auto:
            black_provider = white_provider
    players = {"White": white_model, "Black": black_model}
    player_providers = {
        "White": provider_for_model(white_model, white_provider),
        "Black": (
            "random"
            if black_model.lower() == "random"
            else provider_for_model(black_model, black_provider)
        ),
    }

    game = InternationalDraughts()
    audit: dict[str, Any] = {
        "schema_version": 1,
        "game": "international-draughts",
        "variant": "International Draughts (10x10)",
        "run_id": run_id,
        "trial_id": trial_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "players": players,
        "providers": player_providers,
        "reasoning_effort": reasoning_effort,
        "max_plies": max_plies,
        "system_prompt": SYSTEM_PROMPT,
        "board_print_requests": 0,
        "initial_state": game.state(0, None),
        "turns": [],
    }

    failed = False
    failure_reason = ""
    end_reason = "Max Plies Reached"
    board_print_requests = 0
    conversations: dict[str, list[dict[str, str]]] = {
        "White": [],
        "Black": [],
    }

    for ply in range(1, max_plies + 1):
        if game.finished:
            end_reason = "Draw" if game.draw else "No Legal Moves"
            break
        player = game.turn
        model_name = players[player]
        pre_board = {str(square): piece for square, piece in sorted(game.board.items())}
        user_prompt = ""
        response_metadata: dict[str, Any] = {}
        if model_name.lower() == "random":
            legal_moves = game.legal_moves()
            selected = random.choice(legal_moves)
            raw_response = selected.notation
            response_metadata = {"provider": "random"}
        else:
            if audit["turns"]:
                opponent_move = audit["turns"][-1]["move"]
                user_prompt = (
                    f"Opponent played: {opponent_move}. You play {player}. Your move:"
                )
            else:
                user_prompt = (
                    f"Game start. You are {player}; the standard initial position "
                    "is in effect. Your move:"
                )
            while True:
                raw_response, user_prompt, response_metadata = query_model(
                    user_prompt,
                    model_name,
                    clients,
                    reasoning_effort,
                    player_providers[player],
                    conversations[player],
                )
                if not is_print_board_response(raw_response):
                    break
                board_print_requests += 1
                audit["board_print_requests"] = board_print_requests
                user_prompt = (
                    "Current board (numbered playable squares):\n"
                    f"{game.board_text()}\n"
                    f"It is still {player}'s turn. Choose a legal complete turn, "
                    f"or reply exactly {PRINT_BOARD_RESPONSE} to display the "
                    "board again."
                )

        attempted_path = parse_move(raw_response)
        if raw_response.startswith("API_ERROR"):
            valid, reason, applied_move = False, raw_response, None
        elif attempted_path is None:
            valid, reason, applied_move = (
                False,
                "Response did not contain exactly one move in 1-50 notation.",
                None,
            )
        else:
            valid, reason, applied_move = game.play(attempted_path)

        event: dict[str, Any] = {
            "ply": ply,
            "player": player,
            "model": model_name,
            "provider": player_providers[player],
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": user_prompt,
            "raw_response": raw_response,
            "parsed_path": list(attempted_path) if attempted_path else None,
            "move": applied_move.notation if applied_move else None,
            "captured_squares": list(applied_move.captured) if applied_move else [],
            "valid": valid,
            "status": "LEGAL" if valid else (
                "API_ERROR" if raw_response.startswith("API_ERROR") else "INVALID"
            ),
            "reason": reason,
            "pre_board": pre_board,
            "post_board": {
                str(square): piece for square, piece in sorted(game.board.items())
            },
            "request_metadata": response_metadata,
            "captured_at": datetime.now().astimezone().isoformat(),
        }
        audit["turns"].append(event)

        if not valid:
            failed = True
            failure_reason = reason
            end_reason = "Invalid Move" if event["status"] == "INVALID" else "API Error"
            break
        if game.finished:
            end_reason = "Draw" if game.draw else "No Legal Moves"
            break
    else:
        end_reason = "Max Plies Reached"

    winner = game.winner
    result = f"{winner} wins" if winner else (
        "Draw" if game.draw else f"Stopped after {len(audit['turns'])} plies"
    )
    audit.update(
        completed_at=datetime.now().astimezone().isoformat(),
        winner=winner,
        draw=game.draw,
        result=result,
        end_reason=end_reason,
        failed=failed,
        failure_reason=failure_reason,
        plies_played=len(audit["turns"]),
        board_print_requests=board_print_requests,
    )
    audit["pdn"] = build_pdn(audit)

    slimmed_replay = slim_checkers_audit(audit)
    last_turn = slimmed_replay["turns"][-1] if slimmed_replay["turns"] else {}
    last_raw = str(last_turn.get("raw_response", ""))
    culprit_player = str(last_turn.get("player", "White"))
    culprit_model = str(last_turn.get("model", white_model))

    status, clean_reason = classify_checkers_outcome(
        failed=failed,
        failure_reason=failure_reason or result,
        raw_response=last_raw,
        culprit_label=f"{culprit_player} / {culprit_model}",
    )

    exact_prompt = SYSTEM_PROMPT
    if last_turn.get("user_prompt"):
        exact_prompt = (
            f"System:\n{SYSTEM_PROMPT}\n\n"
            f"User (Ply {last_turn.get('ply')}):\n{last_turn.get('user_prompt')}"
        )

    cloud_trial_id = (
        f"checkers__{white_model}__{run_id}__Trial_{trial_id:03d}"
        .replace(" ", "_")
        .replace("/", "-")
    )

    log_trial_to_supabase(
        game="checkers",
        white_model=white_model,
        black_model=black_model,
        status=status,
        plies_survived=len(audit["turns"]),
        failure_reason=clean_reason,
        board_print_requests=board_print_requests,
        exact_prompt=exact_prompt,
        trial_id=cloud_trial_id,
        replay_data=slimmed_replay,
    )

    return {
        "trial_id": cloud_trial_id,
        "white_model": white_model,
        "black_model": black_model,
        "winner": winner or "",
        "result": result,
        "status": status,
        "plies_played": len(audit["turns"]),
        "board_print_requests": board_print_requests,
        "failed": int(failed),
        "failure_reason": clean_reason,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--white-model", required=True, help="Model to test as White.")
    parser.add_argument(
        "--black-model",
        default="random",
        help="Black model, 'self' for self-play, or 'random' for a legal random baseline.",
    )
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--max-plies", type=int, default=100)
    parser.add_argument(
        "--reasoning-effort",
        choices=("auto", "low", "medium", "high"),
        default="auto",
    )
    parser.add_argument("--openai-api-key")
    parser.add_argument("--groq-api-key")
    parser.add_argument("--gemini-api-key")
    parser.add_argument("--anthropic-api-key")
    parser.add_argument(
        "--white-provider",
        choices=SUPPORTED_PROVIDERS,
        default="auto",
    )
    parser.add_argument(
        "--black-provider",
        choices=SUPPORTED_PROVIDERS,
        default="auto",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be at least 1.")
    if args.max_plies < 1:
        parser.error("--max-plies must be at least 1.")
    if args.white_model.lower() == "random":
        parser.error("White must be an API-backed model.")

    run_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    try:
        clients = create_clients(
            [args.white_model, args.black_model],
            args.openai_api_key,
            args.groq_api_key,
            [args.white_provider, args.black_provider],
            args.gemini_api_key,
            args.anthropic_api_key,
        )
        for trial_num in range(1, args.trials + 1):
            trial = run_trial(
                trial_num,
                args.white_model,
                args.black_model,
                args.max_plies,
                clients,
                args.reasoning_effort,
                run_id,
                args.white_provider,
                args.black_provider,
            )
            print(
                f"[Cloud Logged] Trial {trial_num:02d}/{args.trials:02d} | "
                f"Status: {trial['status']} | Plies: {trial['plies_played']} | "
                f"Note: {trial['failure_reason']}"
            )
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
