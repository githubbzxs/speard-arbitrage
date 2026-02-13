from __future__ import annotations

from decimal import Decimal

from arbbot.models import ExchangeName, TradeFill, TradeSide
from arbbot.strategy.performance_tracker import PerformanceTracker


def test_performance_tracker_tracks_realized_unrealized_and_drawdown() -> None:
    tracker = PerformanceTracker()
    tracker.reset(started_at="2026-02-13T00:00:00+00:00", initial_equity=Decimal("1000"))

    tracker.on_fill(
        TradeFill(
            exchange=ExchangeName.PARADEX,
            symbol="BTC-PERP",
            side=TradeSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("100"),
            order_id="o1",
            tag="test",
        )
    )
    tracker.on_mark(symbol="BTC-PERP", paradex_mid=Decimal("110"), grvt_mid=Decimal("100"))

    snap_1 = tracker.snapshot()
    assert snap_1["run_realized_pnl"] == 0.0
    assert snap_1["run_unrealized_pnl"] == 10.0
    assert snap_1["run_total_pnl"] == 10.0
    assert snap_1["run_turnover_usd"] == 100.0
    assert snap_1["run_trade_count"] == 1
    assert snap_1["max_drawdown_pct"] == 0.0

    tracker.on_mark(symbol="BTC-PERP", paradex_mid=Decimal("90"), grvt_mid=Decimal("100"))
    snap_2 = tracker.snapshot()
    assert snap_2["run_unrealized_pnl"] == -10.0
    assert snap_2["drawdown_pct"] > 0.0
    assert snap_2["max_drawdown_pct"] >= snap_2["drawdown_pct"]

    tracker.on_fill(
        TradeFill(
            exchange=ExchangeName.PARADEX,
            symbol="BTC-PERP",
            side=TradeSide.SELL,
            quantity=Decimal("1"),
            price=Decimal("95"),
            order_id="o2",
            tag="test",
        )
    )
    snap_3 = tracker.snapshot()
    assert snap_3["run_realized_pnl"] == -5.0
    assert snap_3["run_unrealized_pnl"] == 0.0
    assert snap_3["run_total_pnl"] == -5.0
    assert snap_3["run_turnover_usd"] == 195.0
    assert snap_3["run_trade_count"] == 2
