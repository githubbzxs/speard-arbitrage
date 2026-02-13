"""策略绩效追踪器（本次运行周期）。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..models import ExchangeName, TradeFill, TradeSide


@dataclass(slots=True)
class _LegState:
    qty: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")


class PerformanceTracker:
    """跟踪本次运行盈亏、成交量、回撤与最大回撤。"""

    def __init__(self) -> None:
        self._running_since = ""
        self._initial_equity = Decimal("0")
        self._realized_pnl = Decimal("0")
        self._run_turnover_usd = Decimal("0")
        self._run_trade_count = 0
        self._equity_now = Decimal("0")
        self._equity_peak = Decimal("0")
        self._max_drawdown_pct = Decimal("0")

        self._legs: dict[tuple[ExchangeName, str], _LegState] = {}
        self._marks: dict[tuple[ExchangeName, str], Decimal] = {}

    def reset(self, started_at: str, initial_equity: Decimal) -> None:
        self._running_since = started_at
        self._initial_equity = initial_equity
        self._realized_pnl = Decimal("0")
        self._run_turnover_usd = Decimal("0")
        self._run_trade_count = 0
        self._equity_now = initial_equity
        self._equity_peak = initial_equity
        self._max_drawdown_pct = Decimal("0")
        self._legs.clear()
        self._marks.clear()
        self._refresh_equity()

    def on_fill(self, fill: TradeFill) -> None:
        if fill.quantity <= 0:
            return

        self._run_trade_count += 1
        self._run_turnover_usd += abs(fill.quantity * fill.price)

        delta_qty = fill.quantity if fill.side == TradeSide.BUY else -fill.quantity
        key = (fill.exchange, fill.symbol)
        leg = self._legs.setdefault(key, _LegState())
        self._realized_pnl += self._apply_delta(leg, delta_qty, fill.price)

        self._marks.setdefault(key, fill.price)
        self._refresh_equity()

    def on_mark(self, symbol: str, paradex_mid: Decimal, grvt_mid: Decimal) -> None:
        if paradex_mid > 0:
            self._marks[(ExchangeName.PARADEX, symbol)] = paradex_mid
        if grvt_mid > 0:
            self._marks[(ExchangeName.GRVT, symbol)] = grvt_mid
        self._refresh_equity()

    def snapshot(self) -> dict[str, float | int | str]:
        unrealized = self._compute_unrealized()
        total_pnl = self._realized_pnl + unrealized

        drawdown_pct = Decimal("0")
        if self._equity_peak > 0:
            drawdown_pct = max(
                Decimal("0"),
                ((self._equity_peak - self._equity_now) / self._equity_peak) * Decimal("100"),
            )

        pnl_pct = Decimal("0")
        if self._initial_equity > 0:
            pnl_pct = (total_pnl / self._initial_equity) * Decimal("100")

        return {
            "running_since": self._running_since,
            "run_realized_pnl": float(self._realized_pnl),
            "run_unrealized_pnl": float(unrealized),
            "run_total_pnl": float(total_pnl),
            "run_pnl_pct": float(pnl_pct),
            "run_turnover_usd": float(self._run_turnover_usd),
            "run_trade_count": self._run_trade_count,
            "equity_now": float(self._equity_now),
            "equity_peak": float(self._equity_peak),
            "drawdown_pct": float(drawdown_pct),
            "max_drawdown_pct": float(self._max_drawdown_pct),
        }

    @staticmethod
    def _apply_delta(leg: _LegState, delta_qty: Decimal, price: Decimal) -> Decimal:
        if delta_qty == 0:
            return Decimal("0")

        current_qty = leg.qty
        if current_qty == 0:
            leg.qty = delta_qty
            leg.avg_price = price
            return Decimal("0")

        # 同向加仓：更新均价，不产生已实现盈亏。
        if current_qty * delta_qty > 0:
            next_qty = current_qty + delta_qty
            leg.avg_price = (
                abs(current_qty) * leg.avg_price + abs(delta_qty) * price
            ) / abs(next_qty)
            leg.qty = next_qty
            return Decimal("0")

        # 反向成交：先平仓，再决定是否反手开仓。
        close_qty = min(abs(current_qty), abs(delta_qty))
        direction_sign = Decimal("1") if current_qty > 0 else Decimal("-1")
        realized = (price - leg.avg_price) * close_qty * direction_sign

        next_qty = current_qty + delta_qty
        if next_qty == 0:
            leg.qty = Decimal("0")
            leg.avg_price = Decimal("0")
            return realized

        if current_qty * next_qty > 0:
            leg.qty = next_qty
            return realized

        # 穿仓后反手，剩余部分按当前成交价作为新开仓成本。
        leg.qty = next_qty
        leg.avg_price = price
        return realized

    def _compute_unrealized(self) -> Decimal:
        unrealized = Decimal("0")
        for key, leg in self._legs.items():
            mark = self._marks.get(key)
            if mark is None or leg.qty == 0:
                continue
            unrealized += (mark - leg.avg_price) * leg.qty
        return unrealized

    def _refresh_equity(self) -> None:
        unrealized = self._compute_unrealized()
        total_pnl = self._realized_pnl + unrealized
        self._equity_now = self._initial_equity + total_pnl
        if self._equity_now > self._equity_peak:
            self._equity_peak = self._equity_now

        if self._equity_peak > 0:
            drawdown_pct = max(
                Decimal("0"),
                ((self._equity_peak - self._equity_now) / self._equity_peak) * Decimal("100"),
            )
            if drawdown_pct > self._max_drawdown_pct:
                self._max_drawdown_pct = drawdown_pct
