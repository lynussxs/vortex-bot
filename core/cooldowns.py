"""Small in-memory cooldown and rate-limit helpers."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque


class Cooldowns:
    def __init__(self) -> None:
        self._expires: dict[tuple[int, int], float] = {}

    def remaining(self, guild_id: int, user_id: int) -> float:
        return max(0.0, self._expires.get((guild_id, user_id), 0.0) - time.monotonic())

    def start(self, guild_id: int, user_id: int, seconds: int) -> None:
        self._expires[(guild_id, user_id)] = time.monotonic() + seconds


class EventWindow:
    def __init__(self) -> None:
        self._events: dict[tuple[int, int], Deque[float]] = defaultdict(deque)

    def add(self, guild_id: int, user_id: int, window: int) -> int:
        now = time.monotonic()
        events = self._events[(guild_id, user_id)]
        while events and now - events[0] > window:
            events.popleft()
        events.append(now)
        return len(events)
