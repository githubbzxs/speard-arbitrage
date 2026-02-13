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

    def close(self) -> None:
        self._conn.close()
