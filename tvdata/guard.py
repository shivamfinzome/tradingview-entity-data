"""What stands between the web page and an open network: a login, a request budget, a short cache.

Kept free of the web framework so each piece can be tested on its own.
"""
from __future__ import annotations

import base64
import secrets
import threading
import time
from collections import deque


def credentials_ok(header: str | None, user: str, password: str) -> bool:
    """Does this Authorization header carry `user` and `password` (HTTP Basic)?"""
    scheme, _, encoded = (header or "").partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        given_user, colon, given_password = base64.b64decode(encoded.strip(), validate=True).decode("utf-8").partition(":")
    except ValueError:  # not base64, or not UTF-8
        return False
    # Compare both in constant time, and both every time, so a wrong name costs the same as a wrong password.
    user_ok = secrets.compare_digest(given_user.encode(), user.encode())
    password_ok = secrets.compare_digest(given_password.encode(), password.encode())
    return bool(colon) and user_ok and password_ok


class RateLimit:
    """At most `per_minute` calls in any 60 seconds, counted across every visitor.

    Every lookup leaves from the same server address, so this is the budget TradingView sees.
    """

    def __init__(self, per_minute: int, clock=time.monotonic):
        self.per_minute = per_minute
        self._clock = clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = self._clock()
        with self._lock:
            while self._calls and now - self._calls[0] >= 60:
                self._calls.popleft()
            if len(self._calls) >= self.per_minute:
                return False
            self._calls.append(now)
            return True


class Cache:
    """Answers kept for a short while, so the same lookup does not go back to TradingView."""

    def __init__(self, max_entries: int = 512, clock=time.monotonic):
        self.max_entries = max_entries
        self._clock = clock
        self._entries: dict = {}  # key -> (expires, value), oldest first
        self._lock = threading.Lock()

    def get(self, key) -> tuple[bool, object]:
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry[0] > self._clock():
                return True, entry[1]
            self._entries.pop(key, None)
            return False, None

    def put(self, key, value, ttl: float) -> None:
        now = self._clock()
        with self._lock:
            self._entries.pop(key, None)
            if len(self._entries) >= self.max_entries:
                for stale in [k for k, (expires, _) in self._entries.items() if expires <= now]:
                    del self._entries[stale]
            while len(self._entries) >= self.max_entries:
                del self._entries[next(iter(self._entries))]
            self._entries[key] = (now + ttl, value)
