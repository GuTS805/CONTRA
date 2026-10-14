"""Load local settings from a .env file without third-party packages."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: str | Path | None = None) -> list[str]:
    """Set variables from KEY=VALUE lines that are not already in the environment.

    Returns the names that were set. Values are never printed or logged.
    """
    target = Path(path or os.environ.get("CONTRA_ENV_FILE") or DEFAULT_ENV_FILE)
    if not target.is_file():
        return []
    loaded = []
    for raw in target.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key.isidentifier() and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
