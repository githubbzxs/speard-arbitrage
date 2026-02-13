"""核心领域模型定义。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from time import time
from typing import Any


def utc_ms() -> int:
    """返回当前 UTC 毫秒时间戳。"""
    return int(time() * 1000)


def utc_iso() -> str:
    """返回当前 UTC ISO 时间字符串。"""
    return datetime.now(UTC).isoformat()


class ExchangeName(str, Enum):
    """支持的交易所。"""

    PARADEX = "paradex"
    GRVT = "grvt"


class TradeSide(str, Enum):
    """下单方向。"""

    BUY = "buy"
    SELL = "sell"


class SignalAction(str, Enum):
    """策略动作。"""

    HOLD = "hold"
    OPEN = "open"
    CLOSE = "close"
    REBALANCE = "rebalance"


class ArbitrageDirection(str, Enum):
    """套利方向。"""

    LONG_PARA_SHORT_GRVT = "long_paradex_short_grvt"
    LONG_GRVT_SHORT_PARA = "long_grvt_short_paradex"


class EngineStatus(str, Enum):
    """引擎状态。"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class StrategyMode(str, Enum):
    """策略模式。"""

    NORMAL_ARB = "normal_arb"
    ZERO_WEAR = "zero_wear"


class EventLevel(str, Enum):
    """事件日志等级。"""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


@dataclass(slots=True)
class BBO:
    """最优买卖价快照。"""

    bid: Decimal
    ask: Decimal
    timestamp_ms: int = field(default_factory=utc_ms)
    source: str = "ws"

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def valid(self) -> bool:
        return self.bid > 0 and self.ask > 0 and self.bid < self.ask


@dataclass(slots=True)
class SpreadMetrics:
    """价差与统计指标。"""

    symbol: str
    edge_para_to_grvt_price: Decimal
    edge_grvt_to_para_price: Decimal
    edge_para_to_grvt_bps: Decimal
    edge_grvt_to_para_bps: Decimal
    signed_edge_bps: Decimal
    signed_edge_price: Decimal
    ma: Decimal
    std: Decimal
    zscore: Decimal
    timestamp_ms: int = field(default_factory=utc_ms)


@dataclass(slots=True)
class SpreadSignal:
    """策略信号。"""

    action: SignalAction
    direction: ArbitrageDirection | None
    edge_bps: Decimal
    zscore: Decimal
    threshold_bps: Decimal
    reason: str
    batches: list[Decimal] = field(default_factory=list)
    timestamp_ms: int = field(default_factory=utc_ms)


@dataclass(slots=True)
class OrderRequest:
    """统一下单请求。"""

    exchange: ExchangeName
    symbol: str
    side: TradeSide
    quantity: Decimal
    order_type: str = "market"
    price: Decimal | None = None
    reduce_only: bool = False
    post_only: bool = False
    tag: str = ""


@dataclass(slots=True)
class OrderAck:
    """统一下单响应。"""

    success: bool
    exchange: ExchangeName
    order_id: str
    side: TradeSide
    requested_quantity: Decimal
    filled_quantity: Decimal
    avg_price: Decimal | None = None
    message: str = ""
    timestamp_ms: int = field(default_factory=utc_ms)


@dataclass(slots=True)
class TradeFill:
    """成交记录。"""

    exchange: ExchangeName
    symbol: str
    side: TradeSide
    quantity: Decimal
    price: Decimal
    order_id: str
    tag: str
    timestamp_ms: int = field(default_factory=utc_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange.value,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "price": str(self.price),
            "order_id": self.order_id,
            "tag": self.tag,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(slots=True)
class PositionState:
    """双交易所仓位状态。"""

    paradex: Decimal = Decimal("0")
    grvt: Decimal = Decimal("0")
    target_net: Decimal = Decimal("0")
    active_direction: ArbitrageDirection | None = None

    @property
    def net_exposure(self) -> Decimal:
        return self.paradex + self.grvt

    def to_dict(self) -> dict[str, str | None]:
        return {
            "paradex": str(self.paradex),
            "grvt": str(self.grvt),
            "net_exposure": str(self.net_exposure),
            "target_net": str(self.target_net),
            "active_direction": self.active_direction.value if self.active_direction else None,
        }


@dataclass(slots=True)
class RebalanceOrder:
    """再平衡指令。"""

    exchange: ExchangeName
    side: TradeSide
    quantity: Decimal
    symbol: str


@dataclass(slots=True)
class ExecutionReport:
    """执行结果报告。"""

    signal: SpreadSignal
    attempted_orders: int
    success_orders: int
    failed_orders: int
    message: str
    order_ids: list[str] = field(default_factory=list)
    timestamp_ms: int = field(default_factory=utc_ms)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["signal"]["action"] = self.signal.action.value
        data["signal"]["direction"] = (
            self.signal.direction.value if self.signal.direction else None
        )
        data["signal"]["edge_bps"] = str(self.signal.edge_bps)
        data["signal"]["zscore"] = str(self.signal.zscore)
        data["signal"]["threshold_bps"] = str(self.signal.threshold_bps)
        data["signal"]["batches"] = [str(x) for x in self.signal.batches]
        return data


@dataclass(slots=True)
class RiskState:
    """风险状态快照。"""

    stale: bool
    consistency_ok: bool
    health_ok: bool
    ws_ok: bool
    can_open: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SymbolSnapshot:
    """单标的状态快照，用于 WebUI。"""

    symbol: str
    status: str
    signal: str
    paradex_bid: Decimal
    paradex_ask: Decimal
    paradex_mid: Decimal
    grvt_bid: Decimal
    grvt_ask: Decimal
    grvt_mid: Decimal
    spread_bps: Decimal
    spread_price: Decimal
    zscore: Decimal
    net_position: Decimal
    target_position: Decimal
    paradex_position: Decimal
    grvt_position: Decimal
    updated_at: str
    risk: RiskState

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "signal": self.signal,
            "paradex_bid": float(self.paradex_bid),
            "paradex_ask": float(self.paradex_ask),
            "paradex_mid": float(self.paradex_mid),
            "grvt_bid": float(self.grvt_bid),
            "grvt_ask": float(self.grvt_ask),
            "grvt_mid": float(self.grvt_mid),
            "spread_bps": float(self.spread_bps),
            "spread_price": float(self.spread_price),
            "zscore": float(self.zscore),
            "net_position": float(self.net_position),
            "target_position": float(self.target_position),
            "paradex_position": float(self.paradex_position),
            "grvt_position": float(self.grvt_position),
            "updated_at": self.updated_at,
            "risk": self.risk.to_dict(),
        }


@dataclass(slots=True)
class EventRecord:
    """事件记录。"""

    id: str
    ts: str
    level: EventLevel
    source: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "level": self.level.value,
            "source": self.source,
            "message": self.message,
            "data": self.data,
        }
