from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ProviderStatus:
    llm_provider: str
    llm_model: str
    music_provider: str
    music_model: str
    llm_configured: bool
    music_configured: bool


def _has_any_env(*names: str) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


def detect_provider_status(
    *,
    llm_provider: str,
    llm_model: str,
    music_provider: str,
    music_model: str,
) -> ProviderStatus:
    llm_configured = _has_any_env(
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    )
    music_configured = _has_any_env(
        "MINIMAX_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "COMFY_API_KEY",
        "COMFY_CLOUD_API_KEY",
    )
    return ProviderStatus(
        llm_provider=llm_provider,
        llm_model=llm_model,
        music_provider=music_provider,
        music_model=music_model,
        llm_configured=llm_configured,
        music_configured=music_configured,
    )
