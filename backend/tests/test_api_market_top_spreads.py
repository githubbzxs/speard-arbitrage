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
from arbbot.web.api import create_app


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "market-spreads.db"
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


def test_market_top_spreads_endpoint_returns_scanner_payload(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    async def fake_get_top_spreads(
        limit: int,
        paradex_fallback_leverage: float,
        grvt_fallback_leverage: float,
        force_refresh: bool,
    ) -> dict[str, object]:
        assert limit == 7
        assert paradex_fallback_leverage == 3.0
        assert grvt_fallback_leverage == 4.0
        assert force_refresh is True
        return {
            "updated_at": "2026-02-13T00:00:00+00:00",
            "scan_interval_sec": 300,
            "limit": 7,
            "total_symbols": 1,
            "fallback": {"paradex": 3.0, "grvt": 4.0},
            "last_error": None,
            "rows": [
                {
                    "symbol": "BTC-PERP",
                    "nominal_spread": 12.34,
                    "spread_price": 6.17,
                }
            ],
        }

    app.state.market_scanner.get_top_spreads = fake_get_top_spreads

    with TestClient(app) as client:
        response = client.get(
            "/api/market/top-spreads?limit=7&paradex_fallback_leverage=3&grvt_fallback_leverage=4&force_refresh=true"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 7
    assert payload["rows"][0]["symbol"] == "BTC-PERP"
    assert payload["rows"][0]["nominal_spread"] == 12.34
