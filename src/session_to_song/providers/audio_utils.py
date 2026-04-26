from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .music_common import MusicGenerationError


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def trim_audio_to_mp3(input_path: Path, output_path: Path, duration_seconds: int) -> Path:
    ffmpeg = "ffmpeg"
    if not ffmpeg_available():
        raise MusicGenerationError("ffmpeg is required to trim generated audio.")
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                "-t",
                str(duration_seconds),
                "-codec:a",
                "libmp3lame",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - host-specific
        raise MusicGenerationError("ffmpeg is required to trim generated audio.") from exc

    if completed.returncode != 0:
        raise MusicGenerationError(completed.stderr.strip() or "ffmpeg failed while trimming audio.")
    return output_path
