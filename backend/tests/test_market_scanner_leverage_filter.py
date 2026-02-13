from __future__ import annotations

from pathlib import Path

import pytest

from arbbot.config import AppConfig, ExchangeConfig, ExchangeCredentials, StorageConfig, SymbolConfig
from arbbot.market.scanner import (
    SKIP_REASON_EFFECTIVE_LEVERAGE_BELOW_TARGET,
    NominalSpreadScanner,
)


class _FakeDepthClient:
    async def fetch_order_book(self, market: str, limit: int = 5) -> dict[str, list[list[float]]]:
        return {
            "bids": [[100.0, 1.0]],
            "asks": [[101.0, 1.0]],
        }


class _FakeGrvtDepthClient:
    async def fetch_order_book(self, market: str, limit: int = 10) -> dict[str, list[list[float]]]:
        return {
            "bids": [[103.0, 1.0]],
            "asks": [[104.0, 1.0]],
        }


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "scanner-leverage-filter.db"
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
async def test_fetch_pair_row_skips_below_50x_effective_leverage(tmp_path: Path) -> None:
    scanner = NominalSpreadScanner(_build_test_config(tmp_path), scan_interval_sec=60)
    row, reason = await scanner._fetch_pair_row(  # type: ignore[attr-defined]
        paradex_client=_FakeDepthClient(),
        grvt_client=_FakeGrvtDepthClient(),
        base_asset="BTC",
        paradex_info={"market": "BTC/USD:USDC", "max_leverage": 20},
        grvt_info={"market": "BTC_USDT_Perp", "max_leverage": 50},
    )

    assert row is None
    assert reason == SKIP_REASON_EFFECTIVE_LEVERAGE_BELOW_TARGET


@pytest.mark.asyncio
async def test_fetch_pair_row_keeps_50x_effective_leverage(tmp_path: Path) -> None:
    scanner = NominalSpreadScanner(_build_test_config(tmp_path), scan_interval_sec=60)
    row, reason = await scanner._fetch_pair_row(  # type: ignore[attr-defined]
        paradex_client=_FakeDepthClient(),
        grvt_client=_FakeGrvtDepthClient(),
        base_asset="BTC",
        paradex_info={"market": "BTC/USD:USDC", "max_leverage": 50},
        grvt_info={"market": "BTC_USDT_Perp", "max_leverage": 100},
    )

    assert reason is None
    assert row is not None
    assert row["symbol"] == "BTC-PERP"
    assert row["effective_leverage"] == 50.0
