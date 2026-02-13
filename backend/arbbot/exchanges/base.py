"""交易所抽象接口。"""

from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable
from decimal import Decimal

from ..config import SymbolConfig
from ..models import BBO, ExchangeName, OrderAck, OrderRequest

OrderbookCallback = Callable[[ExchangeName, str, BBO], Awaitable[None]]
OrderUpdateCallback = Callable[[OrderAck], Awaitable[None]]


class BaseExchangeAdapter(abc.ABC):
    """统一交易所适配器抽象。"""

    def __init__(self, name: ExchangeName, simulate_market_data: bool) -> None:
        self.name = name
        self.simulate_market_data = simulate_market_data
        # 向后兼容历史字段，避免下游模块引用崩溃。
        self.dry_run = simulate_market_data
        self._orderbook_callback: OrderbookCallback | None = None
        self._order_update_callback: OrderUpdateCallback | None = None

    def set_orderbook_callback(self, callback: OrderbookCallback | None) -> None:
        """设置盘口回调。"""
        self._orderbook_callback = callback

    def set_order_update_callback(self, callback: OrderUpdateCallback | None) -> None:
        """设置订单回调。"""
        self._order_update_callback = callback

    async def emit_orderbook(self, symbol: str, bbo: BBO) -> None:
        """向上层发出盘口事件。"""
        if self._orderbook_callback is not None:
            await self._orderbook_callback(self.name, symbol, bbo)

    async def emit_order_update(self, ack: OrderAck) -> None:
        """向上层发出订单更新事件。"""
        if self._order_update_callback is not None:
            await self._order_update_callback(ack)

    @abc.abstractmethod
    async def connect(self, symbols: list[SymbolConfig]) -> None:
        """建立连接与初始化。"""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """关闭连接。"""

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """健康检查。"""

    @abc.abstractmethod
    async def fetch_bbo(self, symbol: SymbolConfig) -> BBO | None:
        """获取用于交易决策的盘口。"""

    @abc.abstractmethod
    async def fetch_rest_bbo(self, symbol: SymbolConfig) -> BBO | None:
        """获取 REST 盘口，用于与 WS 一致性校验。"""

    @abc.abstractmethod
    async def fetch_position(self, symbol: SymbolConfig) -> Decimal:
        """获取当前净仓位。"""

    @abc.abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderAck:
        """下单。"""

    @abc.abstractmethod
    async def cancel_order(self, symbol: SymbolConfig, order_id: str) -> bool:
        """撤单。"""
