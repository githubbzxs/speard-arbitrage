"""交易执行引擎。"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable

from ..config import StrategyConfig, SymbolConfig
from ..models import (
    ArbitrageDirection,
    ExecutionReport,
    ExchangeName,
    OrderAck,
    OrderRequest,
    SignalAction,
    SpreadSignal,
    TradeFill,
    TradeSide,
)
from ..risk.rate_limiter import RateLimiter
from .position_manager import PositionManager


class ExecutionEngine:
    """执行开平仓、再平衡与强平动作。"""

    def __init__(
        self,
        adapters: dict[ExchangeName, object],
        rate_limiter: RateLimiter,
        position_manager: PositionManager,
        strategy_cfg: StrategyConfig,
        live_order_enabled: bool,
        on_fill: Callable[[TradeFill], None] | None = None,
    ) -> None:
        self.adapters = adapters
        self.rate_limiter = rate_limiter
        self.position_manager = position_manager
        self.strategy_cfg = strategy_cfg
        self.live_order_enabled = live_order_enabled
        self._on_fill = on_fill

    def set_live_order_enabled(self, enabled: bool) -> None:
        """动态切换真实下单开关。"""
        self.live_order_enabled = enabled

    async def execute_signal(
        self,
        symbol_cfg: SymbolConfig,
        signal: SpreadSignal,
        paradex_bid: Decimal,
        paradex_ask: Decimal,
        grvt_bid: Decimal,
        grvt_ask: Decimal,
        can_open: bool,
    ) -> ExecutionReport:
        """执行策略信号。"""
        if signal.action in {SignalAction.OPEN, SignalAction.CLOSE} and not self.live_order_enabled:
            return self._order_blocked_report(signal, "真实下单已禁用，仅执行行情监控")

        if signal.action == SignalAction.HOLD:
            return ExecutionReport(
                signal=signal,
                attempted_orders=0,
                success_orders=0,
                failed_orders=0,
                message=signal.reason,
            )

        if signal.action == SignalAction.OPEN and not can_open:
            return ExecutionReport(
                signal=signal,
                attempted_orders=0,
                success_orders=0,
                failed_orders=1,
                message="风控禁止开仓",
            )

        if signal.action == SignalAction.OPEN and not self.position_manager.can_open(
            symbol_cfg.symbol,
            self.strategy_cfg.max_position,
        ):
            return ExecutionReport(
                signal=signal,
                attempted_orders=0,
                success_orders=0,
                failed_orders=1,
                message="达到最大仓位限制",
            )

        if signal.action == SignalAction.OPEN:
            return await self._open_batches(
                symbol_cfg,
                signal,
                paradex_bid,
                paradex_ask,
                grvt_bid,
                grvt_ask,
            )

        if signal.action == SignalAction.CLOSE:
            return await self._close_position(symbol_cfg, signal)

        return ExecutionReport(
            signal=signal,
            attempted_orders=0,
            success_orders=0,
            failed_orders=1,
            message="未知信号动作",
        )

    async def execute_rebalance(self, symbol_cfg: SymbolConfig, orders: list[OrderRequest]) -> ExecutionReport:
        """执行再平衡订单。"""
        fake_signal = SpreadSignal(
            action=SignalAction.REBALANCE,
            direction=None,
            edge_bps=Decimal("0"),
            zscore=Decimal("0"),
            threshold_bps=Decimal("0"),
            reason="仓位再平衡",
            batches=[x.quantity for x in orders],
        )
        if not self.live_order_enabled:
            return self._order_blocked_report(fake_signal, "真实下单已禁用，再平衡仅记录未执行")

        attempted = 0
        success = 0
        failed = 0
        order_ids: list[str] = []

        for req in orders:
            attempted += 1
            ack = await self._submit(req)
            if ack.success and ack.filled_quantity > 0:
                success += 1
                order_ids.append(ack.order_id)
                self._record_fill(
                    TradeFill(
                        exchange=ack.exchange,
                        symbol=symbol_cfg.symbol,
                        side=ack.side,
                        quantity=ack.filled_quantity,
                        price=ack.avg_price or Decimal("0"),
                        order_id=ack.order_id,
                        tag="rebalance",
                    )
                )
            else:
                failed += 1

        return ExecutionReport(
            signal=fake_signal,
            attempted_orders=attempted,
            success_orders=success,
            failed_orders=failed,
            message="再平衡完成",
            order_ids=order_ids,
        )

    async def flatten_symbol(self, symbol_cfg: SymbolConfig) -> ExecutionReport:
        """强制将标的双边仓位降为 0。"""
        if not self.live_order_enabled:
            blocked_signal = SpreadSignal(
                action=SignalAction.REBALANCE,
                direction=None,
                edge_bps=Decimal("0"),
                zscore=Decimal("0"),
                threshold_bps=Decimal("0"),
                reason="真实下单已禁用",
                batches=[],
            )
            return self._order_blocked_report(blocked_signal, "真实下单已禁用，一键平仓未执行")

        state = self.position_manager.get_state(symbol_cfg.symbol)
        requests: list[OrderRequest] = []

        if state.paradex > 0:
            requests.append(
                OrderRequest(
                    exchange=ExchangeName.PARADEX,
                    symbol=symbol_cfg.symbol,
                    side=TradeSide.SELL,
                    quantity=abs(state.paradex),
                    order_type="market",
                    reduce_only=True,
                    tag="flatten",
                )
            )
        elif state.paradex < 0:
            requests.append(
                OrderRequest(
                    exchange=ExchangeName.PARADEX,
                    symbol=symbol_cfg.symbol,
                    side=TradeSide.BUY,
                    quantity=abs(state.paradex),
                    order_type="market",
                    reduce_only=True,
                    tag="flatten",
                )
            )

        if state.grvt > 0:
            requests.append(
                OrderRequest(
                    exchange=ExchangeName.GRVT,
                    symbol=symbol_cfg.symbol,
                    side=TradeSide.SELL,
                    quantity=abs(state.grvt),
                    order_type="market",
                    reduce_only=True,
                    tag="flatten",
                )
            )
        elif state.grvt < 0:
            requests.append(
                OrderRequest(
                    exchange=ExchangeName.GRVT,
                    symbol=symbol_cfg.symbol,
                    side=TradeSide.BUY,
                    quantity=abs(state.grvt),
                    order_type="market",
                    reduce_only=True,
                    tag="flatten",
                )
            )

        return await self.execute_rebalance(symbol_cfg, requests)

    async def _open_batches(
        self,
        symbol_cfg: SymbolConfig,
        signal: SpreadSignal,
        paradex_bid: Decimal,
        paradex_ask: Decimal,
        grvt_bid: Decimal,
        grvt_ask: Decimal,
    ) -> ExecutionReport:
        attempted = 0
        success = 0
        failed = 0
        order_ids: list[str] = []

        paradex_taker_side, hedge_side = self._resolve_sides(signal.direction)
        fallback_price = paradex_ask if paradex_taker_side == TradeSide.BUY else paradex_bid

        for qty in signal.batches:
            paradex_req = OrderRequest(
                exchange=ExchangeName.PARADEX,
                symbol=symbol_cfg.symbol,
                side=paradex_taker_side,
                quantity=qty,
                order_type="market",
                reduce_only=False,
                tag="open-taker",
            )
            attempted += 1
            paradex_ack = await self._submit(paradex_req)
            if not paradex_ack.success or paradex_ack.filled_quantity <= 0:
                failed += 1
                continue

            success += 1
            order_ids.append(paradex_ack.order_id)
            self._record_fill(
                TradeFill(
                    exchange=paradex_ack.exchange,
                    symbol=symbol_cfg.symbol,
                    side=paradex_ack.side,
                    quantity=paradex_ack.filled_quantity,
                    price=paradex_ack.avg_price or fallback_price,
                    order_id=paradex_ack.order_id,
                    tag="open-taker",
                )
            )

            hedge_qty = paradex_ack.filled_quantity
            hedge_maker_price = grvt_bid if hedge_side == TradeSide.BUY else grvt_ask
            hedge_req = OrderRequest(
                exchange=ExchangeName.GRVT,
                symbol=symbol_cfg.symbol,
                side=hedge_side,
                quantity=hedge_qty,
                order_type="limit",
                price=hedge_maker_price,
                post_only=True,
                reduce_only=False,
                tag="open-hedge",
            )
            attempted += 1
            hedge_ack = await self._submit(hedge_req)
            if not hedge_ack.success or hedge_ack.filled_quantity <= 0:
                failed += 1
                continue

            success += 1
            order_ids.append(hedge_ack.order_id)
            self._record_fill(
                TradeFill(
                    exchange=hedge_ack.exchange,
                    symbol=symbol_cfg.symbol,
                    side=hedge_ack.side,
                    quantity=hedge_ack.filled_quantity,
                    price=hedge_ack.avg_price or hedge_maker_price,
                    order_id=hedge_ack.order_id,
                    tag="open-hedge",
                )
            )

        return ExecutionReport(
            signal=signal,
            attempted_orders=attempted,
            success_orders=success,
            failed_orders=failed,
            message="开仓执行完成",
            order_ids=order_ids,
        )

    async def _close_position(self, symbol_cfg: SymbolConfig, signal: SpreadSignal) -> ExecutionReport:
        state = self.position_manager.get_state(symbol_cfg.symbol)
        close_qty = sum(signal.batches) if signal.batches else self.strategy_cfg.base_order_qty

        requests: list[OrderRequest] = []
        if state.paradex > 0:
            requests.append(
                OrderRequest(
                    exchange=ExchangeName.PARADEX,
                    symbol=symbol_cfg.symbol,
                    side=TradeSide.SELL,
                    quantity=min(abs(state.paradex), close_qty),
                    order_type="market",
                    reduce_only=True,
                    tag="close",
                )
            )
        elif state.paradex < 0:
            requests.append(
                OrderRequest(
                    exchange=ExchangeName.PARADEX,
                    symbol=symbol_cfg.symbol,
                    side=TradeSide.BUY,
                    quantity=min(abs(state.paradex), close_qty),
                    order_type="market",
                    reduce_only=True,
                    tag="close",
                )
            )

        if state.grvt > 0:
            requests.append(
                OrderRequest(
                    exchange=ExchangeName.GRVT,
                    symbol=symbol_cfg.symbol,
                    side=TradeSide.SELL,
                    quantity=min(abs(state.grvt), close_qty),
                    order_type="market",
                    reduce_only=True,
                    tag="close",
                )
            )
        elif state.grvt < 0:
            requests.append(
                OrderRequest(
                    exchange=ExchangeName.GRVT,
                    symbol=symbol_cfg.symbol,
                    side=TradeSide.BUY,
                    quantity=min(abs(state.grvt), close_qty),
                    order_type="market",
                    reduce_only=True,
                    tag="close",
                )
            )

        return await self.execute_rebalance(symbol_cfg, requests)

    def _resolve_sides(self, direction: ArbitrageDirection | None) -> tuple[TradeSide, TradeSide]:
        if direction == ArbitrageDirection.LONG_GRVT_SHORT_PARA:
            return TradeSide.SELL, TradeSide.BUY
        return TradeSide.BUY, TradeSide.SELL

    async def _submit(self, request: OrderRequest) -> OrderAck:
        allowed = await self.rate_limiter.acquire(request.exchange.value, "order", timeout=0.8)
        if not allowed:
            return OrderAck(
                success=False,
                exchange=request.exchange,
                order_id="",
                side=request.side,
                requested_quantity=request.quantity,
                filled_quantity=Decimal("0"),
                message="触发限流",
            )

        adapter = self.adapters[request.exchange]
        ack = await adapter.place_order(request)

        if ack.success and ack.filled_quantity <= 0 and request.order_type == "market":
            ack.filled_quantity = request.quantity

        return ack

    def _record_fill(self, fill: TradeFill) -> None:
        self.position_manager.apply_fill(fill)
        if self._on_fill is None:
            return
        try:
            self._on_fill(fill)
        except Exception:
            # 成交回调失败不影响主交易流程，避免因统计异常阻塞执行。
            return

    @staticmethod
    def _order_blocked_report(signal: SpreadSignal, message: str) -> ExecutionReport:
        return ExecutionReport(
            signal=signal,
            attempted_orders=0,
            success_orders=0,
            failed_orders=0,
            message=message,
            order_ids=[],
        )
