from __future__ import annotations

import json
from pathlib import Path

from ..domain import SongArtifacts


def write_artifacts(outdir: str | Path, artifacts: SongArtifacts) -> dict[str, Path]:
    out_path = Path(outdir)
    out_path.mkdir(parents=True, exist_ok=True)
    files = {
        "pulse": out_path / "pulse.txt",
        "lyrics": out_path / "lyrics.txt",
        "music_prompt": out_path / "music_prompt.txt",
        "manifest": out_path / "run_manifest.json",
    }
    files["pulse"].write_text(artifacts.pulse + "\n", encoding="utf-8")
    files["lyrics"].write_text(artifacts.lyrics + "\n", encoding="utf-8")
    files["music_prompt"].write_text(artifacts.music_prompt + "\n", encoding="utf-8")
    files["manifest"].write_text(json.dumps(artifacts.manifest, indent=2) + "\n", encoding="utf-8")
    return files
