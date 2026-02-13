from __future__ import annotations

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
    assert payload["executable_symbols"] == 3


def test_compute_zscore_reads_history_from_repository(tmp_path: Path) -> None:
    config = _build_test_config(tmp_path)
    sqlite_path = Path(config.storage.sqlite_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_spread_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signed_edge_bps TEXT NOT NULL,
                tradable_edge_pct TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'scanner'
            )
            """
        )
        for idx in range(80):
            conn.execute(
                """
                INSERT INTO market_spread_history (ts, symbol, signed_edge_bps, tradable_edge_pct, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"2026-02-13T00:00:{idx:02d}+00:00",
                    "BTC-PERP",
                    str(10 + (idx % 5)),
                    str((10 + (idx % 5)) / 100),
                    "unit_seed",
                ),
            )
        conn.commit()
    finally:
        conn.close()

    scanner = NominalSpreadScanner(config, scan_interval_sec=60)
    scanner._append_market_history_point(  # type: ignore[attr-defined]
        symbol="BTC-PERP",
        signed_edge_bps=Decimal("25"),
        tradable_edge_pct=Decimal("0.25"),
        source="unit_test",
    )
    zscore, zscore_status, sample_count = scanner._compute_zscore("BTC-PERP")  # type: ignore[attr-defined]
    assert zscore_status == "ready"
    assert sample_count >= 60
    assert abs(float(zscore)) > 0


def test_compute_spread_speed_metrics_returns_speed_and_volatility(tmp_path: Path) -> None:
    scanner = NominalSpreadScanner(_build_test_config(tmp_path), scan_interval_sec=60)

    speed_1, vol_1, samples_1 = scanner._compute_spread_speed_metrics("BTC-PERP", Decimal("0.10"))  # type: ignore[attr-defined]
    assert float(speed_1) == 0.0
    assert float(vol_1) == 0.0
    assert samples_1 == 1

    time.sleep(0.01)
    speed_2, vol_2, samples_2 = scanner._compute_spread_speed_metrics("BTC-PERP", Decimal("0.30"))  # type: ignore[attr-defined]
    assert samples_2 >= 2
    assert float(speed_2) != 0.0
    assert float(vol_2) > 0.0
