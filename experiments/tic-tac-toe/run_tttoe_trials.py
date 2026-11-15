"""Run lightweight Tic-Tac-Toe trials and log results directly to Supabase."""

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
from cloud_logger import classify_tictactoe_outcome, log_trial_to_supabase

SYSTEM_PROMPT = (
    "You are playing tic-tac-toe as {mark}. The board starts empty, with squares "
    "numbered 1-9 left-to-right and top-to-bottom. Maintain the game state across "
    "this conversation: your prior move replies are your moves, and each new user "
    "message gives the opponent's latest mark and square. PRINT OUT BOARD replies "
    "only request the current board and do not advance the game. Choose an empty "
    "square, or reply exactly PRINT OUT BOARD to request the current board. For a "
    "move, reply with exactly one digit from 1 to 9 and no other text."
)
PRINT_BOARD_RESPONSE = "PRINT OUT BOARD"
REQUEST_CONFIG = {"temperature": 0.2, "max_tokens": 16}
ASTRA_REQUEST_CONFIG = {
    "max_completion_tokens": 512,
    "reasoning_effort": "low",
}
GPT_OSS_REQUEST_CONFIG = {
    "temperature": 0.2,
    "max_completion_tokens": 512,
    "reasoning_effort": "low",
    "extra_body": {"reasoning_format": "hidden"},
}
GPT_OSS_MAX_COMPLETION_TOKENS = (512, 1024, 2048)
WINNING_LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


class TicTacToe:
    def __init__(self) -> None:
        self.board: list[str | None] = [None] * 9
        self.next_mark = "X"
        self.winner: str | None = None

    @property
    def finished(self) -> bool:
        return self.winner is not None or all(mark is not None for mark in self.board)

    def play(self, mark: str, position: int) -> tuple[bool, str]:
        if self.finished:
            return False, "Game is already over."
        if mark != self.next_mark:
            return False, f"It is {self.next_mark}'s turn, not {mark}'s."
        if position < 1 or position > 9:
            return False, "Position must be between 1 and 9."
        if self.board[position - 1] is not None:
            return False, f"Position {position} is already occupied."

        self.board[position - 1] = mark
        self.winner = next(
            (
                played_mark
                for line in WINNING_LINES
                if (played_mark := self.board[line[0]]) == mark
                and self.board[line[1]] == mark
                and self.board[line[2]] == mark
            ),
            None,
        )
        self.next_mark = "O" if mark == "X" else "X"
        return True, "Legal move."


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
            return model_name[len(prefix):]
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
                api_key="ollama",  # Ollama ignores the key but the SDK requires a non-empty string
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


def board_text(board: list[str | None]) -> str:
    cells = [mark or str(index + 1) for index, mark in enumerate(board)]
    return "\n".join(" | ".join(cells[row : row + 3]) for row in (0, 3, 6))


def query_model(
    mark: str,
    model_name: str,
    clients: dict[str, OpenAI],
    user_prompt: str,
    conversation: list[dict[str, str]] | None = None,
) -> tuple[str, str]:
    system_prompt = SYSTEM_PROMPT.format(mark=mark)
    provider = provider_for_model(model_name)
    client = clients[provider]
    request_config = (
        GPT_OSS_REQUEST_CONFIG
        if provider == "groq" and "gpt-oss" in model_name.lower()
        else ASTRA_REQUEST_CONFIG
        if "astra" in model_name.lower()
        else REQUEST_CONFIG
    )
    request = {

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


def parse_integer_response(raw_response: str) -> int | None:
    """Returns the integer if the response is a number (even outside 1-9), else None."""
    cleaned = raw_response.strip()
    if re.fullmatch(r"[-+]?\d+", cleaned):
        return int(cleaned)
    return None


def is_print_board_response(raw_response: str) -> bool:
    return raw_response.strip().casefold() == PRINT_BOARD_RESPONSE.casefold()


def run_trial(
    trial_num: int,
    x_model: str,
    o_model: str,
    clients: dict[str, OpenAI],
    run_id: str,
) -> dict[str, Any]:
    if o_model == "self":
        o_model = x_model
    players = {"X": x_model, "O": o_model}
    game = TicTacToe()

    board_print_requests = 0
    moves_played = 0
    last_move: dict[str, Any] | None = None
    last_Prompt_sent = ""
    conversations: dict[str, list[dict[str, str]]] = {"X": [], "O": []}

    failed_raw_response: str | None = None
    occupied_square_error = False

    for _turn in range(1, 10):
        if game.finished:
            break
        mark = game.next_mark
        model_name = players[mark]

        if model_name.lower() == "random":
            raw_response = str(
                random.choice([idx + 1 for idx, cell in enumerate(game.board) if cell is None])
            )
            user_prompt = "Random baseline move"
        else:
            if last_move is not None:
                user_prompt = (
                    f"Opponent played: {last_move['mark']} in square "
                    f"{last_move['position']}. Your move:"
                )
            else:
                user_prompt = f"Game start. You are {mark}; the board is empty. Your move:"

            while True:
                raw_response, user_prompt = query_model(
                    mark, model_name, clients, user_prompt, conversations[mark]
                )
                last_Prompt_sent = f"System:\n{SYSTEM_PROMPT.format(mark=mark)}\n\nUser:\n{user_prompt}"
                if not is_print_board_response(raw_response):
                    break
                board_print_requests += 1
                user_prompt = (
                    "Current board (squares are numbered 1-9, left-to-right, "
                    f"top-to-bottom):\n{board_text(game.board)}\n"
                    f"It is still {mark}'s turn. Choose an empty square, or "
                    f"reply exactly {PRINT_BOARD_RESPONSE} to display the board again."
                )

        moves_played += 1
        parsed_num = parse_integer_response(raw_response)

        if raw_response.startswith("API_ERROR") or parsed_num is None:
            failed_raw_response = raw_response
            break

        valid, reason = game.play(mark, parsed_num)
        if not valid:
            failed_raw_response = raw_response
            occupied_square_error = "occupied" in reason.lower()
            break

        last_move = {"mark": mark, "position": parsed_num}

    completed = failed_raw_response is None and game.finished
    status, failure_reason = classify_tictactoe_outcome(
        completed=completed,
        raw_response=failed_raw_response,
        occupied_square=occupied_square_error,
    )

    cloud_trial_id = f"tic-tac-toe__{x_model}__{run_id}__Trial_{trial_num:03d}".replace(" ", "_").replace("/", "-")
    exact_prompt_record = last_Prompt_sent or SYSTEM_PROMPT

    log_trial_to_supabase(
        game="tic-tac-toe",
        white_model=x_model,
        black_model=o_model,
        status=status,
        plies_survived=moves_played,
        failure_reason=failure_reason,
        board_print_requests=board_print_requests,
        exact_prompt=exact_prompt_record,
        trial_id=cloud_trial_id,
        replay_data=None,  # Keep Tic-Tac-Toe ultra-lightweight
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
    parser.add_argument("--x-model", required=True, help="Model or 'random' for X.")
    parser.add_argument("--o-model", default="self", help="Model, 'self', or 'random'.")
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
    clients = create_clients([args.x_model, args.o_model], args.openai_api_key, args.groq_api_key)

    for trial_num in range(1, args.trials + 1):
        res = run_trial(trial_num, args.x_model, args.o_model, clients, run_id)
        print(
            f"[Cloud Logged] Trial {trial_num:02d}/{args.trials:02d} | "
            f"Status: {res['status']} | Plies: {res['moves_played']} | "
            f"Note: {res['failure_reason']}"
        )


if __name__ == "__main__":
    main()