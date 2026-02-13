"""FastAPI 服务。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..strategy.orchestrator import ArbitrageOrchestrator


class ModeRequest(BaseModel):
    mode: str = Field(description="normal_arb 或 zero_wear")


class ActionResponse(BaseModel):
    ok: bool
    message: str
    data: dict[str, Any] | None = None


def create_app(config: AppConfig) -> FastAPI:
    """创建 API 应用。"""
    orchestrator = ArbitrageOrchestrator(config)

    app = FastAPI(title="跨所价差套利", version="1.0.0")
    app.state.orchestrator = orchestrator

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
        await orchestrator.shutdown()

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
