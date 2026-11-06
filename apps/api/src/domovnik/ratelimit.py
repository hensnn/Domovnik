"""Jednoduchý in-memory limiter (stačí pro jednu instanci v domácí síti)."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from domovnik.errors import DomainError


class TooManyRequests(DomainError):
    status = 429
    code = "too_many_requests"


class FailureLimiter:
    """Blokuje klíč po `limit` neúspěších v okně `window` sekund."""

    def __init__(self, limit: int = 8, window: float = 300.0) -> None:
        self.limit, self.window = limit, window
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, key: str) -> deque[float]:
        q = self._events[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def check(self, key: str) -> None:
        if len(self._trim(key)) >= self.limit:
            raise TooManyRequests("Příliš mnoho neúspěšných pokusů. Zkus to později.")

    def fail(self, key: str) -> None:
        self._trim(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._events.pop(key, None)


login_limiter = FailureLimiter()
