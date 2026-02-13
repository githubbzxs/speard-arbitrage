import { DEFAULT_STATUS } from "../types";
import type {
  ActionResult,
  DashboardStatus,
  EngineStatus,
  EventLevel,
  EventLog,
  MarketTopSpreadRow,
  MarketTopSpreadsResponse,
  PublicConfig,
  SupportedSymbolInfo,
  SymbolParamsPayload,
  SymbolRow,
  TradeSelection,
  TradeTopCandidate,
  TradingMode
} from "../types";

const REQUEST_TIMEOUT_MS = 15000;
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").trim();

const PARADEX_FIELDS = ["l2_private_key", "l2_address"] as const;
const GRVT_FIELDS = ["private_key", "trading_account_id", "api_key"] as const;

export type ParadexCredentialField = (typeof PARADEX_FIELDS)[number];
export type GrvtCredentialField = (typeof GRVT_FIELDS)[number];

export interface ParadexCredentialsInput {
  l2_private_key: string;
  l2_address: string;
}

export interface GrvtCredentialsInput {
  api_key: string;
  private_key: string;
  trading_account_id: string;
}

export interface CredentialsPayload {
  paradex?: Partial<ParadexCredentialsInput>;
  grvt?: Partial<GrvtCredentialsInput>;
}

export interface CredentialFieldStatus {
  configured: boolean;
  masked: string;
}

export interface CredentialsStatus {
  paradex: Record<ParadexCredentialField, CredentialFieldStatus>;
  grvt: Record<GrvtCredentialField, CredentialFieldStatus>;
}

export interface ExchangeValidationResult {
  valid: boolean;
  reason: string;
  checks: Record<string, boolean>;
}

export interface CredentialsValidationResponse {
  ok: boolean;
  message: string;
  data: {
    paradex: ExchangeValidationResult;
    grvt: ExchangeValidationResult;
  } | null;
}

export type CredentialsValidationSource = "saved" | "draft";

export const DEFAULT_CREDENTIALS_STATUS: CredentialsStatus = {
  paradex: {
    l2_private_key: { configured: false, masked: "" },
    l2_address: { configured: false, masked: "" }
  },
  grvt: {
    private_key: { configured: false, masked: "" },
    trading_account_id: { configured: false, masked: "" },
    api_key: { configured: false, masked: "" }
  }
};

function cloneDefaultCredentialsStatus(): CredentialsStatus {
  return {
    paradex: {
      l2_private_key: { configured: false, masked: "" },
      l2_address: { configured: false, masked: "" }
    },
    grvt: {
      private_key: { configured: false, masked: "" },
      trading_account_id: { configured: false, masked: "" },
      api_key: { configured: false, masked: "" }
    }
  };
}

function buildUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  if (!API_BASE_URL) {
    return path;
  }

  const normalizedBase = API_BASE_URL.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const headers = new Headers(init?.headers ?? {});

  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  try {
    const response = await fetch(buildUrl(path), {
      ...init,
      headers,
      signal: controller.signal
    });

    const rawText = await response.text();
    const parsedData = rawText ? tryParseJson(rawText) : null;

    if (!response.ok) {
      const detail = readErrorDetail(parsedData, rawText, response.statusText);
      throw new Error(`HTTP ${response.status}: ${detail}`);
    }

    if (parsedData !== null) {
      return parsedData as T;
    }

    return (rawText as unknown) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`请求超时（${REQUEST_TIMEOUT_MS}ms），请稍后重试`);
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function tryParseJson(value: string): unknown | null {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

function readErrorDetail(data: unknown, rawText: string, fallback: string): string {
  const record = toRecord(data);
  if (record) {
    const detail = pickString(record, ["detail", "message", "error"], "");
    if (detail) {
      return detail;
    }
  }

  if (rawText.trim()) {
    return rawText;
  }

  return fallback || "请求失败";
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "发生未知错误";
}

export function toRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function pickString(record: Record<string, unknown>, keys: string[], fallback: string): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return fallback;
}

function pickNumber(record: Record<string, unknown>, keys: string[], fallback: number): number {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return fallback;
}

function parseEngineStatus(value: string): EngineStatus {
  const normalized = value.toLowerCase();
  if (normalized === "running") return "running";
  if (normalized === "stopped") return "stopped";
  if (normalized === "starting") return "starting";
  if (normalized === "stopping") return "stopping";
  if (normalized === "error") return "error";
  return "unknown";
}

