import asyncio

from pprouter.security import SlidingWindowRateLimiter


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


def test_rate_limiter_prunes_expired_buckets() -> None:
    limiter = SlidingWindowRateLimiter()

    async def exercise() -> int:
        for index in range(255):
            await limiter.check(f"client:{index}", 1, window_seconds=0.001)
        await asyncio.sleep(0.01)
        await limiter.check("current", 1, window_seconds=0.001)
        return len(limiter._events)

    assert asyncio.run(exercise()) == 1
