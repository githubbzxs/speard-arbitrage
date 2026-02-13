"""套利编排器。"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from decimal import Decimal
from typing import Any

from ..config import AppConfig, SymbolConfig
from ..exchanges import GrvtAdapter, ParadexAdapter
from ..models import (
    EngineStatus,
    EventLevel,
    EventRecord,
    OrderRequest,
    RiskState,
    SignalAction,
    SpreadMetrics,
    SpreadSignal,
    StrategyMode,
    SymbolSnapshot,
    TradeSide,
    utc_iso,
)
from ..risk import ConsistencyGuard, HealthGuard, RateLimiter, WsSupervisor
from ..storage import CsvLogger, Repository
from .execution_engine import ExecutionEngine
from .modes import ModeController
from .order_book_manager import OrderBookManager
from .position_manager import PositionManager
from .spread_engine import SpreadEngine


class ArbitrageOrchestrator:
    """统筹交易、风控、状态广播。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

        self.paradex = ParadexAdapter(
            config.paradex,
            simulate_market_data=config.runtime.simulated_market_data,
        )
        self.grvt = GrvtAdapter(
            config.grvt,
            simulate_market_data=config.runtime.simulated_market_data,
        )
        self.adapters = {
            self.paradex.name: self.paradex,
            self.grvt.name: self.grvt,
        }

        self.rate_limiter = RateLimiter()
        for exchange_name, scopes in config.rate_limits.items():
            for scope_name, (rate, cap) in scopes.items():
                self.rate_limiter.register(exchange_name, scope_name, rate, cap)

        self.order_books = OrderBookManager()
        self.spread_engine = SpreadEngine(config.strategy)
        self.position_manager = PositionManager()
        self.mode_controller = ModeController(config.runtime.default_mode)

        self.health_guard = HealthGuard(
            fail_threshold=config.risk.health_fail_threshold,
            cache_ms=config.risk.health_cache_ms,
        )
        self.consistency_guard = ConsistencyGuard(
            tolerance_bps=config.risk.consistency_tolerance_bps,
            max_failures=config.risk.consistency_max_failures,
        )
        self.ws_supervisor = WsSupervisor(config.risk.ws_idle_timeout_sec)

        self.execution_engine = ExecutionEngine(
            adapters=self.adapters,
            rate_limiter=self.rate_limiter,
            position_manager=self.position_manager,
            strategy_cfg=config.strategy,
            live_order_enabled=config.runtime.live_order_enabled,
        )

        self.repository = Repository(config.storage.sqlite_path)
        self.csv_logger = CsvLogger(config.storage.csv_dir)

        self.engine_status = EngineStatus.STOPPED
        self.started_at = ""

        self._consistency_ok: dict[str, bool] = {}
        self._symbol_snapshots: dict[str, SymbolSnapshot] = {}
        self._event_memory: deque[dict[str, Any]] = deque(maxlen=500)

        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._status_lock = asyncio.Lock()

        self._ws_queues: set[asyncio.Queue] = set()

    async def start(self) -> bool:
        """启动引擎。"""
        async with self._status_lock:
            if self.engine_status in {EngineStatus.STARTING, EngineStatus.RUNNING}:
                return False
            self.engine_status = EngineStatus.STARTING

            try:
                if self.config.runtime.simulated_market_data and self.config.runtime.live_order_enabled:
                    self.engine_status = EngineStatus.STOPPED
                    await self._emit_event(
                        EventLevel.ERROR,
                        "engine",
                        "模拟行情模式下禁止启用真实下单，请先切换到真实行情",
                    )
                    return False

                symbols = [cfg for cfg in self.config.symbols if cfg.enabled]
                await asyncio.gather(self.paradex.connect(symbols), self.grvt.connect(symbols))
                self.ws_supervisor.mark_connected("paradex")
                self.ws_supervisor.mark_connected("grvt")

                self._stop_event.clear()
                self._tasks = [
                    asyncio.create_task(self._run_symbol_loop(symbol_cfg), name=f"symbol-loop-{symbol_cfg.symbol}")
                    for symbol_cfg in symbols
                ]

                self.engine_status = EngineStatus.RUNNING
                self.started_at = utc_iso()
                await self._emit_event(EventLevel.INFO, "engine", "套利引擎已启动")
                return True
            except Exception as exc:
                self.engine_status = EngineStatus.ERROR
                await self._emit_event(EventLevel.ERROR, "engine", f"启动失败: {exc}")
                return False

    async def stop(self) -> bool:
        """停止引擎。"""
        async with self._status_lock:
            if self.engine_status in {EngineStatus.STOPPED, EngineStatus.STOPPING}:
                return False

            self.engine_status = EngineStatus.STOPPING
            self._stop_event.set()

            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

            await asyncio.gather(self.paradex.disconnect(), self.grvt.disconnect())

            self.engine_status = EngineStatus.STOPPED
            await self._emit_event(EventLevel.INFO, "engine", "套利引擎已停止")
            return True

    async def shutdown(self) -> None:
        """进程退出时关闭资源。"""
        if self.engine_status != EngineStatus.STOPPED:
            await self.stop()
        self.repository.close()

    async def _run_symbol_loop(self, symbol_cfg: SymbolConfig) -> None:
        symbol = symbol_cfg.symbol
        last_rest_ms = 0
        last_position_sync_ms = 0
        last_aggregate_push_ms = 0

        while not self._stop_event.is_set():
            loop_start = time.monotonic()
            try:
                paradex_ws = await self.paradex.fetch_bbo(symbol_cfg)
                grvt_ws = await self.grvt.fetch_bbo(symbol_cfg)

                if paradex_ws is not None:
                    self.order_books.update_ws(self.paradex.name, symbol, paradex_ws)
                    self.ws_supervisor.mark_message("paradex")
                else:
                    self.ws_supervisor.mark_disconnected("paradex")

                if grvt_ws is not None:
                    self.order_books.update_ws(self.grvt.name, symbol, grvt_ws)
                    self.ws_supervisor.mark_message("grvt")
                else:
                    self.ws_supervisor.mark_disconnected("grvt")

                now_ms = int(time.time() * 1000)

                if now_ms - last_rest_ms >= self.config.strategy.rest_consistency_ms:
                    last_rest_ms = now_ms
                    paradex_rest = await self.paradex.fetch_rest_bbo(symbol_cfg)
                    grvt_rest = await self.grvt.fetch_rest_bbo(symbol_cfg)
                    if paradex_rest is not None:
                        self.order_books.update_rest(self.paradex.name, symbol, paradex_rest)
                    if grvt_rest is not None:
                        self.order_books.update_rest(self.grvt.name, symbol, grvt_rest)

                    pd_ws, gr_ws = self.order_books.get_ws_pair(symbol)
                    pd_rest, gr_rest = self.order_books.get_rest_pair(symbol)
                    self._consistency_ok[symbol] = self.consistency_guard.check(
                        symbol,
                        pd_ws,
                        pd_rest,
                        gr_ws,
                        gr_rest,
                    )

                if self.health_guard.should_check("paradex"):
                    pd_ok = await self.paradex.health_check()
                    self.health_guard.update("paradex", pd_ok, "ok" if pd_ok else "health_check 失败")

                if self.health_guard.should_check("grvt"):
                    gr_ok = await self.grvt.health_check()
                    self.health_guard.update("grvt", gr_ok, "ok" if gr_ok else "health_check 失败")

                if now_ms - last_position_sync_ms >= self.config.strategy.position_sync_ms:
                    last_position_sync_ms = now_ms
                    paradex_pos = await self.paradex.fetch_position(symbol_cfg)
                    grvt_pos = await self.grvt.fetch_position(symbol_cfg)
                    self.position_manager.set_positions(symbol, paradex_pos, grvt_pos)

                stale = self.order_books.is_stale(symbol, self.config.risk.stale_ms)
                ws_ok = self.ws_supervisor.is_ok()
                consistency_ok = self._consistency_ok.get(symbol, False)
                health_ok = self.health_guard.can_open()

                net_guard = self.config.strategy.base_order_qty * self.config.risk.net_pos_guard_multiplier
                hard_limit = self.config.strategy.base_order_qty * self.config.risk.hard_net_limit_multiplier

                if self.position_manager.is_hard_limit_breached(symbol, hard_limit):
                    await self._emit_event(
                        EventLevel.WARN,
                        symbol,
                        "触发硬净仓上限，执行强制减仓",
                    )
                    await self.execution_engine.flatten_symbol(symbol_cfg)

                can_open = (not stale) and ws_ok and consistency_ok and health_ok

                paradex_eff, grvt_eff = self.order_books.get_effective_pair(symbol)
                if paradex_eff is None or grvt_eff is None or not paradex_eff.valid or not grvt_eff.valid:
                    signal = SpreadSignal(
                        action=SignalAction.HOLD,
                        direction=None,
                        edge_bps=Decimal("0"),
                        zscore=Decimal("0"),
                        threshold_bps=self.config.strategy.min_edge_bps,
                        reason="盘口不可用",
                        batches=[],
                    )
                    metrics = SpreadMetrics(
                        symbol=symbol,
                        edge_para_to_grvt_price=Decimal("0"),
                        edge_grvt_to_para_price=Decimal("0"),
                        edge_para_to_grvt_bps=Decimal("0"),
                        edge_grvt_to_para_bps=Decimal("0"),
                        signed_edge_bps=Decimal("0"),
                        signed_edge_price=Decimal("0"),
                        ma=Decimal("0"),
                        std=Decimal("0"),
                        zscore=Decimal("0"),
                    )
                else:
                    metrics = self.spread_engine.compute_metrics(symbol, paradex_eff, grvt_eff)
                    signal = self.spread_engine.generate_signal(metrics, self.mode_controller.mode)

                if self.position_manager.is_imbalanced(symbol, net_guard):
                    rebalance_ops = self.position_manager.build_rebalance_orders(
                        symbol=symbol,
                        tolerance=net_guard,
                        base_qty=self.config.strategy.base_order_qty,
                    )
                    requests = [
                        OrderRequest(
                            exchange=item.exchange,
                            symbol=item.symbol,
                            side=item.side,
                            quantity=item.quantity,
                            order_type="market",
                            reduce_only=True,
                            tag="rebalance",
                        )
                        for item in rebalance_ops
                    ]
                    if requests:
                        report = await self.execution_engine.execute_rebalance(symbol_cfg, requests)
                        await self._emit_event(
                            EventLevel.INFO,
                            symbol,
                            "执行仓位再平衡",
                            data=report.to_dict(),
                        )

                report = await self.execution_engine.execute_signal(
                    symbol_cfg=symbol_cfg,
                    signal=signal,
                    paradex_bid=paradex_eff.bid if paradex_eff else Decimal("0"),
                    paradex_ask=paradex_eff.ask if paradex_eff else Decimal("0"),
                    grvt_bid=grvt_eff.bid if grvt_eff else Decimal("0"),
                    grvt_ask=grvt_eff.ask if grvt_eff else Decimal("0"),
                    can_open=can_open,
                )
                if report.attempted_orders > 0:
                    level = EventLevel.WARN if report.failed_orders > 0 else EventLevel.INFO
                    await self._emit_event(level, symbol, report.message, data=report.to_dict())

                state = self.position_manager.get_state(symbol)
                risk_state = RiskState(
                    stale=stale,
                    consistency_ok=consistency_ok,
                    health_ok=health_ok,
                    ws_ok=ws_ok,
                    can_open=can_open,
                    reason=signal.reason,
                )
                paradex_bid = paradex_eff.bid if paradex_eff else Decimal("0")
                paradex_ask = paradex_eff.ask if paradex_eff else Decimal("0")
                grvt_bid = grvt_eff.bid if grvt_eff else Decimal("0")
                grvt_ask = grvt_eff.ask if grvt_eff else Decimal("0")
                snapshot = SymbolSnapshot(
                    symbol=symbol,
                    status=self.engine_status.value,
                    signal=signal.action.value,
                    paradex_bid=paradex_bid,
                    paradex_ask=paradex_ask,
                    paradex_mid=(paradex_bid + paradex_ask) / Decimal("2")
                    if paradex_bid > 0 and paradex_ask > 0
                    else Decimal("0"),
                    grvt_bid=grvt_bid,
                    grvt_ask=grvt_ask,
                    grvt_mid=(grvt_bid + grvt_ask) / Decimal("2")
                    if grvt_bid > 0 and grvt_ask > 0
                    else Decimal("0"),
                    spread_bps=metrics.signed_edge_bps,
                    spread_price=metrics.signed_edge_price,
                    zscore=metrics.zscore,
                    net_position=state.net_exposure,
                    target_position=state.target_net,
                    paradex_position=state.paradex,
                    grvt_position=state.grvt,
                    updated_at=utc_iso(),
                    risk=risk_state,
                )
                self._symbol_snapshots[symbol] = snapshot
                self.repository.add_symbol_snapshot(snapshot)
                self.csv_logger.log_snapshot(snapshot)

                await self._broadcast({"type": "symbol", "data": snapshot.to_dict()})

                if now_ms - last_aggregate_push_ms >= 1000:
                    last_aggregate_push_ms = now_ms
                    await self._broadcast(
                        {
                            "type": "snapshot",
                            "data": {
                                "status": await self.get_status(),
                                "symbols": self.get_symbols(),
                            },
                        }
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                await self._emit_event(EventLevel.ERROR, symbol, f"symbol loop 异常: {exc}")

            elapsed_ms = int((time.monotonic() - loop_start) * 1000)
            sleep_ms = max(10, self.config.strategy.loop_interval_ms - elapsed_ms)
            await asyncio.sleep(sleep_ms / 1000)

    async def _emit_event(
        self,
        level: EventLevel,
        source: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        event = EventRecord(
            id=uuid.uuid4().hex,
            ts=utc_iso(),
            level=level,
            source=source,
            message=message,
            data=data or {},
        )
        payload = event.to_dict()
        self._event_memory.appendleft(payload)
        self.repository.add_event(event)
        self.csv_logger.log_event(event)
        await self._broadcast({"type": "event", "data": payload})

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        for queue in list(self._ws_queues):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(payload)
                except Exception:
                    pass

    def register_ws_queue(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._ws_queues.add(queue)
        return queue

    def unregister_ws_queue(self, queue: asyncio.Queue) -> None:
        self._ws_queues.discard(queue)

    async def get_status(self) -> dict[str, Any]:
        active_symbols = len(self._symbol_snapshots)
        consistency_ok_count = sum(1 for ok in self._consistency_ok.values() if ok)
        bucket_stats = await self.rate_limiter.snapshot()
        net_exposure = sum(snapshot.net_position for snapshot in self._symbol_snapshots.values())

        normal_count = 0
        warning_count = 0
        critical_count = 0
        for snapshot in self._symbol_snapshots.values():
            risk = snapshot.risk
            if not risk.ws_ok or not risk.health_ok:
                critical_count += 1
            elif not risk.consistency_ok or risk.stale:
                warning_count += 1
            else:
                normal_count += 1

        return {
            "engine_status": self.engine_status.value,
            "mode": self.mode_controller.mode.value,
            "runtime": {
                "simulated_market_data": self.config.runtime.simulated_market_data,
                "live_order_enabled": self.config.runtime.live_order_enabled,
            },
            "active_symbols": active_symbols,
            "consistency_ok_count": consistency_ok_count,
            "ws_ok": self.ws_supervisor.is_ok(),
            "health_ok": self.health_guard.can_open(),
            "net_exposure": float(net_exposure),
            "daily_volume": 0.0,
            "risk_counts": {
                "normal": normal_count,
                "warning": warning_count,
                "critical": critical_count,
            },
            "started_at": self.started_at,
            "updated_at": utc_iso(),
            "rate_limit": {
                ex: {
                    scope: {
                        "rate_per_sec": item.rate_per_sec,
                        "capacity": item.capacity,
                        "tokens": round(item.tokens, 2),
                    }
                    for scope, item in scopes.items()
                }
                for ex, scopes in bucket_stats.items()
            },
        }

    def get_symbols(self) -> list[dict[str, Any]]:
        if not self._symbol_snapshots:
            return self.repository.latest_symbol_snapshots()
        return [snapshot.to_dict() for _, snapshot in sorted(self._symbol_snapshots.items())]

    def get_events(self, limit: int = 100) -> list[dict[str, Any]]:
        in_memory = list(self._event_memory)[:limit]
        if len(in_memory) >= limit:
            return in_memory
        from_db = self.repository.list_events(limit=limit)
        if not in_memory:
            return from_db
        seen = {item["id"] for item in in_memory}
        merged = in_memory + [item for item in from_db if item["id"] not in seen]
        return merged[:limit]

    async def apply_credentials(self, credentials: dict[str, dict[str, str]]) -> dict[str, Any]:
        """将网页保存的凭证应用到运行时配置（仅允许在引擎停止时执行）。"""

        def apply_fields(exchange: str, fields: tuple[str, ...]) -> list[str]:
            payload = credentials.get(exchange)
            if not isinstance(payload, dict):
                return []

            applied: list[str] = []
            target = (
                self.config.paradex.credentials
                if exchange == "paradex"
                else self.config.grvt.credentials
            )

            for field in fields:
                raw_value = payload.get(field)
                if not isinstance(raw_value, str):
                    continue
                value = raw_value.strip()
                if not value:
                    continue
                setattr(target, field, value)
                applied.append(field)

            return applied

        async with self._status_lock:
            if self.engine_status != EngineStatus.STOPPED:
                return {
                    "ok": False,
                    "message": "引擎运行中，请先停止引擎再应用凭证",
                    "data": {"engine_status": self.engine_status.value},
                }

            applied_fields = {
                "paradex": apply_fields("paradex", ("l2_private_key", "l2_address")),
                "grvt": apply_fields("grvt", ("private_key", "trading_account_id", "api_key", "api_secret")),
            }

            if not applied_fields["paradex"] and not applied_fields["grvt"]:
                return {
                    "ok": False,
                    "message": "没有可应用的凭证，请先保存凭证",
                    "data": {"applied_fields": applied_fields},
                }

            missing_fields: list[str] = []
            if self.config.runtime.live_order_enabled:
                if not self.config.paradex.credentials.l2_private_key.strip():
                    missing_fields.append("paradex.l2_private_key")
                if not self.config.paradex.credentials.l2_address.strip():
                    missing_fields.append("paradex.l2_address")
                if not self.config.grvt.credentials.private_key.strip():
                    missing_fields.append("grvt.private_key")
                if not self.config.grvt.credentials.trading_account_id.strip():
                    missing_fields.append("grvt.trading_account_id")

            if missing_fields:
                message = f"凭证已应用，但仍缺少必填字段：{', '.join(missing_fields)}"
                await self._emit_event(
                    EventLevel.WARN,
                    "config",
                    message,
                    data={"applied_fields": applied_fields, "missing_fields": missing_fields},
                )
                return {
                    "ok": False,
                    "message": message,
                    "data": {"applied_fields": applied_fields, "missing_fields": missing_fields},
                }

            message = "凭证已应用到运行时配置（引擎已停止），现在可以启动引擎"
            await self._emit_event(
                EventLevel.INFO,
                "config",
                message,
                data={"applied_fields": applied_fields},
            )
            return {
                "ok": True,
                "message": message,
                "data": {"applied_fields": applied_fields},
            }

    async def set_mode(self, mode: str) -> None:
        if mode == "zero_wear":
            self.mode_controller.set_mode(StrategyMode.ZERO_WEAR)
        else:
            self.mode_controller.set_mode(StrategyMode.NORMAL_ARB)
        await self._emit_event(EventLevel.INFO, "engine", f"切换模式为 {self.mode_controller.mode.value}")

    async def set_live_order_enabled(self, enabled: bool) -> dict[str, Any]:
        """切换真实下单开关。"""
        async with self._status_lock:
            current = self.config.runtime.live_order_enabled
            if enabled == current:
                return {
                    "ok": True,
                    "message": "真实下单开关未变化",
                    "data": {
                        "live_order_enabled": current,
                        "engine_status": self.engine_status.value,
                    },
                }

            if enabled and self.config.runtime.simulated_market_data:
                return {
                    "ok": False,
                    "message": "当前为模拟行情，禁止开启真实下单",
                    "data": {
                        "simulated_market_data": self.config.runtime.simulated_market_data,
                        "live_order_enabled": current,
                    },
                }

            if enabled and self.engine_status != EngineStatus.STOPPED:
                return {
                    "ok": False,
                    "message": "引擎运行中仅允许关闭下单，请先停止引擎再开启真实下单",
                    "data": {"engine_status": self.engine_status.value},
                }

            self.config.runtime.live_order_enabled = enabled
            self.execution_engine.set_live_order_enabled(enabled)

            if enabled:
                level = EventLevel.WARN
                message = "已开启真实下单，请确认仓位与风控参数"
            else:
                level = EventLevel.INFO
                message = "已关闭真实下单"

            await self._emit_event(
                level,
                "runtime",
                message,
                data={
                    "live_order_enabled": self.config.runtime.live_order_enabled,
                    "simulated_market_data": self.config.runtime.simulated_market_data,
                },
            )

            return {
                "ok": True,
                "message": message,
                "data": {
                    "live_order_enabled": self.config.runtime.live_order_enabled,
                    "simulated_market_data": self.config.runtime.simulated_market_data,
                    "engine_status": self.engine_status.value,
                },
            }

    async def set_simulated_market_data(self, enabled: bool) -> dict[str, Any]:
        """切换模拟行情开关（需引擎停止）。"""
        async with self._status_lock:
            if self.engine_status != EngineStatus.STOPPED:
                return {
                    "ok": False,
                    "message": "切换行情模式前请先停止引擎",
                    "data": {"engine_status": self.engine_status.value},
                }

            current = self.config.runtime.simulated_market_data
            forced_order_disabled = False

            self.config.runtime.simulated_market_data = enabled
            self.paradex.simulate_market_data = enabled
            self.paradex.dry_run = enabled
            self.grvt.simulate_market_data = enabled
            self.grvt.dry_run = enabled

            if enabled and self.config.runtime.live_order_enabled:
                self.config.runtime.live_order_enabled = False
                self.execution_engine.set_live_order_enabled(False)
                forced_order_disabled = True

            mode_label = "模拟行情" if enabled else "真实行情"
            message = f"已切换为{mode_label}"
            if forced_order_disabled:
                message = f"{message}，并自动关闭真实下单"

            await self._emit_event(
                EventLevel.INFO,
                "runtime",
                message,
                data={
                    "simulated_market_data": self.config.runtime.simulated_market_data,
                    "live_order_enabled": self.config.runtime.live_order_enabled,
                    "previous_simulated_market_data": current,
                    "forced_order_disabled": forced_order_disabled,
                },
            )

            return {
                "ok": True,
                "message": message,
                "data": {
                    "simulated_market_data": self.config.runtime.simulated_market_data,
                    "live_order_enabled": self.config.runtime.live_order_enabled,
                    "forced_order_disabled": forced_order_disabled,
                },
            }

    async def update_symbol_params(self, symbol: str, params: dict[str, Any]) -> dict[str, Any]:
        allowed_decimal = {
            "z_entry": "z_entry",
            "z_exit": "z_exit",
            "z_zero_entry": "z_zero_entry",
            "z_zero_exit": "z_zero_exit",
            "base_order_qty": "base_order_qty",
            "max_batch_qty": "max_batch_qty",
            "max_position": "max_position",
            "min_edge_bps": "min_edge_bps",
        }
        for key, attr in allowed_decimal.items():
            if key in params:
                setattr(self.config.strategy, attr, Decimal(str(params[key])))

        if "loop_interval_ms" in params:
            self.config.strategy.loop_interval_ms = int(params["loop_interval_ms"])
        if "rest_consistency_ms" in params:
            self.config.strategy.rest_consistency_ms = int(params["rest_consistency_ms"])

        await self._emit_event(EventLevel.INFO, symbol, "已更新参数", data=params)
        return {"ok": True, "message": "参数更新成功"}

    async def flatten_symbol(self, symbol: str) -> dict[str, Any]:
        symbol_cfg = next((cfg for cfg in self.config.symbols if cfg.symbol == symbol), None)
        if symbol_cfg is None:
            return {"ok": False, "message": f"symbol 不存在: {symbol}"}

        report = await self.execution_engine.flatten_symbol(symbol_cfg)
        await self._emit_event(EventLevel.WARN, symbol, "执行一键平仓", data=report.to_dict())
        return {
            "ok": True,
            "message": "平仓指令已执行",
            "report": report.to_dict(),
        }
