import asyncio
import base64
import hmac
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request


@dataclass(frozen=True, slots=True)
class SessionClaims:
    subject: str
    issued_at: int
    expires_at: int


class SessionManager:
    def __init__(self, access_key: str, session_secret: str, ttl_seconds: int) -> None:
        self._access_key = access_key.encode()
        self._secret = session_secret.encode()
        self._ttl_seconds = ttl_seconds

    def verify_access_key(self, candidate: str) -> bool:
        return hmac.compare_digest(self._access_key, candidate.encode())

    def issue(self, subject: str = "owner") -> tuple[str, int]:
        now = int(time.time())
        expires_at = now + self._ttl_seconds
        payload = {
            "sub": subject,
            "iat": now,
            "exp": expires_at,
        }
        encoded = _b64url(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        signature = _b64url(hmac.digest(self._secret, encoded.encode(), "sha256"))
        return f"{encoded}.{signature}", expires_at

    def verify(self, token: str) -> SessionClaims | None:
        try:
            encoded, signature = token.split(".", 1)
            expected = _b64url(hmac.digest(self._secret, encoded.encode(), "sha256"))
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(_b64url_decode(encoded))
            subject = payload["sub"]
            issued_at = payload["iat"]
            expires_at = payload["exp"]
            if not isinstance(subject, str):
                return None
            if not isinstance(issued_at, int) or not isinstance(expires_at, int):
                return None
            if expires_at <= int(time.time()) or issued_at > int(time.time()) + 60:
                return None
            return SessionClaims(subject, issued_at, expires_at)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int, window_seconds: float = 60.0) -> int:
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(1, int(window_seconds - (now - events[0])) + 1)
            events.append(now)
            if not events:
                self._events.pop(key, None)
            return 0


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


async def require_session(
    request: Request,
    authorization: str | None = Header(default=None),
) -> SessionClaims:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()
    claims = request.app.state.sessions.verify(authorization[7:].strip())
    if claims is None:
        raise _unauthorized()
    return claims


def client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded[:64]
    if request.client:
        return request.client.host[:64]
    return "unknown"


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
