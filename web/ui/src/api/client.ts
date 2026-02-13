import { DEFAULT_STATUS } from "../types";
import type {
  ActionResult,
  DashboardStatus,
  EngineStatus,
  EventLevel,
  EventLog,
  PublicConfig,
  SymbolParamsPayload,
  SymbolRow,
  TradingMode
} from "../types";

const REQUEST_TIMEOUT_MS = 8000;
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").trim();

const PARADEX_FIELDS = ["api_key", "api_secret", "passphrase"] as const;
const GRVT_FIELDS = ["private_key", "trading_account_id", "api_key"] as const;

export type ParadexCredentialField = (typeof PARADEX_FIELDS)[number];
export type GrvtCredentialField = (typeof GRVT_FIELDS)[number];

export interface ParadexCredentialsInput {
  api_key: string;
  api_secret: string;
  passphrase: string;
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
}

export interface CredentialsStatus {
  paradex: Record<ParadexCredentialField, CredentialFieldStatus>;
  grvt: Record<GrvtCredentialField, CredentialFieldStatus>;
}

export const DEFAULT_CREDENTIALS_STATUS: CredentialsStatus = {
  paradex: {
    api_key: { configured: false },
    api_secret: { configured: false },
    passphrase: { configured: false }
  },
  grvt: {
    private_key: { configured: false },
    trading_account_id: { configured: false },
    api_key: { configured: false }
  }
};

