from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict

from ..errors import AppError


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        events = self._events[key]
        while events and events[0] <= now - window_seconds:
            events.popleft()
        if len(events) >= limit:
            raise AppError(429, "RATE_LIMITED", "操作过于频繁，请稍后再试")
        events.append(now)


rate_limiter = SlidingWindowLimiter()
