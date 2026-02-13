import { useCallback, useEffect, useMemo, useState } from "react";

import { apiClient, getErrorMessage, normalizeMarketTopSpreads } from "../api/client";
import type { MarketTopSpreadRow, MarketTopSpreadsResponse, WsConnectionStatus, WsStreamMessage } from "../types";
import { formatNumber, formatSigned, formatTimestamp } from "../utils/format";
import { WsStreamClient } from "../ws/client";

const REFRESH_INTERVAL_MS = 20000;
const TOP_LIMIT = 10;
const DEFAULT_WS_STATUS: WsConnectionStatus = {
  state: "connecting",
  attempt: 0,
  message: "准备连接实时行情流"
};

const EMPTY_RESULT: MarketTopSpreadsResponse = {
  updatedAt: "",
  scanIntervalSec: 300,
  limit: TOP_LIMIT,
  configuredSymbols: 0,
  comparableSymbols: 0,
  executableSymbols: 0,
  scannedSymbols: 0,
  totalSymbols: 0,
  skippedCount: 0,
  skippedReasons: {},
  feeProfile: {
    paradexLeg: "taker",
    grvtLeg: "maker"
  },
  lastError: null,
  rows: []
};

function formatSkippedReasons(skippedReasons: Record<string, number>): string {
  const entries = Object.entries(skippedReasons);
  if (entries.length === 0) {
    return "无";
  }

  return entries
    .sort((a, b) => b[1] - a[1])
    .map(([reason, count]) => `${reason}(${count})`)
    .join("，");
}

function toNominalSpreadPct(row: MarketTopSpreadRow): number {
  if (!Number.isFinite(row.referenceMid) || row.referenceMid <= 0) {
    return 0;
  }
  return (row.grossNominalSpread / row.referenceMid) * 100;
}

function toNetNominalSpreadPct(row: MarketTopSpreadRow): number {
  if (!Number.isFinite(row.referenceMid) || row.referenceMid <= 0) {
    return 0;
  }
  return (row.netNominalSpread / row.referenceMid) * 100;
}

function marketWsHint(status: WsConnectionStatus): string {
  if (status.state === "connected") {
    return "WS 实时流已连接";
  }
  if (status.state === "reconnecting") {
    return `WS 重连中（第 ${status.attempt} 次），当前使用轮询兜底`;
  }
  if (status.state === "error") {
    return "WS 异常，当前使用轮询兜底";
  }
  if (status.state === "disconnected") {
    return "WS 已断开，当前使用轮询兜底";
  }
  return "WS 连接中...";
}

export default function MarketPage() {
  const [result, setResult] = useState<MarketTopSpreadsResponse>(EMPTY_RESULT);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [wsStatus, setWsStatus] = useState<WsConnectionStatus>(DEFAULT_WS_STATUS);

  const loadSpreads = useCallback(async (options?: { forceRefresh?: boolean; silent?: boolean }) => {
    const forceRefresh = options?.forceRefresh ?? false;
    const silent = options?.silent ?? false;

    if (!silent) {
      setLoading(true);
    }
    if (forceRefresh) {
      setRefreshing(true);
    }

    try {
      const response = await apiClient.getMarketTopSpreads({
        limit: TOP_LIMIT,
        forceRefresh
      });
      setResult(response);
      setErrorMessage("");
    } catch (error) {
      setErrorMessage(`加载行情排行失败：${getErrorMessage(error)}`);
    } finally {
      if (!silent) {
        setLoading(false);
      }
      if (forceRefresh) {
        setRefreshing(false);
      }
    }
  }, []);

  const handleWsMessage = useCallback((message: WsStreamMessage) => {
    if (message.type !== "market_top_spreads") {
      return;
    }
    setResult(normalizeMarketTopSpreads(message.data));
    setLoading(false);
    setErrorMessage("");
  }, []);

  useEffect(() => {
    const client = new WsStreamClient({
      onMessage: handleWsMessage,
      onStateChange: setWsStatus
    });
    client.connect();
    return () => client.disconnect();
  }, [handleWsMessage]);

  useEffect(() => {
    void loadSpreads({ forceRefresh: true });
  }, [loadSpreads]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (wsStatus.state !== "connected") {
        void loadSpreads({ forceRefresh: true, silent: true });
      }
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadSpreads, wsStatus.state]);

  const onForceRefreshClick = () => {
    void loadSpreads({ forceRefresh: true });
  };

  const topRows = useMemo(
    () => [...result.rows].sort((a, b) => toNominalSpreadPct(b) - toNominalSpreadPct(a)).slice(0, TOP_LIMIT),
    [result.rows]
  );

  const summaryText = useMemo(() => {
    if (loading) {
      return "加载中...";
    }
    if (topRows.length === 0) {
      return "当前无可执行价差";
    }
    return `下单配置 ${result.configuredSymbols} 个币对，可比 ${result.comparableSymbols} 个，可执行 ${result.executableSymbols} 个`;
  }, [loading, result.comparableSymbols, result.configuredSymbols, result.executableSymbols, topRows.length]);

  return (
    <div className="page-grid">
      {errorMessage ? <div className="banner banner-error">{errorMessage}</div> : null}
      {result.lastError ? <div className="banner banner-warning">{result.lastError}</div> : null}

      <section className="panel page-panel">
        <div className="panel-title">
          <h2>行情页</h2>
          <small>{summaryText}</small>
        </div>

        <div className="market-controls market-controls-compact">
          <button className="btn btn-ghost" type="button" onClick={onForceRefreshClick} disabled={refreshing}>
            {refreshing ? "刷新中..." : "强制刷新"}
          </button>
        </div>

        <p className="hint">
          展示口径已统一为百分比：实际价差(%) 使用可执行价差百分比；名义价差(%) 与净名义价差(%) 均按参考中间价换算。
        </p>
        <p className="hint">{marketWsHint(wsStatus)}</p>
        <p className="hint">
          最近刷新 {formatTimestamp(result.updatedAt)}，扫描周期约 {result.scanIntervalSec} 秒，
          下单配置 {result.configuredSymbols} 个币对，可比 {result.comparableSymbols} 个，可执行 {result.executableSymbols} 个，
          跳过 {result.skippedCount} 个（{formatSkippedReasons(result.skippedReasons)}）。
        </p>
      </section>

      <section className="panel page-panel">
        <div className="panel-title">
          <h2>名义价差 Top10</h2>
          <small>仅保留核心百分比字段</small>
        </div>

        <div className="table-wrap">
          <table className="responsive-table">
            <thead>
              <tr>
                <th>#</th>
                <th>币对</th>
                <th>实际价差(%)</th>
                <th>有效杠杆</th>
                <th>名义价差(%)</th>
                <th>净名义价差(%)</th>
              </tr>
            </thead>
            <tbody>
              {topRows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="empty-cell">
                    暂无行情数据
                  </td>
                </tr>
              ) : (
                topRows.map((row, index) => (
                  <tr key={row.symbol}>
                    <td data-label="排名">{index + 1}</td>
                    <td data-label="币对">{row.symbol}</td>
                    <td data-label="实际价差(%)">
                      <strong>{formatSigned(row.tradableEdgePct, 4)}%</strong>
                    </td>
                    <td data-label="有效杠杆">
                      <strong>{formatNumber(row.effectiveLeverage, 2)}x</strong>
                    </td>
                    <td data-label="名义价差(%)">
                      <strong>{formatSigned(toNominalSpreadPct(row), 4)}%</strong>
                    </td>
                    <td data-label="净名义价差(%)">
                      <strong>{formatSigned(toNetNominalSpreadPct(row), 4)}%</strong>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
