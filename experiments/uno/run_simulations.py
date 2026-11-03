"""Run simplified UNO state-tracking trials against supported language models."""

import argparse
import csv
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from openai import APIError, OpenAI, RateLimitError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "local"
COLORS = ("Red", "Blue", "Green", "Yellow")
VALUES = tuple(str(number) for number in range(10)) + ("Skip", "Reverse", "Draw Two")
PLAYERS = ("Agent_A", "Agent_B")
SYSTEM_PROMPT = (
    "You are an automated UNO player. Respond ONLY with either "
    "'PLAY <Color> <Value>' or 'DRAW'. Never add quotes, conversational text, "
    "markdown, or explanations. Format strictly as specified."
)
PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


@dataclass(frozen=True)
class Card:
    color: str
    value: str

    def __str__(self) -> str:
        return f"{self.color} {self.value}"


class UnoReferee:
    """Small UNO-like rules engine used by the experiment."""

    def __init__(self) -> None:
        deck = [Card(color, value) for color in COLORS for value in VALUES] * 2
        random.shuffle(deck)
        self.deck = deck
        self.hands = {
            player: [self.deck.pop() for _ in range(7)] for player in PLAYERS
        }
        self.discard_pile = [self.deck.pop()]
        while self.discard_pile[-1].value in {"Skip", "Reverse", "Draw Two"}:
            self.discard_pile.append(self.deck.pop())

    @property
    def top_card(self) -> Card:
        return self.discard_pile[-1]

    def validate_and_play(self, player: str, action: str) -> tuple[bool, str]:
        cleaned = action.strip()
        if cleaned.upper() == "DRAW":
            if self.deck:
                self.hands[player].append(self.deck.pop())
            return True, "Valid Draw"

        if not cleaned.upper().startswith("PLAY "):
            return (
                False,
                f"Syntax Error: Invalid format '{cleaned}'. "
                "Expected 'PLAY <Color> <Value>' or 'DRAW'.",
            )

        card_parts = cleaned[5:].strip().split(" ", 1)
        if len(card_parts) != 2:
            return False, f"Syntax Error: Unrecognized card format '{cleaned[5:].strip()}'."

        color, value = card_parts[0].capitalize(), card_parts[1].title()
        matching_indices = [
            index
            for index, card in enumerate(self.hands[player])
            if card.color == color and card.value == value
        ]
        if not matching_indices:
            return False, f"Inventory Amnesia: Claimed {color} {value} not in hand."

        chosen_card = self.hands[player][matching_indices[0]]
        if chosen_card.color != self.top_card.color and chosen_card.value != self.top_card.value:
            return False, f"Rule Mismatch: Played {chosen_card} on top of {self.top_card}."

        self.hands[player].pop(matching_indices[0])
        self.discard_pile.append(chosen_card)
        return True, "Valid Move"


def infer_provider(model_name: str) -> str:
    lowered = model_name.lower()
    if "gemini" in lowered:
        return "gemini"
    if "deepseek" in lowered:
        return "ollama"
    if "groq" in lowered or "oss" in lowered or "120b" in lowered:
        return "groq"
    return "openai"


def create_client(
    provider: str, api_key: str | None = None
) -> OpenAI | genai.Client:
    if provider == "ollama":
        return OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    if provider not in PROVIDER_ENV_VARS:
        raise ValueError(f"Unsupported provider: {provider}")

    key = (api_key or os.getenv(PROVIDER_ENV_VARS[provider]) or "").strip()
    if not key:
        raise ValueError(
            f"Set {PROVIDER_ENV_VARS[provider]} or provide --api-key for {provider}."
        )
    if provider == "gemini":
        return genai.Client(api_key=key)
    if provider == "groq":
        return OpenAI(base_url="https://api.groq.com/openai/v1", api_key=key)
    return OpenAI(api_key=key)


def query_model(
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    provider: str,
    client: OpenAI | genai.Client,
) -> str:
    if provider == "gemini":
        return query_gemini(system_prompt, user_prompt, model_name, client)
    if not isinstance(client, OpenAI):
        raise TypeError("OpenAI-compatible providers require an OpenAI client.")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.2,
                max_tokens=300,
            )
            return (response.choices[0].message.content or "").strip()
        except RateLimitError as error:
            if attempt < 2:
                wait_seconds = 25
                print(
                    f"Rate limit; retrying in {wait_seconds}s ({attempt + 1}/3)."
                )
                time.sleep(wait_seconds)
                continue
            return f"API_ERROR: {error}"
        except APIError as error:
            return f"API_ERROR: {error}"
    return "API_ERROR: Maximum retries exceeded."


