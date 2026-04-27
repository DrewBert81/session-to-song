# session-to-song

Turn OpenClaw, Hermes, or plain text sessions into:
- a short pulse
- a use-aware draft
- a music-generation prompt
- audio-ready artifacts for wakeups, reminders, celebrations, and next steps

This is a **repo**, not just a skill.

It is built around a simple product idea:
**work you can hear again.**

## Listen first

Sample celebration track from a real session-to-song run:

- [Play/download the MP3 directly](https://raw.githubusercontent.com/DrewBert81/session-to-song/master/content/examples/audio/session-to-song-commit.mp3)
- Repo file: [`session-to-song-commit.mp3`](content/examples/audio/session-to-song-commit.mp3)

GitHub's file viewer may not show an audio player for MP3 files. Use the direct raw link above, or right-click/save the repo file.

This is the concrete loop: ship work, turn the session into lyrics/music prompt/audio, then hear the milestone back as a short celebration.

## Why music memory?

OpenClaw can already preserve sessions, memories, and dreams as text. `session-to-song` adds a replay layer on top: it turns the important parts of that context into something you can hear later.

That matters because a song can carry more than a summary:

- **memory:** what happened and what mattered
- **mood:** how the work felt
- **momentum:** what to do next
- **ritual:** wake up, return from a break, or celebrate a ship

The goal is not to mush all context into a song. The goal is to choose a use — `alarm`, `reminder`, `celebrate`, or `next_steps` — and make a short artifact that helps the human re-enter the work with the right energy.

### Persisting songs back into OpenClaw memory

Generated text artifacts are always written to the selected output folder. If you also want OpenClaw to remember the song run, enable the memory export:

```bash
SESSION_TO_SONG_OPENCLAW_MEMORY=1
```

When enabled, each generated run appends a compact record to OpenClaw's daily memory file under `memory/YYYY-MM-DD.md`, including:

- pulse
- lyrics
- music prompt
- manifest summary
- local artifact paths

This stores the reusable context and pointers, not the audio bytes themselves. It keeps the song connected to OpenClaw's memory/dream trail without turning the memory file into a media dump.

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
- can play generated MP3s on the local computer for speaker/Bluetooth output
- can publish a stable `S2S-morning.mp3` alarm-slot file into a local Drive/sync folder for Android Clock-style alarms

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

### No-terminal Windows install

If you do not use Bash, PowerShell, or Python commands, use the double-click Windows setup:

1. Install Python 3 from <https://www.python.org/downloads/> and check **Add python.exe to PATH**.
2. Download this repo as a ZIP from GitHub and unzip it.
3. Open `scripts`.
4. Double-click **Install Session to Song.bat**.
5. Double-click **Start Session to Song.bat**.

See [`docs/no-terminal-install.md`](docs/no-terminal-install.md) for the full no-terminal guide.

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
- **Google/Gemini live audio path:** install `pip install -e .[google-audio]`, then set `GOOGLE_API_KEY` or `GEMINI_API_KEY`
- **Comfy live audio path:** set `COMFY_MUSIC_WORKFLOW_PATH` and `COMFY_MUSIC_PROMPT_NODE_ID` (plus `COMFY_API_KEY`/`COMFY_CLOUD_API_KEY` if using cloud mode)

Live audio requires `ffmpeg` on your PATH so the app can trim/export generated audio to MP3. `session-to-song doctor` checks for it.

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

## How it works with someone else's OpenClaw

On another machine, `session-to-song` reads that user's own local OpenClaw session registry under:

```text
~/.openclaw/agents/*/sessions/sessions.json
```

Those registry files point to that user's local session JSONL transcripts. If OpenClaw has recent sessions, `--source auto` and the web UI's one-click flow pick high-signal recent work. If the user adds a project filter, the resolver biases toward sessions and lines matching that project and filters out unrelated session noise.

Expected public behavior:
- **Curated OpenClaw context exists:** auto mode prefers local wiki, memory, and archived session digests because they are cleaner than raw transcripts.
- **Only raw OpenClaw sessions exist:** auto mode falls back to the user's own recent JSONL session transcripts and filters/scopes them.
- **No OpenClaw sessions yet:** text/file input still works, and `--source auto` fails clearly with `No recent session source found.`
- **Project filter set:** auto mode narrows to project-relevant memory/wiki/session material instead of generic recent chatter.
- **No API keys:** template text artifacts still work.
- **LLM/music keys present:** live text/audio providers can improve the artifacts and generate audio.

Source ladder for `--source auto`:
1. local OpenClaw curated context: `workspace/knowledge-base/wiki`, `workspace/knowledge-base/raw/sessions`, and `workspace/memory`
2. raw OpenClaw session registry/transcripts: `agents/*/sessions/sessions.json` + JSONL session files
3. explicit text/file input when auto-source is unavailable or the user wants exact control

## Localhost web UI

Run the web UI from the repo root:

```bash
python -m session_to_song.web_app
```

Then open `http://127.0.0.1:8311`.

The main supported UI path is:
1. generate text artifacts
2. optionally generate audio if Google/Gemini, MiniMax, or Comfy music is configured

Use the optional **Project filter** field to scope the selected artifact use to a
project, for example an alarm from only recent ExampleProject work.

## Playback and alarm delivery

### Preview/play on this computer

After generating audio in the web UI, use the built-in audio player or click **Play on this computer**.
On Windows this uses local playback so whatever Windows is currently routing audio to should be used. If a Bluetooth adapter/speaker such as BOT63 is connected and selected as the current output, the track should come out there.

CLI equivalent:

```bash
session-to-song play content/output/webui-latest/generated_audio.mp3 --volume 100
```

Useful variants:

```bash
session-to-song play content/output/webui-latest/generated_audio.mp3 --backend powershell --volume 100
session-to-song play content/output/webui-latest/generated_audio.mp3 --backend open --no-block
```

Backends are resolved in this order when `--backend auto` is used:
1. Windows PowerShell MediaPlayer
2. `ffplay`
3. VLC
4. default OS file opener

### Android / Google Clock alarm slot

The simplest phone-alarm MVP is a stable MP3 file that Android Clock points at once:

```text
My Drive/sessiontosong/alarms/S2S-morning.mp3
```

Recommended flow:
1. Create/select `sessiontosong/alarms/S2S-morning.mp3` in My Drive from Android Clock.
2. Generate the morning alarm in session-to-song.
3. Click **Update phone alarm** in the web UI, or run the CLI command below.
4. Google Drive sync updates the same file name, and Android Clock keeps using that slot.

CLI equivalent:

```bash
session-to-song alarm-slot morning --file content/output/webui-latest/generated_audio.mp3 --target-dir "G:\My Drive\sessiontosong\alarms"
```

You can avoid passing `--target-dir` every time by setting:

```bash
SESSION_TO_SONG_ALARM_SLOT_DIR="G:\My Drive\sessiontosong\alarms"
```

Then:

```bash
session-to-song alarm-slot morning --file content/output/webui-latest/generated_audio.mp3
```

This path does **not** require Google OAuth. It writes to a local Drive-for-Desktop/sync folder and lets Google Drive handle sync. If Android Clock caches the old file on a device, re-select the file once or force Drive/media sync; the intended contract is stable filename, changing contents.

### Wiring a nightly alarm

The repo now has the pieces needed for a scheduled generated alarm:

```text
scheduled trigger -> generate alarm audio -> publish S2S-morning.mp3 -> Android Clock plays the stable slot
```

Use the built-in morning command for the nightly Android alarm file:

```bash
session-to-song morning-alarm --target-dir "G:\My Drive\Sessiontosong Alarms"
```

On Windows, prefer the hardened wrapper because it sets the repo root, checks `ffmpeg`, and writes logs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\run_morning_alarm.ps1"
```

An external scheduler such as OpenClaw cron or Windows Task Scheduler can call that wrapper. For true audible local-speaker alarms, keep the computer awake and use `session-to-song play` at trigger time.

### Celebrate after a push

Git itself does not have a reliable built-in post-push hook. To celebrate only after a successful push, use the wrapper:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\push_and_celebrate.ps1" origin master
```

The wrapper runs `git push` with the arguments you pass it. If the push succeeds, it runs:

```bash
session-to-song celebrate-push --project "session-to-song" --play --no-block
```

This generates a short celebration track from recent git context and plays it locally. If the push fails, celebration is skipped.

## Outputs

Each run writes:
- `pulse.txt`
- `lyrics.txt`
- `music_prompt.txt`
- `run_manifest.json`
- optionally `generated_audio.mp3`

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
