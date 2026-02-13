import { useCallback, useEffect, useRef, useState } from "react";
import {
  apiClient,
  getErrorMessage,
  normalizeEvent,
  normalizeEvents,
  normalizeStatus,
  normalizeSymbol,
  normalizeSymbols,
  toRecord
} from "../api/client";
import { DEFAULT_STATUS } from "../types";
import type {
  ActionResult,
  DashboardStatus,
  EventLevel,
  EventLog,
  SymbolParamsPayload,
  SymbolRow,
  TradingMode,
  WsConnectionStatus,
  WsStreamMessage
} from "../types";
import { WsStreamClient } from "../ws/client";

const EVENTS_LIMIT = 200;
const POLL_INTERVAL_MS = 15000;
const WS_SYMBOL_FLUSH_MS = 250;

const DEFAULT_WS_STATUS: WsConnectionStatus = {
  state: "connecting",
  attempt: 0,
  message: "准备连接实时流"
};

function sortSymbols(rows: SymbolRow[]): SymbolRow[] {
  return [...rows].sort((a, b) => a.symbol.localeCompare(b.symbol));
}

function upsertSymbol(rows: SymbolRow[], nextItem: SymbolRow): SymbolRow[] {
  const nextRows = [...rows];
  const index = nextRows.findIndex((item) => item.symbol === nextItem.symbol);

  if (index === -1) {
    nextRows.push(nextItem);
  } else {
    nextRows[index] = nextItem;
  }

  return sortSymbols(nextRows);
}

function sortEvents(rows: EventLog[]): EventLog[] {
  return [...rows].sort((a, b) => b.ts.localeCompare(a.ts));
}

function limitEvents(rows: EventLog[]): EventLog[] {
  return rows.slice(0, EVENTS_LIMIT);
}

function createLocalEvent(level: EventLevel, message: string): EventLog {
  const ts = new Date().toISOString();
  return {
    id: `ui-${ts}-${Math.random().toString(36).slice(2, 8)}`,
    ts,
    level,
    source: "ui",
    message
  };
}

