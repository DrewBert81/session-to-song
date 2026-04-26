from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

ArtifactUse = Literal["alarm", "reminder", "celebrate", "next_steps"]
Genre = Literal["rap", "country", "heavy_metal", "pop", "rock", "alternative", "folk"]
DeliveryMode = Literal["save", "immediate", "scheduled", "milestone"]
SourceMode = Literal["auto", "current_session", "recent_session", "manual"]
LegacyRunMode = Literal["alarm", "recap", "milestone", "memory", "build"]

LEGACY_MODE_TO_USE: dict[str, ArtifactUse] = {
    "alarm": "alarm",
    "memory": "reminder",
    "recap": "reminder",
    "milestone": "celebrate",
    "build": "celebrate",
}

LEGACY_STYLE_TO_GENRE: dict[str, Genre] = {
    "boom_bap_alarm": "rap",
    "metalcore_wake": "heavy_metal",
    "ambient_memory": "alternative",
    "victory_anthem": "rock",
    "build_reflection": "alternative",
}


@dataclass
class SessionMaterial:
    source: str
    title: str
    raw_text: str
    project: str | None = None
    wins: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class UserConfig:
    llm_provider: str = "auto"
    llm_model: str = ""
    music_provider: str = "auto"
    music_model: str = ""
    default_genre: Genre = "rap"
    genre_by_use: dict[str, str] = field(default_factory=dict)
    genre_by_project: dict[str, str] = field(default_factory=dict)
    delivery: DeliveryMode = "save"
    duration_seconds: int = 45
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "06:30"

    @property
    def default_style(self) -> str:
        return self.default_genre

    @property
    def mode_styles(self) -> dict[str, str]:
        return self.genre_by_use

    @property
    def project_styles(self) -> dict[str, str]:
        return self.genre_by_project


@dataclass
class RunRequest:
    use: ArtifactUse | None = None
    genre: Genre | None = None
    focus: str | None = None
    sound_reference: str | None = None
    delivery: DeliveryMode | None = None
    duration_seconds: int | None = None
    input_source: str = "text"
    source_mode: SourceMode = "manual"
    source_session_key: str | None = None
    lookback_hours: int | None = None
    project: str | None = None
    mode: LegacyRunMode | str | None = None
    style: str | None = None
    question: str | None = None

    def __post_init__(self) -> None:
        if self.mode and not self.use:
            self.use = LEGACY_MODE_TO_USE.get(self.mode, "alarm")
        elif self.mode:
            self.use = self.use or LEGACY_MODE_TO_USE.get(self.mode, "alarm")
        if self.style and not self.genre:
            self.genre = LEGACY_STYLE_TO_GENRE.get(self.style)
        if self.question and not self.focus:
            self.focus = self.question

    @property
    def resolved_use(self) -> ArtifactUse:
        return self.use or LEGACY_MODE_TO_USE.get(self.mode or "alarm", "alarm")

    @property
    def resolved_focus(self) -> str | None:
        return self.focus or self.question

    @property
    def resolved_genre(self) -> Genre | None:
        return self.genre or (LEGACY_STYLE_TO_GENRE.get(self.style) if self.style else None)


@dataclass
class GenrePreset:
    key: str
    label: str
    music_prompt_seed: str
    intro_seed: str
    hook_seed: str


StylePreset = GenrePreset


@dataclass
class SongArtifacts:
    pulse: str
    lyrics: str
    music_prompt: str
    manifest: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
