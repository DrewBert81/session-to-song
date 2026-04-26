from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .music_common import MusicGenerationError


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def trim_audio_to_mp3(input_path: Path, output_path: Path, duration_seconds: int) -> Path:
    ffmpeg = "ffmpeg"
    if not ffmpeg_available():
        raise MusicGenerationError("ffmpeg is required to trim generated audio.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_name(f"{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}")
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
                str(temp_output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - host-specific
        raise MusicGenerationError("ffmpeg is required to trim generated audio.") from exc

    if completed.returncode != 0:
        temp_output.unlink(missing_ok=True)
        raise MusicGenerationError(completed.stderr.strip() or "ffmpeg failed while trimming audio.")

    last_error: Exception | None = None
    for _ in range(5):
        try:
            temp_output.replace(output_path)
            return output_path
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.25)

    unlocked_output = output_path.with_name(f"{output_path.stem}-{int(time.time())}{output_path.suffix}")
    try:
        temp_output.replace(unlocked_output)
    except Exception as exc:
        temp_output.unlink(missing_ok=True)
        raise MusicGenerationError(f"Could not write trimmed audio: {exc}") from exc
    return unlocked_output
