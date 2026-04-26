# session-to-song

Turn OpenClaw, Hermes, or plain text sessions into:
- a short pulse
- a use-aware draft
- a music-generation prompt
- audio-ready artifacts for wakeups, reminders, celebrations, and next steps

This is a **repo**, not just a skill.

It is built around a simple product idea:
**work you can hear again.**

## What it does now

- supports input adapters for:
  - `text`
  - `openclaw`
  - `hermes`
- supports **Use** selection:
  - `alarm`
  - `reminder`
  - `celebrate`
  - `next_steps`
- supports **Genre** selection:
  - `rap`
  - `country`
  - `heavy_metal`
  - `pop`
  - `rock`
  - `alternative`
  - `folk`
- resolves providers from explicit config **or** your local env automatically
- keeps **BYOK** first-class
- includes a `doctor` command for public-repo setup checks
- writes a manifest for every run
- can generate browser-playable audio from the localhost web UI when Google/Gemini, MiniMax, or Comfy music is configured

## Supported production path

This repo is production-ready for a focused baseline, not every detected provider.

- **Text artifacts:** always supported, even with no API keys
- **Live LLM artifact synthesis:** supported via `openrouter`, `openai`, and `google` / `gemini`
- **Live audio generation:** supported via `google` / `gemini`, `minimax`, and `comfy`
- **Still detected but not runnable yet:** LLM `anthropic`, `ollama`

If you point config at an unsupported live provider, `doctor` now fails clearly instead of making it look runnable.

See also: `docs/setup.md` for the fastest supported clone-to-working paths.

## Architecture

```text
config/
content/
  input/
  output/
  examples/
scripts/
src/session_to_song/
  adapters/
  config_loader.py
  delivery/
  domain.py
  pipeline/
  providers/
  storage/
  styles/
  cli.py
tests/
```

## Config model

Set provider defaults once, then let **genre stay sticky** until you change it.

Project is optional. When you pass `--project` or fill the web UI project field,
it filters automatic session sourcing to material for that project while keeping
the selected use the same (`alarm`, `reminder`, `celebrate`, or `next_steps`).
For example, `Use=alarm + Project=ExampleProject` creates an alarm artifact from recent
ExampleProject work, not a separate build-mode artifact.

Genre resolution order is:
1. one-off genre override
2. project genre
3. use genre
4. global default genre

Current default config lives at:
- `config/defaults.json`

Local user overrides are written to:
- `config/user.json`

That file is intentionally ignored for public-safe BYOK/local setup.

It includes:
- default LLM provider/model (or `auto` env fallback)
- default music provider/model (or `auto` env fallback)
- global default genre
- per-use genre defaults
- optional per-project genre overrides
- default use
- default delivery mode
- default target duration in seconds
- quiet hours

## Install

### Editable local install

```bash
pip install -e .
```

Then use either:

```bash
session-to-song --help
```

or:

```bash
python -m session_to_song.cli --help
```

## Quick start

### 1) Initialize local config

```bash
session-to-song init
```

This writes `config/user.json` locally. That file is gitignored on purpose.

Optional: pin providers/models during init instead of using auto detection.

```bash
session-to-song init --llm-provider openrouter --llm-model anthropic/claude-3.7-sonnet --music-provider minimax --music-model minimax/music-2.5+ --genre rap --duration 45
```

### 2) Add your keys (optional, BYOK)

```bash
cp .env.example .env
```

Then fill in only the providers you actually want to use.

Recommended paths:

- **Zero-key / offline:** leave `.env` empty and use template mode
- **Best supported live text path:** set `OPENROUTER_API_KEY` or `OPENAI_API_KEY`
- **Simple live audio path:** set `MINIMAX_API_KEY`
- **Google/Gemini live audio path:** set `GOOGLE_API_KEY` or `GEMINI_API_KEY`
- **Comfy live audio path:** set `COMFY_MUSIC_WORKFLOW_PATH` and `COMFY_MUSIC_PROMPT_NODE_ID` (plus `COMFY_API_KEY`/`COMFY_CLOUD_API_KEY` if using cloud mode)

Live audio requires `ffmpeg` on your PATH so the app can trim/export generated audio to MP3.

### 3) Verify setup