function parseMode(value: string): TradingMode {
  return value === "zero_wear" ? "zero_wear" : "normal_arb";
}

function parseEventLevel(value: string): EventLevel {
  const normalized = value.toLowerCase();
  if (normalized === "warn" || normalized === "warning") {
    return "warn";
  }
  if (normalized === "error") {
    return "error";
  }
  return "info";
}

function extractArray(value: unknown): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }

  const record = toRecord(value);
  if (!record) {
    return [];
  }

  for (const key of ["items", "rows", "list", "data", "symbols", "events", "top10_candidates"]) {
    const candidate = record[key];
    if (Array.isArray(candidate)) {
      return candidate;
    }
  }

  return [];
}

export function normalizeStatus(data: unknown): DashboardStatus {
  const record = toRecord(data);
  if (!record) {
    return { ...DEFAULT_STATUS };
  }

  const riskRecord = toRecord(record.risk_counts) ?? toRecord(record.riskCounts);

  const normalRisk = riskRecord
    ? pickNumber(riskRecord, ["normal", "ok", "safe"], 0)
    : pickNumber(record, ["risk_normal", "normal_count"], 0);
  const warningRisk = riskRecord
    ? pickNumber(riskRecord, ["warning", "warn"], 0)
    : pickNumber(record, ["risk_warning", "warning_count"], 0);
  const criticalRisk = riskRecord
    ? pickNumber(riskRecord, ["critical", "high"], 0)
    : pickNumber(record, ["risk_critical", "critical_count"], 0);

  return {
    engineStatus: parseEngineStatus(pickString(record, ["engine_status", "engineStatus", "status"], DEFAULT_STATUS.engineStatus)),
    mode: parseMode(pickString(record, ["mode"], DEFAULT_STATUS.mode)),
    netExposure: pickNumber(record, ["net_exposure", "netExposure", "exposure"], 0),
    dailyVolume: pickNumber(record, ["daily_volume", "dailyVolume", "volume"], 0),
    riskCounts: {
      normal: normalRisk,
      warning: warningRisk,
      critical: criticalRisk
    },
    updatedAt: pickString(record, ["updated_at", "updatedAt", "ts", "timestamp"], new Date().toISOString())
  };
}

export function normalizeSymbol(data: unknown): SymbolRow | null {
  const record = toRecord(data);
  if (!record) {
    return null;
  }

  const symbol = pickString(record, ["symbol", "name", "id"], "");
  if (!symbol) {
    return null;
  }

  return {
    symbol,
    paradexBid: pickNumber(record, ["paradex_bid", "paradexBid"], 0),
    paradexAsk: pickNumber(record, ["paradex_ask", "paradexAsk"], 0),
    paradexMid: pickNumber(record, ["paradex_mid", "paradexMid"], 0),
    grvtBid: pickNumber(record, ["grvt_bid", "grvtBid"], 0),
    grvtAsk: pickNumber(record, ["grvt_ask", "grvtAsk"], 0),
    grvtMid: pickNumber(record, ["grvt_mid", "grvtMid"], 0),
    spreadBps: pickNumber(record, ["spread_bps", "spreadBps", "spread"], 0),
    spreadPrice: pickNumber(record, ["spread_price", "spreadPrice"], 0),
    zscore: pickNumber(record, ["zscore", "z_score", "zScore"], 0),
    position: pickNumber(record, ["position", "net_position", "netPosition"], 0),
    signal: pickString(record, ["signal"], "neutral"),
    status: pickString(record, ["status", "state"], "unknown"),
    updatedAt: pickString(record, ["updated_at", "updatedAt", "ts"], new Date().toISOString())
  };
}

export function normalizeSymbols(data: unknown): SymbolRow[] {
  return extractArray(data)
    .map((item) => normalizeSymbol(item))
    .filter((item): item is SymbolRow => item !== null)
    .sort((a, b) => a.symbol.localeCompare(b.symbol));
}

