"""CSV 审计日志。"""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import EventRecord, SymbolSnapshot, TradeFill


class CsvLogger:
    """将事件、成交、快照写入 CSV。"""

    def __init__(self, csv_dir: str) -> None:
        self.csv_dir = Path(csv_dir)
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        self.event_path = self.csv_dir / "events.csv"
        self.trade_path = self.csv_dir / "trades.csv"
        self.snapshot_path = self.csv_dir / "symbol_snapshots.csv"
        self._ensure_headers()

    def _ensure_headers(self) -> None:
        if not self.event_path.exists():
            with self.event_path.open("w", newline="", encoding="utf-8") as fp:
                csv.writer(fp).writerow(["id", "ts", "level", "source", "message", "data"])
        if not self.trade_path.exists():
            with self.trade_path.open("w", newline="", encoding="utf-8") as fp:
                csv.writer(fp).writerow(
                    ["ts_ms", "exchange", "symbol", "side", "quantity", "price", "order_id", "tag"]
                )
        if not self.snapshot_path.exists():
            with self.snapshot_path.open("w", newline="", encoding="utf-8") as fp:
                csv.writer(fp).writerow(
                    [
                        "updated_at",
                        "symbol",
                        "status",
                        "signal",
                        "spread_bps",
                        "zscore",
                        "net_position",
                        "target_position",
                    ]
                )

    def log_event(self, event: EventRecord) -> None:
        with self.event_path.open("a", newline="", encoding="utf-8") as fp:
            csv.writer(fp).writerow(
                [
                    event.id,
                    event.ts,
                    event.level.value,
                    event.source,
                    event.message,
                    event.data,
                ]
            )

    def log_trade(self, fill: TradeFill) -> None:
        with self.trade_path.open("a", newline="", encoding="utf-8") as fp:
            csv.writer(fp).writerow(
                [
                    fill.timestamp_ms,
                    fill.exchange.value,
                    fill.symbol,
                    fill.side.value,
                    str(fill.quantity),
                    str(fill.price),
                    fill.order_id,
                    fill.tag,
                ]
            )

    def log_snapshot(self, snapshot: SymbolSnapshot) -> None:
        with self.snapshot_path.open("a", newline="", encoding="utf-8") as fp:
            csv.writer(fp).writerow(
                [
                    snapshot.updated_at,
                    snapshot.symbol,
                    snapshot.status,
                    snapshot.signal,
                    float(snapshot.spread_bps),
                    float(snapshot.zscore),
                    float(snapshot.net_position),
                    float(snapshot.target_position),
                ]
            )
