"""REST 与 WS 一致性校验。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..models import BBO


def _diff_bps(a: Decimal, b: Decimal) -> Decimal:
    if a <= 0 or b <= 0:
        return Decimal("0")
    base = (a + b) / Decimal("2")
    if base <= 0:
        return Decimal("0")
    return abs(a - b) / base * Decimal("10000")


@dataclass(slots=True)
class SymbolConsistency:
    """单标的一致性状态。"""

    failed_count: int = 0
    ok: bool = True
    last_reason: str = ""


class ConsistencyGuard:
    """盘口一致性守卫。"""

    def __init__(self, tolerance_bps: Decimal, max_failures: int) -> None:
        self.tolerance_bps = tolerance_bps
        self.max_failures = max_failures
        self._state: dict[str, SymbolConsistency] = {}

    def check(
        self,
        symbol: str,
        paradex_ws: BBO | None,
        paradex_rest: BBO | None,
        grvt_ws: BBO | None,
        grvt_rest: BBO | None,
    ) -> bool:
        state = self._state.setdefault(symbol, SymbolConsistency())

        if not all([paradex_ws, paradex_rest, grvt_ws, grvt_rest]):
            state.failed_count += 1
            state.ok = state.failed_count < self.max_failures
            state.last_reason = "缺少用于对比的盘口数据"
            return state.ok

        pd_bid_diff = _diff_bps(paradex_ws.bid, paradex_rest.bid)
        pd_ask_diff = _diff_bps(paradex_ws.ask, paradex_rest.ask)
        gr_bid_diff = _diff_bps(grvt_ws.bid, grvt_rest.bid)
        gr_ask_diff = _diff_bps(grvt_ws.ask, grvt_rest.ask)

        max_diff = max(pd_bid_diff, pd_ask_diff, gr_bid_diff, gr_ask_diff)
        if max_diff > self.tolerance_bps:
            state.failed_count += 1
            state.ok = state.failed_count < self.max_failures
            state.last_reason = f"最大偏差 {max_diff:.4f} bps 超阈值 {self.tolerance_bps}"
            return state.ok

        state.failed_count = 0
        state.ok = True
        state.last_reason = ""
        return True

    def snapshot(self) -> dict[str, dict[str, str | int | bool]]:
        return {
            symbol: {
                "ok": state.ok,
                "failed_count": state.failed_count,
                "last_reason": state.last_reason,
            }
            for symbol, state in self._state.items()
        }
