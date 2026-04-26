from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..env_loader import load_dotenv
from .comfy_music import DEFAULT_COMFY_MODEL, describe_comfy_music_runtime


PSEUDO_PROVIDERS = {"", "auto", "byok", "default"}


@dataclass(frozen=True)
class ProviderSpec:
    kind: str
    name: str
    default_model: str
    env_vars: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    runtime_supported: bool = True

    def matches(self, provider_name: str) -> bool:
        normalized = provider_name.strip().lower()
        return normalized == self.name or normalized in self.aliases

    def is_available(self, environ: dict[str, str]) -> bool:
        return any(bool(environ.get(name, "").strip()) for name in self.env_vars)


@dataclass
class ProviderAvailability:
    name: str
    default_model: str
    env_vars: tuple[str, ...]
    available: bool
    runtime_supported: bool


@dataclass
class ProviderSelection:
    configured_provider: str
    configured_model: str
    provider: str
    model: str
    source: str
    available: bool
    runtime_supported: bool
    env_vars: tuple[str, ...] = ()
    message: str = ""


@dataclass
class ProviderStatus:
    llm_provider: str
    llm_model: str
    music_provider: str
    music_model: str
    llm_configured: bool
    music_configured: bool
    llm: ProviderSelection
    music: ProviderSelection
    env: dict[str, bool] = field(default_factory=dict)
    llm_options: list[ProviderAvailability] = field(default_factory=list)
    music_options: list[ProviderAvailability] = field(default_factory=list)


LLM_SPECS = (
    ProviderSpec("llm", "openrouter", "anthropic/claude-3.7-sonnet", ("OPENROUTER_API_KEY",)),
    ProviderSpec("llm", "openai", "gpt-4o-mini", ("OPENAI_API_KEY",)),
    ProviderSpec("llm", "anthropic", "claude-3-5-sonnet-latest", ("ANTHROPIC_API_KEY",), runtime_supported=False),
    ProviderSpec("llm", "google", "gemini-2.5-flash", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), aliases=("gemini",), runtime_supported=True),
    ProviderSpec("llm", "ollama", "llama3.2", ("OLLAMA_HOST",), runtime_supported=False),
)

MUSIC_SPECS = (
    ProviderSpec("music", "minimax", "minimax/music-2.5+", ("MINIMAX_API_KEY",)),
    ProviderSpec("music", "google", "lyria-3-pro-preview", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), aliases=("gemini",)),
    ProviderSpec("music", "comfy", DEFAULT_COMFY_MODEL, ("COMFY_API_KEY", "COMFY_CLOUD_API_KEY"), aliases=("comfy_cloud",)),
)


def _environment_snapshot(environ: dict[str, str]) -> dict[str, bool]:
    tracked = {
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "OLLAMA_HOST",
        "MINIMAX_API_KEY",
        "COMFY_API_KEY",
        "COMFY_BASE_URL",
        "COMFY_CLOUD_API_KEY",
        "COMFY_MODE",
        "COMFY_MUSIC_OUTPUT_NODE_ID",
        "COMFY_MUSIC_PROMPT_NODE_ID",
        "COMFY_MUSIC_WORKFLOW_PATH",
    }
    return {name: bool(environ.get(name, "").strip()) for name in sorted(tracked)}


def _find_spec(specs: tuple[ProviderSpec, ...], provider_name: str) -> ProviderSpec | None:
    normalized = provider_name.strip().lower()
    for spec in specs:
        if spec.matches(normalized):
            return spec
    return None


def _music_provider_state(spec: ProviderSpec, environ: dict[str, str]) -> tuple[bool, bool, str]:
    if spec.name == "minimax":
        available = spec.is_available(environ)
        return available, True, "" if available else _missing_env_message("music", spec)
    if spec.name == "comfy":
        comfy = describe_comfy_music_runtime(environ)
        return comfy.available, comfy.runtime_supported, comfy.message
    available = spec.is_available(environ)
    return available, spec.runtime_supported, "" if available else _missing_env_message("music", spec)


