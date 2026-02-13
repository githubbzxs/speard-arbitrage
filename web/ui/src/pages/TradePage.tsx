import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { apiClient, getErrorMessage, normalizeMarketTopSpreads } from "../api/client";
import { useDashboard } from "../hooks/useDashboard";
import type { MarketTopSpreadRow, MarketTopSpreadsResponse, SymbolParamsPayload, TradeSelection, TradingMode } from "../types";
import { formatNumber, formatSigned, formatTimestamp } from "../utils/format";

const TOP_LIMIT = 10;
const MARKET_REFRESH_INTERVAL_MS = 20000;

const EMPTY_TRADE_SELECTION: TradeSelection = {
  selectedSymbol: "",
  top10Candidates: [],
  updatedAt: ""
};

const EMPTY_MARKET_RESULT: MarketTopSpreadsResponse = {
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

function parseOptionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function wsStateLabel(state: string): string {
  if (state === "connected") {
    return "已连接";
  }
  if (state === "connecting") {
    return "连接中";
  }
  if (state === "reconnecting") {
    return "重连中";
  }
  if (state === "error") {
    return "异常";
  }
  if (state === "disconnected") {
    return "已断开";
  }
  return "未知";
}

function wsStateClass(state: string): string {
  if (state === "connected") {
    return "state-ok";
  }
  if (state === "connecting" || state === "reconnecting") {
    return "state-warn";
  }
  if (state === "error") {
    return "state-danger";
  }
  return "state-muted";
}

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

export default function TradePage() {
  const {
    status,
    symbols,
    events,
    loading,
    errorMessage,
    actionMessage,
    wsStatus,
    isBusy,
    refresh,
    startEngine,
    stopEngine,
    changeMode,
    updateSymbolParams,
    flattenSymbol
  } = useDashboard();

  const [modeDraft, setModeDraft] = useState<TradingMode>("normal_arb");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [zEntry, setZEntry] = useState("");
  const [zExit, setZExit] = useState("");
  const [maxPosition, setMaxPosition] = useState("");
  const [formError, setFormError] = useState("");
  const [selectionMessage, setSelectionMessage] = useState("");
  const [selectionLoading, setSelectionLoading] = useState(false);
  const [selectionSaving, setSelectionSaving] = useState(false);
  const [tradeSelection, setTradeSelection] = useState<TradeSelection>(EMPTY_TRADE_SELECTION);
  const [marketResult, setMarketResult] = useState<MarketTopSpreadsResponse>(EMPTY_MARKET_RESULT);
  const [marketLoading, setMarketLoading] = useState(true);
  const [marketRefreshing, setMarketRefreshing] = useState(false);
  const [marketError, setMarketError] = useState("");

  useEffect(() => {
    setModeDraft(status.mode);
  }, [status.mode]);

  const loadTradeSelection = useCallback(async (forceRefresh: boolean) => {
    setSelectionLoading(true);
    try {
      const response = await apiClient.getTradeSelection({ forceRefresh });
      setTradeSelection(response);
      setSelectionMessage("");
      setFormError("");
    } catch (error) {
      setFormError(`加载 Top10 交易候选失败：${getErrorMessage(error)}`);
    } finally {
      setSelectionLoading(false);
    }
  }, []);

  const loadMarketSpreads = useCallback(async (options?: { forceRefresh?: boolean; silent?: boolean }) => {
    const forceRefresh = options?.forceRefresh ?? false;
    const silent = options?.silent ?? false;

    if (!silent) {
      setMarketLoading(true);
    }
    if (forceRefresh) {
      setMarketRefreshing(true);
    }

    try {
      const response = await apiClient.getMarketTopSpreads({ limit: TOP_LIMIT, forceRefresh });
      const normalized = normalizeMarketTopSpreads(response);
      setMarketResult(normalized);
      setMarketError("");
    } catch (error) {
      setMarketError(`加载行情失败：${getErrorMessage(error)}`);
    } finally {
      if (!silent) {
        setMarketLoading(false);
      }
      if (forceRefresh) {
        setMarketRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadTradeSelection(false);
  }, [loadTradeSelection]);

  useEffect(() => {
    void loadMarketSpreads({ forceRefresh: true });
  }, [loadMarketSpreads]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadMarketSpreads({ forceRefresh: true, silent: true });
    }, MARKET_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadMarketSpreads]);

  useEffect(() => {
    if (tradeSelection.selectedSymbol) {
      setSelectedSymbol(tradeSelection.selectedSymbol);
      return;
    }
    if (tradeSelection.top10Candidates.length > 0) {
      setSelectedSymbol((previous) => {
        if (previous && tradeSelection.top10Candidates.some((item) => item.symbol === previous)) {
          return previous;
        }
        return tradeSelection.top10Candidates[0].symbol;
      });
      return;
    }
    setSelectedSymbol("");
  }, [tradeSelection.selectedSymbol, tradeSelection.top10Candidates]);

  const selectedTradeSymbol = tradeSelection.selectedSymbol;

  const selectedSymbolInfo = useMemo(
    () => symbols.find((item) => item.symbol === selectedTradeSymbol) ?? null,
    [selectedTradeSymbol, symbols]
  );

  const selectedCandidate = useMemo(
    () => tradeSelection.top10Candidates.find((item) => item.symbol === selectedSymbol) ?? null,
    [selectedSymbol, tradeSelection.top10Candidates]
  );
  const hasAppliedTradeSymbol = Boolean(selectedTradeSymbol);
  const needsApplySelection = Boolean(selectedSymbol) && selectedSymbol !== selectedTradeSymbol;
  const canStartEngine = hasAppliedTradeSymbol && !needsApplySelection;

  const isEngineRunning = status.engineStatus === "running";

  const totalRiskCount = useMemo(
    () => status.riskCounts.normal + status.riskCounts.warning + status.riskCounts.critical,
    [status.riskCounts.critical, status.riskCounts.normal, status.riskCounts.warning]
  );

  const topRows = useMemo(
    () =>
      [...marketResult.rows]
        .filter((row) => row.zscore > 0)
        .sort((a, b) => b.zscore - a.zscore || toNominalSpreadPct(b) - toNominalSpreadPct(a))
        .slice(0, TOP_LIMIT),
    [marketResult.rows]
  );

  const marketSummaryText = useMemo(() => {
    if (marketLoading) {
      return "行情加载中...";
    }
    if (topRows.length === 0) {
      return "当前无满足条件的标的（仅展示 Z-score > 0）";
    }
    return `仅展示 Z-score > 0，当前 ${topRows.length} 个标的`;
  }, [marketLoading, topRows.length]);

  const onModeSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await changeMode(modeDraft);
  };

  const onTradeSymbolChange = (symbol: string) => {
    setSelectedSymbol(symbol);
    setSelectionMessage("");
    setFormError("");
  };

  const onApplyTradeSymbol = async () => {
    if (!selectedSymbol.trim()) {
      setFormError("请先在 Top10 候选中选择交易标的");
      return;
    }

    setSelectionSaving(true);
    try {
      const result = await apiClient.setTradeSelection(selectedSymbol, { forceRefresh: false });
      if (!result.ok) {
        throw new Error(result.message || "设置交易标的失败");
      }
      setSelectionMessage(result.message || `已切换交易标的：${selectedSymbol}`);
      setFormError("");
      await loadTradeSelection(true);
      await loadMarketSpreads({ forceRefresh: true, silent: true });
      await refresh();
    } catch (error) {
      setFormError(`设置交易标的失败：${getErrorMessage(error)}`);
    } finally {
      setSelectionSaving(false);
    }
  };

  const onParamsSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!selectedTradeSymbol.trim()) {
      setFormError("请先在 Top10 候选中选择并应用交易标的");
      return;
    }

    const zEntryValue = parseOptionalNumber(zEntry);
    const zExitValue = parseOptionalNumber(zExit);
    const maxPositionValue = parseOptionalNumber(maxPosition);

    if (zEntry.trim() && zEntryValue === undefined) {
      setFormError("z_entry 必须是数字");
      return;
    }
    if (zExit.trim() && zExitValue === undefined) {
      setFormError("z_exit 必须是数字");
      return;
    }
    if (maxPosition.trim() && maxPositionValue === undefined) {
      setFormError("max_position 必须是数字");
      return;
    }

    const payload: SymbolParamsPayload = {};
    if (zEntryValue !== undefined) {
      payload.z_entry = zEntryValue;
    }
    if (zExitValue !== undefined) {
      payload.z_exit = zExitValue;
    }
    if (maxPositionValue !== undefined) {
      payload.max_position = maxPositionValue;
    }

    if (Object.keys(payload).length === 0) {
      setFormError("至少填写一个参数");
      return;
    }

    setFormError("");
    await updateSymbolParams(selectedTradeSymbol, payload);
  };

  const onFlattenClick = async () => {
    if (!selectedTradeSymbol.trim()) {
      setFormError("请先在 Top10 候选中选择并应用交易标的");
      return;
    }
    setFormError("");
    await flattenSymbol(selectedTradeSymbol);
  };

  return (
    <div className="page-grid">
      {errorMessage ? <div className="banner banner-error">{errorMessage}</div> : null}
      {marketError ? <div className="banner banner-error">{marketError}</div> : null}
      {actionMessage ? <div className="banner banner-success">{actionMessage}</div> : null}
      {selectionMessage ? <div className="banner banner-success">{selectionMessage}</div> : null}
      {marketResult.lastError ? <div className="banner banner-warning">{marketResult.lastError}</div> : null}

      <section className="panel overview-panel">
        <div className="panel-title">
          <h2>行情/下单页</h2>
          <small>{loading ? "状态加载中..." : marketSummaryText}</small>
        </div>
        <div className="overview-grid">
          <article className="metric-card">
            <h3>引擎状态</h3>
            <p>{status.engineStatus}</p>
            <small>模式 {status.mode}</small>
          </article>
          <article className="metric-card">
            <h3>净敞口</h3>
            <p>{formatSigned(status.netExposure, 2)}</p>
            <small>USDT</small>
          </article>
          <article className="metric-card">
            <h3>风控计数</h3>
            <p>{totalRiskCount}</p>
            <small>
              高风险 {status.riskCounts.critical} / 预警 {status.riskCounts.warning} / 正常 {status.riskCounts.normal}
            </small>
          </article>
          <article className="metric-card">
            <h3>连接状态</h3>
            <p className={wsStateClass(wsStatus.state)}>{wsStateLabel(wsStatus.state)}</p>
            <small>{formatTimestamp(status.updatedAt)}</small>
          </article>
        </div>
      </section>

      <section className="panel control-panel page-panel">
        <div className="panel-title">
          <h2>策略控制</h2>
          <small>{isBusy || selectionSaving ? "命令执行中..." : "可操作"}</small>
        </div>

        <div className="form-block">
          <label htmlFor="trade-symbol-select">交易标的（仅 Top10 候选）</label>
          <div className="trade-selection-flow">
            <div className="trade-step-card">
              <p className="trade-step-title">步骤 1：选择交易标的</p>
              <div className="inline-form trade-symbol-select-form">
                <select
                  id="trade-symbol-select"
                  value={selectedSymbol}
                  onChange={(event) => onTradeSymbolChange(event.target.value)}
                  disabled={isBusy || selectionSaving || selectionLoading}
                >
                  {tradeSelection.top10Candidates.length === 0 ? (
                    <option value="">暂无 Top10 候选（先点击刷新 Top10）</option>
                  ) : (
                    tradeSelection.top10Candidates.map((item) => (
                      <option key={item.symbol} value={item.symbol}>
                        {item.symbol}
                      </option>
                    ))
                  )}
                </select>
                <button
                  className="btn btn-ghost trade-symbol-btn"
                  type="button"
                  onClick={() => {
                    void loadTradeSelection(true);
                    void loadMarketSpreads({ forceRefresh: true, silent: true });
                  }}
                  disabled={isBusy || selectionSaving || selectionLoading}
                >
                  {selectionLoading ? "刷新中..." : "刷新 Top10"}
                </button>
              </div>
            </div>

            <div className="trade-step-card">
              <p className="trade-step-title">步骤 2：应用到引擎</p>
              <div className="trade-apply-row">
                <button
                  className="btn btn-secondary trade-symbol-btn"
                  type="button"
                  onClick={() => void onApplyTradeSymbol()}
                  disabled={isBusy || selectionSaving || selectionLoading || !selectedSymbol}
                >
                  {selectionSaving ? "应用中..." : "应用交易标的"}
                </button>
                <p className={`trade-apply-state ${canStartEngine ? "trade-apply-state-ok" : "trade-apply-state-warn"}`}>
                  {canStartEngine ? "已完成应用，可启动引擎" : "未完成应用，启动引擎会被禁用"}
                </p>
              </div>
            </div>
          </div>

          <p className="hint">
            当前已应用交易标的：{selectedTradeSymbol || "未应用"}；当前选择：{selectedSymbol || "未选择"}。Top10 候选{" "}
            {tradeSelection.top10Candidates.length} 个，
            更新时间 {formatTimestamp(tradeSelection.updatedAt)}。
          </p>
          {!selectedTradeSymbol ? <p className="hint">请先完成“步骤 2 应用到引擎”，然后才能启动引擎。</p> : null}
          {needsApplySelection ? <p className="hint">你已切换交易标的，但还未应用，当前仍按旧标的运行。</p> : null}
          {selectedCandidate ? (
            <p className="hint">
              候选口径：{formatSigned(selectedCandidate.tradableEdgePct, 4)}%，Z-score {formatSigned(selectedCandidate.zscore, 3)}
            </p>
          ) : null}
        </div>

        <div className="action-row action-row-3">
          <button
            className="btn btn-primary"
            onClick={() => void startEngine()}
            disabled={isBusy || selectionSaving || !canStartEngine}
          >
            启动引擎
          </button>
          <button className="btn btn-danger" onClick={() => void stopEngine()} disabled={isBusy || selectionSaving}>
            停止引擎
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              void refresh();
              void loadMarketSpreads({ forceRefresh: true, silent: true });
            }}
            disabled={isBusy || selectionSaving || loading || marketRefreshing}
          >
            {marketRefreshing ? "刷新中..." : "手动刷新"}
          </button>
        </div>

        <form className="form-block" onSubmit={onModeSubmit}>
          <label htmlFor="mode-select">运行模式</label>
          <div className="inline-form">
            <select
              id="mode-select"
              value={modeDraft}
              onChange={(event) => setModeDraft(event.target.value as TradingMode)}
              disabled={isBusy || selectionSaving}
            >
              <option value="normal_arb">normal_arb</option>
              <option value="zero_wear">zero_wear</option>
            </select>
            <button className="btn btn-secondary" type="submit" disabled={isBusy || selectionSaving}>
              应用模式
            </button>
          </div>
        </form>

        <form className="form-block" onSubmit={onParamsSubmit}>
          <div className="param-grid">
            <div>
              <label htmlFor="z-entry">z_entry</label>
              <input
                id="z-entry"
                value={zEntry}
                onChange={(event) => setZEntry(event.target.value)}
                placeholder="例如 2.2"
              />
            </div>
            <div>
              <label htmlFor="z-exit">z_exit</label>
              <input
                id="z-exit"
                value={zExit}
                onChange={(event) => setZExit(event.target.value)}
                placeholder="例如 0.8"
              />
            </div>
            <div>
              <label htmlFor="max-position">max_position</label>
              <input
                id="max-position"
                value={maxPosition}
                onChange={(event) => setMaxPosition(event.target.value)}
                placeholder="例如 1500"
              />
            </div>
          </div>

          {selectedSymbolInfo ? (
            <p className="hint">
              {selectedSymbolInfo.symbol}：
              {isEngineRunning
                ? `Spread ${formatSigned(selectedSymbolInfo.spreadBps / 100, 4)}%，zscore ${formatNumber(
                    selectedSymbolInfo.zscore,
                    3
                  )}，仓位 ${formatSigned(selectedSymbolInfo.position, 4)}。`
                : "引擎未运行，指标将在启动后实时更新。"}
            </p>
          ) : (
            <p className="hint">当前没有该交易标的的实时数据。</p>
          )}

          {formError ? <p className="form-error">{formError}</p> : null}

          <div className="action-row">
            <button className="btn btn-secondary" type="submit" disabled={isBusy || selectionSaving}>
              更新参数
            </button>
            <button
              className="btn btn-danger-outline"
              type="button"
              onClick={() => void onFlattenClick()}
              disabled={isBusy || selectionSaving}
            >
              一键平仓
            </button>
          </div>
        </form>
      </section>

      <section className="panel symbol-panel page-panel">
        <div className="panel-title">
          <h2>当前行情（单表）</h2>
          <small>仅展示 Z-score &gt; 0</small>
        </div>
        <p className="hint">
          最近刷新 {formatTimestamp(marketResult.updatedAt)}，扫描周期约 {marketResult.scanIntervalSec} 秒，
          可比 {marketResult.comparableSymbols} 个，可执行 {marketResult.executableSymbols} 个，
          跳过 {marketResult.skippedCount} 个（{formatSkippedReasons(marketResult.skippedReasons)}）。
        </p>
        <div className="table-wrap">
          <table className="responsive-table">
            <thead>
              <tr>
                <th>#</th>
                <th>币对</th>
                <th>实际价差(%)</th>
                <th>Z-score</th>
                <th>有效杠杆</th>
                <th>名义价差(%)</th>
                <th>净名义价差(%)</th>
              </tr>
            </thead>
            <tbody>
              {topRows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="empty-cell">
                    暂无满足条件的行情数据
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
                    <td data-label="Z-score">
                      <strong>{formatNumber(row.zscore, 3)}</strong>
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

      <section className="panel event-panel page-panel">
        <div className="panel-title">
          <h2>事件日志</h2>
          <small>最近 {events.length} 条</small>
        </div>
        <ul className="event-list">
          {events.length === 0 ? (
            <li className="event-empty">暂无事件。</li>
          ) : (
            events.map((event) => (
              <li key={event.id} className="event-item">
                <div className="event-meta">
                  <span className={`tag level-${event.level}`}>{event.level}</span>
                  <span>{event.source}</span>
                  <span>{formatTimestamp(event.ts)}</span>
                </div>
                <p>{event.message}</p>
              </li>
            ))
          )}
        </ul>
      </section>
    </div>
  );
}
