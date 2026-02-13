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
    sqlite_path = tmp_path / "ws-market.db"
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


def test_ws_stream_emits_market_top_spreads(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    async def fake_get_spreads(limit: int, force_refresh: bool) -> dict[str, object]:
        return {
            "updated_at": "2026-02-13T00:00:00+00:00",
            "scan_interval_sec": 300,
            "limit": limit,
            "configured_symbols": 10,
            "comparable_symbols": 8,
            "executable_symbols": 1,
            "scanned_symbols": 8,
            "total_symbols": 1,
            "skipped_count": 0,
            "skipped_reasons": {},
            "fee_profile": {"paradex_leg": "taker", "grvt_leg": "maker"},
            "last_error": None,
            "rows": [
                {
                    "symbol": "BTC-PERP",
                    "base_asset": "BTC",
                    "paradex_market": "BTC/USD:USDC",
                    "grvt_market": "BTC_USDT_Perp",
                    "tradable_edge_pct": 0.5,
                    "tradable_edge_bps": 50.0,
                    "gross_nominal_spread": 12.3,
                    "net_nominal_spread": 9.9,
                    "reference_mid": 100.0,
                }
            ],
        }

    app.state.market_scanner.get_spreads = fake_get_spreads

    with TestClient(app) as client:
        with client.websocket_connect("/ws/stream") as ws:
            first = ws.receive_json()
            second = ws.receive_json()

    assert first["type"] == "snapshot"
    assert second["type"] == "market_top_spreads"
    assert second["data"]["rows"][0]["symbol"] == "BTC-PERP"
