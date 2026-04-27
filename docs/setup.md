# session-to-song setup

## Fastest working paths

### 1) Text-only, no keys

```bash
pip install -e .
session-to-song init
session-to-song doctor
session-to-song test --use celebrate --focus "what shipped and why it matters"
```

That path is fully supported. The repo will stay in built-in template mode.

### 2) Live LLM artifacts

Set one of:

- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`

Then rerun:

```bash
session-to-song doctor
```

### 3) Live audio in the web UI / CLI

Pick one supported path:

- **Google / Gemini**: set `GOOGLE_API_KEY` or `GEMINI_API_KEY`
- **MiniMax**: set `MINIMAX_API_KEY`
- **ComfyUI local**: set `COMFY_MUSIC_WORKFLOW_PATH` and `COMFY_MUSIC_PROMPT_NODE_ID` (plus optional `COMFY_MUSIC_OUTPUT_NODE_ID`, `COMFY_BASE_URL`)
- **Comfy Cloud**: same workflow vars plus `COMFY_MODE=cloud` and `COMFY_API_KEY` or `COMFY_CLOUD_API_KEY`

Live audio also requires `ffmpeg` on your PATH because generated audio is trimmed/exported to MP3.

Then run:

```bash
python -m session_to_song.web_app
```

Or from CLI:

```bash
session-to-song doctor
session-to-song test --use celebrate --focus "what shipped and why it matters"
```

## Provider support matrix

| Area | Detected by doctor | Runnable in this repo |
|---|---|---|
| LLM: openrouter | yes | yes |
| LLM: openai | yes | yes |
| LLM: anthropic | yes | not yet |
| LLM: google/gemini | yes | yes |
| LLM: ollama | yes | not yet |
| Music: google/gemini | yes | yes |
| Music: minimax | yes | yes |
| Music: comfy | yes, with workflow config | yes, with workflow config |

`doctor` now checks whether Comfy has enough workflow config to run instead of treating it as a fake-positive key-only provider.

## Input adapters

The tested input paths are:

```bash
session-to-song generate content/examples/example_1_input.txt --input-source text --use celebrate
session-to-song generate content/examples/hermes_session_sample.txt --input-source hermes --use celebrate --project ExampleProject
session-to-song generate --source auto --input-source openclaw --use reminder
```

`text` and `hermes` read a local file. `openclaw` resolves recent OpenClaw session/memory context when available.

## Fresh-clone rule of thumb

- If you want the repo working immediately: ignore audio, stay text-only first.
- If you want the least setup for live audio: use `MINIMAX_API_KEY`.
- If you want the most configurable self-hosted path: use Comfy with a workflow JSON + prompt node id.
- If you want the most complete live path overall: pair `OPENROUTER_API_KEY` or `OPENAI_API_KEY` with Google/Gemini, MiniMax, or Comfy.
