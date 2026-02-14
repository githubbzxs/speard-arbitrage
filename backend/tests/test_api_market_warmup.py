from pathlib import Path

from fastapi.testclient import TestClient

from arbbot.config import (
    AppConfig,
    ExchangeConfig,
    ExchangeCredentials,
    MarketWarmupConfig,
    RuntimeConfig,
    StorageConfig,
    SymbolConfig,
)
from arbbot.web.api import create_app


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "market-warmup.db"
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
        market_warmup=MarketWarmupConfig(
            enabled=True,
            require_ready_for_market_api=True,
            timeout_sec=1,
            scan_interval_ms=50,
            history_retention=500,
        ),
        storage=StorageConfig(sqlite_path=str(sqlite_path), csv_dir=str(csv_dir)),
    )


def test_market_api_returns_503_when_warmup_not_ready(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    async def fake_warmup_until_ready(*, timeout_sec: float, poll_sec: float) -> dict[str, object]:
        return {
            "done": False,
            "message": "市场数据预热中：0/1",
            "required_samples": 60,
            "symbols_total": 1,
            "symbols_ready": 0,
            "symbols_pending": 1,
            "sample_counts": {"BTC-PERP": 12},
            "updated_at": "2026-02-13T00:00:00+00:00",
        }

    app.state.market_scanner.warmup_until_ready = fake_warmup_until_ready
    app.state.market_scanner.is_warmup_ready = lambda: False
    app.state.market_scanner.get_warmup_status = lambda: {
        "done": False,
        "message": "市场数据预热中：0/1",
        "required_samples": 60,
        "symbols_total": 1,
        "symbols_ready": 0,
        "symbols_pending": 1,
        "sample_counts": {"BTC-PERP": 12},
        "updated_at": "2026-02-13T00:00:00+00:00",
    }

    with TestClient(app) as client:
        response = client.get("/api/market/top-spreads")
        trade_response = client.get("/api/trade/selection")

    assert response.status_code == 503
    assert "预热中" in response.text
    assert trade_response.status_code == 503
    assert "预热中" in trade_response.text


def test_market_api_works_after_warmup_ready(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    async def fake_warmup_until_ready(*, timeout_sec: float, poll_sec: float) -> dict[str, object]:
        return {
            "done": True,
            "message": "预热完成",
            "required_samples": 60,
            "symbols_total": 1,
            "symbols_ready": 1,
            "symbols_pending": 0,
            "sample_counts": {"BTC-PERP": 80},
            "updated_at": "2026-02-13T00:00:00+00:00",
        }

    async def fake_get_spreads(limit: int, force_refresh: bool) -> dict[str, object]:
        return {
            "updated_at": "2026-02-13T00:00:00+00:00",
            "scan_interval_sec": 300,
            "limit": limit,
            "configured_symbols": 1,
            "comparable_symbols": 1,
            "executable_symbols": 1,
            "scanned_symbols": 1,
            "total_symbols": 1,
            "skipped_count": 0,
            "skipped_reasons": {},
            "fee_profile": {"paradex_leg": "taker", "grvt_leg": "maker"},
            "last_error": None,
            "warmup_done": True,
            "warmup_progress": {
                "done": True,
                "message": "预热完成",
                "required_samples": 60,
                "symbols_total": 1,
                "symbols_ready": 1,
                "symbols_pending": 0,
                "sample_counts": {"BTC-PERP": 80},
                "updated_at": "2026-02-13T00:00:00+00:00",
            },
            "rows": [{"symbol": "BTC-PERP", "zscore": 1.2, "zscore_ready": True, "zscore_status": "ready"}],
        }

    app.state.market_scanner.warmup_until_ready = fake_warmup_until_ready
    app.state.market_scanner.is_warmup_ready = lambda: True
    app.state.market_scanner.get_warmup_status = lambda: {
        "done": True,
        "message": "预热完成",
        "required_samples": 60,
        "symbols_total": 1,
        "symbols_ready": 1,
        "symbols_pending": 0,
        "sample_counts": {"BTC-PERP": 80},
        "updated_at": "2026-02-13T00:00:00+00:00",
    }
    app.state.market_scanner.get_spreads = fake_get_spreads

    with TestClient(app) as client:
        response = client.get("/api/market/top-spreads")

    assert response.status_code == 200
    payload = response.json()
    assert payload["warmup_done"] is True
    assert payload["rows"][0]["symbol"] == "BTC-PERP"


def test_market_api_returns_scan_error_when_warmup_stuck(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    async def fake_warmup_until_ready(*, timeout_sec: float, poll_sec: float) -> dict[str, object]:
        return {
            "done": False,
            "message": "尚未开始",
            "required_samples": 60,
            "symbols_total": 0,
            "symbols_ready": 0,
            "symbols_pending": 0,
            "sample_counts": {},
            "updated_at": "2026-02-13T00:00:00+00:00",
        }

    app.state.market_scanner.warmup_until_ready = fake_warmup_until_ready
    app.state.market_scanner.is_warmup_ready = lambda: False
    app.state.market_scanner.get_warmup_status = lambda: {
        "done": False,
        "message": "尚未开始",
        "required_samples": 60,
        "symbols_total": 0,
        "symbols_ready": 0,
        "symbols_pending": 0,
        "sample_counts": {},
        "updated_at": "2026-02-13T00:00:00+00:00",
    }
    app.state.market_scanner.get_last_error = lambda: "扫描失败: GRVT 杠杆接口错误: 401 unauthorized"

    with TestClient(app) as client:
        response = client.get("/api/market/top-spreads")
        warmup_response = client.get("/api/market/warmup-status")

    assert response.status_code == 503
    assert "GRVT" in response.text
    assert warmup_response.status_code == 200
    payload = warmup_response.json()
    assert payload["last_error"] is not None
    assert "GRVT" in payload["last_error"]