function cloneDefaultCredentialsStatus(): CredentialsStatus {
  return {
    paradex: {
      api_key: { configured: false },
      api_secret: { configured: false },
      passphrase: { configured: false }
    },
    grvt: {
      private_key: { configured: false },
      trading_account_id: { configured: false },
      api_key: { configured: false }
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

  if (rawText.trim().length > 0) {
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

  if (normalized === "running") {
    return "running";
  }
  if (normalized === "stopped") {
    return "stopped";
  }
  if (normalized === "starting") {
    return "starting";
  }
  if (normalized === "stopping") {
    return "stopping";
  }
  if (normalized === "error") {
    return "error";
  }
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

  const candidates = ["items", "rows", "list", "data", "symbols", "events"];
  for (const key of candidates) {
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
    engineStatus: parseEngineStatus(
      pickString(record, ["engine_status", "engineStatus", "status"], DEFAULT_STATUS.engineStatus)
    ),
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
  const rows = extractArray(data)
    .map((item) => normalizeSymbol(item))
    .filter((item): item is SymbolRow => item !== null);
  return rows.sort((a, b) => a.symbol.localeCompare(b.symbol));
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
  const id = pickString(
    record,
    ["id", "event_id", "eventId"],
    `${source}-${ts}-${Math.random().toString(36).slice(2, 8)}`
  );

  return {
    id,
    ts,
    level: parseEventLevel(pickString(record, ["level", "severity"], "info")),
    source,
    message
  };
}

export function normalizeEvents(data: unknown): EventLog[] {
  const rows = extractArray(data)
    .map((item) => normalizeEvent(item))
    .filter((item): item is EventLog => item !== null);
  return rows.sort((a, b) => b.ts.localeCompare(a.ts));
}

function normalizeActionResult(data: unknown, fallback: string): ActionResult {
  const record = toRecord(data);
  if (!record) {
    return {
      ok: true,
      message: fallback
    };
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
    if (
      normalized === "true" ||
      normalized === "1" ||
      normalized === "yes" ||
      normalized === "configured" ||
      normalized === "set"
    ) {
      return true;
    }
    if (normalized === "false" || normalized === "0" || normalized === "no" || normalized === "unset") {
      return false;
    }
  }

  const record = toRecord(value);
  if (record) {
    if ("configured" in record) {
      return normalizeConfiguredFlag(record.configured);
    }
    if ("is_configured" in record) {
      return normalizeConfiguredFlag(record.is_configured);
    }
    if ("isConfigured" in record) {
      return normalizeConfiguredFlag(record.isConfigured);
    }
    if ("set" in record) {
      return normalizeConfiguredFlag(record.set);
    }
    if ("exists" in record) {
      return normalizeConfiguredFlag(record.exists);
    }
  }

  return false;
}

function extractConfiguredFieldSet(record: Record<string, unknown>): Set<string> {
  const set = new Set<string>();

  const candidates = ["configured_fields", "configuredFields", "fields"];
  for (const key of candidates) {
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

function normalizeExchangeStatus<T extends string>(
  source: unknown,
  fields: readonly T[]
): Record<T, CredentialFieldStatus> {
  const result = {} as Record<T, CredentialFieldStatus>;
  for (const field of fields) {
    result[field] = { configured: false };
  }

  if (Array.isArray(source)) {
    const configuredSet = new Set(source.filter((item): item is string => typeof item === "string"));
    for (const field of fields) {
      result[field] = { configured: configuredSet.has(field) };
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
      result[field] = { configured: normalizeConfiguredFlag(record[field]) };
      continue;
    }

    result[field] = { configured: configuredSet.has(field) };
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

  const paradexSource =
    sourceRecord.paradex ?? sourceRecord.paradex_status ?? sourceRecord.paradexStatus;
  const grvtSource = sourceRecord.grvt ?? sourceRecord.grvt_status ?? sourceRecord.grvtStatus;

  return {
    paradex: normalizeExchangeStatus(paradexSource, PARADEX_FIELDS),
    grvt: normalizeExchangeStatus(grvtSource, GRVT_FIELDS)
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
    }
  };

  const record = toRecord(data);
  if (!record) {
    return fallback;
  }

  const runtimeRecord = toRecord(record.runtime) ?? toRecord(record.runtime_config) ?? toRecord(record.runtimeConfig);
  if (!runtimeRecord) {
    return fallback;
  }

  const dryRunRaw = runtimeRecord.dry_run ?? runtimeRecord.dryRun;
  const simulatedMarketDataRaw =
    runtimeRecord.simulated_market_data ?? runtimeRecord.simulatedMarketData ?? dryRunRaw;
  const liveOrderEnabledRaw = runtimeRecord.live_order_enabled ?? runtimeRecord.liveOrderEnabled;
  const confirmationTextRaw =
    runtimeRecord.enable_order_confirmation_text ?? runtimeRecord.enableOrderConfirmationText;
  const defaultModeRaw = runtimeRecord.default_mode ?? runtimeRecord.defaultMode;

  return {
    runtime: {
      dryRun: typeof dryRunRaw === "boolean" ? dryRunRaw : fallback.runtime.dryRun,
      simulatedMarketData:
        typeof simulatedMarketDataRaw === "boolean"
          ? simulatedMarketDataRaw
          : fallback.runtime.simulatedMarketData,
      liveOrderEnabled:
        typeof liveOrderEnabledRaw === "boolean" ? liveOrderEnabledRaw : fallback.runtime.liveOrderEnabled,
      enableOrderConfirmationText:
        typeof confirmationTextRaw === "string" && confirmationTextRaw.trim()
          ? confirmationTextRaw
          : fallback.runtime.enableOrderConfirmationText,
      defaultMode: defaultModeRaw === "zero_wear" ? "zero_wear" : "normal_arb"
    }
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
    const response = await requestJson<unknown>("/api/engine/start", {
      method: "POST"
    });
    return normalizeActionResult(response, "引擎启动命令已发送");
  },

  async stopEngine(): Promise<ActionResult> {
    const response = await requestJson<unknown>("/api/engine/stop", {
      method: "POST"
    });
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
      body: JSON.stringify({
        simulated_market_data: simulatedMarketData
      })
    });
    return normalizeActionResult(response, "行情模式已更新");
  },

  async getPublicConfig(): Promise<PublicConfig> {
    const response = await requestJson<unknown>("/api/config");
    return normalizePublicConfig(response);
  }
};
