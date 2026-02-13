from decimal import Decimal

from arbbot.models import ExchangeName, TradeFill, TradeSide
from arbbot.strategy.position_manager import PositionManager


def test_position_manager_rebalance_orders() -> None:
    pm = PositionManager()
    pm.set_positions("BTC-PERP", paradex=Decimal("0.01"), grvt=Decimal("-0.006"))

    assert pm.is_imbalanced("BTC-PERP", Decimal("0.001")) is True

    ops = pm.build_rebalance_orders(
        symbol="BTC-PERP",
        tolerance=Decimal("0.001"),
        base_qty=Decimal("0.002"),
    )
    assert len(ops) == 1
    assert ops[0].exchange in {ExchangeName.PARADEX, ExchangeName.GRVT}


def test_position_apply_fill() -> None:
    pm = PositionManager()
    pm.set_positions("ETH-PERP", paradex=Decimal("0"), grvt=Decimal("0"))

    pm.apply_fill(
        TradeFill(
            exchange=ExchangeName.PARADEX,
            symbol="ETH-PERP",
            side=TradeSide.BUY,
            quantity=Decimal("0.003"),
            price=Decimal("2500"),
            order_id="1",
            tag="test",
        )
    )

    pm.apply_fill(
        TradeFill(
            exchange=ExchangeName.GRVT,
            symbol="ETH-PERP",
            side=TradeSide.SELL,
            quantity=Decimal("0.003"),
            price=Decimal("2501"),
            order_id="2",
            tag="test",
        )
    )

    state = pm.get_state("ETH-PERP")
    assert state.paradex == Decimal("0.003")
    assert state.grvt == Decimal("-0.003")
