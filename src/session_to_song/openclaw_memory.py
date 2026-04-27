from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .domain import SongArtifacts


def openclaw_memory_enabled() -> bool:
    value = (os.getenv("SESSION_TO_SONG_OPENCLAW_MEMORY") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _workspace_root() -> Path:
    explicit = os.getenv("SESSION_TO_SONG_OPENCLAW_WORKSPACE") or os.getenv("OPENCLAW_WORKSPACE")
    if explicit:
        return Path(explicit).expanduser()
    return Path(os.getenv("OPENCLAW_HOME", str(Path.home() / ".openclaw"))).expanduser() / "workspace"


def _safe_excerpt(text: str, limit: int = 1800) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _coerce_audio_info(audio: object | None) -> dict[str, Any] | None:
    if audio is None:
        return None
    if isinstance(audio, dict):
        return {key: value for key, value in audio.items() if value not in (None, "")}
    info: dict[str, Any] = {}
    for attr in ("path", "provider", "model", "mime_type", "prompt_notes"):
        value = getattr(audio, attr, None)
        if value not in (None, ""):
            info[attr] = str(value) if isinstance(value, Path) else value
    return info or None


def _coerce_mapping(value: object | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if item not in (None, "")}
    if hasattr(value, "to_dict"):
        return _coerce_mapping(value.to_dict())
    return None


def _append_audio_block(target: Path, *, audio: object | None = None, alarm_slot: object | None = None) -> None:
    audio_info = _coerce_audio_info(audio)
    alarm_info = _coerce_mapping(alarm_slot)
    if not audio_info and not alarm_info:
        return

    block = ["", "### Audio output"]
    if audio_info:
        path = audio_info.get("path")
        provider = audio_info.get("provider")
        model = audio_info.get("model")
        mime_type = audio_info.get("mime_type")
        if path:
            block.append(f"- audio: `{path}`")
        if provider:
            block.append(f"- provider: {provider}")
        if model:
            block.append(f"- model: {model}")
        if mime_type:
            block.append(f"- mime_type: {mime_type}")
        if audio_info.get("prompt_notes"):
            block.extend(["", "#### Provider notes", _safe_excerpt(str(audio_info["prompt_notes"]), limit=1000)])
    if alarm_info:
        block.append("")
        block.append("#### Alarm slot")
        for key in ("slot", "filename", "target_path", "bytes_written"):
            if key in alarm_info:
                value = alarm_info[key]
                if key.endswith("path"):
                    block.append(f"- {key}: `{value}`")
                else:
                    block.append(f"- {key}: {value}")
    block.append("")
    with target.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(block))


def append_audio_to_openclaw_memory(memory_path: str | Path | None, *, audio: object | None = None, alarm_slot: object | None = None) -> Path | None:
    if not memory_path:
        return None
    target = Path(memory_path).expanduser()
    if not target.exists() or not target.is_file():
        return None
    _append_audio_block(target, audio=audio, alarm_slot=alarm_slot)
    return target


def export_artifacts_to_openclaw_memory(
    artifacts: SongArtifacts,
    files: dict[str, Path],
    *,
    enabled: bool | None = None,
    workspace: str | Path | None = None,
    audio: object | None = None,
    alarm_slot: object | None = None,
) -> Path | None:
    """Append a generated song run to OpenClaw's daily memory file.

    The memory entry stores text artifacts plus local pointers to generated files.
    Audio bytes are not embedded, but generated audio/alarm-slot paths can be included.
    It is opt-in via SESSION_TO_SONG_OPENCLAW_MEMORY=1 unless `enabled` is passed.
    """
    if enabled is None:
        enabled = openclaw_memory_enabled()
    if not enabled:
        return None

    root = Path(workspace).expanduser() if workspace else _workspace_root()
    memory_dir = root / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    target = memory_dir / f"{today}.md"

    manifest = artifacts.manifest or {}
    title = manifest.get("project") or manifest.get("use") or "session-to-song"
    created_at = datetime.now().isoformat(timespec="seconds")
    block = [
        "",
        f"## Session-to-song artifact — {title}",
        f"- Time: {created_at}",
        f"- Use: {manifest.get('use', 'unknown')}",
        f"- Genre: {manifest.get('genre', 'unknown')}",
        f"- Focus: {manifest.get('focus') or '(none)'}",
        "- Files:",
    ]
    for key in ("pulse", "lyrics", "music_prompt", "manifest"):
        if key in files:
            block.append(f"  - {key}: `{files[key]}`")
    block.extend([
        "",
        "### Pulse",
        _safe_excerpt(artifacts.pulse),
        "",
        "### Lyrics",
        _safe_excerpt(artifacts.lyrics, limit=2400),
        "",
        "### Music prompt",
        _safe_excerpt(artifacts.music_prompt, limit=1800),
        "",
        "### Manifest summary",
        "```json",
        json.dumps({
            "use": manifest.get("use"),
            "genre": manifest.get("genre"),
            "focus": manifest.get("focus"),
            "duration_seconds": manifest.get("duration_seconds"),
            "project": manifest.get("project"),
        }, indent=2),
        "```",
        "",
    ])
    with target.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(block))
    _append_audio_block(target, audio=audio, alarm_slot=alarm_slot)
    return target
