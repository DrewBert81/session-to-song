# X Manifesto Slideshow

Create a cinematic moving-picture slideshow from a voiceover MP3 for posting to X.

This is the recommended format for the Session-to-Song launch/demo clip: the voiceover carries the idea, while the visuals move slowly through bold manifesto phrases.

## Generate

```powershell
python scripts/make_manifesto_slideshow.py `
  --audio "path\to\voiceover.mp3" `
  --outdir content/output/x-post-manifesto `
  --footer "github.com/DrewBert81/session-to-song"
```

Output:

```text
content/output/x-post-manifesto/session-to-song-work-you-can-hear-again.mp4
```

## Requirements

- `ffmpeg` and `ffprobe` on PATH
- Python package: `Pillow`

```bash
python -m pip install -e .[slideshow]
```

## Default slide arc

1. Work stops disappearing
2. Effort you can hear again
3. Not notes / not logs
4. The blur of the day becomes signal
5. Replay the mission
6. Look at what you built
7. Momentum with a voice
8. For builders who ship real things
9. Keep building / keep shipping
10. Session to Song — work you can hear again

## X post copy

```text
Built a small experiment: turn AI work sessions into something replayable.

Not just logs. Not just notes.
A pulse. A memory. A wake-up call.

Session to Song: work you can hear again.

Repo: https://github.com/DrewBert81/session-to-song
```
