from __future__ import annotations

from decimal import Decimal

import pytest

from arbbot.config import StrategyConfig, SymbolConfig
from arbbot.models import (
    ArbitrageDirection,
    ExchangeName,
    OrderAck,
    SignalAction,
    SpreadSignal,
    TradeSide,
)
from arbbot.risk.rate_limiter import RateLimiter
from arbbot.strategy.execution_engine import ExecutionEngine
from arbbot.strategy.position_manager import PositionManager


class _DummyAdapter:
    def __init__(self, exchange: ExchangeName) -> None:
        self.exchange = exchange
        self.calls = 0

    async def place_order(self, request):  # noqa: ANN001
        self.calls += 1
        return OrderAck(
            success=True,
            exchange=self.exchange,
            order_id=f"{self.exchange.value}-order-1",
            side=request.side,
            requested_quantity=request.quantity,
            filled_quantity=request.quantity,
            avg_price=Decimal("100"),
            message="ok",
        )


@pytest.mark.asyncio
async def test_execute_signal_blocked_when_live_order_disabled() -> None:
    paradex = _DummyAdapter(ExchangeName.PARADEX)
    grvt = _DummyAdapter(ExchangeName.GRVT)

    engine = ExecutionEngine(
        adapters={
            ExchangeName.PARADEX: paradex,
            ExchangeName.GRVT: grvt,
        },
        rate_limiter=RateLimiter(),
        position_manager=PositionManager(),
        strategy_cfg=StrategyConfig(),
        live_order_enabled=False,
    )

    signal = SpreadSignal(
        action=SignalAction.OPEN,
        direction=ArbitrageDirection.LONG_PARA_SHORT_GRVT,
        edge_bps=Decimal("12"),
        zscore=Decimal("2.5"),
        threshold_bps=Decimal("1.0"),
        reason="测试开仓",
        batches=[Decimal("0.001")],
    )

    report = await engine.execute_signal(
        symbol_cfg=SymbolConfig(
            symbol="BTC-PERP",
            paradex_market="BTC-PERP",
            grvt_market="BTC-PERP",
        ),
        signal=signal,
        paradex_bid=Decimal("100"),
        paradex_ask=Decimal("100.1"),
        can_open=True,
    )

    assert report.attempted_orders == 0
    assert report.success_orders == 0
    assert report.failed_orders == 0
    assert "真实下单已禁用" in report.message
    assert paradex.calls == 0
    assert grvt.calls == 0
