from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain import LEGACY_MODE_TO_USE, LEGACY_STYLE_TO_GENRE, RunRequest, UserConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "defaults.json"
USER_CONFIG_PATH = CONFIG_DIR / "user.json"


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _normalize_config_shape(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    defaults = normalized.setdefault("defaults", {})
    preferences = normalized.setdefault("preferences", {})
    legacy_styles = normalized.get("styles", {})

    if "genre" not in defaults:
        defaults["genre"] = LEGACY_STYLE_TO_GENRE.get(defaults.get("style", ""), "rap")

    genre_by_use = preferences.setdefault("genre_by_use", {})
    if not genre_by_use and legacy_styles.get("by_mode"):
        for legacy_mode, legacy_style in legacy_styles["by_mode"].items():
            genre_by_use[LEGACY_MODE_TO_USE.get(legacy_mode, legacy_mode)] = LEGACY_STYLE_TO_GENRE.get(legacy_style, defaults["genre"])

    genre_by_project = preferences.setdefault("genre_by_project", {})
    if not genre_by_project and legacy_styles.get("by_project"):
        for project, legacy_style in legacy_styles["by_project"].items():
            genre_by_project[project] = LEGACY_STYLE_TO_GENRE.get(legacy_style, defaults["genre"])

    return normalized


def load_config_data(config_path: str | Path | None = None) -> dict[str, Any]:
    base_data = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    effective_path = Path(config_path) if config_path else USER_CONFIG_PATH
    if effective_path.exists():
        override_data = json.loads(effective_path.read_text(encoding="utf-8"))
        base_data = _merge(base_data, override_data)
    return _normalize_config_shape(base_data)


def save_user_config_data(data: dict[str, Any], config_path: str | Path | None = None) -> Path:
    target = Path(config_path) if config_path else USER_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_normalize_config_shape(data), indent=2) + "\n", encoding="utf-8")
    return target


def load_user_config(config_path: str | Path | None = None) -> UserConfig:
    base_data = load_config_data(config_path)
    return UserConfig(
        llm_provider=base_data["providers"]["llm"]["provider"],
        llm_model=base_data["providers"]["llm"]["model"],
        music_provider=base_data["providers"]["music"]["provider"],
        music_model=base_data["providers"]["music"]["model"],
        default_genre=base_data["defaults"]["genre"],
        genre_by_use=base_data.get("preferences", {}).get("genre_by_use", {}),
        genre_by_project=base_data.get("preferences", {}).get("genre_by_project", {}),
        delivery=base_data["defaults"]["delivery"],
        duration_seconds=base_data["defaults"].get("duration_seconds", 45),
        quiet_hours_start=base_data["defaults"]["quiet_hours"]["start"],
        quiet_hours_end=base_data["defaults"]["quiet_hours"]["end"],
    )


def resolve_genre(user_config: UserConfig, request: RunRequest) -> str:
    if request.resolved_genre:
        return request.resolved_genre
    if request.project and request.project in user_config.genre_by_project:
        return user_config.genre_by_project[request.project]
    if request.resolved_use in user_config.genre_by_use:
        return user_config.genre_by_use[request.resolved_use]
    return user_config.default_genre


def resolve_style(user_config: UserConfig, request: RunRequest) -> str:
    return resolve_genre(user_config, request)


def resolve_run_request(user_config: UserConfig, request: RunRequest) -> RunRequest:
    return RunRequest(
        use=request.resolved_use,
        genre=resolve_genre(user_config, request),
        focus=request.resolved_focus,
        delivery=request.delivery or user_config.delivery,
        duration_seconds=request.duration_seconds or user_config.duration_seconds,
        input_source=request.input_source,
        source_mode=request.source_mode,
        source_session_key=request.source_session_key,
        lookback_hours=request.lookback_hours,
        project=request.project,
        mode=request.mode,
        style=request.style,
        question=request.question,
    )
