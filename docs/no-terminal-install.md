# No-terminal install

This path is for people who do not use Bash, PowerShell, or Python commands day to day.

## Windows: double-click setup

1. Install **Python 3** from <https://www.python.org/downloads/>.
2. During install, check **Add python.exe to PATH**.
3. Download this repo from GitHub:
   - click **Code**
   - click **Download ZIP**
   - unzip it somewhere easy, like Desktop or Documents
4. Open the unzipped folder.
5. Open the `scripts` folder.
6. Double-click **Install Session to Song.bat**.
7. When it finishes, double-click **Start Session to Song.bat**.
8. The app opens at <http://127.0.0.1:8311>.

Keep the black terminal window open while using the app. Closing it stops the local web app.

## Check setup

Double-click:

```text
scripts/Check Session to Song.bat
```

That runs the same setup check as:

```bash
session-to-song doctor
```

## What works without API keys?

Without API keys, Session to Song can still create text artifacts:

- pulse
- lyrics
- music prompt
- manifest

Live MP3 audio requires a supported music provider key and `ffmpeg`.

## Live audio requirements

For generated MP3 audio, install `ffmpeg` and configure one of:

- Google/Gemini: `GOOGLE_API_KEY` or `GEMINI_API_KEY`
- MiniMax: `MINIMAX_API_KEY`
- Comfy: local/cloud workflow config

If this sounds too technical, start without audio keys first. Generate lyrics and music prompts, then add audio later.

## macOS / Linux

A no-terminal app bundle is not packaged yet. For now, use the regular README install commands on macOS/Linux.
