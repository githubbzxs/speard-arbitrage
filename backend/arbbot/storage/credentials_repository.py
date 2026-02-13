"""凭证持久化仓储。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..models import utc_iso


class CredentialsRepository:
    """负责交易所凭证的持久化与状态查询。"""

    _ALLOWED_FIELDS: dict[str, tuple[str, ...]] = {
        "paradex": ("api_key", "api_secret", "passphrase"),
        "grvt": ("api_key", "api_secret", "private_key", "trading_account_id"),
    }

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
                CREATE TABLE IF NOT EXISTS credentials (
                    exchange TEXT,
                    field TEXT,
                    value TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (exchange, field)
                )
                """
            )

    def save_credentials(self, payload: dict[str, dict[str, Any]]) -> None:
        """保存凭证；空字符串表示清空字段。"""
        timestamp = utc_iso()
        with self._lock, self._conn:
            for exchange, fields in self._ALLOWED_FIELDS.items():
                exchange_payload = payload.get(exchange)
                if not isinstance(exchange_payload, dict):
                    continue

                for field in fields:
                    if field not in exchange_payload:
                        continue

                    raw_value = exchange_payload[field]
                    if raw_value is None:
                        continue
                    value = str(raw_value)

                    if value == "":
                        self._conn.execute(
                            "DELETE FROM credentials WHERE exchange = ? AND field = ?",
                            (exchange, field),
                        )
                        continue

                    self._conn.execute(
                        """
                        INSERT INTO credentials (exchange, field, value, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(exchange, field)
                        DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                        """,
                        (exchange, field, value, timestamp),
                    )

    def get_status(self) -> dict[str, dict[str, dict[str, bool | str | None]]]:
        """返回脱敏状态，仅包含是否已配置、更新时间和掩码摘要。"""
        status: dict[str, dict[str, dict[str, bool | str | None]]] = {
            exchange: {
                field: {"configured": False, "updated_at": None, "masked": ""}
                for field in fields
            }
            for exchange, fields in self._ALLOWED_FIELDS.items()
        }

        with self._lock:
            rows = self._conn.execute(
                "SELECT exchange, field, value, updated_at FROM credentials"
            ).fetchall()

        for exchange, field, value, updated_at in rows:
            if exchange not in status:
                continue
            if field not in status[exchange]:
                continue
            value_text = str(value or "")
            status[exchange][field] = {
                "configured": bool(value_text),
                "updated_at": updated_at,
                "masked": self._mask_value(value_text),
            }

        return status

    def get_effective_credentials(self) -> dict[str, dict[str, str]]:
        """返回可应用到运行时的明文凭证字典。"""
        credentials: dict[str, dict[str, str]] = {
            exchange: {field: "" for field in fields}
            for exchange, fields in self._ALLOWED_FIELDS.items()
        }

        with self._lock:
            rows = self._conn.execute(
                "SELECT exchange, field, value FROM credentials"
            ).fetchall()

        for exchange, field, value in rows:
            if exchange not in credentials:
                continue
            if field not in credentials[exchange]:
                continue
            credentials[exchange][field] = str(value or "")

        return credentials

    def close(self) -> None:
        """关闭连接。"""
        self._conn.close()

    @staticmethod
    def _mask_value(value: str) -> str:
        if not value:
            return ""
        tail = value[-4:] if len(value) > 4 else value[-1:]
        return f"****{tail}"
