import asyncio

from arbbot.risk.rate_limiter import RateLimiter


def test_rate_limiter_acquire_and_refill() -> None:
    async def _run() -> None:
        limiter = RateLimiter()
        limiter.register("paradex", "order", rate_per_sec=1.0, capacity=1.0)

        first = await limiter.acquire("paradex", "order", timeout=0.1)
        second_try = await limiter.try_acquire("paradex", "order")

        assert first is True
        assert second_try is False

        await asyncio.sleep(1.05)
        third = await limiter.acquire("paradex", "order", timeout=0.1)
        assert third is True

    asyncio.run(_run())
