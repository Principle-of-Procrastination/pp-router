import asyncio

from pprouter.security import SessionManager, SlidingWindowRateLimiter


def test_session_round_trip() -> None:
    manager = SessionManager("a" * 24, "b" * 32, 300)

    token, expires_at = manager.issue()
    claims = manager.verify(token)

    assert claims is not None
    assert claims.subject == "owner"
    assert claims.expires_at == expires_at


def test_session_rejects_tampering() -> None:
    manager = SessionManager("a" * 24, "b" * 32, 300)
    token, _ = manager.issue()

    assert manager.verify(token + "x") is None


def test_rate_limiter_returns_retry_after_limit() -> None:
    limiter = SlidingWindowRateLimiter()

    async def exercise() -> tuple[int, int, int]:
        return (
            await limiter.check("chat", 2),
            await limiter.check("chat", 2),
            await limiter.check("chat", 2),
        )

    first, second, blocked = asyncio.run(exercise())
    assert first == 0
    assert second == 0
    assert blocked >= 1