def _availability(specs: tuple[ProviderSpec, ...], environ: dict[str, str]) -> list[ProviderAvailability]:
    rows: list[ProviderAvailability] = []
    for spec in specs:
        if spec.kind == "music":
            available, runtime_supported, _ = _music_provider_state(spec, environ)
        else:
            available, runtime_supported = spec.is_available(environ), spec.runtime_supported
        rows.append(
            ProviderAvailability(
                name=spec.name,
                default_model=spec.default_model,
                env_vars=spec.env_vars,
                available=available,
                runtime_supported=runtime_supported,
            )
        )
    return rows


def _missing_env_message(kind: str, spec: ProviderSpec) -> str:
    env_names = " or ".join(spec.env_vars)
    return f"Configured {kind} provider '{spec.name}' is missing credentials. Set {env_names}."


def _resolve_selection(kind: str, configured_provider: str, configured_model: str, specs: tuple[ProviderSpec, ...], environ: dict[str, str]) -> ProviderSelection:
    configured_provider = (configured_provider or "auto").strip()
    configured_model = (configured_model or "").strip()
    normalized = configured_provider.lower()

    if normalized not in PSEUDO_PROVIDERS:
        spec = _find_spec(specs, normalized)
        if spec is None:
            return ProviderSelection(
                configured_provider=configured_provider,
                configured_model=configured_model,
                provider=configured_provider,
                model=configured_model,
                source="explicit",
                available=False,
                runtime_supported=False,
                message=f"Unknown {kind} provider '{configured_provider}'.",
            )
        model = configured_model or spec.default_model
        if kind == "music":
            available, runtime_supported, message = _music_provider_state(spec, environ)
        else:
            available, runtime_supported = spec.is_available(environ), spec.runtime_supported
            message = ""
            if not available:
                message = _missing_env_message(kind, spec)
            elif not runtime_supported:
                message = f"{spec.name} credentials are present, but live LLM synthesis is not implemented yet. Template mode will be used."
        return ProviderSelection(
            configured_provider=configured_provider,
            configured_model=configured_model,
            provider=spec.name,
            model=model,
            source="explicit",
            available=available,
            runtime_supported=runtime_supported,
            env_vars=spec.env_vars,
            message=message,
        )

    for spec in specs:
        if kind == "music":
            available, runtime_supported, message = _music_provider_state(spec, environ)
        else:
            available, runtime_supported = spec.is_available(environ), spec.runtime_supported
            message = "" if runtime_supported else f"Auto-selected {spec.name}, but live LLM synthesis is not implemented yet. Template mode will be used."
        if not available:
            continue
        return ProviderSelection(
            configured_provider=configured_provider or "auto",
            configured_model=configured_model,
            provider=spec.name,
            model=configured_model or spec.default_model,
            source="env",
            available=True,
            runtime_supported=runtime_supported,
            env_vars=spec.env_vars,
            message=message,
        )

    if kind == "llm":
        return ProviderSelection(
            configured_provider=configured_provider or "auto",
            configured_model=configured_model,
            provider="template",
            model="builtin-template",
            source="template",
            available=False,
            runtime_supported=False,
            message="No LLM credentials found. Template generation will be used until you set a provider key.",
        )

    comfy_status = describe_comfy_music_runtime(environ)
    extra = f" {comfy_status.message}" if comfy_status.message else ""
    return ProviderSelection(
        configured_provider=configured_provider or "auto",
        configured_model=configured_model,
        provider="unconfigured",
        model="",
        source="none",
        available=False,
        runtime_supported=False,
        message="No music credentials found. Text artifacts still work, but provider-backed audio is unavailable." + extra,
    )


def detect_provider_status(*, llm_provider: str, llm_model: str, music_provider: str, music_model: str, environ: dict[str, str] | None = None) -> ProviderStatus:
    if environ is None:
        load_dotenv()
    env = dict(os.environ if environ is None else environ)
    llm = _resolve_selection("llm", llm_provider, llm_model, LLM_SPECS, env)
    music = _resolve_selection("music", music_provider, music_model, MUSIC_SPECS, env)
    env_snapshot = _environment_snapshot(env)
    return ProviderStatus(
        llm_provider=llm.provider,
        llm_model=llm.model,
        music_provider=music.provider,
        music_model=music.model,
        llm_configured=llm.available,
        music_configured=music.available,
        llm=llm,
        music=music,
        env=env_snapshot,
        llm_options=_availability(LLM_SPECS, env),
        music_options=_availability(MUSIC_SPECS, env),
    )
