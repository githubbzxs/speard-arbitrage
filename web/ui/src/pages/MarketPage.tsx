import { useCallback, useEffect, useMemo, useState } from "react";

import { apiClient, getErrorMessage } from "../api/client";
import type { MarketTopSpreadsResponse } from "../types";
import { formatNumber, formatPrice, formatSigned, formatTimestamp } from "../utils/format";

const REFRESH_INTERVAL_MS = 20000;
const DEFAULT_LIMIT = 10;

const EMPTY_RESULT: MarketTopSpreadsResponse = {
  updatedAt: "",
  scanIntervalSec: 300,
  limit: DEFAULT_LIMIT,
  totalSymbols: 0,
  fallback: {
    paradex: 2,
    grvt: 2
  },
  lastError: null,
  rows: []
};

function parseLeverage(value: string, defaultValue: number): number {
  const parsed = Number(value.trim());
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return defaultValue;
  }
  if (parsed > 200) {
    return 200;
  }
  if (parsed < 1) {
    return 1;
  }
  return parsed;
}

function leverageSourceLabel(source: "market" | "fallback"): string {
  return source === "market" ? "交易所" : "回退";
}

export default function MarketPage() {
  const [result, setResult] = useState<MarketTopSpreadsResponse>(EMPTY_RESULT);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const [appliedParadexFallback, setAppliedParadexFallback] = useState(2);
  const [appliedGrvtFallback, setAppliedGrvtFallback] = useState(2);
  const [draftParadexFallback, setDraftParadexFallback] = useState("2");
  const [draftGrvtFallback, setDraftGrvtFallback] = useState("2");

  const loadSpreads = useCallback(
    async (
      options?: {
        forceRefresh?: boolean;
        paradexFallback?: number;
        grvtFallback?: number;
        silent?: boolean;
      }
    ) => {
      const forceRefresh = options?.forceRefresh ?? false;
      const silent = options?.silent ?? false;
      const paradexFallback = options?.paradexFallback ?? appliedParadexFallback;
      const grvtFallback = options?.grvtFallback ?? appliedGrvtFallback;

      if (!silent) {
        setLoading(true);
      }
      if (forceRefresh) {
        setRefreshing(true);
      }

      try {
        const response = await apiClient.getMarketTopSpreads({
          limit: DEFAULT_LIMIT,
          paradexFallbackLeverage: paradexFallback,
          grvtFallbackLeverage: grvtFallback,
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
    },
    [appliedParadexFallback, appliedGrvtFallback]
  );

  useEffect(() => {
    void loadSpreads();
  }, [loadSpreads]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadSpreads({ silent: true });
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadSpreads]);

  const onApplyFallbackClick = () => {
    const nextParadex = parseLeverage(draftParadexFallback, appliedParadexFallback);
    const nextGrvt = parseLeverage(draftGrvtFallback, appliedGrvtFallback);

    setAppliedParadexFallback(nextParadex);
    setAppliedGrvtFallback(nextGrvt);
    setDraftParadexFallback(String(nextParadex));
    setDraftGrvtFallback(String(nextGrvt));

    void loadSpreads({
      forceRefresh: true,
      paradexFallback: nextParadex,
      grvtFallback: nextGrvt
    });
  };

  const onForceRefreshClick = () => {
    void loadSpreads({ forceRefresh: true });
  };

  const topRows = result.rows;

  const summaryText = useMemo(() => {
    if (topRows.length === 0) {
      return "暂无可用币对";
    }
    return `展示全币对扫描后的 Top${topRows.length} 名义价差`;
  }, [topRows.length]);

  return (
    <div className="page-grid">
      {errorMessage ? <div className="banner banner-error">{errorMessage}</div> : null}
      {result.lastError ? <div className="banner banner-warning">{result.lastError}</div> : null}

      <section className="panel page-panel">
        <div className="panel-title">
          <h2>行情页</h2>
          <small>{loading ? "加载中..." : summaryText}</small>
        </div>

        <div className="market-controls">
          <div className="inline-fields">
            <label htmlFor="paradex-fallback">Paradex 回退杠杆</label>
            <input
              id="paradex-fallback"
              value={draftParadexFallback}
              onChange={(event) => setDraftParadexFallback(event.target.value)}
              placeholder="例如 2"
            />
          </div>

          <div className="inline-fields">
            <label htmlFor="grvt-fallback">GRVT 回退杠杆</label>
            <input
              id="grvt-fallback"
              value={draftGrvtFallback}
              onChange={(event) => setDraftGrvtFallback(event.target.value)}
              placeholder="例如 2"
            />
          </div>

          <button className="btn btn-secondary" type="button" onClick={onApplyFallbackClick} disabled={refreshing}>
            应用并刷新
          </button>
          <button className="btn btn-ghost" type="button" onClick={onForceRefreshClick} disabled={refreshing}>
            强制刷新
          </button>
        </div>

        <p className="hint">
          当前计算：名义价差 = |实际价差| × min(Paradex 杠杆, GRVT 杠杆)。
          当前回退杠杆：Paradex {formatNumber(result.fallback.paradex, 2)} / GRVT {formatNumber(result.fallback.grvt, 2)}。
        </p>
        <p className="hint">
          扫描周期约 {result.scanIntervalSec} 秒，最近刷新 {formatTimestamp(result.updatedAt)}，共覆盖 {result.totalSymbols} 个币对。
        </p>
      </section>

      <section className="panel page-panel">
        <div className="panel-title">
          <h2>名义价差 Top10</h2>
          <small>真实买卖一价格（Paradex + GRVT）</small>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>币对</th>
                <th>Paradex 买/卖</th>
                <th>GRVT 买/卖</th>
                <th>实际价差</th>
                <th>有效杠杆</th>
                <th>名义价差</th>
              </tr>
            </thead>
            <tbody>
              {topRows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="empty-cell">
                    暂无行情数据
                  </td>
                </tr>
              ) : (
                topRows.map((row, index) => (
                  <tr key={row.symbol}>
                    <td>{index + 1}</td>
                    <td>
                      <div>{row.symbol}</div>
                      <small className="muted-inline">{row.paradexMarket} / {row.grvtMarket}</small>
                    </td>
                    <td>
                      <div>{formatPrice(row.paradexBid)} / {formatPrice(row.paradexAsk)}</div>
                      <small className="muted-inline">中间价 {formatPrice(row.paradexMid)}</small>
                    </td>
                    <td>
                      <div>{formatPrice(row.grvtBid)} / {formatPrice(row.grvtAsk)}</div>
                      <small className="muted-inline">中间价 {formatPrice(row.grvtMid)}</small>
                    </td>
                    <td>
                      <div>{formatSigned(row.spreadPrice, 4)}</div>
                      <small className="muted-inline">{formatSigned(row.spreadBps, 2)} bps</small>
                    </td>
                    <td>
                      <div>{formatNumber(row.effectiveLeverage, 2)}x</div>
                      <small className="muted-inline">
                        P {formatNumber(row.paradexLeverage, 2)}x({leverageSourceLabel(row.paradexLeverageSource)}) / G {formatNumber(row.grvtLeverage, 2)}x({leverageSourceLabel(row.grvtLeverageSource)})
                      </small>
                    </td>
                    <td>
                      <strong>{formatSigned(row.nominalSpread, 4)}</strong>
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
