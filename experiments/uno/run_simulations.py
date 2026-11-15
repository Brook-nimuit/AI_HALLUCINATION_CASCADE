"""Run simplified UNO state-tracking trials against supported language models."""

import argparse
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from openai import APIError, OpenAI, RateLimitError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "experiments"))
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "local"
from cloud_logger import classify_uno_outcome, log_trial_to_supabase, slim_uno_audit
COLORS = ("Red", "Blue", "Green", "Yellow")
VALUES = tuple(str(number) for number in range(10)) + ("Skip", "Reverse", "Draw Two")
PLAYERS = ("Agent_A", "Agent_B")
SYSTEM_PROMPT = (
    "You are playing this simplified UNO game. Maintain the game state across "
    "this conversation: your prior assistant replies are your actions, and each "
    "new user message gives the opponent's latest action and your current hand. "
    "Treat the listed hand as authoritative, including any cards drawn by the "
    "referee. Play only a card in your hand matching the active discard by color "
    "or value; if none matches, draw. Respond with exactly 'PLAY <Color> <Value>' "
    "or 'DRAW' and no other text."
)
MAX_FORMAT_RETRIES = 2
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
    if lowered.startswith("ollama/") or lowered.startswith("local/") or "deepseek" in lowered:
        return "ollama"
    if "gemini" in lowered:
        return "gemini"
    if "groq" in lowered or "oss" in lowered or "120b" in lowered:
        return "groq"
    return "openai"


def clean_model_name(model_name: str) -> str:
    for prefix in ("ollama/", "local/"):
        if model_name.lower().startswith(prefix):
            return model_name[len(prefix):]
    return model_name


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


MAX_COMPLETION_TOKENS = (1024, 2048, 4096)


def is_openai_reasoning_model(model_name: str, provider: str) -> bool:
    if provider != "openai":
        return False
    lowered = model_name.lower()
    return (
        "astra" in lowered
        or "luna" in lowered
        or "terra" in lowered
        or lowered.startswith("gpt-6")
        or bool(re.match(r"o[134](?:-|$)", lowered))
    )


def query_model(
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    provider: str,
    client: OpenAI | genai.Client,
    response_details: dict[str, Any] | None = None,
    conversation: list[dict[str, str]] | None = None,
) -> str:
    if provider == "gemini":
        return query_gemini(
            system_prompt,
            user_prompt,
            model_name,
            client,
            response_details,
            conversation,
        )
    if not isinstance(client, OpenAI):
        raise TypeError("OpenAI-compatible providers require an OpenAI client.")

    messages = [
        {"role": "system", "content": system_prompt},
        *(conversation or []),
        {"role": "user", "content": user_prompt},
    ]
    uses_reasoning = is_openai_reasoning_model(model_name, provider)
    request_options: dict[str, Any] = (
        {
            "max_completion_tokens": MAX_COMPLETION_TOKENS[0],
            "reasoning_effort": "low",
        }
        if uses_reasoning
        else {
            "temperature": 0.2,
            "max_tokens": 300,
        }
    )
    if response_details is not None:
        response_details["request_options"] = request_options.copy()

    budget_attempt = 0
    rate_limit_retries = 0
    while True:
        if uses_reasoning:
            request_options["max_completion_tokens"] = MAX_COMPLETION_TOKENS[
                budget_attempt
            ]
        try:
            response = client.chat.completions.create(
                model=clean_model_name(model_name),
                messages=messages,
                **request_options,
            )
            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if uses_reasoning and finish_reason == "length":
                usage = getattr(response, "usage", None)
                if response_details is not None:
                    response_details.setdefault("truncated_attempts", []).append(
                        {
                            "max_completion_tokens": request_options[
                                "max_completion_tokens"
                            ],
                            "completion_tokens": (
                                usage.completion_tokens if usage else None
                            ),
                        }
                    )
                if budget_attempt < len(MAX_COMPLETION_TOKENS) - 1:
                    budget_attempt += 1
                    continue
                err = (
                    "Model response was truncated at "
                    f"{request_options['max_completion_tokens']} completion tokens."
                )
                if response_details is not None:
                    response_details["error"] = err
                return f"API_ERROR: {err}"

            if response_details is not None:
                response_details["request_options"] = request_options.copy()
                response_details["provider_response"] = response.model_dump(
                    mode="json"
                )
            raw_response = (choice.message.content or "").strip()
            if conversation is not None:
                conversation.extend(
                    [
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": raw_response},
                    ]
                )
            return raw_response
        except RateLimitError as error:
            if response_details is not None:
                response_details["error"] = str(error)
            if rate_limit_retries < 2:
                rate_limit_retries += 1
                wait_seconds = 25
                print(
                    f"Rate limit; retrying in {wait_seconds}s ({rate_limit_retries}/3)."
                )
                time.sleep(wait_seconds)
                continue
            return f"API_ERROR: {error}"
        except APIError as error:
            if response_details is not None:
                response_details["error"] = str(error)
            return f"API_ERROR: {error}"

