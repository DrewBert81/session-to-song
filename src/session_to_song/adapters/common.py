from __future__ import annotations

from typing import Iterable

from ..domain import SessionMaterial
from ..project_filter import filter_lines_for_project


def classify_lines(lines: Iterable[str]) -> tuple[list[str], list[str], list[str]]:
    wins: list[str] = []
    blockers: list[str] = []
    next_actions: list[str] = []
    for line in lines:
        lower = line.lower()
        if any(word in lower for word in ("blocked", "stuck", "waiting", "risk", "issue")):
            blockers.append(line)
        elif any(word in lower for word in ("next", "tomorrow", "follow up", "ship next", "need to")):
            next_actions.append(line)
        else:
            wins.append(line)
    return wins, blockers, next_actions


def material_from_text(*, source: str, title: str, raw_text: str, project: str | None = None) -> SessionMaterial:
    original_lines = [line.strip(" -\t") for line in raw_text.splitlines() if line.strip(" -\t")]
    project_lines = filter_lines_for_project(original_lines, project)
    lines = project_lines or original_lines
    if project and project_lines:
        raw_text = "\n".join(lines)
    wins, blockers, next_actions = classify_lines(lines)
    return SessionMaterial(
        source=source,
        title=title,
        raw_text=raw_text,
        project=project,
        wins=wins,
        blockers=blockers,
        next_actions=next_actions,
        metadata={
            "line_count": len(lines),
            "original_line_count": len(original_lines),
            "project_filter_matched": bool(project_lines),
        },
    )
