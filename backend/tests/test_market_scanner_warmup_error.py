from __future__ import annotations

from pathlib import Path

import pytest

from arbbot.config import AppConfig, ExchangeConfig, ExchangeCredentials, StorageConfig, SymbolConfig
from arbbot.market.scanner import NominalSpreadScanner


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "scanner-warmup-error.db"
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
        storage=StorageConfig(sqlite_path=str(sqlite_path), csv_dir=str(csv_dir)),
    )


@pytest.mark.asyncio
async def test_refresh_once_persists_last_error_into_warmup_status(tmp_path: Path) -> None:
    scanner = NominalSpreadScanner(_build_test_config(tmp_path), scan_interval_sec=60)

    async def fake_scan_all_symbols():  # type: ignore[no-untyped-def]
        raise RuntimeError("GRVT 杠杆接口错误: 401 unauthorized")

    scanner._scan_all_symbols = fake_scan_all_symbols  # type: ignore[attr-defined]

    await scanner._refresh_once()  # type: ignore[attr-defined]

    status = scanner.get_warmup_status()
    assert status["done"] is False
    assert status["symbols_total"] == 0
    assert "GRVT 杠杆接口错误" in status["message"]
    assert "GRVT 杠杆接口错误" in scanner.get_last_error()
