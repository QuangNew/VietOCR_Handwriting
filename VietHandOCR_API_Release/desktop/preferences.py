"""Shared desktop preferences; each feature preserves the other saved choices."""

import json
from pathlib import Path


def read_preferences(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def update_preferences(path: Path, **changes) -> None:
    preferences = read_preferences(path)
    preferences.update(changes)
    path.write_text(json.dumps(preferences, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
