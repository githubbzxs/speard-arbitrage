"""Paradex 交易所适配器。"""

from __future__ import annotations

import random
import uuid
from decimal import Decimal

from ..config import ExchangeConfig, SymbolConfig
from ..models import BBO, ExchangeName, OrderAck, OrderRequest, TradeSide
from .base import BaseExchangeAdapter


class ParadexAdapter(BaseExchangeAdapter):
    """Paradex 适配器，支持 dry-run 与实盘两种模式。"""

    def __init__(self, config: ExchangeConfig, simulate_market_data: bool) -> None:
        super().__init__(name=ExchangeName.PARADEX, simulate_market_data=simulate_market_data)
        self.config = config
        self._client = None
        self._symbols: dict[str, SymbolConfig] = {}
        self._sim_mid: dict[str, Decimal] = {}
        self._sim_pos: dict[str, Decimal] = {}

    async def connect(self, symbols: list[SymbolConfig]) -> None:
        self._symbols = {cfg.symbol: cfg for cfg in symbols}
        for cfg in symbols:
            # dry-run 下的模拟行情应尽量贴近真实价格区间，避免 UI 端出现“价差 100+”这类误解。
            self._sim_mid.setdefault(cfg.symbol, self._infer_anchor_mid(cfg.symbol))
            self._sim_pos.setdefault(cfg.symbol, Decimal("0"))

        if self.simulate_market_data:
            return

        import ccxt.async_support as ccxt  # type: ignore

        kwargs = {
            "enableRateLimit": True,
            "walletAddress": self.config.credentials.l2_address,
            "privateKey": self.config.credentials.l2_private_key,
            "options": {
                "paradexAccount": {
                    "privateKey": self.config.credentials.l2_private_key,
                    "address": self.config.credentials.l2_address,
                }
            },
        }

        self._client = ccxt.paradex(kwargs)
        await self._client.load_markets()

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def health_check(self) -> bool:
        if self.simulate_market_data:
            return True
        if self._client is None:
            return False
        try:
            await self._client.fetch_time()
            return True
        except Exception:
            return False

    async def fetch_bbo(self, symbol: SymbolConfig) -> BBO | None:
        if self.simulate_market_data:
            bbo = self._simulate_bbo(symbol.symbol, source="ws")
            await self.emit_orderbook(symbol.symbol, bbo)
            return bbo

        if self._client is None:
            return None

        try:
            depth = await self._client.fetch_order_book(symbol.paradex_market, limit=5)
            bids = depth.get("bids", [])
            asks = depth.get("asks", [])
            if not bids or not asks:
                return None
            bbo = BBO(
                bid=Decimal(str(bids[0][0])),
                ask=Decimal(str(asks[0][0])),
                source="ws",
            )
            await self.emit_orderbook(symbol.symbol, bbo)
            return bbo
        except Exception:
            return None

    async def fetch_rest_bbo(self, symbol: SymbolConfig) -> BBO | None:
        if self.simulate_market_data:
            return self._simulate_bbo(symbol.symbol, source="rest")

        if self._client is None:
            return None

        try:
            depth = await self._client.fetch_order_book(symbol.paradex_market, limit=5)
            bids = depth.get("bids", [])
            asks = depth.get("asks", [])
            if not bids or not asks:
                return None
            return BBO(
                bid=Decimal(str(bids[0][0])),
                ask=Decimal(str(asks[0][0])),
                source="rest",
            )
        except Exception:
            return None

    async def fetch_position(self, symbol: SymbolConfig) -> Decimal:
        if self.simulate_market_data:
            return self._sim_pos.get(symbol.symbol, Decimal("0"))

        if self._client is None:
            return Decimal("0")

        try:
            positions = await self._client.fetch_positions([symbol.paradex_market])
            if not positions:
                return Decimal("0")
            position = positions[0]
            qty = Decimal(str(position.get("contracts") or position.get("size") or 0))
            side = str(position.get("side") or "").lower()
            if side == "short":
                qty = -abs(qty)
            elif side == "long":
                qty = abs(qty)
            return qty
        except Exception:
            return Decimal("0")

    async def place_order(self, request: OrderRequest) -> OrderAck:
        if self.simulate_market_data:
            bbo = self._simulate_bbo(request.symbol, source="ws")
            price = request.price if request.price is not None else bbo.mid
            if request.side == TradeSide.BUY:
                self._sim_pos[request.symbol] = self._sim_pos.get(request.symbol, Decimal("0")) + request.quantity
            else:
                self._sim_pos[request.symbol] = self._sim_pos.get(request.symbol, Decimal("0")) - request.quantity

            ack = OrderAck(
                success=True,
                exchange=self.name,
                order_id=f"pdx-{uuid.uuid4().hex[:12]}",
                side=request.side,
                requested_quantity=request.quantity,
                filled_quantity=request.quantity,
                avg_price=price,
                message="dry-run 成交",
            )
            await self.emit_order_update(ack)
            return ack

        if self._client is None:
            return OrderAck(
                success=False,
                exchange=self.name,
                order_id="",
                side=request.side,
                requested_quantity=request.quantity,
                filled_quantity=Decimal("0"),
                message="Paradex 客户端未连接",
            )

        symbol_cfg = self._symbols.get(request.symbol)
        market = symbol_cfg.paradex_market if symbol_cfg else request.symbol
        params: dict[str, object] = {}
        if request.post_only:
            params["postOnly"] = True
            params["timeInForce"] = "GTC"
        if request.reduce_only:
            params["reduceOnly"] = True

        try:
            created = await self._client.create_order(
                market,
                request.order_type,
                request.side.value,
                float(request.quantity),
                float(request.price) if request.price is not None else None,
                params,
            )
            order_id = str(created.get("id") or created.get("clientOrderId") or "")
            filled = Decimal(str(created.get("filled") or 0))
            avg_price = created.get("average")
            ack = OrderAck(
                success=True,
                exchange=self.name,
                order_id=order_id,
                side=request.side,
                requested_quantity=request.quantity,
                filled_quantity=filled,
                avg_price=Decimal(str(avg_price)) if avg_price is not None else request.price,
                message="提交成功",
            )
            await self.emit_order_update(ack)
            return ack
        except Exception as exc:
            return OrderAck(
                success=False,
                exchange=self.name,
                order_id="",
                side=request.side,
                requested_quantity=request.quantity,
                filled_quantity=Decimal("0"),
                message=f"下单失败: {exc}",
            )

    async def cancel_order(self, symbol: SymbolConfig, order_id: str) -> bool:
        if self.simulate_market_data:
            return True
        if self._client is None:
            return False
        try:
            await self._client.cancel_order(order_id, symbol.paradex_market)
            return True
        except Exception:
            return False

    def _simulate_bbo(self, symbol: str, source: str) -> BBO:
        anchor = self._infer_anchor_mid(symbol)
        mid = self._sim_mid.get(symbol, anchor)

        # 使用“轻微随机 + 轻微均值回归”生成更稳定的模拟价格，避免随机游走长期漂移过大。
        drift = Decimal(str(random.uniform(-0.00005, 0.00005)))
        mid = mid * (Decimal("1") + drift)
        mid = mid + (anchor - mid) * Decimal("0.03")
        mid = max(Decimal("1"), mid)
        self._sim_mid[symbol] = mid

        spread = max(Decimal("0.5"), mid * Decimal("0.0002"))
        bid = mid - spread / Decimal("2")
        ask = mid + spread / Decimal("2")

        if source == "rest":
            # REST 与 WS 之间加入极小偏移，便于一致性逻辑被真实覆盖。
            bias = mid * Decimal("0.00002")
            bid -= bias
            ask -= bias

        return BBO(bid=bid, ask=ask, source=source)

    @staticmethod
    def _infer_anchor_mid(symbol: str) -> Decimal:
        """根据 symbol 粗略推断一个合理的“锚定价格”用于 dry-run 行情。"""
        normalized = symbol.upper()
        if normalized.startswith("BTC"):
            return Decimal("50000")
        if normalized.startswith("ETH"):
            return Decimal("2500")
        if normalized.startswith("SOL"):
            return Decimal("150")
        return Decimal("1000")