def query_gemini(
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    client: object,
    response_details: dict[str, Any] | None = None,
    conversation: list[dict[str, str]] | None = None,
) -> str:
    if not isinstance(client, genai.Client):
        raise TypeError("Gemini provider requires a Google GenAI client.")

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
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    max_output_tokens=40,
                ),
            )
            if response_details is not None:
                response_details["provider_response"] = response.model_dump(
                    mode="json"
                )
            raw_response = (response.text or "").strip()
            if conversation is not None:
                conversation.extend(
                    [
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": raw_response},
                    ]
                )
            return raw_response
        except genai_errors.APIError as error:
            message = str(error)
            if response_details is not None:
                response_details["error"] = message
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
    max_turns: int = 500,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_id: str | None = None,
) -> dict[str, Any]:
    game = UnoReferee()
    player_index = 0
    conversations: dict[str, list[dict[str, str]]] = {
        player: [] for player in PLAYERS
    }
    initial_discard = game.top_card
    run_id = run_id or datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f")
    audit: dict[str, Any] = {
        "schema_version": 1,
        "game": "uno",
        "run_id": run_id,
        "trial_id": trial_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "model": model_name,
        "provider": provider,
        "system_prompt": SYSTEM_PROMPT,
        "max_turns": max_turns,
        "initial_state": {
            "deck": [str(card) for card in game.deck],
            "hands": {
                player: [str(card) for card in cards]
                for player, cards in game.hands.items()
            },
            "discard_pile": [str(card) for card in game.discard_pile],
        },
        "turns": [],
    }

    def current_state(turn: int, active_player: str | None) -> dict[str, Any]:
        return {
            "turn": turn,
            "active_player": active_player,
            "hands": {
                player: [str(card) for card in cards]
                for player, cards in game.hands.items()
            },
            "deck": [str(card) for card in game.deck],
            "discard_pile": [str(card) for card in game.discard_pile],
            "top_card": str(game.top_card),
        }

    def finish(
        turns_survived: int,
        failed: int,
        failure_reason: str,
        raw_response: str,
    ) -> dict[str, Any]:
        audit.update(
            completed_at=datetime.now().astimezone().isoformat(),
            turns_survived=turns_survived,
            failed=bool(failed),
            failure_reason=failure_reason,
            winner=next(
                (player for player, cards in game.hands.items() if not cards),
                None,
            ),
        )
        slimmed_replay = slim_uno_audit(audit)
        status, clean_reason = classify_uno_outcome(
            failed=bool(failed),
            failure_reason=failure_reason,
            raw_response=raw_response,
            culprit_model=model_name,
        )
        last_turn = slimmed_replay["turns"][-1] if slimmed_replay["turns"] else {}
        exact_prompt = SYSTEM_PROMPT
        if last_turn.get("user_prompt"):
            exact_prompt = f"System:\n{SYSTEM_PROMPT}\n\nUser (Turn {last_turn.get('turn')}):\n{last_turn.get('user_prompt')}"

        cloud_trial_id = (
            f"uno__{model_name}__{run_id}__Trial_{trial_id:03d}"
            .replace(" ", "_")
            .replace("/", "-")
        )
        log_trial_to_supabase(
            game="uno",
            white_model=model_name,
            black_model=model_name,
            status=status,
            plies_survived=turns_survived,
            failure_reason=clean_reason,
            board_print_requests=0,
            exact_prompt=exact_prompt,
            trial_id=cloud_trial_id,
            replay_data=slimmed_replay,
        )
        return {
            "trial_id": cloud_trial_id,
            "model": model_name,
            "turns_survived": turns_survived,
            "failed": failed,
            "status": status,
            "failure_reason": clean_reason,
            "raw_response": raw_response,
        }
    for turn in range(1, max_turns + 1):
        player = PLAYERS[player_index]
        if not game.hands[player]:
            return finish(turn - 1, 0, "Game Won Legally", "")

        pre_state = current_state(turn, player)
        hand = ", ".join(str(card) for card in game.hands[player])
        if conversations[player]:
            previous_action = audit["turns"][-1]["action"].strip()
            if previous_action.upper() == "DRAW":
                opponent_action = "Opponent drew a card."
            else:
                played_card = re.sub(r"^PLAY\s+", "", previous_action, flags=re.I)
                opponent_action = f"Opponent played: {played_card}."
            user_prompt = (
                f"{opponent_action} Your hand: [{hand}]. Choose a legal action."
            )
        else:
            opening = f"Initial discard: {initial_discard}."
            if audit["turns"]:
                previous_action = audit["turns"][-1]["action"].strip()
                if previous_action.upper() == "DRAW":
                    opponent_action = "Opponent drew a card."
                else:
                    played_card = re.sub(
                        r"^PLAY\s+", "", previous_action, flags=re.I
                    )
                    opponent_action = f"Opponent played: {played_card}."
                opening += f" {opponent_action}"
            else:
                opening = f"Game start. {opening}"
            user_prompt = f"{opening} Your hand: [{hand}]. Choose a legal action."
        response_details: dict[str, Any] = {
            "provider": provider,
            "model": model_name,
            "temperature": 0.2,
            "max_output_tokens": 40 if provider == "gemini" else 300,
        }
        response_attempts: list[dict[str, Any]] = []
        attempt_prompt = user_prompt
        valid = False
        reason = ""
        for attempt in range(MAX_FORMAT_RETRIES + 1):
            attempt_details: dict[str, Any] = {
                "provider": provider,
                "model": model_name,
                "temperature": 0.2,
                "max_output_tokens": 40 if provider == "gemini" else 300,
            }
            request_started = time.perf_counter()
            raw_response = query_model(
                SYSTEM_PROMPT,
                attempt_prompt,
                model_name,
                provider,
                client,
                attempt_details,
                conversations[player],
            )
            attempt_details["duration_seconds"] = time.perf_counter() - request_started
            response_attempts.append(
                {
                    "prompt": attempt_prompt,
                    "raw_response": raw_response,
                    "request_metadata": attempt_details,
                }
            )
            if raw_response.startswith("API_ERROR"):
                break
            valid, reason = game.validate_and_play(player, raw_response)
            if valid or not reason.startswith("Syntax Error:") or attempt == MAX_FORMAT_RETRIES:
                break
            attempt_prompt = (
                "Your previous response had invalid syntax. Reply with exactly "
                "'PLAY <Color> <Value>' using one card from your current hand, "
                "or exactly 'DRAW'. Do not output only 'PLAY' or add any other "
                f"text. Your hand: [{hand}]."
            )

        response_details = response_attempts[-1]["request_metadata"]
        event: dict[str, Any] = {
            "turn": turn,
            "player": player,
            "model": model_name,
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": user_prompt,
            "raw_response": raw_response,
            "request_metadata": response_details,
            "response_attempts": response_attempts,
            "pre_state": pre_state,
        }
        if raw_response.startswith("API_ERROR"):
            event.update(status="API_ERROR", valid=False, reason=raw_response)
            audit["turns"].append(event)
            event["post_state"] = current_state(turn, player)
            return finish(turn, 1, raw_response, raw_response)

        event.update(
            status="VALID" if valid else "INVALID",
            valid=valid,
            reason=reason,
            action=raw_response.strip(),
        )
        audit["turns"].append(event)
        event["post_state"] = current_state(turn, player)
        if not valid:
            return finish(turn, 1, reason, raw_response)
        if not game.hands[player]:
            return finish(turn, 0, "Game Won Legally", "")
        player_index = 1 - player_index

    return finish(max_turns, 0, "Max Turns Reached", "")


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
    if "<" in args.model or ">" in args.model:
        parser.error(
            "Replace the model placeholder with the provider's model ID and "
            "omit the angle brackets."
        )

    provider = infer_provider(args.model) if args.provider == "auto" else args.provider
    run_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    try:
        client = create_client(provider, args.api_key)
        print(f"Starting {args.trials} UNO trials | {args.model} ({provider})")
        for trial_num in range(1, args.trials + 1):
            result = run_trial(
                trial_num,
                args.model,
                provider,
                client,
                max_turns=args.max_turns,
                run_id=run_id,
            )
            print(
                f"[Cloud Logged] Trial {trial_num:02d}/{args.trials:02d} | "
                f"Status: {result['status']} | Turns: {result['turns_survived']} | "
                f"Note: {result['failure_reason']}"
            )
    except ValueError as error:
        parser.error(str(error))

if __name__ == "__main__":
    main()
