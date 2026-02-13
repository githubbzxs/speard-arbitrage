"""交易所健康检查守卫。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import utc_ms


@dataclass(slots=True)
class HealthItem:
    """单交易所健康状态。"""

    ok: bool = False
    fail_count: int = 0
    last_ok_ms: int = 0
    last_check_ms: int = 0
    message: str = ""


@dataclass(slots=True)
class HealthSnapshot:
    """健康检查快照。"""

    items: dict[str, HealthItem] = field(default_factory=dict)


class HealthGuard:
    """统一健康检查与开仓准入判断。"""

    def __init__(self, fail_threshold: int, cache_ms: int) -> None:
        self.fail_threshold = fail_threshold
        self.cache_ms = cache_ms
        self._items: dict[str, HealthItem] = {}

    def should_check(self, exchange: str) -> bool:
        item = self._items.get(exchange)
        if item is None:
            return True
        return utc_ms() - item.last_check_ms >= self.cache_ms

    def update(self, exchange: str, ok: bool, message: str = "") -> None:
        now = utc_ms()
        item = self._items.setdefault(exchange, HealthItem())
        item.last_check_ms = now
        item.ok = ok
        item.message = message
        if ok:
            item.fail_count = 0
            item.last_ok_ms = now
        else:
            item.fail_count += 1

    def can_open(self) -> bool:
        if not self._items:
            return False
        for item in self._items.values():
            if item.fail_count >= self.fail_threshold:
                return False
            if not item.ok:
                return False
        return True

    def summary(self) -> dict[str, dict[str, int | bool | str]]:
        return {
            exchange: {
                "ok": item.ok,
                "fail_count": item.fail_count,
                "last_ok_ms": item.last_ok_ms,
                "last_check_ms": item.last_check_ms,
                "message": item.message,
            }
            for exchange, item in self._items.items()
        }