export function normalizeEvent(data: unknown): EventLog | null {
  const record = toRecord(data);
  if (!record) {
    return null;
  }

  const ts = pickString(record, ["ts", "timestamp", "time", "created_at"], new Date().toISOString());
  const message = pickString(record, ["message", "detail", "msg"], "");
  if (!message) {
    return null;
  }

  const source = pickString(record, ["source", "module", "component"], "system");
  const id = pickString(record, ["id", "event_id", "eventId"], `${source}-${ts}-${Math.random().toString(36).slice(2, 8)}`);

  return {
    id,
    ts,
    level: parseEventLevel(pickString(record, ["level", "severity"], "info")),
    source,
    message
  };
}

export function normalizeEvents(data: unknown): EventLog[] {
  return extractArray(data)
    .map((item) => normalizeEvent(item))
    .filter((item): item is EventLog => item !== null)
    .sort((a, b) => b.ts.localeCompare(a.ts));
}

function normalizeActionResult(data: unknown, fallback: string): ActionResult {
  const record = toRecord(data);
  if (!record) {
    return { ok: true, message: fallback };
  }

  return {
    ok: typeof record.ok === "boolean" ? record.ok : true,
    message: pickString(record, ["message", "detail"], fallback)
  };
}

function normalizeConfiguredFlag(value: unknown): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return value > 0;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (!normalized) {
      return false;
    }
    if (["true", "1", "yes", "configured", "set"].includes(normalized)) {
      return true;
    }
    if (["false", "0", "no", "unset"].includes(normalized)) {
      return false;
    }
  }

  const record = toRecord(value);
  if (record) {
    if ("configured" in record) return normalizeConfiguredFlag(record.configured);
    if ("is_configured" in record) return normalizeConfiguredFlag(record.is_configured);
    if ("isConfigured" in record) return normalizeConfiguredFlag(record.isConfigured);
    if ("set" in record) return normalizeConfiguredFlag(record.set);
    if ("exists" in record) return normalizeConfiguredFlag(record.exists);
  }

  return false;
}

function extractConfiguredFieldSet(record: Record<string, unknown>): Set<string> {
  const set = new Set<string>();
  for (const key of ["configured_fields", "configuredFields", "fields"]) {
    const value = record[key];
    if (!Array.isArray(value)) {
      continue;
    }
    for (const field of value) {
      if (typeof field === "string" && field.trim()) {
        set.add(field);
      }
    }
  }
  return set;
}

function normalizeExchangeStatus<T extends string>(source: unknown, fields: readonly T[]): Record<T, CredentialFieldStatus> {
  const result = {} as Record<T, CredentialFieldStatus>;
  for (const field of fields) {
    result[field] = { configured: false, masked: "" };
  }

  if (Array.isArray(source)) {
    const configuredSet = new Set(source.filter((item): item is string => typeof item === "string"));
    for (const field of fields) {
      result[field] = { configured: configuredSet.has(field), masked: "" };
    }
    return result;
  }

  const record = toRecord(source);
  if (!record) {
    return result;
  }

  const configuredSet = extractConfiguredFieldSet(record);

  for (const field of fields) {
    if (field in record) {
      const fieldRecord = toRecord(record[field]);
      if (fieldRecord) {
        result[field] = {
          configured: normalizeConfiguredFlag(fieldRecord.configured ?? fieldRecord),
          masked: pickString(fieldRecord, ["masked", "mask"], "")
        };
      } else {
        result[field] = { configured: normalizeConfiguredFlag(record[field]), masked: "" };
      }
      continue;
    }

    result[field] = { configured: configuredSet.has(field), masked: "" };
  }

  return result;
}

export function normalizeCredentialsStatus(data: unknown): CredentialsStatus {
  const fallback = cloneDefaultCredentialsStatus();
  const record = toRecord(data);
  if (!record) {
    return fallback;
  }

  const nestedRecord = toRecord(record.data);
  const sourceRecord = nestedRecord ?? record;

  const paradexSource = sourceRecord.paradex ?? sourceRecord.paradex_status ?? sourceRecord.paradexStatus;
  const grvtSource = sourceRecord.grvt ?? sourceRecord.grvt_status ?? sourceRecord.grvtStatus;

  return {
    paradex: normalizeExchangeStatus(paradexSource, PARADEX_FIELDS),
    grvt: normalizeExchangeStatus(grvtSource, GRVT_FIELDS)
  };
}

