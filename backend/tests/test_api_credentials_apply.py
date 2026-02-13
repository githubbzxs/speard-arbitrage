from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from arbbot.config import AppConfig, ExchangeConfig, ExchangeCredentials, StorageConfig, SymbolConfig
from arbbot.models import EngineStatus
from arbbot.web.api import create_app


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "credentials.db"
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
        storage=StorageConfig(sqlite_path=str(sqlite_path), csv_dir=str(csv_dir)),
    )


def test_apply_credentials_no_saved_credentials(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        response = client.post("/api/credentials/apply")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "没有可应用的凭证" in body["message"]


def test_apply_credentials_rejected_when_engine_running(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    # 模拟引擎正在运行，应用凭证应被拒绝。
    app.state.orchestrator.engine_status = EngineStatus.RUNNING

    with TestClient(app) as client:
        response = client.post("/api/credentials/apply")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "先停止引擎" in body["message"]


def test_apply_credentials_success_updates_runtime_config(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    payload = {
        "paradex": {
            "l2_private_key": "paradex-l2-private",
            "l2_address": "paradex-l2-address",
        },
        "grvt": {
            "private_key": "grvt-private-key",
            "trading_account_id": "acc-1",
        },
    }

    with TestClient(app) as client:
        save_response = client.post("/api/credentials", json=payload)
        assert save_response.status_code == 200

        apply_response = client.post("/api/credentials/apply")
        assert apply_response.status_code == 200
        body = apply_response.json()
        assert body["ok"] is True

    assert app.state.orchestrator.config.paradex.credentials.l2_private_key == "paradex-l2-private"
    assert app.state.orchestrator.config.paradex.credentials.l2_address == "paradex-l2-address"
    assert app.state.orchestrator.config.grvt.credentials.private_key == "grvt-private-key"
    assert app.state.orchestrator.config.grvt.credentials.trading_account_id == "acc-1"


def test_apply_credentials_requires_required_fields_when_live_order_enabled(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))
    app.state.orchestrator.config.runtime.live_order_enabled = True

    payload = {
        "paradex": {
            "l2_private_key": "only-paradex-l2-private",
        }
    }

    with TestClient(app) as client:
        save_response = client.post("/api/credentials", json=payload)
        assert save_response.status_code == 200

        apply_response = client.post("/api/credentials/apply")
        assert apply_response.status_code == 200
        body = apply_response.json()

    assert body["ok"] is False
    assert "缺少必填字段" in body["message"]
