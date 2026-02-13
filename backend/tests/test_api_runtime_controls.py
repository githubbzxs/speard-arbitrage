from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from arbbot.config import (
    AppConfig,
    ExchangeConfig,
    ExchangeCredentials,
    RuntimeConfig,
    StorageConfig,
    SymbolConfig,
)
from arbbot.models import EngineStatus
from arbbot.web.api import create_app


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "runtime-controls.db"
    csv_dir = tmp_path / "csv"
    return AppConfig(
        symbols=[
            SymbolConfig(
                symbol="BTC-PERP",
                paradex_market="BTC-PERP",
                grvt_market="BTC-PERP",
            )
        ],
        paradex=ExchangeConfig(
            name="paradex",
            environment="prod",
            rest_url="https://api.prod.paradex.trade",
            ws_url="wss://ws.api.prod.paradex.trade/v1",
            credentials=ExchangeCredentials(),
        ),
        grvt=ExchangeConfig(
            name="grvt",
            environment="prod",
            rest_url="https://edge.grvt.io",
            ws_url="wss://market-data.grvt.io/ws/full",
            credentials=ExchangeCredentials(),
        ),
        runtime=RuntimeConfig(
            simulated_market_data=True,
            live_order_enabled=False,
            enable_order_confirmation_text="ENABLE_LIVE_ORDER",
        ),
        storage=StorageConfig(sqlite_path=str(sqlite_path), csv_dir=str(csv_dir)),
    )


def test_enable_live_order_requires_confirmation_text(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/api/runtime/order-execution",
            json={"live_order_enabled": True, "confirm_text": "WRONG"},
        )

    assert response.status_code == 400
    assert "确认口令错误" in response.json()["detail"]


def test_enable_live_order_rejected_on_simulated_market(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/api/runtime/order-execution",
            json={"live_order_enabled": True, "confirm_text": "ENABLE_LIVE_ORDER"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "模拟行情" in body["message"]


def test_switch_to_real_market_then_enable_live_order(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        market_response = client.post(
            "/api/runtime/market-data-mode",
            json={"simulated_market_data": False},
        )
        assert market_response.status_code == 200
        assert market_response.json()["ok"] is True

        order_response = client.post(
            "/api/runtime/order-execution",
            json={"live_order_enabled": True, "confirm_text": "ENABLE_LIVE_ORDER"},
        )
        assert order_response.status_code == 200
        assert order_response.json()["ok"] is True

    runtime = app.state.orchestrator.config.runtime
    assert runtime.simulated_market_data is False
    assert runtime.live_order_enabled is True


def test_disable_live_order_allowed_when_engine_running(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))
    orchestrator = app.state.orchestrator
    orchestrator.config.runtime.simulated_market_data = False
    orchestrator.paradex.simulate_market_data = False
    orchestrator.paradex.dry_run = False
    orchestrator.grvt.simulate_market_data = False
    orchestrator.grvt.dry_run = False
    orchestrator.config.runtime.live_order_enabled = True
    orchestrator.execution_engine.set_live_order_enabled(True)
    orchestrator.engine_status = EngineStatus.RUNNING

    with TestClient(app) as client:
        response = client.post(
            "/api/runtime/order-execution",
            json={"live_order_enabled": False},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert app.state.orchestrator.config.runtime.live_order_enabled is False


def test_switch_market_mode_requires_engine_stopped(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))
    app.state.orchestrator.engine_status = EngineStatus.RUNNING

    with TestClient(app) as client:
        response = client.post(
            "/api/runtime/market-data-mode",
            json={"simulated_market_data": False},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "先停止引擎" in body["message"]


def test_public_config_exposes_runtime_switches(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        response = client.get("/api/config")

    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert runtime["simulated_market_data"] is True
    assert runtime["live_order_enabled"] is False
    assert runtime["enable_order_confirmation_text"] == "ENABLE_LIVE_ORDER"
