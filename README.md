# The Hallucination Cascade

Research tools and a static project site for studying state tracking in
language-model game play.

## Project layout

- `web/` contains the public static site. `web/index.html` is the project
  homepage; `web/chess-replay/` and `web/tic-tac-toe-replay/` contain optional
  local replay viewers.
- `experiments/chess/`, `experiments/checkers/`, `experiments/connect-four/`,
  `experiments/uno/`, and `experiments/tic-tac-toe/` contain the trial runners.
- `data/local/` is reserved for generated CSV results, chess audits, and board
  images, structured results, and state snapshots. It is intentionally excluded
  from Git; do not put credentials here.
- `local/` is for personal documents and editor state and is also excluded from
  Git.

The deployed website remains static and does not include a backend. For live
local research data, use the localhost website service described below. Replay
viewers read files selected by the visitor; they do not upload those files.

## Local research dashboard

Install the Python dependencies, then run the Streamlit dashboard from the
repository root:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

The **All Games** dashboard reads `data/local/results/*.json`, counts trials
once gameplay has begun, and retains trials with invalid or illegal moves.
Attempts that fail before a model makes a move are omitted. Chess and Checkers
have interactive replay pages; other games are presented as result tables.
Audited replay-only Chess/Checkers matches are included when they are not
already represented by a run result. Legacy image folders without audits are
reported separately and are not included in research totals.

The website's **All Games** section reads current local research data through a
local HTTP service. Start it from the repository root:

```powershell
python local_website.py
```

Open `http://127.0.0.1:8765/`. The dashboard fetches the saved run JSON and
audited replay-only trials every 15 seconds, so completed trials appear without
rebuilding the website or exporting a snapshot. The service only binds to
localhost and does not upload data. A static deployment cannot provide live
local data; public live hosting will require a separately configured backend.

## Run the website locally

Install the site build dependency and compile the local Tailwind stylesheet:

```powershell
npm install
npm run build
```

The build produces static assets. Use `python local_website.py` for the
live-data website; opening `web/index.html` directly or using a generic static
file server will not provide the local trial API. Vercel can still host the
static site, but live research data there requires a separately configured
public backend. Vercel Web Analytics is included in the static page; enable it
for the project in the Vercel dashboard to collect analytics.

The replay viewer is available at `/chess-replay/`. Its file picker expects the
local `data/local/` folder created by the trial runner. Each new chess match
stores a valid PGN beside its replay frames and embeds that PGN and any illegal
move metadata in its audit. The viewer replays legal plies on a Chess.com-green
board; illegal attempts remain audit annotations, with an arrow and blunder
marker when their source and destination squares can be inferred. The output of
`prepare_visualization_data.py` can also be selected; it includes every saved
chess replay even though its statistical summaries exclude invalid trials.

The Tic-Tac-Toe replay viewer is available at `/tic-tac-toe-replay/`. Select a
run folder inside `data/local/snapshots/tic-tac-toe/` to load its saved match
audits. It replays every recorded attempted move, shows invalid attempts and
their failure reasons, and provides a print-friendly match report.

## Set up the Python experiments

Requires Python 3.10 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run game experiments

Set the key for the provider that issued it in the current PowerShell session.
Use the provider's exact model ID; an API key does not select a model. These
variables are not saved after the shell closes:

```powershell
$env:OPENAI_API_KEY = "your-key"
$env:GROQ_API_KEY = "your-key"
$env:GEMINI_API_KEY = "your-key"

```


Prefer environment variables over key command-line options, which may be saved
in shell history. Never commit keys or paste them into source files. The runners
do not automatically load `.env` files.

| Game | Providers | Environment variable | CLI key option |
| --- | --- | --- | --- |
| Chess | OpenAI, Groq | `OPENAI_API_KEY`, `GROQ_API_KEY` | `--openai-api-key`, `--groq-api-key` |
| Checkers | OpenAI, Groq | `OPENAI_API_KEY`, `GROQ_API_KEY` | `--openai-api-key`, `--groq-api-key` |
| UNO | OpenAI, Groq, Gemini; local Ollama needs no key | `OPENAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` | `--api-key` |
| Tic-Tac-Toe | OpenAI, Groq | `OPENAI_API_KEY`, `GROQ_API_KEY` | `--openai-api-key`, `--groq-api-key` |
| Connect Four | OpenAI, Groq | `OPENAI_API_KEY`, `GROQ_API_KEY` | `--openai-api-key`, `--groq-api-key` |