function normalizeSupportedSymbol(data: unknown): SupportedSymbolInfo | null {
  const record = toRecord(data);
  if (!record) {
    return null;
  }

  const symbol = pickString(record, ["symbol"], "");
  if (!symbol) {
    return null;
  }

  return {
    symbol,
    paradexMarket: pickString(record, ["paradex_market", "paradexMarket"], ""),
    grvtMarket: pickString(record, ["grvt_market", "grvtMarket"], ""),
    baseAsset: pickString(record, ["base_asset", "baseAsset"], symbol),
    quoteAsset: pickString(record, ["quote_asset", "quoteAsset"], "USDT"),
    recommendedLeverage: Math.max(1, pickNumber(record, ["recommended_leverage", "recommendedLeverage"], 2)),
    leverageNote: pickString(record, ["leverage_note", "leverageNote"], "建议低杠杆，用户可在交易所调整")
  };
}

function normalizeMarketSpreadRow(data: unknown): MarketTopSpreadRow | null {
  const record = toRecord(data);
  if (!record) {
    return null;
  }

  const symbol = pickString(record, ["symbol"], "");
  if (!symbol) {
    return null;
  }

  const feeSourceRecord = toRecord(record.fee_source) ?? toRecord(record.feeSource);
  const paradexFeeSourceRaw = pickString(feeSourceRecord ?? {}, ["paradex"], "official");
  const grvtFeeSourceRaw = pickString(feeSourceRecord ?? {}, ["grvt"], "official");

  return {
    symbol,
    baseAsset: pickString(record, ["base_asset", "baseAsset"], symbol.replace("-PERP", "")),
    paradexMarket: pickString(record, ["paradex_market", "paradexMarket"], ""),
    grvtMarket: pickString(record, ["grvt_market", "grvtMarket"], ""),
    paradexBid: pickNumber(record, ["paradex_bid", "paradexBid"], 0),
    paradexAsk: pickNumber(record, ["paradex_ask", "paradexAsk"], 0),
    paradexMid: pickNumber(record, ["paradex_mid", "paradexMid"], 0),
    grvtBid: pickNumber(record, ["grvt_bid", "grvtBid"], 0),
    grvtAsk: pickNumber(record, ["grvt_ask", "grvtAsk"], 0),
    grvtMid: pickNumber(record, ["grvt_mid", "grvtMid"], 0),
    referenceMid: pickNumber(record, ["reference_mid", "referenceMid"], 0),
    tradableEdgePrice: pickNumber(record, ["tradable_edge_price", "tradableEdgePrice"], 0),
    tradableEdgePct: pickNumber(record, ["tradable_edge_pct", "tradableEdgePct"], 0),
    tradableEdgeBps: pickNumber(record, ["tradable_edge_bps", "tradableEdgeBps"], 0),
    direction: pickString(record, ["direction"], "unknown"),
    paradexMaxLeverage: pickNumber(record, ["paradex_max_leverage", "paradexMaxLeverage"], 1),
    grvtMaxLeverage: pickNumber(record, ["grvt_max_leverage", "grvtMaxLeverage"], 1),
    effectiveLeverage: pickNumber(record, ["effective_leverage", "effectiveLeverage"], 1),
    grossNominalSpread: pickNumber(record, ["gross_nominal_spread", "grossNominalSpread"], 0),
    feeCostEstimate: pickNumber(record, ["fee_cost_estimate", "feeCostEstimate"], 0),
    netNominalSpread: pickNumber(record, ["net_nominal_spread", "netNominalSpread"], 0),
    paradexFeeRate: pickNumber(record, ["paradex_fee_rate", "paradexFeeRate"], 0),
    grvtFeeRate: pickNumber(record, ["grvt_fee_rate", "grvtFeeRate"], 0),
    feeSource: {
      paradex: paradexFeeSourceRaw === "api" ? "api" : "official",
      grvt: grvtFeeSourceRaw === "api" ? "api" : "official"
    },
    updatedAt: pickString(record, ["updated_at", "updatedAt"], "")
  };
}

