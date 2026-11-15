"""Run lightweight Connect Four trials and log results directly to Supabase."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any

from openai import APIError, OpenAI, RateLimitError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "experiments"))
from cloud_logger import classify_connect_four_outcome, log_trial_to_supabase

SYSTEM_PROMPT = (
    "You are playing Connect Four as {color} ({mark}). The board has 7 columns "
    "labeled A-G and 6 rows. Discs fall to the lowest empty space in the chosen "
    "column. The game may start from a partially filled board provided in your "
    "first message. Maintain the game state across this conversation: update "
    "your internal board with your own moves and each new user message giving "
    "the opponent's latest move. PRINT OUT BOARD replies only request the "
    "current board and do not advance the game. Choose a column that is not "
    "full. Reply with exactly one column letter from A to G, or reply exactly "
    "PRINT OUT BOARD to request the current board. For a move, provide no other text."
)
PRINT_BOARD_RESPONSE = "PRINT OUT BOARD"
REQUEST_CONFIG = {"temperature": 0.2, "max_tokens": 8}
ASTRA_REQUEST_CONFIG = {
    "max_completion_tokens": 1024,
    "reasoning_effort": "low",
}
GPT_OSS_REQUEST_CONFIG = {
    "temperature": 0.2,
    "max_completion_tokens": 512,
    "reasoning_effort": "low",
    "extra_body": {"reasoning_format": "hidden"},
}
GPT_OSS_MAX_COMPLETION_TOKENS = (512, 1024, 2048)
ROWS = 6
COLUMNS = 7
CONNECT_LENGTH = 4
PLAYER_COLORS = {"R": "Red", "Y": "Yellow"}


class ConnectFour:
    """Connect Four rules with row zero at the top of the visible board."""

    def __init__(self) -> None:
        self.board: list[list[str | None]] = [
            [None for _ in range(COLUMNS)] for _ in range(ROWS)
        ]
        self.next_mark = "R"
        self.winner: str | None = None
        self.moves_played = 0

    @classmethod
    def from_prefilled(cls) -> "ConnectFour":
        """Build a 4-row-high (28/42 discs) staggered board with max run length 2 in all directions."""
        game = cls()
        row_a = ["R", "R", "Y", "Y", "R", "R", "Y"]
        row_b = ["Y", "Y", "R", "R", "Y", "Y", "R"]
        game.board = [
            [None] * COLUMNS,  # Row 6 (open)
            [None] * COLUMNS,  # Row 5 (open)
            list(row_a),       # Row 4
            list(row_b),       # Row 3
            list(row_a),       # Row 2
            list(row_b),       # Row 1 (bottom)
        ]
        game.moves_played = 28  # 14 R and 14 Y
        game.next_mark = "R"
        game.winner = None
        return game

    @property
    def draw(self) -> bool:
        return self.winner is None and self.moves_played == ROWS * COLUMNS

    @property
    def finished(self) -> bool:
        return self.winner is not None or self.draw

    def legal_columns(self) -> list[int]:
        return [
            column + 1
            for column in range(COLUMNS)
            if self.board[0][column] is None
        ]

    def play(self, mark: str, column: int) -> tuple[bool, str, int | None]:
        if self.finished:
            return False, "Game is already over.", None
        if mark != self.next_mark:
            return False, f"It is {self.next_mark}'s turn, not {mark}'s.", None
        if column < 1 or column > COLUMNS:
            return False, "Column must be between A and G.", None

        column_index = column - 1
        row = next(
            (
                candidate
                for candidate in range(ROWS - 1, -1, -1)
                if self.board[candidate][column_index] is None
            ),
            None,
        )
        if row is None:
            return False, f"Column {chr(64 + column)} is full.", None

        self.board[row][column_index] = mark
        self.moves_played += 1
        if self._has_four(row, column_index, mark):
            self.winner = mark
        self.next_mark = "Y" if mark == "R" else "R"
        return True, "Legal move.", ROWS - row

    def _has_four(self, row: int, column: int, mark: str) -> bool:
        for row_step, column_step in ((0, 1), (1, 0), (1, 1), (1, -1)):
            count = 1
            for direction in (-1, 1):
                next_row = row + row_step * direction
                next_column = column + column_step * direction
                while (
                    0 <= next_row < ROWS
                    and 0 <= next_column < COLUMNS
                    and self.board[next_row][next_column] == mark
                ):
                    count += 1
                    next_row += row_step * direction
                    next_column += column_step * direction
            if count >= CONNECT_LENGTH:
                return True
        return False


def provider_for_model(model_name: str) -> str:
    lowered = model_name.lower()
    if lowered.startswith("ollama/") or lowered.startswith("local/"):
        return "ollama"
    if "gpt-oss" in lowered:
        return "groq"
    return "openai" if lowered.startswith("gpt-") or "astra" in lowered else "groq"


def clean_model_name(model_name: str) -> str:
    for prefix in ("ollama/", "local/"):
        if model_name.lower().startswith(prefix):
            return model_name[len(prefix) :]
    return model_name


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
        "openai": (openai_api_key or os.getenv("OPENAI_API_KEY") or "").strip(),
        "groq": (groq_api_key or os.getenv("GROQ_API_KEY") or "").strip(),
    }
    clients: dict[str, OpenAI] = {}
    for provider in required_providers:
        if provider == "ollama":
            clients["ollama"] = OpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
            )
        elif provider == "groq":
            if not keys["groq"]:
                raise ValueError("Set GROQ_API_KEY or pass --groq-api-key.")
            clients["groq"] = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=keys["groq"],
            )
        else:
            if not keys["openai"]:
                raise ValueError("Set OPENAI_API_KEY or pass --openai-api-key.")
            clients["openai"] = OpenAI(api_key=keys["openai"])
    return clients


def parse_column(raw_response: str) -> int | None:
    match = re.fullmatch(
        r"\s*(?:column\s+)?([A-G])\s*\.?\s*",
        raw_response.strip(),
        flags=re.IGNORECASE,
    )
    return ord(match.group(1).upper()) - ord("A") + 1 if match else None


def is_print_board_response(raw_response: str) -> bool:
    return raw_response.strip().casefold() == PRINT_BOARD_RESPONSE.casefold()


def board_text(board: list[list[str | None]]) -> str:
    rows = ["  A B C D E F G"]
    for visible_row, cells in enumerate(board):
        labels = " ".join(cell or "." for cell in cells)
        rows.append(f"{ROWS - visible_row} {labels}")
    return "\n".join(rows)


def query_model(
    mark: str,
    model_name: str,
    clients: dict[str, OpenAI],
    user_prompt: str,
    conversation: list[dict[str, str]] | None = None,
) -> tuple[str, str]:
    system_prompt = SYSTEM_PROMPT.format(color=PLAYER_COLORS[mark], mark=mark)
    provider = provider_for_model(model_name)
    client = clients[provider]
    request_config = (
        GPT_OSS_REQUEST_CONFIG
        if provider == "groq" and "gpt-oss" in model_name.lower()
        else ASTRA_REQUEST_CONFIG
        if "astra" in model_name.lower()
        else REQUEST_CONFIG
    )
    request: dict[str, Any] = {
        "model": clean_model_name(model_name),
        "messages": [
            {"role": "system", "content": system_prompt},
            *(conversation or []),
            {"role": "user", "content": user_prompt},
        ],
        **request_config,
    }
    is_gpt_oss = provider == "groq" and "gpt-oss" in model_name.lower()
    budget_attempt = 0
    rate_limit_retries = 0
    while True:
        if is_gpt_oss:
            request["max_completion_tokens"] = GPT_OSS_MAX_COMPLETION_TOKENS[budget_attempt]
        try:
            response = client.chat.completions.create(**request)
            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if is_gpt_oss and finish_reason == "length":
                if budget_attempt < len(GPT_OSS_MAX_COMPLETION_TOKENS) - 1:
                    budget_attempt += 1
                    continue
                return "API_ERROR: truncated", user_prompt

            raw_response = (choice.message.content or "").strip()
            if conversation is not None:
                conversation.extend(
                    [
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": raw_response},
                    ]
                )
            return raw_response, user_prompt
        except RateLimitError as error:
            if rate_limit_retries < 2:
                rate_limit_retries += 1
                time.sleep(10)
                continue
            return f"API_ERROR: {error}", user_prompt
        except APIError as error:
            return f"API_ERROR: {error}", user_prompt


def run_trial(
    trial_num: int,
    red_model: str,
    yellow_model: str,
    clients: dict[str, OpenAI],
    run_id: str,
) -> dict[str, Any]:
    if yellow_model == "self":
        yellow_model = red_model
    players = {"R": red_model, "Y": yellow_model}
    game = ConnectFour.from_prefilled()
    initial_moves_played = game.moves_played
    remaining_plies = (ROWS * COLUMNS) - initial_moves_played

    board_print_requests = 0
    moves_played = 0
    last_move: dict[str, Any] | None = None
    last_prompt_sent = ""
    conversations: dict[str, list[dict[str, str]]] = {"R": [], "Y": []}

    failed_raw_response: str | None = None
    column_full_error = False
    culprit_label = ""

    for _turn in range(1, remaining_plies + 1):
        if game.finished:
            break
        mark = game.next_mark
        model_name = players[mark]

        if model_name.lower() == "random":
            raw_response = chr(64 + random.choice(game.legal_columns()))
            user_prompt = "Random baseline move"
        else:
            if not conversations[mark]:
                last_note = ""
                if last_move is not None:
                    last_note = (
                        f" Opponent just played {last_move['mark']} in "
                        f"column {last_move['column']}."
                    )
                user_prompt = (
                    f"Game in progress ({game.moves_played}/{ROWS * COLUMNS} "
                    f"spaces filled). You are {PLAYER_COLORS[mark]} ({mark})."
                    f"{last_note}\n"
                    "Starting board state for your first turn (columns A-G, "
                    "top row first):\n"
                    f"{board_text(game.board)}\n"
                    "Track all subsequent moves from this board state without "
                    "relying on repeated board printouts unless needed. Your move:"
                )
            else:
                user_prompt = (
                    f"Opponent played: {last_move['mark']} in column "
                    f"{last_move['column']}. Your move:"
                )

            while True:
                raw_response, user_prompt = query_model(
                    mark, model_name, clients, user_prompt, conversations[mark]
                )
                sys_filled = SYSTEM_PROMPT.format(color=PLAYER_COLORS[mark], mark=mark)
                last_prompt_sent = f"System:\n{sys_filled}\n\nUser:\n{user_prompt}"
                if not is_print_board_response(raw_response):
                    break
                board_print_requests += 1
                user_prompt = (
                    "Current board (columns A-G, top row first):\n"
                    f"{board_text(game.board)}\n"
                    f"It is still your turn as {PLAYER_COLORS[mark]} ({mark}). "
                    "Choose a non-full column, or reply exactly "
                    f"{PRINT_BOARD_RESPONSE} to display the board again."
                )

        moves_played += 1
        column = parse_column(raw_response)

        if raw_response.startswith("API_ERROR") or column is None:
            failed_raw_response = raw_response
            culprit_label = f"{PLAYER_COLORS[mark]} / {model_name}"
            break

        valid, reason, _row = game.play(mark, column)
        if not valid:
            failed_raw_response = raw_response
            column_full_error = "full" in reason.lower()
            culprit_label = f"{PLAYER_COLORS[mark]} / {model_name}"
            break

        last_move = {"mark": mark, "column": chr(64 + column)}

    completed = failed_raw_response is None and game.finished
    status, failure_reason = classify_connect_four_outcome(
        completed=completed,
        raw_response=failed_raw_response,
        column_full=column_full_error,
        culprit_label=culprit_label,
    )

    cloud_trial_id = (
        f"connect-four__{red_model}__{run_id}__Trial_{trial_num:03d}"
        .replace(" ", "_")
        .replace("/", "-")
    )
    exact_prompt_record = last_prompt_sent or SYSTEM_PROMPT

    log_trial_to_supabase(
        game="connect-four",
        white_model=red_model,
        black_model=yellow_model,
        status=status,
        plies_survived=moves_played,
        failure_reason=failure_reason,
        board_print_requests=board_print_requests,
        exact_prompt=exact_prompt_record,
        trial_id=cloud_trial_id,
        replay_data=None,  # Lightweight catalog-only storage like Tic-Tac-Toe
    )

    return {
        "trial_id": cloud_trial_id,
        "status": status,
        "moves_played": moves_played,
        "board_print_requests": board_print_requests,
        "failure_reason": failure_reason,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red-model", required=True, help="Model or 'random' for Red.")
    parser.add_argument("--yellow-model", default="self", help="Model, 'self', or 'random'.")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--openai-api-key")
    parser.add_argument("--groq-api-key")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be at least 1.")

    run_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    clients = create_clients(
        [args.red_model, args.yellow_model], args.openai_api_key, args.groq_api_key
    )

    for trial_num in range(1, args.trials + 1):
        res = run_trial(trial_num, args.red_model, args.yellow_model, clients, run_id)
        print(
            f"[Cloud Logged] Trial {trial_num:02d}/{args.trials:02d} | "
            f"Status: {res['status']} | Plies: {res['moves_played']} | "
            f"Note: {res['failure_reason']}"
        )


if __name__ == "__main__":
    main()