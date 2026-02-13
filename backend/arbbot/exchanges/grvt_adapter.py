"""GRVT 交易所适配器。"""

from __future__ import annotations

import random
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from ..config import ExchangeConfig, SymbolConfig
from ..models import BBO, ExchangeName, OrderAck, OrderRequest, TradeSide, utc_iso
from .base import BaseExchangeAdapter

GRVT_ORDERBOOK_LIMIT = 10


class GrvtAdapter(BaseExchangeAdapter):
    """GRVT 适配器，支持 dry-run 与实盘两种模式。"""

    def __init__(self, config: ExchangeConfig, simulate_market_data: bool) -> None:
        super().__init__(name=ExchangeName.GRVT, simulate_market_data=simulate_market_data)
        self.config = config
        self._client = None
        self._symbols: dict[str, SymbolConfig] = {}
        self._sim_mid: dict[str, Decimal] = {}
        self._sim_pos: dict[str, Decimal] = {}

    async def connect(self, symbols: list[SymbolConfig]) -> None:
        self._symbols = {cfg.symbol: cfg for cfg in symbols}
        for cfg in symbols:
            anchor = self._infer_anchor_mid(cfg.symbol)
            # GRVT 给一个非常轻微的偏置（bps 级别），便于模拟真实两所之间的细微价差。
            self._sim_mid.setdefault(cfg.symbol, anchor * Decimal("1.00015"))
            self._sim_pos.setdefault(cfg.symbol, Decimal("0"))

        if self.simulate_market_data:
            return

        from pysdk.grvt_ccxt_env import GrvtEnv
        from pysdk.grvt_ccxt_pro import GrvtCcxtPro

        env_map = {
            "prod": GrvtEnv.PROD,
            "testnet": GrvtEnv.TESTNET,
            "staging": GrvtEnv.STAGING,
            "dev": GrvtEnv.DEV,
        }
        env = env_map.get(self.config.environment.lower(), GrvtEnv.PROD)

        params = {
            "trading_account_id": self.config.credentials.trading_account_id,
            "private_key": self.config.credentials.private_key,
            "api_key": self.config.credentials.api_key,
        }

        self._client = GrvtCcxtPro(env=env, parameters=params)
        await self._client.load_markets()
        if self.config.credentials.api_key:
            await self._client.refresh_cookie()

    async def disconnect(self) -> None:
        self._client = None

    async def health_check(self) -> bool:
        if self.simulate_market_data:
            return True
        if self._client is None:
            return False
        try:
            await self._client.fetch_markets()
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
            # GRVT depth 参数不接受 5，使用其支持的 10 以保证真实行情可用。
            depth = await self._client.fetch_order_book(symbol.grvt_market, limit=GRVT_ORDERBOOK_LIMIT)
            bid = self._extract_top_price(depth.get("bids", []))
            ask = self._extract_top_price(depth.get("asks", []))
            if bid is None or ask is None:
                return None
            bbo = BBO(
                bid=bid,
                ask=ask,
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
            depth = await self._client.fetch_order_book(symbol.grvt_market, limit=GRVT_ORDERBOOK_LIMIT)
            bid = self._extract_top_price(depth.get("bids", []))
            ask = self._extract_top_price(depth.get("asks", []))
            if bid is None or ask is None:
                return None
            return BBO(
                bid=bid,
                ask=ask,
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
            positions = await self._client.fetch_positions([symbol.grvt_market])
            for pos in positions:
                pos_symbol = str(pos.get("symbol") or pos.get("instrument") or "")
                if pos_symbol and pos_symbol != symbol.grvt_market:
                    continue
                qty = Decimal(str(pos.get("contracts") or pos.get("size") or pos.get("position") or 0))
                side = str(pos.get("side") or "").lower()
                if side == "short":
                    qty = -abs(qty)
                elif side == "long":
                    qty = abs(qty)
                return qty
            return Decimal("0")
        except Exception:
            return Decimal("0")

    async def fetch_balance_summary(self) -> dict[str, Any]:
        if self.simulate_market_data:
            return self._simulated_balance_summary()

        if self._client is None:
            return self._empty_balance_summary(source="unavailable")

        try:
            raw = await self._client.fetch_balance()
            return self._parse_balance_summary(raw, source="live")
        except Exception:
            return self._empty_balance_summary(source="error")

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
                order_id=f"grvt-{uuid.uuid4().hex[:12]}",
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
                message="GRVT 客户端未连接",
            )

        symbol_cfg = self._symbols.get(request.symbol)
        market = symbol_cfg.grvt_market if symbol_cfg else request.symbol

        try:
            created = await self._client.create_order(
                symbol=market,
                order_type=request.order_type,
                side=request.side.value,
                amount=request.quantity,
                price=request.price,
                params={
                    "post_only": request.post_only,
                    "reduce_only": request.reduce_only,
                },
            )
            order_id = str(created.get("id") or created.get("order_id") or "")
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
            await self._client.cancel_order(id=order_id, symbol=symbol.grvt_market)
            return True
        except Exception:
            return False

    def _simulated_balance_summary(self) -> dict[str, Any]:
        total_equity = Decimal("100000")
        notional = Decimal("0")
        for symbol, qty in self._sim_pos.items():
            mark = self._sim_mid.get(symbol) or self._infer_anchor_mid(symbol)
            notional += abs(qty) * mark
        margin_used = notional * Decimal("0.05")
        available = max(Decimal("0"), total_equity - margin_used)
        return {
            "available": True,
            "source": "simulated",
            "currency": "USDT",
            "total_equity": float(total_equity),
            "available_balance": float(available),
            "margin_used": float(margin_used),
            "updated_at": utc_iso(),
        }

    @staticmethod
    def _empty_balance_summary(source: str) -> dict[str, Any]:
        return {
            "available": False,
            "source": source,
            "currency": "USDT",
            "total_equity": 0.0,
            "available_balance": 0.0,
            "margin_used": 0.0,
            "updated_at": utc_iso(),
        }

    @staticmethod
    def _parse_balance_summary(raw: dict[str, Any], source: str) -> dict[str, Any]:
        preferred = ("USDT", "USDC", "USD")
        total_map = raw.get("total") if isinstance(raw.get("total"), dict) else {}
        free_map = raw.get("free") if isinstance(raw.get("free"), dict) else {}
        used_map = raw.get("used") if isinstance(raw.get("used"), dict) else {}

        def pick_amount(map_obj: dict[str, Any], currency: str) -> Decimal | None:
            value = map_obj.get(currency)
            if value is None:
                return None
            try:
                return Decimal(str(value))
            except Exception:
                return None

        currency = "USDT"
        total = Decimal("0")
        free = Decimal("0")
        used = Decimal("0")

        for candidate in preferred:
            candidate_total = pick_amount(total_map, candidate)
            candidate_free = pick_amount(free_map, candidate)
            candidate_used = pick_amount(used_map, candidate)
            if candidate_total is not None or candidate_free is not None or candidate_used is not None:
                currency = candidate
                total = candidate_total or Decimal("0")
                free = candidate_free or Decimal("0")
                used = candidate_used or Decimal("0")
                break

        if total <= 0 and free > 0 and used > 0:
            total = free + used
        if total <= 0 and free > 0:
            total = free
        if free <= 0 and total > 0 and used >= 0:
            free = max(Decimal("0"), total - used)

        return {
            "available": True,
            "source": source,
            "currency": currency,
            "total_equity": float(total),
            "available_balance": float(free),
            "margin_used": float(max(Decimal("0"), used)),
            "updated_at": utc_iso(),
        }

    def _simulate_bbo(self, symbol: str, source: str) -> BBO:
        anchor = self._infer_anchor_mid(symbol) * Decimal("1.00015")
        mid = self._sim_mid.get(symbol, anchor)

        # 使用“轻微随机 + 轻微均值回归”生成更稳定的模拟价格，避免随机游走长期漂移过大。
        drift = Decimal(str(random.uniform(-0.00005, 0.00005)))
        mid = mid * (Decimal("1") + drift)
        mid = mid + (anchor - mid) * Decimal("0.03")
        mid = max(Decimal("1"), mid)
        self._sim_mid[symbol] = mid

        spread = max(Decimal("0.5"), mid * Decimal("0.00022"))
        bid = mid - spread / Decimal("2")
        ask = mid + spread / Decimal("2")

        if source == "rest":
            bias = mid * Decimal("0.00002")
            bid += bias
            ask += bias

        return BBO(bid=bid, ask=ask, source=source)

    @staticmethod
    def _extract_top_price(levels: object) -> Decimal | None:
        if not isinstance(levels, list) or not levels:
            return None
        top = levels[0]
        if isinstance(top, dict):
            price = top.get("price")
            if price is None:
                return None
            return Decimal(str(price))
        if isinstance(top, Sequence) and not isinstance(top, (str, bytes)) and len(top) > 0:
            return Decimal(str(top[0]))
        return None

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