export function normalizeMarketTopSpreads(data: unknown): MarketTopSpreadsResponse {
  const fallback: MarketTopSpreadsResponse = {
    updatedAt: "",
    scanIntervalSec: 300,
    limit: 10,
    configuredSymbols: 0,
    comparableSymbols: 0,
    executableSymbols: 0,
    scannedSymbols: 0,
    totalSymbols: 0,
    skippedCount: 0,
    skippedReasons: {},
    feeProfile: { paradexLeg: "taker", grvtLeg: "maker" },
    lastError: null,
    rows: []
  };

  const record = toRecord(data);
  if (!record) {
    return fallback;
  }

  const rows = extractArray(record.rows)
    .map((item) => normalizeMarketSpreadRow(item))
    .filter((item): item is MarketTopSpreadRow => item !== null)
    .sort((a, b) => b.grossNominalSpread - a.grossNominalSpread);

  const skippedReasonsRecord = toRecord(record.skipped_reasons) ?? toRecord(record.skippedReasons) ?? {};
  const normalizedSkippedReasons: Record<string, number> = {};
  for (const [key, value] of Object.entries(skippedReasonsRecord)) {
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      normalizedSkippedReasons[key] = value;
      continue;
    }
    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed) && parsed > 0) {
        normalizedSkippedReasons[key] = parsed;
      }
    }
  }

  const feeProfileRecord = toRecord(record.fee_profile) ?? toRecord(record.feeProfile);
  const paradexLegRaw = pickString(feeProfileRecord ?? {}, ["paradex_leg", "paradexLeg"], "taker");
  const grvtLegRaw = pickString(feeProfileRecord ?? {}, ["grvt_leg", "grvtLeg"], "maker");
  const lastErrorRaw = record.last_error ?? record.lastError;

  return {
    updatedAt: pickString(record, ["updated_at", "updatedAt"], fallback.updatedAt),
    scanIntervalSec: pickNumber(record, ["scan_interval_sec", "scanIntervalSec"], fallback.scanIntervalSec),
    limit: Math.max(1, pickNumber(record, ["limit"], fallback.limit)),
    configuredSymbols: Math.max(0, pickNumber(record, ["configured_symbols", "configuredSymbols"], fallback.configuredSymbols)),
    comparableSymbols: Math.max(0, pickNumber(record, ["comparable_symbols", "comparableSymbols"], fallback.comparableSymbols)),
    executableSymbols: Math.max(0, pickNumber(record, ["executable_symbols", "executableSymbols"], rows.length)),
    scannedSymbols: Math.max(0, pickNumber(record, ["scanned_symbols", "scannedSymbols"], fallback.scannedSymbols)),
    totalSymbols: Math.max(0, pickNumber(record, ["total_symbols", "totalSymbols"], rows.length)),
    skippedCount: Math.max(0, pickNumber(record, ["skipped_count", "skippedCount"], fallback.skippedCount)),
    skippedReasons: normalizedSkippedReasons,
    feeProfile: {
      paradexLeg: paradexLegRaw === "taker" ? "taker" : "taker",
      grvtLeg: grvtLegRaw === "taker" ? "taker" : "maker"
    },
    lastError: typeof lastErrorRaw === "string" && lastErrorRaw.trim() ? lastErrorRaw : null,
    rows
  };
}

function normalizeTradeTopCandidate(data: unknown): TradeTopCandidate | null {
  const record = toRecord(data);
  if (!record) {
    return null;
  }

  const symbol = pickString(record, ["symbol"], "");
  if (!symbol) {
    return null;
  }

  return {
    symbol,
    paradexMarket: pickString(record, ["paradex_market", "paradexMarket"], ""),
    grvtMarket: pickString(record, ["grvt_market", "grvtMarket"], ""),
    tradableEdgePct: pickNumber(record, ["tradable_edge_pct", "tradableEdgePct"], 0),
    tradableEdgeBps: pickNumber(record, ["tradable_edge_bps", "tradableEdgeBps"], 0),
    grossNominalSpread: pickNumber(record, ["gross_nominal_spread", "grossNominalSpread"], 0)
  };
}

export function normalizeTradeSelection(data: unknown): TradeSelection {
  const fallback: TradeSelection = {
    selectedSymbol: "",
    top10Candidates: [],
    updatedAt: ""
  };

  const record = toRecord(data);
  if (!record) {
    return fallback;
  }

  const top10Candidates = extractArray(record.top10_candidates ?? record.top10Candidates)
    .map((item) => normalizeTradeTopCandidate(item))
    .filter((item): item is TradeTopCandidate => item !== null);

  return {
    selectedSymbol: pickString(record, ["selected_symbol", "selectedSymbol"], ""),
    top10Candidates,
    updatedAt: pickString(record, ["updated_at", "updatedAt"], "")
  };
}

