from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from arbbot.config import AppConfig, ExchangeConfig, ExchangeCredentials, RuntimeConfig, StorageConfig, SymbolConfig
from arbbot.web.api import create_app


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "status-metrics.db"
    csv_dir = tmp_path / "csv"
    return AppConfig(
        symbols=[
            SymbolConfig(
                symbol="BTC-PERP",
                paradex_market="BTC/USD:USDC",
                grvt_market="BTC_USDT_Perp",
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


def test_status_contains_performance_balance_and_positions(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert "performance" in payload
    assert "balances" in payload
    assert "positions_summary" in payload
    assert "run_total_pnl" in payload["performance"]
    assert "paradex" in payload["balances"]
    assert "grvt" in payload["balances"]
    assert "total_net_exposure" in payload["positions_summary"]