```bash
session-to-song doctor
```

`doctor` shows:
- which env vars are present
- which LLM/music providers are available
- the resolved provider/model that will be used
- whether each live path is actually runtime-ready in this repo
- clean next steps when you are missing something

### 4) Inspect config

```bash
session-to-song config show
```

### 5) Set sticky genres

```bash
session-to-song genre set default rap
session-to-song genre set use reminder rock
session-to-song genre set use next_steps heavy_metal
session-to-song genre set project ClientPortal pop
```

### 6) Run a sample test

```bash
session-to-song test --use celebrate --genre rap --duration 30 --focus "what shipped and why it matters"
```

Project-scoped automatic source example:

```bash
session-to-song test --source auto --use alarm --project ExampleProject --focus "what matters today"
```

### 7) Generate from an input file

```bash
session-to-song generate content/input/sample_day.txt --outdir content/output/demo --use celebrate --genre rap --duration 45 --focus "what shipped and why it matters"
```

OpenClaw/Hermes-flavored run:

```bash
session-to-song generate content/input/sample_day.txt --outdir content/output/demo-reminder --use reminder --genre rock --duration 60 --input-source openclaw --focus "where the project stands and where it is going"
```

Project-scoped OpenClaw session run:

```bash
session-to-song generate --source auto --use alarm --project ExampleProject --outdir content/output/exampleproject-alarm
```

## Localhost web UI

Run the web UI from the repo root:

```bash
python -m session_to_song.web_app
```

Then open `http://127.0.0.1:8311`.

The main supported UI path is:
1. generate text artifacts
2. optionally generate audio if Google/Gemini music is configured

Use the optional **Project filter** field to scope the selected artifact use to a
project, for example an alarm from only recent ExampleProject work.

## Outputs

Each run writes:
- `pulse.txt`
- `lyrics.txt`
- `music_prompt.txt`
- `run_manifest.json`

## Product direction

This repo is meant to grow into:
- **Alarm** tracks: wake-up / pump-up
- **Reminder** tracks: where the project is at and where it is going
- **Celebrate** tracks: what you just built
- **Next steps** tracks: what happens next and why to move now

Core rule:
- **Use decides content**
- **Genre decides sound**

## Environment / BYOK

The core artifact pipeline works without any API key.

Duration is first-class in config and CLI. Typical artifact targets are 30, 45, or 60 seconds; use longer values only when you actually want a longer piece.

### Provider resolution

Provider selection is now portable for public GitHub users:

1. if `config/user.json` pins a provider/model, that wins
2. otherwise `auto` falls back to the first matching env-backed provider
3. if no LLM key is present, the repo still works in built-in template mode
4. if no music key is present, text artifacts still work and `doctor` explains what is missing

The web UI lists model presets by intent instead of treating one model name as timeless:
- **quality/latest**: best effort for current high-quality models, when your API account supports them
- **fast/cheap**: conservative starter defaults for public demos and low-cost runs
- **detected**: live models discovered from provider model-list APIs when credentials are present

Discovery currently tries OpenAI, Google/Gemini, and OpenRouter with a short timeout and falls back to curated presets if a provider is offline, rate-limited, or does not expose the expected model list. If a provider releases a newer model, you can either select it when detected or pin it with `session-to-song init --llm-provider ... --llm-model ...` without changing code.

Current detection support:
- LLMs: `openrouter`, `openai`, `anthropic`, `google`/`gemini`, `ollama`
- Music: `minimax`, `google`/`gemini`, `comfy`

Current live execution support in this repo:
- LLMs: `openrouter`, `openai`, `google`/`gemini`
- Music: `google`/`gemini`, `minimax`, `comfy`

Comfy requires a real workflow JSON plus node ids before `doctor`, CLI audio, or the web UI will mark it runnable.

Use `.env.example` as the documented starter file, keep `.env` local, and keep `config/user.json` local too.

## Testing

From the repo root:

```bash
python -m unittest discover -s tests -v
```

or after editable install:

```bash
pytest -q
```

## Notes

- standard-library only right now
- no external API required for the core repo flow
- provider execution is intentionally separate from artifact generation
- local outputs and personal config are gitignored for safe publishing
- developer smoke scripts in `scripts/` are not the primary user path