export function normalizePublicConfig(data: unknown): PublicConfig {
  const fallback: PublicConfig = {
    runtime: {
      dryRun: true,
      simulatedMarketData: true,
      liveOrderEnabled: false,
      enableOrderConfirmationText: "ENABLE_LIVE_ORDER",
      defaultMode: "normal_arb"
    },
    symbols: []
  };

  const record = toRecord(data);
  if (!record) {
    return fallback;
  }

  const runtimeRecord = toRecord(record.runtime) ?? toRecord(record.runtime_config) ?? toRecord(record.runtimeConfig);
  const symbolItems = extractArray(record.symbols)
    .map((item) => normalizeSupportedSymbol(item))
    .filter((item): item is SupportedSymbolInfo => item !== null);

  if (!runtimeRecord) {
    return { ...fallback, symbols: symbolItems };
  }

  const dryRunRaw = runtimeRecord.dry_run ?? runtimeRecord.dryRun;
  const simulatedMarketDataRaw = runtimeRecord.simulated_market_data ?? runtimeRecord.simulatedMarketData ?? dryRunRaw;
  const liveOrderEnabledRaw = runtimeRecord.live_order_enabled ?? runtimeRecord.liveOrderEnabled;
  const confirmationTextRaw = runtimeRecord.enable_order_confirmation_text ?? runtimeRecord.enableOrderConfirmationText;
  const defaultModeRaw = runtimeRecord.default_mode ?? runtimeRecord.defaultMode;

  return {
    runtime: {
      dryRun: typeof dryRunRaw === "boolean" ? dryRunRaw : fallback.runtime.dryRun,
      simulatedMarketData:
        typeof simulatedMarketDataRaw === "boolean" ? simulatedMarketDataRaw : fallback.runtime.simulatedMarketData,
      liveOrderEnabled: typeof liveOrderEnabledRaw === "boolean" ? liveOrderEnabledRaw : fallback.runtime.liveOrderEnabled,
      enableOrderConfirmationText:
        typeof confirmationTextRaw === "string" && confirmationTextRaw.trim()
          ? confirmationTextRaw
          : fallback.runtime.enableOrderConfirmationText,
      defaultMode: defaultModeRaw === "zero_wear" ? "zero_wear" : "normal_arb"
    },
    symbols: symbolItems
  };
}

