from __future__ import annotations

from pathlib import Path

import pytest

from arbbot.config import AppConfig, ExchangeConfig, ExchangeCredentials, StorageConfig, SymbolConfig
from arbbot.market.scanner import NominalSpreadScanner


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "scanner-private-key.db"
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
            credentials=ExchangeCredentials(
                api_key="grvt-key",
                private_key="non-hex-private-key",
                trading_account_id="acc-1",
            ),
        ),
        storage=StorageConfig(sqlite_path=str(sqlite_path), csv_dir=str(csv_dir)),
    )


@pytest.mark.asyncio
async def test_fetch_grvt_leverage_map_rejects_non_hex_private_key(tmp_path: Path) -> None:
    scanner = NominalSpreadScanner(_build_test_config(tmp_path))

    with pytest.raises(ValueError, match="十六进制字符串"):
        await scanner._fetch_grvt_leverage_map()  # type: ignore[attr-defined]
