from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from arbbot.config import AppConfig, ExchangeConfig, ExchangeCredentials, RuntimeConfig, StorageConfig, SymbolConfig
from arbbot.web.api import create_app


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "trade-selection.db"
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


def _fake_candidate_rows() -> dict[str, object]:
    return {
        "updated_at": "2026-02-13T00:00:00+00:00",
        "scan_interval_sec": 300,
        "limit": 0,
        "configured_symbols": 10,
        "comparable_symbols": 10,
        "executable_symbols": 2,
        "scanned_symbols": 10,
        "total_symbols": 2,
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
                "tradable_edge_pct": 0.53,
                "tradable_edge_bps": 53.0,
                "gross_nominal_spread": 12.34,
            },
            {
                "symbol": "ETH-PERP",
                "base_asset": "ETH",
                "paradex_market": "ETH/USD:USDC",
                "grvt_market": "ETH_USDT_Perp",
                "tradable_edge_pct": 0.42,
                "tradable_edge_bps": 42.0,
                "gross_nominal_spread": 8.76,
            },
        ],
    }


def test_get_trade_selection_returns_candidates(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    async def fake_get_spreads(limit: int, force_refresh: bool) -> dict[str, object]:
        assert limit == 0
        assert force_refresh is False
        return _fake_candidate_rows()

    app.state.market_scanner.get_spreads = fake_get_spreads

    with TestClient(app) as client:
        response = client.get("/api/trade/selection")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_symbol"] == "BTC-PERP"
    assert len(payload["candidates"]) == 2
    assert payload["candidates"][0]["symbol"] == "BTC-PERP"
    assert len(payload["top10_candidates"]) == 2
    assert payload["top10_candidates"][0]["symbol"] == "BTC-PERP"


def test_set_trade_selection_reject_symbol_outside_candidates(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    async def fake_get_spreads(limit: int, force_refresh: bool) -> dict[str, object]:
        return _fake_candidate_rows()

    app.state.market_scanner.get_spreads = fake_get_spreads

    with TestClient(app) as client:
        response = client.post("/api/trade/selection", json={"symbol": "XRP-PERP"})

    assert response.status_code == 400
    assert "候选" in response.text


def test_start_engine_requires_trade_selection(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        response = client.post("/api/engine/start")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "选择" in body["message"]


def test_start_engine_after_selecting_symbol(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    async def fake_get_spreads(limit: int, force_refresh: bool) -> dict[str, object]:
        return _fake_candidate_rows()

    async def fake_start() -> bool:
        return True

    app.state.market_scanner.get_spreads = fake_get_spreads
    app.state.orchestrator.start = fake_start

    with TestClient(app) as client:
        set_response = client.post("/api/trade/selection", json={"symbol": "ETH-PERP"})
        start_response = client.post("/api/engine/start")

    assert set_response.status_code == 200
    assert set_response.json()["ok"] is True
    assert start_response.status_code == 200
    assert start_response.json()["ok"] is True
