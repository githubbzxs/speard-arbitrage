"""FastAPI 服务。"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..config import AppConfig, SymbolConfig
from ..market import NominalSpreadScanner
from ..models import EngineStatus, utc_iso
from ..security import CredentialsValidator
from ..storage import CredentialsRepository
from ..strategy.orchestrator import ArbitrageOrchestrator

MARKET_WS_PUSH_INTERVAL_SEC = 3
WS_HEARTBEAT_TIMEOUT_SEC = 20


class ModeRequest(BaseModel):
    mode: str = Field(description="normal_arb 或 zero_wear")


class ActionResponse(BaseModel):
    ok: bool
    message: str
    data: dict[str, Any] | None = None


class ParadexCredentialsPayload(BaseModel):
    l2_private_key: str | None = None
    l2_address: str | None = None


class GrvtCredentialsPayload(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    private_key: str | None = None
    trading_account_id: str | None = None


class CredentialsPayload(BaseModel):
    paradex: ParadexCredentialsPayload | None = None
    grvt: GrvtCredentialsPayload | None = None


class ValidateCredentialsRequest(BaseModel):
    source: Literal["saved", "draft"] = Field(default="saved", description="saved 或 draft")
    payload: CredentialsPayload | None = None


class RuntimeOrderExecutionRequest(BaseModel):
    live_order_enabled: bool = Field(description="是否启用真实下单")
    confirm_text: str | None = Field(default=None, description="开启真实下单时的确认口令")


class RuntimeMarketDataRequest(BaseModel):
    simulated_market_data: bool = Field(description="是否使用模拟行情")


class TradeSelectionRequest(BaseModel):
    symbol: str = Field(description="交易标的（必须来自 Top10）")
    force_refresh: bool = Field(default=False, description="是否强制刷新 Top10 后再校验")


def create_app(config: AppConfig) -> FastAPI:
    """创建 API 应用。"""
    orchestrator = ArbitrageOrchestrator(config)
    credentials_repository = CredentialsRepository(config.storage.sqlite_path)
    credentials_validator = CredentialsValidator(config)
    market_scanner = NominalSpreadScanner(config=config, scan_interval_sec=60)
    top_limit = 10
    selected_symbol = ""
    selected_symbol_config: SymbolConfig | None = None
    top10_candidates: list[dict[str, Any]] = []
    top10_symbol_map: dict[str, SymbolConfig] = {}
    top10_updated_at = ""
    market_ws_queues: set[asyncio.Queue[dict[str, Any]]] = set()
    market_top_push_task: asyncio.Task[None] | None = None
    market_top_push_stop = asyncio.Event()

    def hydrate_runtime_credentials_from_saved() -> None:
        """将已保存凭证同步到运行时配置，供行情扫描等只读场景使用。"""
        saved = credentials_repository.get_effective_credentials()
        paradex_saved = saved.get("paradex") if isinstance(saved.get("paradex"), dict) else {}
        grvt_saved = saved.get("grvt") if isinstance(saved.get("grvt"), dict) else {}

        for field in ("l2_private_key", "l2_address"):
            value = str(paradex_saved.get(field, "")).strip()
            if value:
                setattr(config.paradex.credentials, field, value)

        for field in ("api_key", "api_secret", "private_key", "trading_account_id"):
            value = str(grvt_saved.get(field, "")).strip()
            if value:
                setattr(config.grvt.credentials, field, value)

    def _resolve_symbol_config_from_row(row: dict[str, Any]) -> SymbolConfig | None:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            return None

        configured = next((cfg for cfg in config.symbols if cfg.symbol == symbol), None)
        if configured is not None:
            return configured

        paradex_market = str(row.get("paradex_market") or row.get("paradexMarket") or "").strip()
        grvt_market = str(row.get("grvt_market") or row.get("grvtMarket") or "").strip()
        if not paradex_market or not grvt_market:
            return None

        base_asset = str(row.get("base_asset") or row.get("baseAsset") or symbol.replace("-PERP", "")).strip().upper()
        quote_asset = "USDT"
        return SymbolConfig(
            symbol=symbol,
            paradex_market=paradex_market,
            grvt_market=grvt_market,
            base_asset=base_asset,
            quote_asset=quote_asset,
            recommended_leverage=2,
            leverage_note="Top10 候选标的",
            enabled=True,
        )

    def parse_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def apply_top10_payload(payload: dict[str, Any], reconcile_selected: bool) -> None:
        nonlocal selected_symbol, selected_symbol_config, top10_candidates, top10_symbol_map, top10_updated_at

        rows = payload.get("rows")
        rows_list = rows if isinstance(rows, list) else []

        next_candidates: list[dict[str, Any]] = []
        next_symbol_map: dict[str, SymbolConfig] = {}
        for raw_row in rows_list:
            if not isinstance(raw_row, dict):
                continue
            symbol_cfg = _resolve_symbol_config_from_row(raw_row)
            if symbol_cfg is None:
                continue

            symbol = symbol_cfg.symbol
            next_symbol_map[symbol] = symbol_cfg
            next_candidates.append(
                {
                    "symbol": symbol,
                    "paradex_market": symbol_cfg.paradex_market,
                    "grvt_market": symbol_cfg.grvt_market,
                    "tradable_edge_pct": parse_float(raw_row.get("tradable_edge_pct")),
                    "tradable_edge_bps": parse_float(raw_row.get("tradable_edge_bps")),
                    "gross_nominal_spread": parse_float(raw_row.get("gross_nominal_spread")),
                }
            )

        top10_candidates = next_candidates
        top10_symbol_map = next_symbol_map
        top10_updated_at = str(payload.get("updated_at") or utc_iso())

        if reconcile_selected and selected_symbol:
            next_selected_config = top10_symbol_map.get(selected_symbol)
            if next_selected_config is None:
                selected_symbol = ""
                selected_symbol_config = None
                orchestrator.set_selected_symbol(None)
            else:
                selected_symbol_config = next_selected_config
                orchestrator.set_selected_symbol(next_selected_config)

    async def refresh_top10_candidates(
        force_refresh: bool = False,
        reconcile_selected: bool = True,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        hydrate_runtime_credentials_from_saved()
        fetch_coro = market_scanner.get_top_spreads(limit=top_limit, force_refresh=force_refresh)
        if timeout_sec is not None and timeout_sec > 0:
            payload = await asyncio.wait_for(fetch_coro, timeout=timeout_sec)
        else:
            payload = await fetch_coro
        apply_top10_payload(payload, reconcile_selected=reconcile_selected)
        return payload

    def register_market_ws_queue() -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        market_ws_queues.add(queue)
        return queue

    def unregister_market_ws_queue(queue: asyncio.Queue[dict[str, Any]]) -> None:
        market_ws_queues.discard(queue)

    async def broadcast_market_top_spreads(payload: dict[str, Any]) -> None:
        if not market_ws_queues:
            return

        message = {"type": "market_top_spreads", "data": payload}
        stale_queues: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(market_ws_queues):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(message)
            except Exception:
                stale_queues.append(queue)

        for queue in stale_queues:
            market_ws_queues.discard(queue)

    async def market_top_spreads_worker() -> None:
        while not market_top_push_stop.is_set():
            try:
                if market_ws_queues:
                    payload = await refresh_top10_candidates(force_refresh=False, reconcile_selected=False)
                    await broadcast_market_top_spreads(payload)
            except Exception:
                # 忽略单次推送错误，下一轮继续。
                pass

            try:
                await asyncio.wait_for(market_top_push_stop.wait(), timeout=MARKET_WS_PUSH_INTERVAL_SEC)
            except asyncio.TimeoutError:
                continue

    app = FastAPI(title="跨所价差套利", version="1.0.0")
    app.state.orchestrator = orchestrator
    app.state.credentials_repository = credentials_repository
    app.state.credentials_validator = credentials_validator
    app.state.market_scanner = market_scanner

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def on_startup() -> None:
        nonlocal market_top_push_task

        if config.web.log_level:
            pass

        market_top_push_stop.clear()
        market_top_push_task = asyncio.create_task(market_top_spreads_worker(), name="market-top-spreads-worker")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        nonlocal market_top_push_task

        market_top_push_stop.set()
        if market_top_push_task is not None:
            market_top_push_task.cancel()
            await asyncio.gather(market_top_push_task, return_exceptions=True)
            market_top_push_task = None

        try:
            await orchestrator.shutdown()
        finally:
            credentials_repository.close()

    @app.get("/api/status")
    async def get_status() -> dict[str, Any]:
        return await orchestrator.get_status()

    @app.get("/api/symbols")
    async def get_symbols() -> list[dict[str, Any]]:
        return orchestrator.get_symbols()

    @app.get("/api/events")
    async def get_events(limit: int = 100) -> list[dict[str, Any]]:
        return orchestrator.get_events(limit=limit)

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        return config.to_public_dict()

    @app.get("/api/market/top-spreads")
    async def get_market_top_spreads(
        limit: int = 10,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        hydrate_runtime_credentials_from_saved()
        payload = await market_scanner.get_top_spreads(
            limit=limit,
            force_refresh=force_refresh,
        )
        apply_top10_payload(payload, reconcile_selected=False)
        return payload

    @app.get("/api/trade/selection")
    async def get_trade_selection(force_refresh: bool = False) -> dict[str, Any]:
        if not force_refresh and top10_candidates:
            return {
                "selected_symbol": selected_symbol,
                "top10_candidates": top10_candidates,
                "updated_at": top10_updated_at,
            }

        try:
            await refresh_top10_candidates(
                force_refresh=force_refresh,
                reconcile_selected=True,
                timeout_sec=6 if not force_refresh else 12,
            )
        except asyncio.TimeoutError:
            pass

        return {
            "selected_symbol": selected_symbol,
            "top10_candidates": top10_candidates,
            "updated_at": top10_updated_at,
        }

    @app.post("/api/trade/selection", response_model=ActionResponse)
    async def set_trade_selection(payload: TradeSelectionRequest) -> ActionResponse:
        nonlocal selected_symbol, selected_symbol_config

        if orchestrator.engine_status != EngineStatus.STOPPED:
            return ActionResponse(
                ok=False,
                message="引擎运行中禁止切换交易标的，请先停止引擎",
                data={"engine_status": orchestrator.engine_status.value},
            )

        symbol = payload.symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol 不能为空")

        try:
            await refresh_top10_candidates(
                force_refresh=payload.force_refresh,
                reconcile_selected=True,
                timeout_sec=12,
            )
        except asyncio.TimeoutError:
            if not top10_symbol_map:
                raise HTTPException(status_code=504, detail="Top10 候选加载超时，请稍后重试")
        symbol_cfg = top10_symbol_map.get(symbol)
        if symbol_cfg is None:
            raise HTTPException(status_code=400, detail="symbol 不在当前 Top10 候选中")

        selected_symbol = symbol
        selected_symbol_config = symbol_cfg
        orchestrator.set_selected_symbol(symbol_cfg)

        return ActionResponse(
            ok=True,
            message=f"已选择交易标的：{symbol}",
            data={
                "selected_symbol": selected_symbol,
                "top10_candidates": top10_candidates,
                "updated_at": top10_updated_at,
            },
        )

    @app.post("/api/runtime/order-execution", response_model=ActionResponse)
    async def set_order_execution(payload: RuntimeOrderExecutionRequest) -> ActionResponse:
        if payload.live_order_enabled:
            expected = config.runtime.enable_order_confirmation_text.strip()
            confirm_text = (payload.confirm_text or "").strip()
            if confirm_text != expected:
                raise HTTPException(status_code=400, detail="确认口令错误，已拒绝开启真实下单")

        result = await orchestrator.set_live_order_enabled(payload.live_order_enabled)
        return ActionResponse(
            ok=bool(result.get("ok", False)),
            message=str(result.get("message", "")),
            data=result.get("data"),
        )

    @app.post("/api/runtime/market-data-mode", response_model=ActionResponse)
    async def set_market_data_mode(payload: RuntimeMarketDataRequest) -> ActionResponse:
        result = await orchestrator.set_simulated_market_data(payload.simulated_market_data)
        return ActionResponse(
            ok=bool(result.get("ok", False)),
            message=str(result.get("message", "")),
            data=result.get("data"),
        )

    @app.get("/api/credentials/status", response_model=ActionResponse)
    async def get_credentials_status() -> ActionResponse:
        return ActionResponse(
            ok=True,
            message="凭证状态获取成功",
            data=credentials_repository.get_status(),
        )

    @app.post("/api/credentials", response_model=ActionResponse)
    async def save_credentials(payload: CredentialsPayload) -> ActionResponse:
        credentials_repository.save_credentials(payload.model_dump(exclude_none=True))
        return ActionResponse(
            ok=True,
            message="凭证已保存，可在引擎停止时点击“应用凭证”生效",
            data=credentials_repository.get_status(),
        )

    @app.post("/api/credentials/apply", response_model=ActionResponse)
    async def apply_credentials() -> ActionResponse:
        result = await orchestrator.apply_credentials(credentials_repository.get_effective_credentials())
        return ActionResponse(
            ok=bool(result.get("ok", False)),
            message=str(result.get("message", "")),
            data=result.get("data"),
        )

    @app.post("/api/credentials/validate", response_model=ActionResponse)
    async def validate_credentials(payload: ValidateCredentialsRequest) -> ActionResponse:
        if payload.source == "saved":
            target_credentials = credentials_repository.get_effective_credentials()
        else:
            if payload.payload is None:
                raise HTTPException(status_code=400, detail="source=draft 时必须提供 payload")
            raw_payload = payload.payload.model_dump(exclude_none=True)
            target_credentials = {
                "paradex": {
                    "l2_private_key": str(raw_payload.get("paradex", {}).get("l2_private_key", "")).strip(),
                    "l2_address": str(raw_payload.get("paradex", {}).get("l2_address", "")).strip(),
                },
                "grvt": {
                    "api_key": str(raw_payload.get("grvt", {}).get("api_key", "")).strip(),
                    "api_secret": str(raw_payload.get("grvt", {}).get("api_secret", "")).strip(),
                    "private_key": str(raw_payload.get("grvt", {}).get("private_key", "")).strip(),
                    "trading_account_id": str(raw_payload.get("grvt", {}).get("trading_account_id", "")).strip(),
                },
            }

        result = await credentials_validator.validate(target_credentials)
        return ActionResponse(
            ok=bool(result.get("ok", False)),
            message=str(result.get("message", "")),
            data=result.get("data"),
        )

    @app.post("/api/engine/start", response_model=ActionResponse)
    async def start_engine() -> ActionResponse:
        if selected_symbol_config is None:
            return ActionResponse(ok=False, message="请先在下单页选择一个 Top10 交易标的")
        started = await orchestrator.start()
        if started:
            return ActionResponse(ok=True, message="引擎已启动")
        return ActionResponse(ok=False, message="引擎已在运行或启动失败")

    @app.post("/api/engine/stop", response_model=ActionResponse)
    async def stop_engine() -> ActionResponse:
        stopped = await orchestrator.stop()
        if stopped:
            return ActionResponse(ok=True, message="引擎已停止")
        return ActionResponse(ok=False, message="引擎未运行")

    @app.post("/api/mode", response_model=ActionResponse)
    async def set_mode(payload: ModeRequest) -> ActionResponse:
        if payload.mode not in {"normal_arb", "zero_wear"}:
            raise HTTPException(status_code=400, detail="mode 仅支持 normal_arb 或 zero_wear")
        await orchestrator.set_mode(payload.mode)
        return ActionResponse(ok=True, message=f"模式已切换到 {payload.mode}")

    @app.post("/api/symbol/{symbol}/params", response_model=ActionResponse)
    async def update_symbol_params(symbol: str, payload: dict[str, Any]) -> ActionResponse:
        params = payload.get("params")
        if isinstance(params, dict):
            update_payload = params
        else:
            update_payload = payload
        result = await orchestrator.update_symbol_params(symbol, update_payload)
        return ActionResponse(ok=result.get("ok", False), message=result.get("message", ""), data=result)

    @app.post("/api/symbol/{symbol}/flatten", response_model=ActionResponse)
    async def flatten_symbol(symbol: str) -> ActionResponse:
        result = await orchestrator.flatten_symbol(symbol)
        return ActionResponse(ok=result.get("ok", False), message=result.get("message", ""), data=result)

    @app.websocket("/ws/stream")
    async def ws_stream(ws: WebSocket) -> None:
        await ws.accept()
        queue = orchestrator.register_ws_queue()
        market_queue = register_market_ws_queue()
        try:
            init_payload = {
                "type": "snapshot",
                "data": {
                    "status": await orchestrator.get_status(),
                    "symbols": orchestrator.get_symbols(),
                },
            }
            await ws.send_json(init_payload)
            try:
                initial_market_payload = await refresh_top10_candidates(
                    force_refresh=False,
                    reconcile_selected=False,
                    timeout_sec=6,
                )
            except asyncio.TimeoutError:
                initial_market_payload = {
                    "updated_at": top10_updated_at or utc_iso(),
                    "scan_interval_sec": int(getattr(market_scanner, "_scan_interval_sec", 60)),
                    "limit": top_limit,
                    "configured_symbols": len(config.symbols),
                    "comparable_symbols": 0,
                    "executable_symbols": 0,
                    "scanned_symbols": 0,
                    "total_symbols": 0,
                    "skipped_count": 0,
                    "skipped_reasons": {},
                    "fee_profile": {"paradex_leg": "taker", "grvt_leg": "maker"},
                    "last_error": "Top10 候选初始化较慢，后台加载中",
                    "rows": [],
                }
            await ws.send_json({"type": "market_top_spreads", "data": initial_market_payload})

            while True:
                pending_tasks = [asyncio.create_task(queue.get()), asyncio.create_task(market_queue.get())]
                done, pending = await asyncio.wait(
                    pending_tasks,
                    timeout=WS_HEARTBEAT_TIMEOUT_SEC,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if not done:
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    await ws.send_json({"type": "heartbeat", "data": {"ts": "alive"}})
                    continue

                message: dict[str, Any] | None = None
                for task in done:
                    try:
                        message = task.result()
                        break
                    except Exception:
                        continue

                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                if message is None:
                    continue

                await ws.send_json(message)
        except WebSocketDisconnect:
            pass
        finally:
            orchestrator.unregister_ws_queue(queue)
            unregister_market_ws_queue(market_queue)

    return app