Chess and Tic-Tac-Toe and Connect Four infer the provider from the model ID: `gpt-oss` IDs are
sent to Groq, IDs beginning with `gpt-` or containing `astra` are otherwise
sent to OpenAI, and other API model IDs are sent to Groq. `astra` is only a
routing heuristic, not a model ID—use the exact model ID listed by the
provider. UNO supports `--provider` to select explicitly.

Each seat keeps its own conversation for the duration of a match. After the
opening setup, prompts provide only the latest opponent move: SAN in Chess,
PDN in Checkers, and the opponent's mark and square in Tic-Tac-Toe. UNO sends
the opponent's played card or draw and the acting player's current hand. The
model's own previous replies remain in that seat's conversation as game
context; board diagrams and full move histories are not repeatedly sent.

### Connect Four

The Connect Four runner enforces gravity, full-column rejection, and horizontal,
vertical, and diagonal four-in-a-row wins on a 7-column by 6-row board. Models
play Red (`R`) and Yellow (`Y`) by choosing a column letter from A-G. Each seat
gets its own conversation; after the opening prompt, a turn only identifies the
opponent's latest mark and column. The runner saves a match audit and numbered
board snapshots under `data/local/snapshots/connect-four/<run-id>/`.

```powershell
$env:OPENAI_API_KEY = "your-openai-key"
python experiments\connect-four\run_connect_four_trials.py --red-model gpt-4o --yellow-model random --trials 2
``
Use `--yellow-model self` for same-model play (the default), or supply another
model ID. Run `random` against `random` without API keys to check the runner and
generate a sample audit.

### Chess

`--white-model` is required. Black defaults to `self` (same model); use
`random` for a legal random baseline or pass another provider's model ID. Set
keys for every API-backed provider used in the match.

```powershell
$env:OPENAI_API_KEY = "your-openai-key"
python experiments\chess\run_chess_trials.py --white-model gpt-4o --black-model random --trials 7
```

Groq example: replace the placeholder—including the angle brackets—with the
exact model ID listed in your Groq account. Do not copy `<groq-model-id>`
literally; it is not an actual model:

```powershell
$env:GROQ_API_KEY = "your-groq-key"
python experiments\chess\run_chess_trials.py --white-model "<groq-model-id>" --black-model random --trials 7
```

Claude model IDs are routed to Anthropic automatically. Set
`ANTHROPIC_API_KEY`, or pass `--anthropic-api-key`; the runner allows up to
8,192 response tokens per move.

```powershell
$env:ANTHROPIC_API_KEY = "your-anthropic-key"
python experiments\chess\run_chess_trials.py --white-model claude-opus-5-5 --black-model random --trials 2
```

### UNO

Pass a model ID and optionally choose its provider explicitly. `--provider auto`
is the default; explicit provider selection avoids relying on model-name
inference. Ollama runs locally and requires no API key.

```powershell
$env:OPENAI_API_KEY = "your-openai-key"
python experiments\uno\run_simulations.py --model gpt-4o --provider openai --trials 15
```

Other supported providers:

```powershell
$env:GROQ_API_KEY = "your-groq-key"
python experiments\uno\run_simulations.py --model "openai/gpt-oss-120b" --provider groq --trials 15

$env:GEMINI_API_KEY = "your-gemini-key"
python experiments\uno\run_simulations.py --model gemini-3.8-flash --provider gemini --trials 15

python experiments\uno\run_simulations.py --model "<ollama-model-name>" --provider ollama --trials 15
```

For placeholder examples, replace the text in angle brackets with your actual
model ID and omit the brackets. The `--provider` option selects the provider
(`gemini`); `--model` receives the model ID. See Google's
[Gemini model list](https://ai.google.dev/gemini-api/docs/models) for available
IDs.

UNO keeps its current simplified rules and logging. When a trial fails, its
`failure_reason` is saved in the run results and match audit; each attempted
turn also records its own validation reason. Prompts report the latest
opponent card action and the acting player's current hand. A malformed action
gets up to two same-turn format retries; each response attempt is retained in
the match audit.

### International Draughts (Checkers)

The checkers runner implements 10x10 International Draughts: 50 playable
squares, 20 pieces per side, backward captures by men, flying kings, mandatory
captures, and the maximum-capture rule. It writes each match as a PDN file.
Each model receives the latest opponent move in PDN, with earlier turns kept
in its conversation. Astra and Groq
GPT-OSS use adaptive reasoning defaults: medium for Astra and low for GPT-OSS.
Override either with `--reasoning-effort low|medium|high`. Their completion
budget grows from 1,024 to 4,096 tokens only if a response is truncated. The
first run defaults to two trials against a random legal baseline.

```powershell
$env:OPENAI_API_KEY = "your-openai-key"
python experiments\checkers\run_checkers_trials.py --white-model gpt-6-astra --black-model random --trials 2
```

Each match saves `match.pdn`, `match_audit.json`, and numbered state snapshots
under `data/local/snapshots/checkers/<run-id>/`. PDN uses International
Draughts move notation, such as `31-26` for a quiet move and `31x22x13` for a
multi-capture. Invalid responses are recorded as PDN comments and in the audit.
See the [FMJD rules](https://www.fmjd.org/docs/Annex_1.pdf) for the official
International Draughts rules.

The runner supports OpenAI, Groq, Gemini, Anthropic Claude, and local Ollama.
Claude model IDs are auto-detected and receive an 8,192-token response budget.
Provider IDs are auto-detected when recognizable; use `--white-provider` and
`--black-provider` to select explicitly when needed. For self-play, Black uses
White's provider unless `--black-provider` is set.

```powershell
# Groq model (including provider-specific model IDs)
$env:GROQ_API_KEY = "your-groq-key"
python experiments\checkers\run_checkers_trials.py --white-model "<groq-model-id>" --white-provider groq

