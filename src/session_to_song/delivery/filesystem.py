from __future__ import annotations

from pathlib import Path


def deliver_to_filesystem(outdir: str | Path) -> str:
    return f"Artifacts saved to {Path(outdir)}"