export const apiClient = {
  async getStatus(): Promise<DashboardStatus> {
    const response = await requestJson<unknown>("/api/status");
    return normalizeStatus(response);
  },

  async getSymbols(): Promise<SymbolRow[]> {
    const response = await requestJson<unknown>("/api/symbols");
    return normalizeSymbols(response);
  },

  async getEvents(limit = 100): Promise<EventLog[]> {
    const response = await requestJson<unknown>(`/api/events?limit=${limit}`);
    return normalizeEvents(response);
  },

  async startEngine(): Promise<ActionResult> {
    const response = await requestJson<unknown>("/api/engine/start", { method: "POST" });
    return normalizeActionResult(response, "引擎启动命令已发送");
  },

  async stopEngine(): Promise<ActionResult> {
    const response = await requestJson<unknown>("/api/engine/stop", { method: "POST" });
    return normalizeActionResult(response, "引擎停止命令已发送");
  },

  async setMode(mode: TradingMode): Promise<ActionResult> {
    const response = await requestJson<unknown>("/api/mode", {
      method: "POST",
      body: JSON.stringify({ mode })
    });
    return normalizeActionResult(response, "模式切换命令已发送");
  },

  async updateSymbolParams(symbol: string, payload: SymbolParamsPayload): Promise<ActionResult> {
    const response = await requestJson<unknown>(`/api/symbol/${encodeURIComponent(symbol)}/params`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    return normalizeActionResult(response, `已更新 ${symbol} 参数`);
  },

  async flattenSymbol(symbol: string): Promise<ActionResult> {
    const response = await requestJson<unknown>(`/api/symbol/${encodeURIComponent(symbol)}/flatten`, {
      method: "POST"
    });
    return normalizeActionResult(response, `${symbol} 平仓命令已发送`);
  },

  async getCredentialsStatus(): Promise<CredentialsStatus> {
    const response = await requestJson<unknown>("/api/credentials/status");
    return normalizeCredentialsStatus(response);
  },

  async saveCredentials(payload: CredentialsPayload): Promise<ActionResult> {
    const response = await requestJson<unknown>("/api/credentials", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    return normalizeActionResult(response, "API 凭证保存成功");
  },

  async applyCredentials(): Promise<ActionResult> {
    const response = await requestJson<unknown>("/api/credentials/apply", {
      method: "POST"
    });
    return normalizeActionResult(response, "凭证已应用");
  },

  async validateCredentials(payload: { source: CredentialsValidationSource; payload?: CredentialsPayload }): Promise<CredentialsValidationResponse> {
    const response = await requestJson<unknown>("/api/credentials/validate", {
      method: "POST",
      body: JSON.stringify(payload)
    });

    const record = toRecord(response);
    const dataRecord = toRecord(record?.data);

    const parseExchange = (value: unknown): ExchangeValidationResult => {
      const exchangeRecord = toRecord(value);
      if (!exchangeRecord) {
        return {
          valid: false,
          reason: "未返回校验结果",
          checks: {}
        };
      }

      const checksRecord = toRecord(exchangeRecord.checks);
      const checks: Record<string, boolean> = {};
      if (checksRecord) {
        for (const [key, rawValue] of Object.entries(checksRecord)) {
          checks[key] = normalizeConfiguredFlag(rawValue);
        }
      }

      return {
        valid: normalizeConfiguredFlag(exchangeRecord.valid),
        reason: pickString(exchangeRecord, ["reason", "message", "detail"], ""),
        checks
      };
    };

    const paradex = parseExchange(dataRecord?.paradex);
    const grvt = parseExchange(dataRecord?.grvt);

    return {
      ok: normalizeConfiguredFlag(record?.ok),
      message: pickString(record ?? {}, ["message", "detail"], ""),
      data: dataRecord
        ? {
            paradex,
            grvt
          }
        : null
    };
  },

  async setOrderExecution(liveOrderEnabled: boolean, confirmText?: string): Promise<ActionResult> {
    const response = await requestJson<unknown>("/api/runtime/order-execution", {
      method: "POST",
      body: JSON.stringify({
        live_order_enabled: liveOrderEnabled,
        confirm_text: confirmText ?? ""
      })
    });
    return normalizeActionResult(response, "下单开关已更新");
  },

  async setMarketDataMode(simulatedMarketData: boolean): Promise<ActionResult> {
    const response = await requestJson<unknown>("/api/runtime/market-data-mode", {
      method: "POST",
      body: JSON.stringify({ simulated_market_data: simulatedMarketData })
    });
    return normalizeActionResult(response, "行情模式已更新");
  },

  async getTradeSelection(options?: { forceRefresh?: boolean }): Promise<TradeSelection> {
    const params = new URLSearchParams();
    if (options?.forceRefresh) {
      params.set("force_refresh", "true");
    }
    const query = params.toString();
    const path = query ? `/api/trade/selection?${query}` : "/api/trade/selection";
    const response = await requestJson<unknown>(path);
    return normalizeTradeSelection(response);
  },

  async setTradeSelection(symbol: string, options?: { forceRefresh?: boolean }): Promise<ActionResult> {
    const response = await requestJson<unknown>("/api/trade/selection", {
      method: "POST",
      body: JSON.stringify({
        symbol,
        force_refresh: options?.forceRefresh ?? true
      })
    });
    return normalizeActionResult(response, "交易标的已更新");
  },

  async getPublicConfig(): Promise<PublicConfig> {
    const response = await requestJson<unknown>("/api/config");
    return normalizePublicConfig(response);
  },

  async getMarketTopSpreads(options?: { limit?: number; forceRefresh?: boolean }): Promise<MarketTopSpreadsResponse> {
    const params = new URLSearchParams();
    const limit = options?.limit ?? 10;
    const forceRefresh = options?.forceRefresh ?? false;

    params.set("limit", String(limit));
    if (forceRefresh) {
      params.set("force_refresh", "true");
    }

    const response = await requestJson<unknown>(`/api/market/top-spreads?${params.toString()}`);
    return normalizeMarketTopSpreads(response);
  }
};
