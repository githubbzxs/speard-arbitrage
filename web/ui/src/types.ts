export type EngineStatus = "running" | "stopped" | "starting" | "stopping" | "error" | "unknown";
export type TradingMode = "normal_arb" | "zero_wear";
export type EventLevel = "info" | "warn" | "error";
export type WsConnectionState = "connecting" | "connected" | "reconnecting" | "disconnected" | "error";

export interface RiskCounts {
  normal: number;
  warning: number;
  critical: number;
}

export interface PerformanceSummary {
  runningSince: string;
  runRealizedPnl: number;
  runUnrealizedPnl: number;
  runTotalPnl: number;
  runPnlPct: number;
  runTurnoverUsd: number;
  runTradeCount: number;
  equityNow: number;
  equityPeak: number;
  drawdownPct: number;
  maxDrawdownPct: number;
}

export interface ExchangeBalanceSummary {
  available: boolean;
  source: string;
  currency: string;
  totalEquity: number;
  availableBalance: number;
  marginUsed: number;
  updatedAt: string;
}

export interface PositionSummaryItem {
  symbol: string;
  paradexPosition: number;
  grvtPosition: number;
  netExposure: number;
}

export interface PositionsSummary {
  totalNetExposure: number;
  bySymbol: PositionSummaryItem[];
}

export interface DashboardStatus {
  engineStatus: EngineStatus;
  mode: TradingMode;
  netExposure: number;
  dailyVolume: number;
  riskCounts: RiskCounts;
  performance: PerformanceSummary;
  balances: {
    paradex: ExchangeBalanceSummary;
    grvt: ExchangeBalanceSummary;
  };
  positionsSummary: PositionsSummary;
  updatedAt: string;
}

export const DEFAULT_STATUS: DashboardStatus = {
  engineStatus: "unknown",
  mode: "normal_arb",
  netExposure: 0,
  dailyVolume: 0,
  riskCounts: {
    normal: 0,
    warning: 0,
    critical: 0
  },
  performance: {
    runningSince: "",
    runRealizedPnl: 0,
    runUnrealizedPnl: 0,
    runTotalPnl: 0,
    runPnlPct: 0,
    runTurnoverUsd: 0,
    runTradeCount: 0,
    equityNow: 0,
    equityPeak: 0,
    drawdownPct: 0,
    maxDrawdownPct: 0
  },
  balances: {
    paradex: {
      available: false,
      source: "init",
      currency: "",
      totalEquity: 0,
      availableBalance: 0,
      marginUsed: 0,
      updatedAt: ""
    },
    grvt: {
      available: false,
      source: "init",
      currency: "",
      totalEquity: 0,
      availableBalance: 0,
      marginUsed: 0,
      updatedAt: ""
    }
  },
  positionsSummary: {
    totalNetExposure: 0,
    bySymbol: []
  },
  updatedAt: ""
};

export interface SymbolRow {
  symbol: string;
  paradexBid: number;
  paradexAsk: number;
  paradexMid: number;
  grvtBid: number;
  grvtAsk: number;
  grvtMid: number;
  spreadBps: number;
  spreadPrice: number;
  zscore: number;
  position: number;
  signal: string;
  status: string;
  updatedAt: string;
}

export interface TradeTopCandidate {
  symbol: string;
  paradexMarket: string;
  grvtMarket: string;
  tradableEdgePct: number;
  tradableEdgeBps: number;
  grossNominalSpread: number;
  zscore: number;
  spreadSpeedPctPerMin: number;
  spreadVolatilityPct: number;
}

export interface TradeSelection {
  selectedSymbol: string;
  candidates: TradeTopCandidate[];
  top10Candidates: TradeTopCandidate[];
  updatedAt: string;
}

export interface RuntimeConfig {
  dryRun: boolean;
  simulatedMarketData: boolean;
  liveOrderEnabled: boolean;
  enableOrderConfirmationText: string;
  defaultMode: TradingMode;
}

export interface SupportedSymbolInfo {
  symbol: string;
  paradexMarket: string;
  grvtMarket: string;
  baseAsset: string;
  quoteAsset: string;
  recommendedLeverage: number;
  leverageNote: string;
}

export interface PublicConfig {
  runtime: RuntimeConfig;
  symbols: SupportedSymbolInfo[];
}

export interface MarketTopSpreadRow {
  symbol: string;
  baseAsset: string;
  paradexMarket: string;
  grvtMarket: string;
  paradexBid: number;
  paradexAsk: number;
  paradexMid: number;
  grvtBid: number;
  grvtAsk: number;
  grvtMid: number;
  referenceMid: number;
  tradableEdgePrice: number;
  tradableEdgePct: number;
  tradableEdgeBps: number;
  direction: string;
  paradexMaxLeverage: number;
  grvtMaxLeverage: number;
  effectiveLeverage: number;
  grossNominalSpread: number;
  feeCostEstimate: number;
  netNominalSpread: number;
  zscore: number;
  spreadSpeedPctPerMin: number;
  spreadVolatilityPct: number;
  speedSamples: number;
  paradexFeeRate: number;
  grvtFeeRate: number;
  feeSource: {
    paradex: "api" | "official";
    grvt: "api" | "official";
  };
  updatedAt: string;
}

export interface MarketTopSpreadsResponse {
  updatedAt: string;
  scanIntervalSec: number;
  limit: number;
  configuredSymbols: number;
  comparableSymbols: number;
  executableSymbols: number;
  scannedSymbols: number;
  totalSymbols: number;
  skippedCount: number;
  skippedReasons: Record<string, number>;
  feeProfile: {
    paradexLeg: "taker";
    grvtLeg: "maker" | "taker";
  };
  lastError: string | null;
  rows: MarketTopSpreadRow[];
}

export interface EventLog {
  id: string;
  ts: string;
  level: EventLevel;
  source: string;
  message: string;
}

export interface SymbolParamsPayload {
  z_entry?: number;
  z_exit?: number;
  max_position?: number;
}

export interface ActionResult {
  ok: boolean;
  message: string;
}

export interface WsConnectionStatus {
  state: WsConnectionState;
  attempt: number;
  message: string;
}

export interface SnapshotPayload {
  status?: unknown;
  symbols?: unknown;
  events?: unknown;
  [key: string]: unknown;
}

export type WsStreamMessage =
  | { type: "snapshot"; data: SnapshotPayload | Record<string, unknown> }
  | { type: "event"; data: unknown }
  | { type: "symbol"; data: unknown }
  | { type: "market_top_spreads"; data: unknown };
