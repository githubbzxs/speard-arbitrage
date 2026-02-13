"""SQLite 数据仓库。"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from ..models import EventRecord, SymbolSnapshot, TradeFill


class Repository:
    """负责事件、成交、快照落盘。"""

    def __init__(self, sqlite_path: str) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ms INTEGER NOT NULL,
                    exchange_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    tag TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    data_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
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
            self._conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_market_spread_history_unique
                ON market_spread_history(symbol, ts, source)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_spread_history_symbol_id
                ON market_spread_history(symbol, id)
                """
            )

    def add_event(self, event: EventRecord) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO events (id, ts, level, source, message, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.ts,
                    event.level.value,
                    event.source,
                    event.message,
                    json.dumps(event.data, ensure_ascii=False),
                ),
            )

    def add_trade(self, fill: TradeFill) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO trades (ts_ms, exchange_name, symbol, side, quantity, price, order_id, tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill.timestamp_ms,
                    fill.exchange.value,
                    fill.symbol,
                    fill.side.value,
                    str(fill.quantity),
                    str(fill.price),
                    fill.order_id,
                    fill.tag,
                ),
            )

    def add_symbol_snapshot(self, snapshot: SymbolSnapshot) -> None:
        data = snapshot.to_dict()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO symbol_snapshots (ts, symbol, data_json) VALUES (?, ?, ?)",
                (snapshot.updated_at, snapshot.symbol, json.dumps(data, ensure_ascii=False)),
            )

    def list_events(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, level, source, message, data_json FROM events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()

        out = []
        for row in rows:
            out.append(
                {
                    "id": row[0],
                    "ts": row[1],
                    "level": row[2],
                    "source": row[3],
                    "message": row[4],
                    "data": json.loads(row[5] or "{}"),
                }
            )
        return out

    def latest_symbol_snapshots(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT s.symbol, s.data_json
                FROM symbol_snapshots s
                INNER JOIN (
                    SELECT symbol, MAX(id) AS max_id
                    FROM symbol_snapshots
                    GROUP BY symbol
                ) x ON s.id = x.max_id
                ORDER BY s.symbol ASC
                """
            ).fetchall()

        return [json.loads(row[1]) for row in rows]

    def add_market_spread_point(
        self,
        ts: str,
        symbol: str,
        signed_edge_bps: str,
        tradable_edge_pct: str,
        source: str = "scanner",
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO market_spread_history
                (ts, symbol, signed_edge_bps, tradable_edge_pct, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ts, symbol, signed_edge_bps, tradable_edge_pct, source),
            )

    def list_recent_market_spread_points(self, symbol: str, limit: int) -> list[dict]:
        resolved_limit = max(1, int(limit))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT ts, signed_edge_bps, tradable_edge_pct, source
                FROM market_spread_history
                WHERE symbol = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (symbol, resolved_limit),
            ).fetchall()

        output: list[dict] = []
        for ts, signed_edge_bps, tradable_edge_pct, source in rows:
            output.append(
                {
                    "ts": ts,
                    "signed_edge_bps": signed_edge_bps,
                    "tradable_edge_pct": tradable_edge_pct,
                    "source": source,
                }
            )
        return output

    def count_market_spread_points(self, symbol: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM market_spread_history WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        return int(row[0] if row else 0)

    def trim_market_spread_history(self, symbol: str, max_rows: int) -> None:
        resolved_max_rows = max(1, int(max_rows))
        with self._lock, self._conn:
            self._conn.execute(
                """
                DELETE FROM market_spread_history
                WHERE symbol = ?
                  AND id NOT IN (
                    SELECT id
                    FROM market_spread_history
                    WHERE symbol = ?
                    ORDER BY id DESC
                    LIMIT ?
                  )
                """,
                (symbol, symbol, resolved_max_rows),
            )

    def close(self) -> None:
        self._conn.close()
