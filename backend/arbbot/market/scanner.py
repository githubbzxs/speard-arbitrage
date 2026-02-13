"""全市场名义价差扫描。"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import ccxt.async_support as ccxt  # type: ignore
from pysdk.grvt_ccxt_env import GrvtEnv
from pysdk.grvt_ccxt_pro import GrvtCcxtPro

from ..config import AppConfig
from ..models import utc_iso


DEFAULT_SCAN_INTERVAL_SEC = 300
DEFAULT_TOP_LIMIT = 10
DEFAULT_FALLBACK_LEVERAGE = 2.0
MAX_TOP_LIMIT = 100


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


def _sanitize_leverage(raw: float, fallback: float = DEFAULT_FALLBACK_LEVERAGE) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
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
                return float(parsed)

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
    return float(leverage)


def _extract_grvt_max_leverage(market: dict[str, Any]) -> float | None:
    direct_keys = (
        "max_leverage",
        "maxLeverage",
        "leverage_max",
        "leverageMax",
    )
    for key in direct_keys:
        value = _to_decimal(market.get(key))
        if value is not None and value > 0:
            return float(value)

    info = market.get("info")
    if not isinstance(info, dict):
        return None

    for key in direct_keys:
        value = _to_decimal(info.get(key))
        if value is not None and value > 0:
            return float(value)

    return None


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
        self._scan_interval_sec = max(60, int(scan_interval_sec))
        self._default_limit = max(1, min(int(default_limit), MAX_TOP_LIMIT))
        self._rows: list[dict[str, Any]] = []
        self._updated_at = ""
        self._last_refresh_monotonic = 0.0
        self._last_error = ""
        self._lock = asyncio.Lock()

    async def get_top_spreads(
        self,
        limit: int = DEFAULT_TOP_LIMIT,
        paradex_fallback_leverage: float = DEFAULT_FALLBACK_LEVERAGE,
        grvt_fallback_leverage: float = DEFAULT_FALLBACK_LEVERAGE,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        resolved_limit = max(1, min(int(limit), MAX_TOP_LIMIT))
        fallback_paradex = _sanitize_leverage(paradex_fallback_leverage)
        fallback_grvt = _sanitize_leverage(grvt_fallback_leverage)

        await self._ensure_cache(force_refresh=force_refresh)

        computed_rows: list[dict[str, Any]] = []
        for row in self._rows:
            computed_rows.append(
                self._build_view_row(
                    raw_row=row,
                    fallback_paradex=fallback_paradex,
                    fallback_grvt=fallback_grvt,
                )
            )

        computed_rows.sort(key=lambda item: item["nominal_spread"], reverse=True)

        return {
            "updated_at": self._updated_at,
            "scan_interval_sec": self._scan_interval_sec,
            "limit": resolved_limit,
            "total_symbols": len(computed_rows),
            "fallback": {
                "paradex": fallback_paradex,
                "grvt": fallback_grvt,
            },
            "last_error": self._last_error or None,
            "rows": computed_rows[:resolved_limit],
        }

    async def _ensure_cache(self, force_refresh: bool) -> None:
        if not force_refresh and self._rows and (time.monotonic() - self._last_refresh_monotonic) < self._scan_interval_sec:
            return

        async with self._lock:
            if (
                not force_refresh
                and self._rows
                and (time.monotonic() - self._last_refresh_monotonic) < self._scan_interval_sec
            ):
                return
            await self._refresh_once()

    async def _refresh_once(self) -> None:
        try:
            scanned_rows = await self._scan_all_symbols()
            self._rows = scanned_rows
            self._updated_at = utc_iso()
            self._last_refresh_monotonic = time.monotonic()
            self._last_error = ""
        except Exception as exc:  # pragma: no cover - 网络异常分支
            self._last_error = f"扫描失败: {exc}"
            self._updated_at = utc_iso()
            self._last_refresh_monotonic = time.monotonic()
            if not self._rows:
                self._rows = []

    async def _scan_all_symbols(self) -> list[dict[str, Any]]:
        paradex_client = ccxt.paradex({"enableRateLimit": True})
        grvt_client = GrvtCcxtPro(env=self._resolve_grvt_env(), parameters={})

        try:
            await asyncio.gather(paradex_client.load_markets(), grvt_client.load_markets())

            paradex_map = self._collect_paradex_markets(paradex_client.markets)
            grvt_map = self._collect_grvt_markets(grvt_client.markets)

            shared_bases = sorted(set(paradex_map.keys()) & set(grvt_map.keys()))
            semaphore = asyncio.Semaphore(6)

            async def fetch_one(base_asset: str) -> dict[str, Any] | None:
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

            rows = await asyncio.gather(*(fetch_one(base) for base in shared_bases), return_exceptions=False)
            return [row for row in rows if row is not None]
        finally:
            await paradex_client.close()
            session = getattr(grvt_client, "_session", None)
            if session is not None and not session.closed:
                await session.close()

    async def _fetch_pair_row(
        self,
        paradex_client: Any,
        grvt_client: Any,
        base_asset: str,
        paradex_info: dict[str, Any],
        grvt_info: dict[str, Any],
    ) -> dict[str, Any] | None:
        paradex_market = paradex_info["market"]
        grvt_market = grvt_info["market"]

        paradex_depth_task = paradex_client.fetch_order_book(paradex_market, limit=5)
        grvt_depth_task = grvt_client.fetch_order_book(grvt_market, limit=10)

        paradex_depth, grvt_depth = await asyncio.gather(
            paradex_depth_task,
            grvt_depth_task,
            return_exceptions=True,
        )

        if isinstance(paradex_depth, Exception) or isinstance(grvt_depth, Exception):
            return None

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
            return None

        paradex_mid = (paradex_bid + paradex_ask) / Decimal("2")
        grvt_mid = (grvt_bid + grvt_ask) / Decimal("2")

        spread_price = grvt_mid - paradex_mid
        avg_mid = (paradex_mid + grvt_mid) / Decimal("2")
        spread_bps = Decimal("0") if avg_mid <= 0 else (spread_price / avg_mid) * Decimal("10000")

        return {
            "symbol": f"{base_asset}-PERP",
            "base_asset": base_asset,
            "paradex_market": paradex_market,
            "grvt_market": grvt_market,
            "paradex_bid": float(paradex_bid),
            "paradex_ask": float(paradex_ask),
            "paradex_mid": float(paradex_mid),
            "grvt_bid": float(grvt_bid),
            "grvt_ask": float(grvt_ask),
            "grvt_mid": float(grvt_mid),
            "spread_price": float(spread_price),
            "spread_abs": float(abs(spread_price)),
            "spread_bps": float(spread_bps),
            "paradex_max_leverage": paradex_info.get("max_leverage"),
            "grvt_max_leverage": grvt_info.get("max_leverage"),
            "paradex_leverage_source": "market" if paradex_info.get("max_leverage") else "fallback",
            "grvt_leverage_source": "market" if grvt_info.get("max_leverage") else "fallback",
            "direction": "grvt_gt_paradex" if spread_price >= 0 else "paradex_gt_grvt",
            "updated_at": utc_iso(),
        }

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
            }

        return result

    def _collect_grvt_markets(self, markets: dict[str, Any]) -> dict[str, dict[str, Any]]:
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
                "max_leverage": _extract_grvt_max_leverage(item),
            }

        return result

    def _build_view_row(
        self,
        raw_row: dict[str, Any],
        fallback_paradex: float,
        fallback_grvt: float,
    ) -> dict[str, Any]:
        paradex_market_lev = raw_row.get("paradex_max_leverage")
        grvt_market_lev = raw_row.get("grvt_max_leverage")

        paradex_leverage = _sanitize_leverage(
            paradex_market_lev if paradex_market_lev is not None else fallback_paradex,
            fallback=fallback_paradex,
        )
        grvt_leverage = _sanitize_leverage(
            grvt_market_lev if grvt_market_lev is not None else fallback_grvt,
            fallback=fallback_grvt,
        )

        effective_leverage = min(paradex_leverage, grvt_leverage)
        nominal_spread = abs(float(raw_row["spread_price"])) * effective_leverage

        return {
            **raw_row,
            "paradex_leverage": paradex_leverage,
            "grvt_leverage": grvt_leverage,
            "effective_leverage": effective_leverage,
            "nominal_spread": nominal_spread,
            "paradex_leverage_source": "market" if paradex_market_lev is not None else "fallback",
            "grvt_leverage_source": "market" if grvt_market_lev is not None else "fallback",
        }

    def _resolve_grvt_env(self) -> GrvtEnv:
        env = self._config.grvt.environment.lower().strip()
        if env == "testnet":
            return GrvtEnv.TESTNET
        if env == "staging":
            return GrvtEnv.STAGING
        if env == "dev":
            return GrvtEnv.DEV
        return GrvtEnv.PROD
