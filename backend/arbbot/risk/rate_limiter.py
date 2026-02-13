"""异步令牌桶限流器。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(slots=True)
class BucketStats:
    """限流桶状态。"""

    rate_per_sec: float
    capacity: float
    tokens: float


class TokenBucket:
    """单桶令牌限流。"""

    def __init__(self, rate_per_sec: float, capacity: float) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec 必须大于 0")
        if capacity <= 0:
            raise ValueError("capacity 必须大于 0")
        self.rate_per_sec = float(rate_per_sec)
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._last_refill_at = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill_unlocked(self) -> None:
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_refill_at)
        if elapsed <= 0:
            return
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate_per_sec)
        self._last_refill_at = now

    async def acquire(self, tokens: float = 1.0, timeout: float | None = None) -> bool:
        """获取令牌，超时返回 False。"""
        if tokens <= 0:
            return True
        if tokens > self.capacity:
            raise ValueError("请求令牌数不能超过桶容量")

        deadline = None if timeout is None else (time.monotonic() + timeout)
        while True:
            async with self._lock:
                self._refill_unlocked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                missing = tokens - self._tokens
                wait_seconds = missing / self.rate_per_sec

            if deadline is not None and time.monotonic() + wait_seconds > deadline:
                return False
            await asyncio.sleep(min(wait_seconds, 0.05))

    async def try_acquire(self, tokens: float = 1.0) -> bool:
        """立即尝试获取令牌。"""
        if tokens <= 0:
            return True

        async with self._lock:
            self._refill_unlocked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    async def stats(self) -> BucketStats:
        """读取桶状态。"""
        async with self._lock:
            self._refill_unlocked()
            return BucketStats(
                rate_per_sec=self.rate_per_sec,
                capacity=self.capacity,
                tokens=self._tokens,
            )


class RateLimiter:
    """按交易所与用途管理多个限流桶。"""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], TokenBucket] = {}

    def register(self, exchange: str, scope: str, rate_per_sec: float, capacity: float) -> None:
        self._buckets[(exchange, scope)] = TokenBucket(rate_per_sec=rate_per_sec, capacity=capacity)

    def ensure(self, exchange: str, scope: str, rate_per_sec: float, capacity: float) -> None:
        if (exchange, scope) not in self._buckets:
            self.register(exchange, scope, rate_per_sec, capacity)

    async def acquire(
        self,
        exchange: str,
        scope: str,
        tokens: float = 1.0,
        timeout: float | None = None,
    ) -> bool:
        bucket = self._buckets.get((exchange, scope))
        if bucket is None:
            return True
        return await bucket.acquire(tokens=tokens, timeout=timeout)

    async def try_acquire(self, exchange: str, scope: str, tokens: float = 1.0) -> bool:
        bucket = self._buckets.get((exchange, scope))
        if bucket is None:
            return True
        return await bucket.try_acquire(tokens=tokens)

    async def snapshot(self) -> dict[str, dict[str, BucketStats]]:
        out: dict[str, dict[str, BucketStats]] = {}
        for (exchange, scope), bucket in self._buckets.items():
            out.setdefault(exchange, {})
            out[exchange][scope] = await bucket.stats()
        return out
