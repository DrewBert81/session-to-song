from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if os.getenv("SESSION_TO_SONG_ALLOW_DEV_SCRIPTS", "").strip().lower() not in {"1", "true", "yes"}:
    raise SystemExit(
        "run_demo.py is a developer smoke script, not the supported public setup path. "
        "Use `session-to-song test` or set SESSION_TO_SONG_ALLOW_DEV_SCRIPTS=1 if you really want this script."
    )

CMD = [
    sys.executable,
    "-m",
    "session_to_song.cli",
    "generate",
    "content/input/sample_day.txt",
    "--outdir",
    "content/output/demo",
    "--mode",
    "alarm",
    "--style",
    "boom_bap_alarm",
    "--input-source",
    "text",
]

raise SystemExit(subprocess.call(CMD, cwd=ROOT))
