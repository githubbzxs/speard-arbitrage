from decimal import Decimal

from arbbot.config import StrategyConfig
from arbbot.models import BBO, SignalAction, StrategyMode
from arbbot.strategy.spread_engine import SpreadEngine


def test_spread_engine_open_signal_by_zscore() -> None:
    cfg = StrategyConfig(
        ma_window=20,
        std_window=20,
        min_samples=20,
        z_entry=Decimal("1.5"),
        z_exit=Decimal("0.5"),
        base_order_qty=Decimal("0.01"),
        max_batch_qty=Decimal("0.02"),
    )
    engine = SpreadEngine(cfg)

    paradex = BBO(bid=Decimal("100"), ask=Decimal("100.2"))
    # 构造一段稳定历史。
    for idx in range(25):
        grvt = BBO(bid=Decimal("100.22") + Decimal(str(idx % 3)) * Decimal("0.002"), ask=Decimal("100.42"))
        engine.compute_metrics("BTC-PERP", paradex, grvt)

    # 构造明显放大边际，触发开仓。
    grvt_big = BBO(bid=Decimal("100.9"), ask=Decimal("101.1"))
    metrics = engine.compute_metrics("BTC-PERP", paradex, grvt_big)
    signal = engine.generate_signal(metrics, StrategyMode.NORMAL_ARB)

    assert signal.action == SignalAction.OPEN
    assert signal.batches


def test_spread_engine_close_signal_when_reversion() -> None:
    cfg = StrategyConfig(
        ma_window=10,
        std_window=10,
        min_samples=10,
        z_entry=Decimal("1.2"),
        z_exit=Decimal("0.8"),
        base_order_qty=Decimal("0.01"),
        max_batch_qty=Decimal("0.02"),
    )
    engine = SpreadEngine(cfg)

    paradex = BBO(bid=Decimal("100"), ask=Decimal("100.2"))
    for _ in range(12):
        grvt = BBO(bid=Decimal("100.4"), ask=Decimal("100.6"))
        engine.compute_metrics("ETH-PERP", paradex, grvt)

    # 回归到中性，触发平仓。
    grvt_flat = BBO(bid=Decimal("100.21"), ask=Decimal("100.41"))
    metrics = engine.compute_metrics("ETH-PERP", paradex, grvt_flat)
    signal = engine.generate_signal(metrics, StrategyMode.NORMAL_ARB)

    assert signal.action in {SignalAction.CLOSE, SignalAction.HOLD}
