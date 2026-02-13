export type EngineStatus = "running" | "stopped" | "starting" | "stopping" | "error" | "unknown";
export type TradingMode = "normal_arb" | "zero_wear";
export type EventLevel = "info" | "warn" | "error";
export type WsConnectionState = "connecting" | "connected" | "reconnecting" | "disconnected" | "error";

export interface RiskCounts {
  normal: number;
  warning: number;
  critical: number;
}

export interface DashboardStatus {
  engineStatus: EngineStatus;
  mode: TradingMode;
  netExposure: number;
  dailyVolume: number;
  riskCounts: RiskCounts;
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
  updatedAt: ""
};

export interface SymbolRow {
  symbol: string;
  spread: number;
  zscore: number;
  position: number;
  signal: string;
  status: string;
  updatedAt: string;
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
  | { type: "symbol"; data: unknown };
