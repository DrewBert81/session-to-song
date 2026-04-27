from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

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


def export_artifacts_to_openclaw_memory(
    artifacts: SongArtifacts,
    files: dict[str, Path],
    *,
    enabled: bool | None = None,
    workspace: str | Path | None = None,
) -> Path | None:
    """Append a generated song run to OpenClaw's daily memory file.

    This intentionally stores text artifacts and file pointers, not generated audio bytes.
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
    return target
