from __future__ import annotations

import json
import sqlite3
import time
from decimal import Decimal
from pathlib import Path

import pytest

from arbbot.config import AppConfig, ExchangeConfig, ExchangeCredentials, StorageConfig, SymbolConfig
from arbbot.market.scanner import NominalSpreadScanner


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "scanner-zscore.db"
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


@pytest.mark.asyncio
async def test_get_top_spreads_sorted_by_abs_zscore(tmp_path: Path) -> None:
    scanner = NominalSpreadScanner(_build_test_config(tmp_path), scan_interval_sec=60)
    scanner._rows = [  # type: ignore[attr-defined]
        {"symbol": "AAA-PERP", "gross_nominal_spread": 999.0, "zscore": 0.4},
        {"symbol": "BBB-PERP", "gross_nominal_spread": 100.0, "zscore": -3.2},
        {"symbol": "CCC-PERP", "gross_nominal_spread": 200.0, "zscore": 2.1},
    ]
    scanner._last_refresh_monotonic = time.monotonic()  # type: ignore[attr-defined]

    payload = await scanner.get_top_spreads(limit=3)
    symbols = [item["symbol"] for item in payload["rows"]]
    assert symbols == ["BBB-PERP", "CCC-PERP", "AAA-PERP"]


def test_compute_zscore_reads_history_from_repository(tmp_path: Path) -> None:
    config = _build_test_config(tmp_path)
    sqlite_path = Path(config.storage.sqlite_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS symbol_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                data_json TEXT NOT NULL
            )
            """
        )
        for idx in range(80):
            payload = {"symbol": "BTC-PERP", "spread_bps": 10 + (idx % 5)}
            conn.execute(
                "INSERT INTO symbol_snapshots (ts, symbol, data_json) VALUES (?, ?, ?)",
                (f"2026-02-13T00:00:{idx:02d}+00:00", "BTC-PERP", json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()

    scanner = NominalSpreadScanner(config, scan_interval_sec=60)
    zscore = scanner._compute_zscore("BTC-PERP", Decimal("25"))  # type: ignore[attr-defined]
    assert abs(float(zscore)) > 0