export function useDashboard() {
  const [status, setStatus] = useState<DashboardStatus>({ ...DEFAULT_STATUS });
  const [symbols, setSymbols] = useState<SymbolRow[]>([]);
  const [events, setEvents] = useState<EventLog[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [actionMessage, setActionMessage] = useState<string>("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [wsStatus, setWsStatus] = useState<WsConnectionStatus>(DEFAULT_WS_STATUS);
  const offlineHintShownRef = useRef(false);
  const pendingSymbolUpdatesRef = useRef<Record<string, SymbolRow>>({});
  const symbolFlushTimerRef = useRef<number | null>(null);

  const pushEvent = useCallback((event: EventLog) => {
    setEvents((previous) => limitEvents(sortEvents([event, ...previous])));
  }, []);

  const flushPendingSymbols = useCallback(() => {
    symbolFlushTimerRef.current = null;

    const pending = pendingSymbolUpdatesRef.current;
    pendingSymbolUpdatesRef.current = {};
    const updates = Object.values(pending);
    if (updates.length === 0) {
      return;
    }

    // 合并一批 symbol 更新，避免 WebSocket 高频推送导致 UI 持续抖动。
    setSymbols((previous) => {
      let next = previous;
      for (const item of updates) {
        next = upsertSymbol(next, item);
      }
      return next;
    });
  }, []);

  const clearPendingSymbolUpdates = useCallback(() => {
    if (symbolFlushTimerRef.current !== null) {
      window.clearTimeout(symbolFlushTimerRef.current);
      symbolFlushTimerRef.current = null;
    }
    pendingSymbolUpdatesRef.current = {};
  }, []);

  const loadDashboard = useCallback(
    async (silent: boolean) => {
      if (!silent) {
        setLoading(true);
      }

      const results = await Promise.allSettled([
        apiClient.getStatus(),
        apiClient.getSymbols(),
        apiClient.getEvents(100)
      ]);

      const nextErrors: string[] = [];

      const statusResult = results[0];
      if (statusResult.status === "fulfilled") {
        setStatus(statusResult.value);
      } else {
        nextErrors.push(`/api/status: ${getErrorMessage(statusResult.reason)}`);
      }

      const symbolsResult = results[1];
      if (symbolsResult.status === "fulfilled") {
        setSymbols(sortSymbols(symbolsResult.value));
      } else {
        nextErrors.push(`/api/symbols: ${getErrorMessage(symbolsResult.reason)}`);
      }

      const eventsResult = results[2];
      if (eventsResult.status === "fulfilled") {
        setEvents(limitEvents(sortEvents(eventsResult.value)));
      } else {
        nextErrors.push(`/api/events: ${getErrorMessage(eventsResult.reason)}`);
      }

      if (nextErrors.length > 0) {
        const friendlyMessage = `部分数据加载失败：${nextErrors.join("；")}`;
        setErrorMessage(friendlyMessage);

        if (nextErrors.length === 3 && !offlineHintShownRef.current) {
          offlineHintShownRef.current = true;
          pushEvent(createLocalEvent("warn", "后端暂不可达，页面已进入离线展示模式。"));
        }
      } else {
        setErrorMessage("");
      }

      if (!silent) {
        setLoading(false);
      }
    },
    [pushEvent]
  );

  useEffect(() => {
    void loadDashboard(false);
  }, [loadDashboard]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadDashboard(true);
    }, POLL_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [loadDashboard]);

  const handleWsMessage = useCallback(
    (message: WsStreamMessage) => {
      if (message.type === "event") {
        const next = normalizeEvent(message.data);
        if (next) {
          pushEvent(next);
        }
        return;
      }

      if (message.type === "symbol") {
        const next = normalizeSymbol(message.data);
        if (next) {
          pendingSymbolUpdatesRef.current[next.symbol] = next;
          if (symbolFlushTimerRef.current === null) {
            symbolFlushTimerRef.current = window.setTimeout(flushPendingSymbols, WS_SYMBOL_FLUSH_MS);
          }
        }
        return;
      }

      if (message.type === "market_top_spreads") {
        return;
      }

      // snapshot 到来时，以聚合数据为准，清空等待刷新队列，避免旧的 symbol 更新覆盖新快照。
      clearPendingSymbolUpdates();

      const payload = toRecord(message.data);
      if (!payload) {
        return;
      }

      if ("status" in payload) {
        setStatus(normalizeStatus(payload.status));
      } else if ("engine_status" in payload || "engineStatus" in payload || "mode" in payload) {
        setStatus(normalizeStatus(payload));
      }

      if ("symbols" in payload) {
        setSymbols(normalizeSymbols(payload.symbols));
      }

      if ("events" in payload) {
        const nextEvents = normalizeEvents(payload.events);
        if (nextEvents.length > 0) {
          setEvents(limitEvents(sortEvents(nextEvents)));
        }
      }
    },
    [clearPendingSymbolUpdates, flushPendingSymbols, pushEvent]
  );

  useEffect(() => {
    const client = new WsStreamClient({
      onMessage: handleWsMessage,
      onStateChange: setWsStatus
    });

    client.connect();

    return () => {
      clearPendingSymbolUpdates();
      client.disconnect();
    };
  }, [clearPendingSymbolUpdates, handleWsMessage]);

  const runAction = useCallback(
    async (actionKey: string, actionName: string, action: () => Promise<ActionResult>): Promise<boolean> => {
      setBusyAction(actionKey);
      setActionMessage("");

      try {
        const result = await action();
        if (!result.ok) {
          throw new Error(result.message || `${actionName}执行失败`);
        }

        const message = result.message || `${actionName}成功`;
        setActionMessage(message);
        setErrorMessage("");
        pushEvent(createLocalEvent("info", message));
        return true;
      } catch (error) {
        const message = `${actionName}失败：${getErrorMessage(error)}`;
        setErrorMessage(message);
        pushEvent(createLocalEvent("error", message));
        return false;
      } finally {
        setBusyAction(null);
      }
    },
    [pushEvent]
  );

  const startEngine = useCallback(async () => {
    const ok = await runAction("start", "启动引擎", () => apiClient.startEngine());
    if (ok) {
      setStatus((previous) => ({
        ...previous,
        engineStatus: "starting",
        updatedAt: new Date().toISOString()
      }));
      void loadDashboard(true);
    }
  }, [loadDashboard, runAction]);

  const stopEngine = useCallback(async () => {
    const ok = await runAction("stop", "停止引擎", () => apiClient.stopEngine());
    if (ok) {
      setStatus((previous) => ({
        ...previous,
        engineStatus: "stopping",
        updatedAt: new Date().toISOString()
      }));
      void loadDashboard(true);
    }
  }, [loadDashboard, runAction]);

  const changeMode = useCallback(
    async (mode: TradingMode) => {
      const ok = await runAction("mode", "切换模式", () => apiClient.setMode(mode));
      if (ok) {
        setStatus((previous) => ({
          ...previous,
          mode,
          updatedAt: new Date().toISOString()
        }));
        void loadDashboard(true);
      }
    },
    [loadDashboard, runAction]
  );

  const updateSymbolParams = useCallback(
    async (symbol: string, payload: SymbolParamsPayload) => {
      if (!symbol.trim()) {
        const message = "更新参数失败：未选择交易对";
        setErrorMessage(message);
        pushEvent(createLocalEvent("error", message));
        return;
      }

      const ok = await runAction("params", "更新参数", () => apiClient.updateSymbolParams(symbol, payload));
      if (ok) {
        void loadDashboard(true);
      }
    },
    [loadDashboard, pushEvent, runAction]
  );

  const flattenSymbol = useCallback(
    async (symbol: string) => {
      if (!symbol.trim()) {
        const message = "平仓失败：未选择交易对";
        setErrorMessage(message);
        pushEvent(createLocalEvent("error", message));
        return;
      }

      const ok = await runAction("flatten", "一键平仓", () => apiClient.flattenSymbol(symbol));
      if (ok) {
        void loadDashboard(true);
      }
    },
    [loadDashboard, pushEvent, runAction]
  );

  const refresh = useCallback(async () => {
    await loadDashboard(false);
  }, [loadDashboard]);

  return {
    status,
    symbols,
    events,
    loading,
    errorMessage,
    actionMessage,
    wsStatus,
    busyAction,
    isBusy: busyAction !== null,
    refresh,
    startEngine,
    stopEngine,
    changeMode,
    updateSymbolParams,
    flattenSymbol
  };
}
