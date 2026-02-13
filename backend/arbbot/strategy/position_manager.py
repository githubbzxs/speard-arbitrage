"""仓位管理与再平衡逻辑。"""

from __future__ import annotations

from decimal import Decimal

from ..models import ExchangeName, PositionState, RebalanceOrder, TradeFill, TradeSide


class PositionManager:
    """集中维护双交易所仓位。"""

    def __init__(self) -> None:
        self._states: dict[str, PositionState] = {}

    def _ensure(self, symbol: str) -> PositionState:
        return self._states.setdefault(symbol, PositionState())

    def set_positions(self, symbol: str, paradex: Decimal, grvt: Decimal) -> None:
        state = self._ensure(symbol)
        state.paradex = paradex
        state.grvt = grvt

    def set_target(self, symbol: str, target: Decimal) -> None:
        state = self._ensure(symbol)
        state.target_net = target

    def apply_fill(self, fill: TradeFill) -> None:
        state = self._ensure(fill.symbol)
        if fill.exchange == ExchangeName.PARADEX:
            state.paradex += fill.quantity if fill.side == TradeSide.BUY else -fill.quantity
        else:
            state.grvt += fill.quantity if fill.side == TradeSide.BUY else -fill.quantity

    def get_state(self, symbol: str) -> PositionState:
        return self._ensure(symbol)

    def can_open(self, symbol: str, max_position: Decimal) -> bool:
        state = self._ensure(symbol)
        return abs(state.paradex) <= max_position and abs(state.grvt) <= max_position

    def is_imbalanced(self, symbol: str, tolerance: Decimal) -> bool:
        state = self._ensure(symbol)
        return abs(state.net_exposure) > tolerance

    def is_hard_limit_breached(self, symbol: str, hard_limit: Decimal) -> bool:
        state = self._ensure(symbol)
        return abs(state.net_exposure) > hard_limit

    def build_rebalance_orders(self, symbol: str, tolerance: Decimal, base_qty: Decimal) -> list[RebalanceOrder]:
        state = self._ensure(symbol)
        if abs(state.net_exposure) <= tolerance:
            return []

        qty = min(abs(state.net_exposure), base_qty)
        if qty <= 0:
            return []

        orders: list[RebalanceOrder] = []
        if state.net_exposure > 0:
            # 总体偏多，需要卖出净敞口。
            if state.paradex >= state.grvt:
                orders.append(
                    RebalanceOrder(
                        exchange=ExchangeName.PARADEX,
                        side=TradeSide.SELL,
                        quantity=qty,
                        symbol=symbol,
                    )
                )
            else:
                orders.append(
                    RebalanceOrder(
                        exchange=ExchangeName.GRVT,
                        side=TradeSide.SELL,
                        quantity=qty,
                        symbol=symbol,
                    )
                )
        else:
            # 总体偏空，需要买入净敞口。
            if state.paradex <= state.grvt:
                orders.append(
                    RebalanceOrder(
                        exchange=ExchangeName.PARADEX,
                        side=TradeSide.BUY,
                        quantity=qty,
                        symbol=symbol,
                    )
                )
            else:
                orders.append(
                    RebalanceOrder(
                        exchange=ExchangeName.GRVT,
                        side=TradeSide.BUY,
                        quantity=qty,
                        symbol=symbol,
                    )
                )

        return orders

    def snapshot(self) -> dict[str, dict[str, str | None]]:
        return {symbol: state.to_dict() for symbol, state in self._states.items()}
