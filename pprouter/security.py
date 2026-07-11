import asyncio
import time
from collections import deque

from fastapi import Request


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._checks = 0

    async def check(self, key: str, limit: int, window_seconds: float = 60.0) -> int:
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            self._checks += 1
            if self._checks % 256 == 0:
                self._prune_expired(cutoff)

            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(1, int(window_seconds - (now - events[0])) + 1)
            events.append(now)
            return 0

    def _prune_expired(self, cutoff: float) -> None:
        expired = [
            key for key, events in self._events.items() if not events or events[-1] <= cutoff
        ]
        for key in expired:
            self._events.pop(key, None)


class ConcurrencyGate:
    def __init__(self, limit: int) -> None:
        self._semaphore = asyncio.Semaphore(limit)

    async def acquire(self, timeout: float = 0.1) -> bool:
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def release(self) -> None:
        self._semaphore.release()


def client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded[:64]
    if request.client:
        return request.client.host[:64]
    return "unknown"
