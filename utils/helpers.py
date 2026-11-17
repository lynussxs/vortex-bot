"""Small utility functions shared by cogs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def decode_json_list(value: str | None) -> list[Any]:
    try:
        loaded = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return loaded if isinstance(loaded, list) else []


def encode_json_list(values: list[Any]) -> str:
    return json.dumps(values, ensure_ascii=False)


def utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def discord_timestamp(seconds: int, style: str = "R") -> str:
    return f"<t:{seconds}:{style}>"
