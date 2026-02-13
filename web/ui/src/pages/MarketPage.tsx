import { useCallback, useEffect, useMemo, useState } from "react";

import { apiClient, getErrorMessage } from "../api/client";
import type { MarketTopSpreadsResponse } from "../types";
import { formatNumber, formatPrice, formatSigned, formatTimestamp } from "../utils/format";

const REFRESH_INTERVAL_MS = 20000;
const TOP_LIMIT = 10;

const EMPTY_RESULT: MarketTopSpreadsResponse = {
  updatedAt: "",
  scanIntervalSec: 300,
  limit: TOP_LIMIT,
  scannedSymbols: 0,
  totalSymbols: 0,
  skippedCount: 0,
  skippedReasons: {},
  feeProfile: {
    paradexLeg: "taker",
    grvtLeg: "taker"
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

function directionLabel(direction: string): string {
  if (direction === "sell_paradex_taker_buy_grvt_taker" || direction === "sell_paradex_taker_buy_grvt_maker") {
    return "卖 Paradex / 买 GRVT";
  }
  if (direction === "buy_paradex_taker_sell_grvt_taker" || direction === "buy_paradex_taker_sell_grvt_maker") {
    return "买 Paradex / 卖 GRVT";
  }
  return direction || "--";
}

export default function MarketPage() {
  const [result, setResult] = useState<MarketTopSpreadsResponse>(EMPTY_RESULT);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

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

  useEffect(() => {
    void loadSpreads();
  }, [loadSpreads]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadSpreads({ silent: true });
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadSpreads]);

  const onForceRefreshClick = () => {
    void loadSpreads({ forceRefresh: true });
  };

  const topRows = result.rows.slice(0, TOP_LIMIT);

  const summaryText = useMemo(() => {
    if (loading) {
      return "加载中...";
    }
    if (topRows.length === 0) {
      return "当前无可执行价差";
    }
    return `全市场扫描 ${result.scannedSymbols} 个可比币对，展示名义价差 Top${topRows.length}`;
  }, [loading, result.scannedSymbols, topRows.length]);

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
          计算口径：实际价差 = max(Paradex 买一 - GRVT 卖一, GRVT 买一 - Paradex 卖一)；
          名义价差 = 实际价差 × min(Paradex 最大杠杆, GRVT 最大杠杆)。
        </p>
        <p className="hint">
          最近刷新 {formatTimestamp(result.updatedAt)}，扫描周期约 {result.scanIntervalSec} 秒，
          共覆盖 {result.totalSymbols} 个可用机会，跳过 {result.skippedCount} 个（{formatSkippedReasons(result.skippedReasons)}）。
        </p>
      </section>

      <section className="panel page-panel">
        <div className="panel-title">
          <h2>名义价差 Top10</h2>
          <small>两所真实买卖价（实时）</small>
        </div>

        <div className="table-wrap">
          <table className="responsive-table">
            <thead>
              <tr>
                <th>#</th>
                <th>币对</th>
                <th>Paradex 买/卖</th>
                <th>GRVT 买/卖</th>
                <th>方向</th>
                <th>实际价差</th>
                <th>有效杠杆</th>
                <th>名义价差</th>
                <th>预估费用</th>
                <th>净名义价差</th>
              </tr>
            </thead>
            <tbody>
              {topRows.length === 0 ? (
                <tr>
                  <td colSpan={10} className="empty-cell">
                    暂无行情数据
                  </td>
                </tr>
              ) : (
                topRows.map((row, index) => (
                  <tr key={row.symbol}>
                    <td data-label="排名">{index + 1}</td>
                    <td data-label="币对">
                      <div>{row.symbol}</div>
                      <small className="muted-inline">
                        {row.paradexMarket} / {row.grvtMarket}
                      </small>
                    </td>
                    <td data-label="Paradex 买/卖">
                      <div>
                        {formatPrice(row.paradexBid)} / {formatPrice(row.paradexAsk)}
                      </div>
                      <small className="muted-inline">中间价 {formatPrice(row.paradexMid)}</small>
                    </td>
                    <td data-label="GRVT 买/卖">
                      <div>
                        {formatPrice(row.grvtBid)} / {formatPrice(row.grvtAsk)}
                      </div>
                      <small className="muted-inline">中间价 {formatPrice(row.grvtMid)}</small>
                    </td>
                    <td data-label="方向">{directionLabel(row.direction)}</td>
                    <td data-label="实际价差">
                      <div>{formatSigned(row.tradableEdgePrice, 6)}</div>
                      <small className="muted-inline">{formatSigned(row.tradableEdgeBps, 2)} bps</small>
                    </td>
                    <td data-label="有效杠杆">
                      <div>{formatNumber(row.effectiveLeverage, 2)}x</div>
                      <small className="muted-inline">
                        P {formatNumber(row.paradexMaxLeverage, 2)}x / G {formatNumber(row.grvtMaxLeverage, 2)}x
                      </small>
                    </td>
                    <td data-label="名义价差">
                      <strong>{formatSigned(row.grossNominalSpread, 4)}</strong>
                    </td>
                    <td data-label="预估费用">{formatSigned(row.feeCostEstimate, 4)}</td>
                    <td data-label="净名义价差">
                      <strong>{formatSigned(row.netNominalSpread, 4)}</strong>
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
