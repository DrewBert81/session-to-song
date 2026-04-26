from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

RunMode = Literal["alarm", "recap", "milestone", "memory"]


@dataclass
class RunConfig:
    mode: RunMode = "alarm"
    llm_provider: str = "byok"
    llm_model: str = "openrouter:auto"
    music_provider: str = "byok"
    music_model: str = "minimax/music-2.5+"
    input_source: str = "text"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
