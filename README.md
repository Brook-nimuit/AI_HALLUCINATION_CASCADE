# The Hallucination Cascade

Research tools and a static project site for studying state tracking in
language-model game play.

## Project layout

- `web/` contains the public static site. `web/index.html` is the project
  homepage; `web/chess-replay/` contains the optional local replay viewer.
- `experiments/chess/` and `experiments/uno/` contain the trial runners.
- `data/local/` is reserved for generated CSV results, chess audits, and board
  images. It is intentionally excluded from Git; do not put credentials here.
- `local/` is for personal documents and editor state and is also excluded from
  Git.

The website is static and does not include a backend. The chess replay viewer
reads files selected by the visitor; it does not upload those files.

## Run the website locally

Install the site build dependency and compile the local Tailwind stylesheet:

```powershell
npm install
npm run build
```

Then open `web/index.html` in a browser or use any static file server. To deploy
to Vercel, use the repository root as the project root. `vercel.json` builds the
site and configures `web/` as the static output directory.

The replay viewer is available at `/chess-replay/`. Its file picker expects the
local `data/local/` folder created by the trial runner.

## Set up the Python experiments

Requires Python 3.10 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set provider credentials in environment variables, or supply them with the
corresponding CLI option. Environment variables are recommended to avoid
saving secrets in shell history.

```powershell
$env:OPENAI_API_KEY = "your-key"
python experiments\chess\run_chess_trials.py --white-model gpt-4o --trials 7
```

The chess runner supports OpenAI-compatible OpenAI and Groq models. UNO also
supports Ollama and Gemini. Run either script with `--help` for all options.
Results and replay files are written under `data/local/` and are not tracked by
Git.

Run the offline test suite with:

```powershell
python -m unittest discover -s tests -v
```

## Public release notes

- Do not commit `.env`, API keys, local trial data, or personal documents.
- No open-source license has been selected yet. Until a license is added, the
  repository should not be treated as licensed for reuse.
