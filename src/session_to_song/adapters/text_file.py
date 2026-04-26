from __future__ import annotations

from pathlib import Path

from .common import material_from_text
from ..domain import SessionMaterial


def load_text_file_material(path: str | Path, *, project: str | None = None) -> SessionMaterial:
    input_path = Path(path)
    return material_from_text(
        source="text",
        title=input_path.stem,
        raw_text=input_path.read_text(encoding="utf-8"),
        project=project,
    )
