"""IP-based sliding window rate limiter.

Default: 3 requests per IP per 24-hour window, stored in-memory (resets on server restart).
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Tuple

# Tune these to change limits
_MAX_REQUESTS = 3
_WINDOW_SECONDS = 86400  # 24 hours


class RateLimiter:
    def __init__(self, max_requests: int = _MAX_REQUESTS, window_seconds: int = _WINDOW_SECONDS) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._log: dict[str, list[float]] = defaultdict(list)

    def check(self, ip: str) -> Tuple[bool, int]:
        """Return (allowed, retry_after_seconds). retry_after is 0 when allowed."""
        now = time.time()
        cutoff = now - self._window
        self._log[ip] = [t for t in self._log[ip] if t > cutoff]
        if len(self._log[ip]) >= self._max:
            retry_after = int(self._log[ip][0] + self._window - now)
            return False, max(0, retry_after)
        return True, 0

    def record(self, ip: str) -> None:
        self._log[ip].append(time.time())
