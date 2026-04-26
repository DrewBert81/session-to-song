from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    dotenv_path = Path(path) if path else Path.cwd() / ".env"
    if not dotenv_path.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ or not os.environ.get(key, "").strip():
            os.environ[key] = value
        loaded[key] = value
    return loaded