# Gemini
$env:GEMINI_API_KEY = "your-gemini-key"
python experiments\checkers\run_checkers_trials.py --white-model gemini-2.5-flash

# Local Ollama model (Ollama must be running)
python experiments\checkers\run_checkers_trials.py --white-model "<ollama-model-name>" --white-provider ollama
```

```powershell
# Claude
$env:ANTHROPIC_API_KEY = "your-anthropic-key"
python experiments\checkers\run_checkers_trials.py --white-model claude-sonnet-4-5 --black-model random
```

The static [Checkers replay viewer](web/checkers-replay/index.html) loads
`match_audit.json` files from a selected local run folder. It replays legal and
illegal attempts from recorded board states, displays the PDN record, and does
not upload audit data.

### Tic-Tac-Toe

`--x-model` is required. O defaults to `self`; use `random` for a random
baseline. The model receives the opponent's mark and square number, while its
own previous moves stay in its conversation. The runner uses a four-token
output cap for standard chat models. Groq GPT-OSS models use low reasoning effort and
hidden reasoning output. If a response is truncated, the runner retries with
completion budgets of 512, 1,024, then 2,048 tokens; only the move response is
stored in the audit.

```powershell
$env:OPENAI_API_KEY = "your-openai-key"
python experiments\tic-tac-toe\run_tttoe_trials.py --x-model gpt-4o --o-model random --trials 5
```

Groq example: replace the placeholder—including the angle brackets—with the
exact model ID listed in your Groq account. Do not copy `<groq-model-id>`
literally; it is not an actual model:

```powershell
$env:GROQ_API_KEY = "your-groq-key"
python experiments\tic-tac-toe\run_tttoe_trials.py --x-model "<groq-model-id>" --o-model random --trials 5
```

As an alternative to environment variables, pass the matching key option:

```powershell
python experiments\chess\run_chess_trials.py --white-model gpt-4o --openai-api-key "your-openai-key"
python experiments\uno\run_simulations.py --model gpt-4o --provider openai --api-key "your-openai-key"
python experiments\tic-tac-toe\run_tttoe_trials.py --x-model gpt-4o --openai-api-key "your-openai-key"
```

### Experiment output and tests

The runners write summary CSVs and incrementally updated JSON run results
under `data/local/results/`. Per-game state snapshots and full match audits
(including prompts, raw responses, moves/actions, and before/after state) are
stored under `data/local/snapshots/<game>/<run-id>/`. Chess writes PGN files
and PNG replay frames, Checkers writes PDN files, and Tic-Tac-Toe writes PNG
board frames alongside their snapshots. These artifacts are local and not
tracked by Git.

To remove trials that failed before any model gameplay and regenerate the
visualization-ready exports, run:

```powershell
python experiments\prepare_visualization_data.py --prune-unplayed --replace-output
```

The cleanup removes no-play API/model-name failure trials and their associated
CSV rows and audited artifact folders. It preserves any trial with model
gameplay, including illegal moves and partial games that later encounter an API
error. Future per-run CSVs omit no-play failures; a partial game is retained
with `trial_status=partial_api_error` and without the raw API error text.
Exports are written under `data/local/visualization-ready/`.

Run the offline test suite with:

```powershell
python -m unittest discover -s tests -v
```

## Public release notes

- Do not commit `.env`, API keys, local trial data, or personal documents.
- No open-source license has been selected yet. Until a license is added, the
  repository should not be treated as licensed for reuse.
