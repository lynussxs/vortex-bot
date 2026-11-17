"""Input validation helpers."""

from __future__ import annotations

import re

DURATION_RE = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)
HTTP_URL_RE = re.compile(r"^https?://[^\s<>]{1,1900}$", re.IGNORECASE)


def parse_duration(value: str, *, maximum_seconds: int = 28 * 24 * 60 * 60) -> int:
    match = DURATION_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("Use a duration such as 30s, 15m, 2h, 3d, or 1w.")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    if amount <= 0 or seconds > maximum_seconds:
        raise ValueError("The duration must be greater than zero and no longer than 28 days.")
    return seconds


def valid_http_url(value: str | None) -> bool:
    return value is None or bool(HTTP_URL_RE.fullmatch(value.strip()))


def clean_text(value: str, maximum: int, *, allow_empty: bool = False) -> str:
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise ValueError("This value cannot be empty.")
    if len(cleaned) > maximum:
        raise ValueError(f"This value must be {maximum} characters or fewer.")
    return cleaned
