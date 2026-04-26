from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class GeneratedAudio:
    provider: str
    model: str
    mime_type: str
    path: Path
    prompt_notes: str | None = None


class MusicGenerationError(RuntimeError):
    pass
