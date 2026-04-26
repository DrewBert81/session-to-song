from __future__ import annotations

from pathlib import Path

from ..domain import UserConfig
from .comfy_music import generate_comfy_music
from .google_music import generate_google_music
from .minimax_music import generate_minimax_music
from .music_common import GeneratedAudio, MusicGenerationError
from .status import detect_provider_status


SUPPORTED_MUSIC_RUNTIME_PROVIDERS = {"google", "minimax", "comfy"}


def music_generation_available(user_config: UserConfig) -> bool:
    status = detect_provider_status(
        llm_provider=user_config.llm_provider,
        llm_model=user_config.llm_model,
        music_provider=user_config.music_provider,
        music_model=user_config.music_model,
    )
    return status.music.available and status.music.runtime_supported and status.music.provider in SUPPORTED_MUSIC_RUNTIME_PROVIDERS


def generate_music_audio(
    *,
    prompt: str,
    out_dir: Path,
    duration_seconds: int,
    user_config: UserConfig,
    preferred_model: str | None = None,
    preferred_provider: str | None = None,
) -> GeneratedAudio:
    status = detect_provider_status(
        llm_provider=user_config.llm_provider,
        llm_model=user_config.llm_model,
        music_provider=preferred_provider or user_config.music_provider,
        music_model=preferred_model or user_config.music_model,
    )
    resolved = status.music

    if not resolved.available:
        raise MusicGenerationError(resolved.message or "Music generation is not configured.")
    if not resolved.runtime_supported:
        raise MusicGenerationError(
            resolved.message
            or f"Configured music provider '{resolved.provider}' is detected but not runnable in this repo yet."
        )

    model = (preferred_model or resolved.model or "").strip() or None
    if resolved.provider == "google":
        return generate_google_music(
            prompt=prompt,
            out_dir=out_dir,
            duration_seconds=duration_seconds,
            preferred_model=model,
        )
    if resolved.provider == "minimax":
        return generate_minimax_music(
            prompt=prompt,
            out_dir=out_dir,
            duration_seconds=duration_seconds,
            preferred_model=model,
        )
    if resolved.provider == "comfy":
        return generate_comfy_music(
            prompt=prompt,
            out_dir=out_dir,
            duration_seconds=duration_seconds,
            preferred_model=model,
        )

    raise MusicGenerationError(
        f"Configured music provider '{resolved.provider}' is not supported for live generation in this repo."
    )
