"""FastAPI 服务。"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..market import NominalSpreadScanner
from ..security import CredentialsValidator
from ..storage import CredentialsRepository
from ..strategy.orchestrator import ArbitrageOrchestrator


class ModeRequest(BaseModel):
    mode: str = Field(description="normal_arb 或 zero_wear")


class ActionResponse(BaseModel):
    ok: bool
    message: str
    data: dict[str, Any] | None = None


class ParadexCredentialsPayload(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    passphrase: str | None = None


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


def create_app(config: AppConfig) -> FastAPI:
    """创建 API 应用。"""
    orchestrator = ArbitrageOrchestrator(config)
    credentials_repository = CredentialsRepository(config.storage.sqlite_path)
    credentials_validator = CredentialsValidator(config)
    market_scanner = NominalSpreadScanner(config=config)

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
        if config.web.log_level:
            pass

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
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
        return await market_scanner.get_top_spreads(
            limit=limit,
            force_refresh=force_refresh,
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
                    "api_key": str(raw_payload.get("paradex", {}).get("api_key", "")).strip(),
                    "api_secret": str(raw_payload.get("paradex", {}).get("api_secret", "")).strip(),
                    "passphrase": str(raw_payload.get("paradex", {}).get("passphrase", "")).strip(),
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
        try:
            init_payload = {
                "type": "snapshot",
                "data": {
                    "status": await orchestrator.get_status(),
                    "symbols": orchestrator.get_symbols(),
                },
            }
            await ws.send_json(init_payload)

            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=20)
                    await ws.send_json(message)
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "heartbeat", "data": {"ts": "alive"}})
        except WebSocketDisconnect:
            pass
        finally:
            orchestrator.unregister_ws_queue(queue)

    return app
