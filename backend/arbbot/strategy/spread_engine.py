"""动态价差策略引擎。"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from statistics import mean, pstdev

from ..config import StrategyConfig
from ..models import (
    ArbitrageDirection,
    BBO,
    SignalAction,
    SpreadMetrics,
    SpreadSignal,
    StrategyMode,
)


def _to_bps(value: Decimal, base: Decimal) -> Decimal:
    if base <= 0:
        return Decimal("0")
    return value / base * Decimal("10000")


class SpreadEngine:
    """基于 MA + Rolling Std 的动态开平仓逻辑。"""

    def __init__(self, config: StrategyConfig) -> None:
        self.config = config
        self._history: dict[str, deque[Decimal]] = {}

    def _history_for(self, symbol: str) -> deque[Decimal]:
        return self._history.setdefault(symbol, deque(maxlen=max(self.config.ma_window, self.config.std_window) * 2))

    def compute_metrics(self, symbol: str, paradex: BBO, grvt: BBO) -> SpreadMetrics:
        """计算双向 edge 与 z-score。"""
        edge_para_to_grvt = grvt.bid - paradex.ask
        edge_grvt_to_para = paradex.bid - grvt.ask

        base_mid = (paradex.mid + grvt.mid) / Decimal("2")
        edge_para_to_grvt_bps = _to_bps(edge_para_to_grvt, base_mid)
        edge_grvt_to_para_bps = _to_bps(edge_grvt_to_para, base_mid)

        signed_edge = edge_para_to_grvt_bps if edge_para_to_grvt_bps >= edge_grvt_to_para_bps else -edge_grvt_to_para_bps
        history = self._history_for(symbol)
        history.append(signed_edge)

        samples = list(history)
        if len(samples) >= self.config.min_samples:
            ma_value = Decimal(str(mean([float(x) for x in samples[-self.config.ma_window :]])))
            std_value = Decimal(str(pstdev([float(x) for x in samples[-self.config.std_window :]])))
        else:
            ma_value = Decimal("0")
            std_value = Decimal("0")

        if std_value > Decimal("0"):
            zscore = (signed_edge - ma_value) / std_value
        else:
            zscore = Decimal("0")

        return SpreadMetrics(
            symbol=symbol,
            edge_para_to_grvt_bps=edge_para_to_grvt_bps,
            edge_grvt_to_para_bps=edge_grvt_to_para_bps,
            signed_edge_bps=signed_edge,
            ma=ma_value,
            std=std_value,
            zscore=zscore,
        )

    def generate_signal(self, metrics: SpreadMetrics, mode: StrategyMode) -> SpreadSignal:
        """根据当前模式生成策略信号。"""
        edge_abs = abs(metrics.signed_edge_bps)

        if mode == StrategyMode.ZERO_WEAR:
            z_entry = self.config.z_zero_entry
            z_exit = self.config.z_zero_exit
            min_edge = self.config.min_edge_bps * Decimal("0.7")
        else:
            z_entry = self.config.z_entry
            z_exit = self.config.z_exit
            min_edge = self.config.min_edge_bps

        direction = (
            ArbitrageDirection.LONG_PARA_SHORT_GRVT
            if metrics.signed_edge_bps >= 0
            else ArbitrageDirection.LONG_GRVT_SHORT_PARA
        )

        if edge_abs < min_edge:
            return SpreadSignal(
                action=SignalAction.HOLD,
                direction=direction,
                edge_bps=edge_abs,
                zscore=metrics.zscore,
                threshold_bps=min_edge,
                reason="边际不足，不开仓",
                batches=[],
            )

        if abs(metrics.zscore) >= z_entry:
            batches = self._build_batches(abs(metrics.zscore), mode)
            return SpreadSignal(
                action=SignalAction.OPEN,
                direction=direction,
                edge_bps=edge_abs,
                zscore=metrics.zscore,
                threshold_bps=min_edge,
                reason="满足动态开仓条件",
                batches=batches,
            )

        if abs(metrics.zscore) <= z_exit:
            return SpreadSignal(
                action=SignalAction.CLOSE,
                direction=direction,
                edge_bps=edge_abs,
                zscore=metrics.zscore,
                threshold_bps=min_edge,
                reason="均值回归，触发平仓",
                batches=[self.config.base_order_qty],
            )

        return SpreadSignal(
            action=SignalAction.HOLD,
            direction=direction,
            edge_bps=edge_abs,
            zscore=metrics.zscore,
            threshold_bps=min_edge,
            reason="等待更优价差",
            batches=[],
        )

    def _build_batches(self, zscore_abs: Decimal, mode: StrategyMode) -> list[Decimal]:
        if zscore_abs < Decimal("2.3"):
            count = 1
        elif zscore_abs < Decimal("3.0"):
            count = 2
        else:
            count = 3

        if mode == StrategyMode.ZERO_WEAR:
            weights = [Decimal("0.6"), Decimal("0.4"), Decimal("0.2")]
        else:
            weights = [Decimal("1.0"), Decimal("0.7"), Decimal("0.5")]

        batches: list[Decimal] = []
        for weight in weights[:count]:
            qty = min(self.config.base_order_qty * weight, self.config.max_batch_qty)
            if qty > 0:
                batches.append(qty)

        return batches if batches else [min(self.config.base_order_qty, self.config.max_batch_qty)]