def query_gemini(
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    client: object,
) -> str:
    if not isinstance(client, genai.Client):
        raise TypeError("Gemini provider requires a Google GenAI client.")

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    max_output_tokens=40,
                ),
            )
            return (response.text or "").strip()
        except genai_errors.APIError as error:
            message = str(error)
            retryable = any(
                marker in message.upper()
                for marker in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")
            )
            if retryable and attempt < 2:
                wait_seconds = 25
                print(
                    f"Temporary provider error; retrying in {wait_seconds}s "
                    f"({attempt + 1}/3)."
                )
                time.sleep(wait_seconds)
                continue
            return f"API_ERROR: {message}"
    return "API_ERROR: Maximum retries exceeded."


def run_trial(
    trial_id: int,
    model_name: str,
    provider: str,
    client: OpenAI | genai.Client,
    max_turns: int = 50,
) -> dict[str, str | int]:
    game = UnoReferee()
    player_index = 0

    for turn in range(1, max_turns + 1):
        player = PLAYERS[player_index]
        if not game.hands[player]:
            return {
                "trial_id": trial_id,
                "model": model_name,
                "turns_survived": turn - 1,
                "failed": 0,
                "failure_reason": "Game Won Legally",
                "raw_response": "",
            }

        hand = ", ".join(str(card) for card in game.hands[player])
        user_prompt = (
            f"Active Discard Card: {game.top_card}\n"
            f"Cards Currently In Your Hand: [{hand}]\n\n"
            "CRITICAL CONSTRAINTS:\n"
            "1. You may ONLY choose a card listed in your hand.\n"
            "2. The chosen card must match the Active Discard Card by color or value.\n"
            "3. If NO card in your hand matches, respond with 'DRAW'.\n\n"
            "Your Command:"
        )
        raw_response = query_model(
            SYSTEM_PROMPT, user_prompt, model_name, provider, client
        )
        if raw_response.startswith("API_ERROR"):
            return {
                "trial_id": trial_id,
                "model": model_name,
                "turns_survived": turn,
                "failed": 1,
                "failure_reason": raw_response,
                "raw_response": raw_response,
            }

        valid, reason = game.validate_and_play(player, raw_response)
        if not valid:
            return {
                "trial_id": trial_id,
                "model": model_name,
                "turns_survived": turn,
                "failed": 1,
                "failure_reason": reason,
                "raw_response": raw_response,
            }
        if not game.hands[player]:
            return {
                "trial_id": trial_id,
                "model": model_name,
                "turns_survived": turn,
                "failed": 0,
                "failure_reason": "Game Won Legally",
                "raw_response": "",
            }
        player_index = 1 - player_index

    return {
        "trial_id": trial_id,
        "model": model_name,
        "turns_survived": max_turns,
        "failed": 0,
        "failure_reason": "Max Turns Reached",
        "raw_response": "",
    }


def execute_batch(
    model_name: str,
    provider: str,
    client: OpenAI | genai.Client,
    csv_path: Path,
    num_trials: int,
    max_turns: int,
    append: bool = False,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists() and not append:
        raise FileExistsError(f"{csv_path} already exists; use --append to add rows.")

    fieldnames = [
        "trial_id",
        "model",
        "turns_survived",
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
        print(f"Starting {num_trials} UNO trials | {model_name} ({provider})")
        print(f"Results: {csv_path}")
        for trial_id in range(1, num_trials + 1):
            result = run_trial(
                trial_id, model_name, provider, client, max_turns=max_turns
            )
            writer.writerow(result)
            results_file.flush()
            print(
                f"Trial {trial_id:02d}/{num_trials:02d} | "
                f"Turns: {result['turns_survived']} | "
                f"Failed: {result['failed']} | {result['failure_reason']}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Provider model identifier.")
    parser.add_argument(
        "--provider",
        choices=("auto", "openai", "groq", "ollama", "gemini"),
        default="auto",
    )
    parser.add_argument("--trials", type=int, default=15)
    parser.add_argument("--max-turns", type=int, default=50)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--append", action="store_true")
    parser.add_argument(
        "--api-key",
        help="Provider key; setting the provider's environment variable is preferred.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be at least 1.")
    if args.max_turns < 1:
        parser.error("--max-turns must be at least 1.")
    if args.append and args.output_csv is None:
        parser.error("--append requires --output-csv.")

    provider = infer_provider(args.model) if args.provider == "auto" else args.provider
    run_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    safe_model = re.sub(r"[^a-zA-Z0-9_-]", "_", args.model)
    csv_path = args.output_csv or (
        DEFAULT_OUTPUT_DIR / "results" / f"uno_{safe_model}_{run_id}.csv"
    )
    try:
        client = create_client(provider, args.api_key)
        execute_batch(
            args.model,
            provider,
            client,
            csv_path,
            args.trials,
            args.max_turns,
            append=args.append,
        )
    except (FileExistsError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
