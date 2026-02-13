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
            order_id=f"{self.exchange.value}-order-{self.calls}",
            side=request.side,
            requested_quantity=request.quantity,
            filled_quantity=request.quantity,
            avg_price=Decimal("100"),
            message="ok",
        )


class _CaptureAdapter:
    def __init__(self, exchange: ExchangeName) -> None:
        self.exchange = exchange
        self.requests = []

    async def place_order(self, request):  # noqa: ANN001
        self.requests.append(request)
        return OrderAck(
            success=True,
            exchange=self.exchange,
            order_id=f"{self.exchange.value}-order-{len(self.requests)}",
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
        reason="test open",
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
        grvt_bid=Decimal("100"),
        grvt_ask=Decimal("100.1"),
        can_open=True,
    )

    assert report.attempted_orders == 0
    assert report.success_orders == 0
    assert report.failed_orders == 0
    assert "真实下单已禁用" in report.message
    assert paradex.calls == 0
    assert grvt.calls == 0


@pytest.mark.asyncio
async def test_open_signal_uses_paradex_taker_then_grvt_hedge() -> None:
    paradex = _CaptureAdapter(ExchangeName.PARADEX)
    grvt = _CaptureAdapter(ExchangeName.GRVT)

    engine = ExecutionEngine(
        adapters={
            ExchangeName.PARADEX: paradex,
            ExchangeName.GRVT: grvt,
        },
        rate_limiter=RateLimiter(),
        position_manager=PositionManager(),
        strategy_cfg=StrategyConfig(),
        live_order_enabled=True,
    )

    signal = SpreadSignal(
        action=SignalAction.OPEN,
        direction=ArbitrageDirection.LONG_PARA_SHORT_GRVT,
        edge_bps=Decimal("15"),
        zscore=Decimal("2.2"),
        threshold_bps=Decimal("1.0"),
        reason="test open",
        batches=[Decimal("0.001"), Decimal("0.002")],
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
        grvt_bid=Decimal("99.9"),
        grvt_ask=Decimal("100.2"),
        can_open=True,
    )

    assert report.failed_orders == 0
    assert len(paradex.requests) == 2
    assert len(grvt.requests) == 2

    for index in range(2):
        paradex_request = paradex.requests[index]
        grvt_request = grvt.requests[index]
        assert paradex_request.order_type == "market"
        assert paradex_request.post_only is False
        assert grvt_request.order_type == "limit"
        assert grvt_request.post_only is True
        expected_grvt_price = Decimal("99.9") if grvt_request.side.value == "buy" else Decimal("100.2")
        assert grvt_request.price == expected_grvt_price
        assert grvt_request.quantity == paradex_request.quantity
