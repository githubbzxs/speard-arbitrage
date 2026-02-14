"""全市场名义价差扫描。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from statistics import mean, pstdev
from typing import Any

import ccxt.async_support as ccxt  # type: ignore
from pysdk.grvt_ccxt_env import GrvtEnv as GrvtCcxtEnv
from pysdk.grvt_ccxt_pro import GrvtCcxtPro
from pysdk.grvt_raw_async import GrvtRawAsync
from pysdk.grvt_raw_base import GrvtApiConfig, GrvtError
from pysdk.grvt_raw_env import GrvtEnv as GrvtRawEnv
from pysdk.grvt_raw_types import ApiGetAllInitialLeverageRequest

from ..config import AppConfig
from ..models import utc_iso

DEFAULT_SCAN_INTERVAL_SEC = 300
DEFAULT_TOP_LIMIT = 200
MAX_TOP_LIMIT = 2000
DEFAULT_SPEED_WINDOW_SEC = 600
DEFAULT_WARMUP_POLL_SEC = 0.3
DEFAULT_MIN_EFFECTIVE_LEVERAGE = 50.0

ZSCORE_STATUS_READY = "ready"
ZSCORE_STATUS_INSUFFICIENT_SAMPLES = "insufficient_samples"
ZSCORE_STATUS_ZERO_STD = "zero_std"
SKIP_REASON_EFFECTIVE_LEVERAGE_BELOW_TARGET = "effective_leverage_below_50x"

# 官方兜底费率（当接口字段缺失时使用）：
# Paradex: https://docs.paradex.trade/risk/fees-and-discounts
# GRVT: https://help.grvt.io/hc/en-us/articles/10465949828111
DEFAULT_OFFICIAL_PARADEX_TAKER_FEE = Decimal("0.0002")
DEFAULT_OFFICIAL_GRVT_TAKER_FEE = Decimal("0.0002")
DEFAULT_OFFICIAL_GRVT_MAKER_FEE = Decimal("0.0002")


def _is_valid_hex_key(value: str) -> bool:
    normalized = value.strip()
    if normalized.startswith(("0x", "0X")):
        normalized = normalized[2:]
    if not normalized:
        return False
    if len(normalized) % 2 != 0:
        return False
    try:
        bytes.fromhex(normalized)
        return True
    except ValueError:
        return False


def _to_decimal(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and (raw != raw):
            return None
        return Decimal(str(raw))
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            return Decimal(stripped)
        except InvalidOperation:
            return None
    return None


def _sanitize_leverage(raw: Decimal | float | int) -> float:
    value = float(raw)
    if value < 1:
        return 1.0
    if value > 200:
        return 200.0
    return value


def _extract_paradex_max_leverage(market: dict[str, Any]) -> float | None:
    limits = market.get("limits")
    if isinstance(limits, dict):
        leverage = limits.get("leverage")
        if isinstance(leverage, dict):
            parsed = _to_decimal(leverage.get("max"))
            if parsed is not None and parsed > 0:
                return _sanitize_leverage(parsed)

    info = market.get("info")
    if not isinstance(info, dict):
        return None

    margin_params = info.get("delta1_cross_margin_params")
    if not isinstance(margin_params, dict):
        return None

    imf_base = _to_decimal(margin_params.get("imf_base"))
    if imf_base is None or imf_base <= 0:
        return None

    leverage = Decimal("1") / imf_base
    if leverage <= 0:
        return None
    return _sanitize_leverage(leverage)


def _extract_paradex_taker_fee(market: dict[str, Any]) -> Decimal | None:
    taker = _to_decimal(market.get("taker"))
    if taker is None:
        return None
    return taker


def _extract_grvt_taker_fee(market: dict[str, Any]) -> Decimal | None:
    taker = _to_decimal(market.get("taker"))
    if taker is None:
        return None
    return taker


def _extract_grvt_maker_fee(market: dict[str, Any]) -> Decimal | None:
    maker = _to_decimal(market.get("maker"))
    if maker is None:
        return None
    return maker


def _extract_paradex_top(levels: Any) -> Decimal | None:
    if not isinstance(levels, list) or not levels:
        return None
    top = levels[0]
    if not isinstance(top, list) or len(top) < 1:
        return None
    return _to_decimal(top[0])


def _extract_grvt_top(levels: Any) -> Decimal | None:
    if not isinstance(levels, list) or not levels:
        return None

    top = levels[0]
    if isinstance(top, dict):
        return _to_decimal(top.get("price"))

    if isinstance(top, list) and len(top) > 0:
        return _to_decimal(top[0])

    return None


def _extract_grvt_base_symbol(market: dict[str, Any]) -> str:
    base = str(market.get("base") or "").upper().strip()
    if base:
        return base

    instrument = str(market.get("instrument") or "")
    if "_" in instrument:
        return instrument.split("_", 1)[0].upper().strip()

    return ""


class NominalSpreadScanner:
    """全市场名义价差扫描器（真实行情）。"""

    def __init__(
        self,
        config: AppConfig,
        scan_interval_sec: int = DEFAULT_SCAN_INTERVAL_SEC,
        default_limit: int = DEFAULT_TOP_LIMIT,
    ) -> None:
        self._config = config
        self._scan_interval_sec = max(5, int(scan_interval_sec))
        self._default_limit = max(1, min(int(default_limit), MAX_TOP_LIMIT))
        self._history_retention = max(
            self._history_capacity(),
            int(getattr(getattr(config, "market_warmup", None), "history_retention", 2000)),
        )
        self._min_effective_leverage = DEFAULT_MIN_EFFECTIVE_LEVERAGE

        self._rows: list[dict[str, Any]] = []
        self._updated_at = ""
        self._last_refresh_monotonic = 0.0
        self._last_error = ""
        self._configured_symbols = 0
        self._comparable_symbols = 0
        self._scanned_symbols = 0
        self._skipped_reasons: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._history_by_symbol: dict[str, deque[Decimal]] = {}
        self._history_seeded_symbols: set[str] = set()
        self._history_append_counter_by_symbol: dict[str, int] = {}
        self._edge_pct_history_by_symbol: dict[str, deque[tuple[float, Decimal]]] = {}
        self._warmup_required_samples = max(1, int(self._config.strategy.min_samples))
        self._warmup_done = False
        self._warmup_last_message = "尚未开始"
        self._warmup_symbol_total = 0
        self._warmup_symbol_ready = 0
        self._warmup_symbol_samples: dict[str, int] = {}
        self._warmup_symbols: list[str] = []
        self._ensure_market_history_schema()

    def _resolve_effective_leverage(self, paradex_max_leverage: Any, grvt_max_leverage: Any) -> float | None:
        if paradex_max_leverage is None or grvt_max_leverage is None:
            return None
        try:
            return min(_sanitize_leverage(paradex_max_leverage), _sanitize_leverage(grvt_max_leverage))
        except (TypeError, ValueError):
            return None

    def _edge_pct_history_for(self, symbol: str) -> deque[tuple[float, Decimal]]:
        return self._edge_pct_history_by_symbol.setdefault(symbol, deque(maxlen=240))

    def _ensure_market_history_schema(self) -> None:
        sqlite_path = str(self._config.storage.sqlite_path).strip()
        if not sqlite_path:
            return
        try:
            conn = sqlite3.connect(sqlite_path)
            try:
                with conn:
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
                    conn.execute(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_market_spread_history_unique
                        ON market_spread_history(symbol, ts, source)
                        """
                    )
                    conn.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_market_spread_history_symbol_id
                        ON market_spread_history(symbol, id)
                        """
                    )
            finally:
                conn.close()
        except Exception:
            return

    def _append_market_history_point(
        self,
        *,
        symbol: str,
        signed_edge_bps: Decimal,
        tradable_edge_pct: Decimal,
        ts: str | None = None,
        source: str = "scanner",
    ) -> None:
        history = self._history_for(symbol)

        sqlite_path = str(self._config.storage.sqlite_path).strip()
        if not sqlite_path:
            history.append(signed_edge_bps)
            return

        inserted = True
        try:
            conn = sqlite3.connect(sqlite_path)
            try:
                with conn:
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO market_spread_history
                        (ts, symbol, signed_edge_bps, tradable_edge_pct, source)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            ts or utc_iso(),
                            symbol,
                            str(signed_edge_bps),
                            str(tradable_edge_pct),
                            source,
                        ),
                    )
                inserted = bool(cursor.rowcount)
            finally:
                conn.close()
        except Exception:
            history.append(signed_edge_bps)
            return

        if not inserted:
            return

        history.append(signed_edge_bps)

        current_count = self._history_append_counter_by_symbol.get(symbol, 0) + 1
        self._history_append_counter_by_symbol[symbol] = current_count
        if current_count % 20 != 0:
            return

        try:
            conn = sqlite3.connect(sqlite_path)
            try:
                with conn:
                    conn.execute(
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
                        (symbol, symbol, self._history_retention),
                    )
            finally:
                conn.close()
        except Exception:
            return

    def _compute_spread_speed_metrics(self, symbol: str, edge_pct: Decimal) -> tuple[Decimal, Decimal, int]:
        now_ts = time.time()
        history = self._edge_pct_history_for(symbol)
        history.append((now_ts, edge_pct))

        # 仅保留最近窗口内样本，减少陈旧数据对速度与波动率的干扰。
        while history and (now_ts - history[0][0]) > DEFAULT_SPEED_WINDOW_SEC:
            history.popleft()

        samples = list(history)
        sample_count = len(samples)
        if sample_count < 2:
            return Decimal("0"), Decimal("0"), sample_count

        start_ts, start_val = samples[0]
        end_ts, end_val = samples[-1]
        elapsed_sec = max(end_ts - start_ts, 1e-6)
        speed_per_min = (end_val - start_val) / Decimal(str(elapsed_sec)) * Decimal("60")

        volatility = Decimal("0")
        if sample_count >= 2:
            volatility = Decimal(str(pstdev([float(item[1]) for item in samples])))

        return speed_per_min, volatility, sample_count

    def _history_capacity(self) -> int:
        return max(self._config.strategy.ma_window, self._config.strategy.std_window) * 2

    def _history_for(self, symbol: str) -> deque[Decimal]:
        return self._history_by_symbol.setdefault(symbol, deque(maxlen=self._history_retention))

    def _seed_history_from_repository(self, symbol: str) -> None:
        if symbol in self._history_seeded_symbols:
            return
        self._history_seeded_symbols.add(symbol)

        sqlite_path = str(self._config.storage.sqlite_path).strip()
        if not sqlite_path:
            return

        history = self._history_for(symbol)

        try:
            conn = sqlite3.connect(sqlite_path)
            try:
                history_rows = conn.execute(
                    """
                    SELECT signed_edge_bps
                    FROM market_spread_history
                    WHERE symbol = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (symbol, self._history_retention),
                ).fetchall()
                has_market_history = len(history_rows) > 0
                if not has_market_history:
                    snapshot_rows = conn.execute(
                        """
                        SELECT ts, data_json
                        FROM symbol_snapshots
                        WHERE symbol = ?
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (symbol, self._history_retention),
                    ).fetchall()
                else:
                    snapshot_rows = []
            finally:
                conn.close()
        except Exception:
            return

        if history_rows:
            for row in reversed(history_rows):
                if not row:
                    continue
                value = _to_decimal(row[0])
                if value is None:
                    continue
                history.append(value)
            return

        migrated_points: list[tuple[str, Decimal]] = []
        for row in reversed(snapshot_rows):
            if not row or len(row) < 2:
                continue
            raw_ts = row[0]
            raw_payload = row[1]
            if not isinstance(raw_payload, str) or not raw_payload.strip():
                continue
            try:
                parsed = json.loads(raw_payload)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            value = _to_decimal(parsed.get("spread_bps"))
            if value is None:
                continue
            migrated_points.append((str(raw_ts or utc_iso()), value))

        for ts, value in migrated_points:
            self._append_market_history_point(
                symbol=symbol,
                signed_edge_bps=value,
                tradable_edge_pct=value / Decimal("100"),
                ts=ts,
                source="snapshot_migration",
            )

    def _compute_zscore(self, symbol: str) -> tuple[Decimal, str, int]:
        self._seed_history_from_repository(symbol)
        history = self._history_for(symbol)

        samples = list(history)
        sample_count = len(samples)
        if sample_count < self._config.strategy.min_samples:
            return Decimal("0"), ZSCORE_STATUS_INSUFFICIENT_SAMPLES, sample_count

        ma_window = max(1, min(self._config.strategy.ma_window, sample_count))
        std_window = max(1, min(self._config.strategy.std_window, sample_count))
        ma_value = Decimal(str(mean([float(x) for x in samples[-ma_window:]])))
        std_value = Decimal(str(pstdev([float(x) for x in samples[-std_window:]])))
        if std_value <= 0:
            return Decimal("0"), ZSCORE_STATUS_ZERO_STD, sample_count

        current_value = samples[-1]
        zscore = (current_value - ma_value) / std_value
        return zscore, ZSCORE_STATUS_READY, sample_count

    def _update_warmup_progress(self, symbols: list[str]) -> None:
        unique_symbols = sorted({item.strip().upper() for item in symbols if item and item.strip()})
        self._warmup_symbols = unique_symbols
        self._warmup_symbol_total = len(unique_symbols)

        samples_map: dict[str, int] = {}
        ready_count = 0
        for symbol in unique_symbols:
            self._seed_history_from_repository(symbol)
            sample_count = len(self._history_for(symbol))
            samples_map[symbol] = sample_count
            if sample_count >= self._warmup_required_samples:
                ready_count += 1

        self._warmup_symbol_samples = samples_map
        self._warmup_symbol_ready = ready_count
        if self._warmup_symbol_total == 0:
            self._warmup_done = True
            self._warmup_last_message = "无需预热：暂无可比币对"
            return

        self._warmup_done = self._warmup_symbol_ready >= self._warmup_symbol_total
        if self._warmup_done:
            self._warmup_last_message = "预热完成"
        else:
            self._warmup_last_message = (
                f"预热中：{self._warmup_symbol_ready}/{self._warmup_symbol_total} "
                f"个币对达到 {self._warmup_required_samples} 样本"
            )

    def get_warmup_status(self) -> dict[str, Any]:
        remaining = max(0, self._warmup_symbol_total - self._warmup_symbol_ready)
        message = self._warmup_last_message
        if not self._warmup_done and self._last_error:
            message = self._last_error
        return {
            "done": self._warmup_done,
            "message": message,
            "required_samples": self._warmup_required_samples,
            "symbols_total": self._warmup_symbol_total,
            "symbols_ready": self._warmup_symbol_ready,
            "symbols_pending": remaining,
            "sample_counts": dict(self._warmup_symbol_samples),
            "updated_at": self._updated_at or utc_iso(),
        }

    def is_warmup_ready(self) -> bool:
        return bool(self._warmup_done)

    def get_last_error(self) -> str:
        return str(self._last_error or "")

    def build_warmup_payload(self, *, limit: int) -> dict[str, Any]:
        status = self.get_warmup_status()
        return {
            "updated_at": self._updated_at or utc_iso(),
            "scan_interval_sec": self._scan_interval_sec,
            "limit": max(0, int(limit)),
            "configured_symbols": self._configured_symbols,
            "comparable_symbols": self._comparable_symbols,
            "executable_symbols": 0,
            "scanned_symbols": self._scanned_symbols,
            "total_symbols": 0,
            "skipped_count": sum(self._skipped_reasons.values()),
            "skipped_reasons": self._skipped_reasons,
            "fee_profile": {"paradex_leg": "taker", "grvt_leg": "maker"},
            "last_error": self._last_error or status["message"],
            "warmup_done": False,
            "warmup_progress": status,
            "rows": [],
        }

    async def warmup_until_ready(
        self,
        *,
        timeout_sec: float,
        poll_sec: float = DEFAULT_WARMUP_POLL_SEC,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(1.0, float(timeout_sec))
        while time.monotonic() < deadline:
            await self._ensure_cache(force_refresh=True)
            if self.is_warmup_ready():
                return self.get_warmup_status()
            await asyncio.sleep(max(0.05, float(poll_sec)))
        return self.get_warmup_status()

    async def get_top_spreads(
        self,
        limit: int = DEFAULT_TOP_LIMIT,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        requested_limit = int(limit)
        await self._ensure_cache(force_refresh=force_refresh)

        sorted_rows = sorted(
            self._rows,
            key=lambda item: (
                abs(float(item.get("spread_speed_pct_per_min", 0.0))),
                abs(float(item.get("zscore", 0.0))),
                float(item.get("gross_nominal_spread", 0.0)),
            ),
            reverse=True,
        )
        if requested_limit <= 0:
            resolved_limit = len(sorted_rows)
            output_rows = sorted_rows
        else:
            resolved_limit = max(1, min(requested_limit, MAX_TOP_LIMIT))
            output_rows = sorted_rows[:resolved_limit]

        warmup_status = self.get_warmup_status()

        return {
            "updated_at": self._updated_at,
            "scan_interval_sec": self._scan_interval_sec,
            "limit": resolved_limit,
            "configured_symbols": self._configured_symbols,
            "comparable_symbols": self._comparable_symbols,
            "executable_symbols": len(sorted_rows),
            "scanned_symbols": self._scanned_symbols,
            "total_symbols": len(sorted_rows),
            "skipped_count": sum(self._skipped_reasons.values()),
            "skipped_reasons": self._skipped_reasons,
            "fee_profile": {
                "paradex_leg": "taker",
                "grvt_leg": "maker",
            },
            "last_error": self._last_error or None,
            "warmup_done": warmup_status["done"],
            "warmup_progress": warmup_status,
            "rows": output_rows,
        }

    async def get_spreads(
        self,
        limit: int = 0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        return await self.get_top_spreads(limit=limit, force_refresh=force_refresh)

    async def _ensure_cache(self, force_refresh: bool) -> None:
        if not force_refresh and self._rows and (time.monotonic() - self._last_refresh_monotonic) < self._scan_interval_sec:
            return

        async with self._lock:
            if not force_refresh and self._rows and (time.monotonic() - self._last_refresh_monotonic) < self._scan_interval_sec:
                return
            await self._refresh_once()

    async def _refresh_once(self) -> None:
        try:
            scanned_rows, configured_symbols, comparable_symbols, skipped_reasons, warmup_symbols = await self._scan_all_symbols()
            self._rows = scanned_rows
            self._configured_symbols = configured_symbols
            self._comparable_symbols = comparable_symbols
            self._scanned_symbols = comparable_symbols
            self._skipped_reasons = skipped_reasons
            self._update_warmup_progress(warmup_symbols)
            self._updated_at = utc_iso()
            self._last_refresh_monotonic = time.monotonic()
            self._last_error = ""
        except Exception as exc:  # pragma: no cover - 网络异常分支
            raw_message = str(exc).strip()
            if "non-hexadecimal digit found" in raw_message.lower():
                raw_message = "GRVT private_key 格式错误：必须是十六进制字符串（可带 0x 前缀）"
            self._last_error = f"扫描失败: {raw_message or '未知异常'}"
            self._warmup_done = False
            self._warmup_symbol_total = 0
            self._warmup_symbol_ready = 0
            self._warmup_symbol_samples = {}
            self._warmup_last_message = self._last_error
            self._updated_at = utc_iso()
            self._last_refresh_monotonic = time.monotonic()
            if not self._rows:
                self._rows = []

    async def _scan_all_symbols(self) -> tuple[list[dict[str, Any]], int, int, dict[str, int], list[str]]:
        paradex_client = ccxt.paradex({"enableRateLimit": True})
        grvt_client = GrvtCcxtPro(env=self._resolve_grvt_ccxt_env(), parameters=self._build_grvt_ccxt_params())

        try:
            await asyncio.gather(paradex_client.load_markets(), grvt_client.load_markets())
            grvt_leverage_map = await self._fetch_grvt_leverage_map()

            paradex_map = self._collect_paradex_markets(paradex_client.markets)
            grvt_map = self._collect_grvt_markets(grvt_client.markets, grvt_leverage_map)

            shared_bases = sorted(set(paradex_map.keys()) & set(grvt_map.keys()))
            configured_bases = {
                str(cfg.base_asset).upper().strip()
                for cfg in self._config.symbols
                if cfg.enabled and str(cfg.base_asset).strip()
            }
            skipped_reasons: dict[str, int] = {}
            target_bases: list[str] = []
            for base_asset in shared_bases:
                para_info = paradex_map[base_asset]
                grvt_info = grvt_map[base_asset]
                paradex_max_leverage = para_info.get("max_leverage")
                grvt_max_leverage = grvt_info.get("max_leverage")
                if paradex_max_leverage is None:
                    skipped_reasons["paradex_leverage_missing"] = skipped_reasons.get("paradex_leverage_missing", 0) + 1
                    continue
                if grvt_max_leverage is None:
                    skipped_reasons["grvt_leverage_missing"] = skipped_reasons.get("grvt_leverage_missing", 0) + 1
                    continue

                effective_leverage = self._resolve_effective_leverage(paradex_max_leverage, grvt_max_leverage)
                if effective_leverage is None:
                    skipped_reasons["invalid_leverage"] = skipped_reasons.get("invalid_leverage", 0) + 1
                    continue
                if effective_leverage < self._min_effective_leverage:
                    skipped_reasons[SKIP_REASON_EFFECTIVE_LEVERAGE_BELOW_TARGET] = (
                        skipped_reasons.get(SKIP_REASON_EFFECTIVE_LEVERAGE_BELOW_TARGET, 0) + 1
                    )
                    continue
                target_bases.append(base_asset)

            warmup_symbols = [f"{base}-PERP" for base in target_bases]
            await self._backfill_missing_history(
                paradex_client=paradex_client,
                grvt_client=grvt_client,
                shared_bases=target_bases,
                paradex_map=paradex_map,
                grvt_map=grvt_map,
            )
            semaphore = asyncio.Semaphore(6)

            async def fetch_one(base_asset: str) -> tuple[dict[str, Any] | None, str | None]:
                async with semaphore:
                    para_info = paradex_map[base_asset]
                    grvt_info = grvt_map[base_asset]
                    return await self._fetch_pair_row(
                        paradex_client=paradex_client,
                        grvt_client=grvt_client,
                        base_asset=base_asset,
                        paradex_info=para_info,
                        grvt_info=grvt_info,
                    )

            gathered = await asyncio.gather(*(fetch_one(base) for base in target_bases), return_exceptions=False)
            rows: list[dict[str, Any]] = []
            for row, reason in gathered:
                if row is not None:
                    rows.append(row)
                elif reason:
                    skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1

            return rows, len(configured_bases), len(target_bases), skipped_reasons, warmup_symbols
        finally:
            await paradex_client.close()
            session = getattr(grvt_client, "_session", None)
            if session is not None and not session.closed:
                await session.close()

    async def _backfill_missing_history(
        self,
        *,
        paradex_client: Any,
        grvt_client: Any,
        shared_bases: list[str],
        paradex_map: dict[str, dict[str, Any]],
        grvt_map: dict[str, dict[str, Any]],
    ) -> None:
        if not shared_bases:
            return

        semaphore = asyncio.Semaphore(4)

        async def backfill_one(base_asset: str) -> None:
            symbol = f"{base_asset}-PERP"
            self._seed_history_from_repository(symbol)
            history = self._history_for(symbol)
            missing = self._warmup_required_samples - len(history)
            if missing <= 0:
                return
            paradex_market = str(paradex_map.get(base_asset, {}).get("market") or "").strip()
            grvt_market = str(grvt_map.get(base_asset, {}).get("market") or "").strip()
            if not paradex_market or not grvt_market:
                return

            async with semaphore:
                await self._backfill_symbol_history_from_ohlcv(
                    paradex_client=paradex_client,
                    grvt_client=grvt_client,
                    symbol=symbol,
                    paradex_market=paradex_market,
                    grvt_market=grvt_market,
                    missing_samples=missing,
                )

        await asyncio.gather(*(backfill_one(base_asset) for base_asset in shared_bases), return_exceptions=True)

    async def _backfill_symbol_history_from_ohlcv(
        self,
        *,
        paradex_client: Any,
        grvt_client: Any,
        symbol: str,
        paradex_market: str,
        grvt_market: str,
        missing_samples: int,
    ) -> None:
        # 缺口补齐策略：优先拉取两所 1m K 线，按时间戳对齐后回填 signed_edge_bps。
        fetch_limit = max(self._warmup_required_samples * 4, missing_samples * 6, 120)
        fetch_limit = min(fetch_limit, 720)

        paradex_task = paradex_client.fetch_ohlcv(paradex_market, timeframe="1m", limit=fetch_limit)
        grvt_task = grvt_client.fetch_ohlcv(grvt_market, timeframe="1m", limit=fetch_limit)
        paradex_ohlcv, grvt_ohlcv = await asyncio.gather(paradex_task, grvt_task, return_exceptions=True)

        if isinstance(paradex_ohlcv, Exception) or isinstance(grvt_ohlcv, Exception):
            return

        paradex_map: dict[int, Decimal] = {}
        for row in paradex_ohlcv:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            ts_raw = row[0]
            close_raw = row[4]
            if not isinstance(ts_raw, (int, float)):
                continue
            close_price = _to_decimal(close_raw)
            if close_price is None or close_price <= 0:
                continue
            paradex_map[int(ts_raw)] = close_price

        grvt_map: dict[int, Decimal] = {}
        for row in grvt_ohlcv:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            ts_raw = row[0]
            close_raw = row[4]
            if not isinstance(ts_raw, (int, float)):
                continue
            close_price = _to_decimal(close_raw)
            if close_price is None or close_price <= 0:
                continue
            grvt_map[int(ts_raw)] = close_price

        aligned_ts = sorted(set(paradex_map.keys()) & set(grvt_map.keys()))
        if not aligned_ts:
            return

        for ts_ms in aligned_ts:
            paradex_close = paradex_map[ts_ms]
            grvt_close = grvt_map[ts_ms]
            reference_mid = (paradex_close + grvt_close) / Decimal("2")
            if reference_mid <= 0:
                continue
            signed_edge_bps = ((grvt_close - paradex_close) / reference_mid) * Decimal("10000")
            edge_pct = signed_edge_bps / Decimal("100")
            ts_iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
            self._append_market_history_point(
                symbol=symbol,
                signed_edge_bps=signed_edge_bps,
                tradable_edge_pct=edge_pct,
                ts=ts_iso,
                source="ohlcv_backfill",
            )

    async def _fetch_pair_row(
        self,
        paradex_client: Any,
        grvt_client: Any,
        base_asset: str,
        paradex_info: dict[str, Any],
        grvt_info: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        paradex_market = paradex_info["market"]
        grvt_market = grvt_info["market"]
        paradex_max_leverage = paradex_info.get("max_leverage")
        grvt_max_leverage = grvt_info.get("max_leverage")

        if paradex_max_leverage is None:
            return None, "paradex_leverage_missing"
        if grvt_max_leverage is None:
            return None, "grvt_leverage_missing"
        effective_leverage = self._resolve_effective_leverage(paradex_max_leverage, grvt_max_leverage)
        if effective_leverage is None:
            return None, "invalid_leverage"
        if effective_leverage < self._min_effective_leverage:
            return None, SKIP_REASON_EFFECTIVE_LEVERAGE_BELOW_TARGET

        paradex_depth_task = paradex_client.fetch_order_book(paradex_market, limit=5)
        grvt_depth_task = grvt_client.fetch_order_book(grvt_market, limit=10)

        paradex_depth, grvt_depth = await asyncio.gather(
            paradex_depth_task,
            grvt_depth_task,
            return_exceptions=True,
        )

        if isinstance(paradex_depth, Exception):
            return None, "paradex_orderbook_error"
        if isinstance(grvt_depth, Exception):
            return None, "grvt_orderbook_error"

        paradex_bid = _extract_paradex_top(paradex_depth.get("bids"))
        paradex_ask = _extract_paradex_top(paradex_depth.get("asks"))
        grvt_bid = _extract_grvt_top(grvt_depth.get("bids"))
        grvt_ask = _extract_grvt_top(grvt_depth.get("asks"))

        if (
            paradex_bid is None
            or paradex_ask is None
            or grvt_bid is None
            or grvt_ask is None
            or paradex_bid <= 0
            or paradex_ask <= 0
            or grvt_bid <= 0
            or grvt_ask <= 0
            or paradex_bid >= paradex_ask
            or grvt_bid >= grvt_ask
        ):
            return None, "invalid_bbo"

        paradex_mid = (paradex_bid + paradex_ask) / Decimal("2")
        grvt_mid = (grvt_bid + grvt_ask) / Decimal("2")
        reference_mid = (paradex_mid + grvt_mid) / Decimal("2")
        symbol = f"{base_asset}-PERP"

        edge_para_to_grvt_bps = Decimal("0")
        edge_grvt_to_para_bps = Decimal("0")
        if reference_mid > 0:
            edge_para_to_grvt_bps = ((grvt_bid - paradex_ask) / reference_mid) * Decimal("10000")
            edge_grvt_to_para_bps = ((paradex_bid - grvt_ask) / reference_mid) * Decimal("10000")
        signed_edge_bps = edge_para_to_grvt_bps if edge_para_to_grvt_bps >= edge_grvt_to_para_bps else -edge_grvt_to_para_bps
        self._append_market_history_point(
            symbol=symbol,
            signed_edge_bps=signed_edge_bps,
            tradable_edge_pct=(signed_edge_bps / Decimal("100")),
            source="scanner",
        )
        zscore, zscore_status, history_samples = self._compute_zscore(symbol)

        # 口径对齐执行引擎：Paradex taker + GRVT maker。
        edge_sell_paradex_buy_grvt = paradex_bid - grvt_bid
        edge_buy_paradex_sell_grvt = grvt_ask - paradex_ask
        tradable_edge_price = max(edge_sell_paradex_buy_grvt, edge_buy_paradex_sell_grvt)

        if tradable_edge_price <= 0:
            return None, "edge_not_positive"

        direction = (
            "sell_paradex_taker_buy_grvt_maker"
            if tradable_edge_price == edge_sell_paradex_buy_grvt
            else "buy_paradex_taker_sell_grvt_maker"
        )

        tradable_edge_bps = Decimal("0")
        if reference_mid > 0:
            tradable_edge_bps = (tradable_edge_price / reference_mid) * Decimal("10000")
        tradable_edge_pct = tradable_edge_bps / Decimal("100")
        spread_speed_pct_per_min, spread_volatility_pct, speed_samples = self._compute_spread_speed_metrics(
            symbol=symbol,
            edge_pct=tradable_edge_pct,
        )

        gross_nominal_spread = tradable_edge_price * Decimal(str(effective_leverage))

        paradex_fee_rate, paradex_fee_source = self._resolve_paradex_taker_fee(paradex_info)
        grvt_fee_rate, grvt_fee_source = self._resolve_grvt_maker_fee(grvt_info)
        total_fee_rate = paradex_fee_rate + grvt_fee_rate

        # 与名义价差同口径：使用参考中间价 * 有效杠杆作为名义 notional。
        fee_cost_estimate = reference_mid * Decimal(str(effective_leverage)) * total_fee_rate
        net_nominal_spread = gross_nominal_spread - fee_cost_estimate
        if net_nominal_spread <= 0:
            return None, "net_spread_not_positive"

        return (
            {
                "symbol": symbol,
                "base_asset": base_asset,
                "paradex_market": paradex_market,
                "grvt_market": grvt_market,
                "paradex_bid": float(paradex_bid),
                "paradex_ask": float(paradex_ask),
                "paradex_mid": float(paradex_mid),
                "grvt_bid": float(grvt_bid),
                "grvt_ask": float(grvt_ask),
                "grvt_mid": float(grvt_mid),
                "reference_mid": float(reference_mid),
                "tradable_edge_price": float(tradable_edge_price),
                "tradable_edge_pct": float(tradable_edge_pct),
                "tradable_edge_bps": float(tradable_edge_bps),
                "direction": direction,
                "paradex_max_leverage": float(paradex_max_leverage),
                "grvt_max_leverage": float(grvt_max_leverage),
                "effective_leverage": float(effective_leverage),
                "gross_nominal_spread": float(gross_nominal_spread),
                "fee_cost_estimate": float(fee_cost_estimate),
                "net_nominal_spread": float(net_nominal_spread),
                "paradex_fee_rate": float(paradex_fee_rate),
                "grvt_fee_rate": float(grvt_fee_rate),
                "fee_source": {
                    "paradex": paradex_fee_source,
                    "grvt": grvt_fee_source,
                },
                "zscore": float(zscore),
                "zscore_ready": zscore_status == ZSCORE_STATUS_READY,
                "zscore_status": zscore_status,
                "history_samples": history_samples,
                "required_samples": self._warmup_required_samples,
                "spread_speed_pct_per_min": float(spread_speed_pct_per_min),
                "spread_volatility_pct": float(spread_volatility_pct),
                "speed_samples": speed_samples,
                "updated_at": utc_iso(),
            },
            None,
        )

    def _collect_paradex_markets(self, markets: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}

        for item in markets.values():
            if not isinstance(item, dict):
                continue
            if not item.get("swap"):
                continue

            base_asset = str(item.get("base") or "").upper().strip()
            quote_asset = str(item.get("quote") or "").upper().strip()
            market_symbol = str(item.get("symbol") or "").strip()
            if not base_asset or not market_symbol:
                continue
            if quote_asset not in {"USDC", "USD"}:
                continue

            priority = 2 if quote_asset == "USDC" else 1
            current = result.get(base_asset)
            if current is not None and current.get("priority", 0) >= priority:
                continue

            result[base_asset] = {
                "market": market_symbol,
                "quote": quote_asset,
                "priority": priority,
                "max_leverage": _extract_paradex_max_leverage(item),
                "taker_fee_rate": _extract_paradex_taker_fee(item),
            }

        return result

    def _collect_grvt_markets(
        self,
        markets: dict[str, Any],
        leverage_map: dict[str, float],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}

        for item in markets.values():
            if not isinstance(item, dict):
                continue

            kind = str(item.get("kind") or "").upper().strip()
            if kind not in {"PERPETUAL", "PERP"}:
                continue

            quote_asset = str(item.get("quote") or "").upper().strip()
            if quote_asset not in {"USDT", "USDC", "USD"}:
                continue

            market_symbol = str(item.get("instrument") or "").strip()
            if not market_symbol:
                continue

            base_asset = _extract_grvt_base_symbol(item)
            if not base_asset:
                continue

            priority = 3 if quote_asset == "USDT" else (2 if quote_asset == "USDC" else 1)
            current = result.get(base_asset)
            if current is not None and current.get("priority", 0) >= priority:
                continue

            result[base_asset] = {
                "market": market_symbol,
                "quote": quote_asset,
                "priority": priority,
                "max_leverage": leverage_map.get(market_symbol),
                "taker_fee_rate": _extract_grvt_taker_fee(item),
                "maker_fee_rate": _extract_grvt_maker_fee(item),
            }

        return result

    def _resolve_paradex_taker_fee(self, paradex_info: dict[str, Any]) -> tuple[Decimal, str]:
        fee = paradex_info.get("taker_fee_rate")
        if isinstance(fee, Decimal):
            return fee, "api"
        return DEFAULT_OFFICIAL_PARADEX_TAKER_FEE, "official"

    def _resolve_grvt_taker_fee(self, grvt_info: dict[str, Any]) -> tuple[Decimal, str]:
        fee = grvt_info.get("taker_fee_rate")
        if isinstance(fee, Decimal):
            return fee, "api"
        return DEFAULT_OFFICIAL_GRVT_TAKER_FEE, "official"

    def _resolve_grvt_maker_fee(self, grvt_info: dict[str, Any]) -> tuple[Decimal, str]:
        fee = grvt_info.get("maker_fee_rate")
        if isinstance(fee, Decimal):
            return fee, "api"
        return DEFAULT_OFFICIAL_GRVT_MAKER_FEE, "official"

    def _build_grvt_ccxt_params(self) -> dict[str, str]:
        credentials = self._config.grvt.credentials
        return {
            "trading_account_id": credentials.trading_account_id,
            "private_key": credentials.private_key,
            "api_key": credentials.api_key,
        }

    async def _fetch_grvt_leverage_map(self) -> dict[str, float]:
        credentials = self._config.grvt.credentials
        if not credentials.trading_account_id.strip() or not credentials.private_key.strip() or not credentials.api_key.strip():
            raise ValueError("GRVT 凭证不足，无法获取真实杠杆（需要 api_key/private_key/trading_account_id）")
        if not _is_valid_hex_key(credentials.private_key):
            raise ValueError("GRVT private_key 格式错误：必须是十六进制字符串（可带 0x 前缀）")

        raw_client = GrvtRawAsync(
            GrvtApiConfig(
                env=self._resolve_grvt_raw_env(),
                trading_account_id=credentials.trading_account_id,
                private_key=credentials.private_key,
                api_key=credentials.api_key,
                logger=None,
            )
        )

        try:
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    response = await raw_client.get_all_initial_leverage_v1(
                        ApiGetAllInitialLeverageRequest(sub_account_id=credentials.trading_account_id)
                    )
                    if isinstance(response, GrvtError):
                        raise ValueError(
                            "GRVT 杠杆接口错误: "
                            f"{response.code} {response.message} "
                            "（请确认 trading_account_id 与 API Key 属于同一子账户）"
                        )

                    leverage_map: dict[str, float] = {}
                    for item in response.results:
                        parsed = _to_decimal(item.max_leverage)
                        if parsed is None or parsed <= 0:
                            continue
                        leverage_map[item.instrument] = _sanitize_leverage(parsed)

                    if not leverage_map:
                        raise ValueError("GRVT 杠杆接口返回为空")

                    return leverage_map
                except Exception as exc:  # pragma: no cover - 网络抖动重试分支
                    last_error = exc
                    if attempt < 2:
                        await asyncio.sleep(0.35 * (attempt + 1))
                        continue
                    break

            raise ValueError(str(last_error or "GRVT 杠杆接口异常"))
        finally:
            session = getattr(raw_client, "_session", None)
            if session is not None and not session.closed:
                await session.close()

    def _resolve_grvt_ccxt_env(self) -> GrvtCcxtEnv:
        env = self._config.grvt.environment.lower().strip()
        if env == "testnet":
            return GrvtCcxtEnv.TESTNET
        if env == "staging":
            return GrvtCcxtEnv.STAGING
        if env == "dev":
            return GrvtCcxtEnv.DEV
        return GrvtCcxtEnv.PROD

    def _resolve_grvt_raw_env(self) -> GrvtRawEnv:
        env = self._config.grvt.environment.lower().strip()
        if env == "testnet":
            return GrvtRawEnv.TESTNET
        if env == "staging":
            return GrvtRawEnv.STAGING
        if env == "dev":
            return GrvtRawEnv.DEV
        return GrvtRawEnv.PROD
