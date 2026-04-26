from __future__ import annotations

from pathlib import Path

from .common import material_from_text
from ..domain import SessionMaterial


def load_hermes_material(path: str | Path, *, project: str | None = None) -> SessionMaterial:
    input_path = Path(path)
    title = f"Hermes session: {input_path.stem}"
    return material_from_text(
        source="hermes",
        title=title,
        raw_text=input_path.read_text(encoding="utf-8"),
        project=project,
    )
