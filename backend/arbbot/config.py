"""应用配置加载。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from .models import StrategyMode


def _to_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _to_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    return int(raw)


def _to_decimal(raw: str | None, default: str) -> Decimal:
    return Decimal(raw if raw is not None else default)


def _to_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    return float(raw)


def _split_csv(raw: str | None, default: str) -> list[str]:
    value = raw if raw is not None else default
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass(slots=True)
class ExchangeCredentials:
    """交易所凭证。"""

    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    private_key: str = ""
    trading_account_id: str = ""


@dataclass(slots=True)
class ExchangeConfig:
    """交易所配置。"""

    name: str
    environment: str
    rest_url: str
    ws_url: str
    credentials: ExchangeCredentials


@dataclass(slots=True)
class SymbolConfig:
    """单标的配置。"""

    symbol: str
    paradex_market: str
    grvt_market: str
    enabled: bool = True


@dataclass(slots=True)
class StrategyConfig:
    """策略参数。"""

    ma_window: int = 120
    std_window: int = 120
    min_samples: int = 60
    z_entry: Decimal = Decimal("1.8")
    z_exit: Decimal = Decimal("0.6")
    z_zero_entry: Decimal = Decimal("1.2")
    z_zero_exit: Decimal = Decimal("0.3")
    min_edge_bps: Decimal = Decimal("1.0")
    base_order_qty: Decimal = Decimal("0.001")
    max_batch_qty: Decimal = Decimal("0.005")
    max_position: Decimal = Decimal("0.1")
    loop_interval_ms: int = 100
    position_sync_ms: int = 1500
    rest_consistency_ms: int = 1000


@dataclass(slots=True)
class RiskConfig:
    """风控参数。"""

    stale_ms: int = 1200
    consistency_tolerance_bps: Decimal = Decimal("0.08")
    consistency_max_failures: int = 3
    ws_idle_timeout_sec: int = 8
    health_fail_threshold: int = 3
    health_cache_ms: int = 3000
    net_pos_guard_multiplier: Decimal = Decimal("1.5")
    hard_net_limit_multiplier: Decimal = Decimal("3.0")


@dataclass(slots=True)
class StorageConfig:
    """存储配置。"""

    sqlite_path: str = "backend/data/arbbot.db"
    csv_dir: str = "backend/data/csv"


@dataclass(slots=True)
class WebConfig:
    """Web 服务配置。"""

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


@dataclass(slots=True)
class RuntimeConfig:
    """运行时配置。"""

    simulated_market_data: bool = True
    live_order_enabled: bool = False
    enable_order_confirmation_text: str = "ENABLE_LIVE_ORDER"
    default_mode: StrategyMode = StrategyMode.NORMAL_ARB


@dataclass(slots=True)
class AppConfig:
    """应用总配置。"""

    symbols: list[SymbolConfig]
    paradex: ExchangeConfig
    grvt: ExchangeConfig
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    rate_limits: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env_path: str | None = ".env") -> "AppConfig":
        """从环境变量构建配置。"""
        if env_path:
            load_dotenv(env_path, override=False)

        symbols = _split_csv(os.getenv("ARB_SYMBOLS"), "BTC-PERP")
        paradex_markets = _split_csv(os.getenv("PARADEX_MARKETS"), ",".join(symbols))
        grvt_markets = _split_csv(os.getenv("GRVT_MARKETS"), ",".join(symbols))

        symbol_cfgs: list[SymbolConfig] = []
        for idx, symbol in enumerate(symbols):
            para_market = paradex_markets[idx] if idx < len(paradex_markets) else symbol
            grvt_market = grvt_markets[idx] if idx < len(grvt_markets) else symbol
            symbol_cfgs.append(
                SymbolConfig(
                    symbol=symbol,
                    paradex_market=para_market,
                    grvt_market=grvt_market,
                    enabled=True,
                )
            )

        paradex = ExchangeConfig(
            name="paradex",
            environment=os.getenv("PARADEX_ENV", "prod"),
            rest_url=os.getenv("PARADEX_REST_URL", "https://api.prod.paradex.trade"),
            ws_url=os.getenv("PARADEX_WS_URL", "wss://ws.api.prod.paradex.trade/v1"),
            credentials=ExchangeCredentials(
                api_key=os.getenv("PARADEX_API_KEY", ""),
                api_secret=os.getenv("PARADEX_API_SECRET", ""),
                passphrase=os.getenv("PARADEX_API_PASSPHRASE", ""),
            ),
        )

        grvt = ExchangeConfig(
            name="grvt",
            environment=os.getenv("GRVT_ENV", "prod"),
            rest_url=os.getenv("GRVT_REST_URL", "https://edge.grvt.io"),
            ws_url=os.getenv("GRVT_WS_URL", "wss://market-data.grvt.io/ws/full"),
            credentials=ExchangeCredentials(
                api_key=os.getenv("GRVT_API_KEY", ""),
                api_secret=os.getenv("GRVT_API_SECRET", ""),
                private_key=os.getenv("GRVT_PRIVATE_KEY", ""),
                trading_account_id=os.getenv("GRVT_TRADING_ACCOUNT_ID", ""),
            ),
        )

        strategy = StrategyConfig(
            ma_window=_to_int(os.getenv("ARB_MA_WINDOW"), 120),
            std_window=_to_int(os.getenv("ARB_STD_WINDOW"), 120),
            min_samples=_to_int(os.getenv("ARB_MIN_SAMPLES"), 60),
            z_entry=_to_decimal(os.getenv("ARB_Z_ENTRY"), "1.8"),
            z_exit=_to_decimal(os.getenv("ARB_Z_EXIT"), "0.6"),
            z_zero_entry=_to_decimal(os.getenv("ARB_Z_ZERO_ENTRY"), "1.2"),
            z_zero_exit=_to_decimal(os.getenv("ARB_Z_ZERO_EXIT"), "0.3"),
            min_edge_bps=_to_decimal(os.getenv("ARB_MIN_EDGE_BPS"), "1.0"),
            base_order_qty=_to_decimal(os.getenv("ARB_BASE_ORDER_QTY"), "0.001"),
            max_batch_qty=_to_decimal(os.getenv("ARB_MAX_BATCH_QTY"), "0.005"),
            max_position=_to_decimal(os.getenv("ARB_MAX_POSITION"), "0.1"),
            loop_interval_ms=_to_int(os.getenv("ARB_LOOP_INTERVAL_MS"), 100),
            position_sync_ms=_to_int(os.getenv("ARB_POSITION_SYNC_MS"), 1500),
            rest_consistency_ms=_to_int(os.getenv("ARB_REST_CONSISTENCY_MS"), 1000),
        )

        risk = RiskConfig(
            stale_ms=_to_int(os.getenv("ARB_STALE_MS"), 1200),
            consistency_tolerance_bps=_to_decimal(os.getenv("ARB_CONSISTENCY_TOL_BPS"), "0.08"),
            consistency_max_failures=_to_int(os.getenv("ARB_CONSISTENCY_MAX_FAILURES"), 3),
            ws_idle_timeout_sec=_to_int(os.getenv("ARB_WS_IDLE_TIMEOUT_SEC"), 8),
            health_fail_threshold=_to_int(os.getenv("ARB_HEALTH_FAIL_THRESHOLD"), 3),
            health_cache_ms=_to_int(os.getenv("ARB_HEALTH_CACHE_MS"), 3000),
            net_pos_guard_multiplier=_to_decimal(os.getenv("ARB_NET_POS_GUARD_MULT"), "1.5"),
            hard_net_limit_multiplier=_to_decimal(os.getenv("ARB_HARD_NET_LIMIT_MULT"), "3.0"),
        )

        storage = StorageConfig(
            sqlite_path=os.getenv("ARB_SQLITE_PATH", "backend/data/arbbot.db"),
            csv_dir=os.getenv("ARB_CSV_DIR", "backend/data/csv"),
        )

        web = WebConfig(
            host=os.getenv("ARB_WEB_HOST", "0.0.0.0"),
            port=_to_int(os.getenv("ARB_WEB_PORT"), 8000),
            log_level=os.getenv("ARB_WEB_LOG_LEVEL", "info"),
        )

        mode_raw = os.getenv("ARB_DEFAULT_MODE", StrategyMode.NORMAL_ARB.value)
        default_mode = (
            StrategyMode.ZERO_WEAR if mode_raw == StrategyMode.ZERO_WEAR.value else StrategyMode.NORMAL_ARB
        )
        dry_run_value = _to_bool(os.getenv("ARB_DRY_RUN"), True)
        simulated_market_data = _to_bool(
            os.getenv("ARB_SIMULATED_MARKET_DATA"),
            dry_run_value,
        )
        live_order_enabled = _to_bool(
            os.getenv("ARB_LIVE_ORDER_ENABLED"),
            not dry_run_value,
        )
        confirm_text = os.getenv("ARB_ENABLE_LIVE_ORDER_CONFIRM_TEXT", "ENABLE_LIVE_ORDER").strip()
        runtime = RuntimeConfig(
            simulated_market_data=simulated_market_data,
            live_order_enabled=live_order_enabled,
            enable_order_confirmation_text=confirm_text or "ENABLE_LIVE_ORDER",
            default_mode=default_mode,
        )

        rate_limits = {
            "paradex": {
                "market_data": (
                    _to_float(os.getenv("ARB_RL_PARADEX_MARKET_DATA_RATE"), 15.0),
                    _to_float(os.getenv("ARB_RL_PARADEX_MARKET_DATA_CAP"), 25.0),
                ),
                "order": (
                    _to_float(os.getenv("ARB_RL_PARADEX_ORDER_RATE"), 8.0),
                    _to_float(os.getenv("ARB_RL_PARADEX_ORDER_CAP"), 12.0),
                ),
            },
            "grvt": {
                "market_data": (
                    _to_float(os.getenv("ARB_RL_GRVT_MARKET_DATA_RATE"), 15.0),
                    _to_float(os.getenv("ARB_RL_GRVT_MARKET_DATA_CAP"), 25.0),
                ),
                "order": (
                    _to_float(os.getenv("ARB_RL_GRVT_ORDER_RATE"), 8.0),
                    _to_float(os.getenv("ARB_RL_GRVT_ORDER_CAP"), 12.0),
                ),
            },
        }

        return cls(
            symbols=symbol_cfgs,
            paradex=paradex,
            grvt=grvt,
            strategy=strategy,
            risk=risk,
            storage=storage,
            web=web,
            runtime=runtime,
            rate_limits=rate_limits,
        )

    def to_public_dict(self) -> dict[str, Any]:
        """输出给 Web 层的可公开配置。"""
        return {
            "symbols": [
                {
                    "symbol": cfg.symbol,
                    "paradex_market": cfg.paradex_market,
                    "grvt_market": cfg.grvt_market,
                }
                for cfg in self.symbols
            ],
            "strategy": {
                "ma_window": self.strategy.ma_window,
                "std_window": self.strategy.std_window,
                "z_entry": str(self.strategy.z_entry),
                "z_exit": str(self.strategy.z_exit),
                "z_zero_entry": str(self.strategy.z_zero_entry),
                "z_zero_exit": str(self.strategy.z_zero_exit),
                "base_order_qty": str(self.strategy.base_order_qty),
                "max_batch_qty": str(self.strategy.max_batch_qty),
                "max_position": str(self.strategy.max_position),
            },
            "risk": {
                "stale_ms": self.risk.stale_ms,
                "consistency_tolerance_bps": str(self.risk.consistency_tolerance_bps),
                "consistency_max_failures": self.risk.consistency_max_failures,
                "ws_idle_timeout_sec": self.risk.ws_idle_timeout_sec,
            },
            "runtime": {
                # 兼容旧版前端：dry_run 等价于 simulated_market_data。
                "dry_run": self.runtime.simulated_market_data,
                "simulated_market_data": self.runtime.simulated_market_data,
                "live_order_enabled": self.runtime.live_order_enabled,
                "enable_order_confirmation_text": self.runtime.enable_order_confirmation_text,
                "default_mode": self.runtime.default_mode.value,
            },
        }
