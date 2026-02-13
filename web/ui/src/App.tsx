import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useDashboard } from "./hooks/useDashboard";
import { formatNumber, formatSigned, formatTimestamp } from "./utils/format";
import type { SymbolParamsPayload, TradingMode } from "./types";

function parseOptionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }

  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function wsStateLabel(state: string): string {
  switch (state) {
    case "connected":
      return "已连接";
    case "connecting":
      return "连接中";
    case "reconnecting":
      return "重连中";
    case "error":
      return "异常";
    case "disconnected":
      return "已断开";
    default:
      return "未知";
  }
}

function wsStateClass(state: string): string {
  if (state === "connected") {
    return "state-ok";
  }
  if (state === "reconnecting" || state === "connecting") {
    return "state-warn";
  }
  if (state === "error") {
    return "state-danger";
  }
  return "state-muted";
}

function signalClass(signal: string): string {
  const normalized = signal.toLowerCase();
  if (normalized.includes("long")) {
    return "signal-long";
  }
  if (normalized.includes("short")) {
    return "signal-short";
  }
  return "signal-neutral";
}

export default function App() {
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

  useEffect(() => {
    setModeDraft(status.mode);
  }, [status.mode]);

  useEffect(() => {
    if (selectedSymbol && symbols.some((item) => item.symbol === selectedSymbol)) {
      return;
    }

    if (symbols.length > 0) {
      setSelectedSymbol(symbols[0].symbol);
    }
  }, [selectedSymbol, symbols]);

  const selectedSymbolInfo = useMemo(
    () => symbols.find((item) => item.symbol === selectedSymbol) ?? null,
    [selectedSymbol, symbols]
  );

  const totalRiskCount = useMemo(
    () => status.riskCounts.normal + status.riskCounts.warning + status.riskCounts.critical,
    [status.riskCounts.critical, status.riskCounts.normal, status.riskCounts.warning]
  );

  const onModeSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await changeMode(modeDraft);
  };

  const onParamsSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!selectedSymbol.trim()) {
      setFormError("请先选择交易对");
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
    await updateSymbolParams(selectedSymbol, payload);
  };

  const onFlattenClick = async () => {
    if (!selectedSymbol.trim()) {
      setFormError("请先选择交易对");
      return;
    }

    setFormError("");
    await flattenSymbol(selectedSymbol);
  };

  return (
    <div className="app-shell">
      <header className="panel topbar">
        <div className="brand">
          <p className="eyebrow">跨所套利系统</p>
          <h1>前端控制台</h1>
          <p className="subtitle">实时观察引擎、风险与交易对状态</p>
        </div>
        <div className="top-status">
          <div className="status-cell">
            <span>引擎状态</span>
            <strong>{status.engineStatus}</strong>
          </div>
          <div className="status-cell">
            <span>运行模式</span>
            <strong>{status.mode}</strong>
          </div>
          <div className="status-cell">
            <span>连接状态</span>
            <strong className={wsStateClass(wsStatus.state)}>{wsStateLabel(wsStatus.state)}</strong>
          </div>
          <div className="status-cell">
            <span>更新时间</span>
            <strong>{formatTimestamp(status.updatedAt)}</strong>
          </div>
          <button className="btn btn-ghost" onClick={() => void refresh()} disabled={loading || isBusy}>
            手动刷新
          </button>
        </div>
      </header>

      {errorMessage ? <div className="banner banner-error">{errorMessage}</div> : null}
      {actionMessage ? <div className="banner banner-success">{actionMessage}</div> : null}

      <section className="panel overview-panel">
        <div className="panel-title">
          <h2>总览卡片</h2>
          <small>{loading ? "加载中..." : "实时状态"}</small>
        </div>
        <div className="overview-grid">
          <article className="metric-card">
            <h3>净敞口</h3>
            <p>{formatSigned(status.netExposure, 2)}</p>
            <small>USDT</small>
          </article>
          <article className="metric-card">
            <h3>当日成交量</h3>
            <p>{formatNumber(status.dailyVolume, 2)}</p>
            <small>USD</small>
          </article>
          <article className="metric-card">
            <h3>风险状态计数</h3>
            <p>{totalRiskCount}</p>
            <small>
              高风险 {status.riskCounts.critical} / 预警 {status.riskCounts.warning} / 正常{" "}
              {status.riskCounts.normal}
            </small>
          </article>
        </div>
      </section>

      <div className="dashboard-grid">
        <section className="panel symbol-panel">
          <div className="panel-title">
            <h2>Symbol 实时表格</h2>
            <small>共 {symbols.length} 个交易对</small>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Spread</th>
                  <th>ZScore</th>
                  <th>仓位</th>
                  <th>信号</th>
                  <th>状态</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {symbols.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="empty-cell">
                      当前没有交易对数据
                    </td>
                  </tr>
                ) : (
                  symbols.map((item) => (
                    <tr key={item.symbol}>
                      <td>{item.symbol}</td>
                      <td>{formatNumber(item.spread, 4)}</td>
                      <td>{formatNumber(item.zscore, 3)}</td>
                      <td>{formatSigned(item.position, 4)}</td>
                      <td>
                        <span className={`tag ${signalClass(item.signal)}`}>{item.signal}</span>
                      </td>
                      <td>{item.status}</td>
                      <td>{formatTimestamp(item.updatedAt)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel control-panel">
          <div className="panel-title">
            <h2>控制面板</h2>
            <small>{isBusy ? "命令执行中..." : "可操作"}</small>
          </div>

          <div className="action-row">
            <button className="btn btn-primary" onClick={() => void startEngine()} disabled={isBusy}>
              启动引擎
            </button>
            <button className="btn btn-danger" onClick={() => void stopEngine()} disabled={isBusy}>
              停止引擎
            </button>
          </div>

          <form className="form-block" onSubmit={onModeSubmit}>
            <label htmlFor="mode-select">运行模式</label>
            <div className="inline-form">
              <select
                id="mode-select"
                value={modeDraft}
                onChange={(event) => setModeDraft(event.target.value as TradingMode)}
                disabled={isBusy}
              >
                <option value="normal_arb">normal_arb</option>
                <option value="zero_wear">zero_wear</option>
              </select>
              <button className="btn btn-secondary" type="submit" disabled={isBusy}>
                应用模式
              </button>
            </div>
          </form>

          <form className="form-block" onSubmit={onParamsSubmit}>
            <label htmlFor="symbol-select">目标交易对</label>
            <select
              id="symbol-select"
              value={selectedSymbol}
              onChange={(event) => setSelectedSymbol(event.target.value)}
              disabled={isBusy}
            >
              {symbols.length === 0 ? (
                <option value="">暂无交易对</option>
              ) : (
                symbols.map((item) => (
                  <option key={item.symbol} value={item.symbol}>
                    {item.symbol}
                  </option>
                ))
              )}
            </select>

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
                当前 {selectedSymbolInfo.symbol}：spread {formatNumber(selectedSymbolInfo.spread, 4)} / zscore{" "}
                {formatNumber(selectedSymbolInfo.zscore, 3)} / 仓位 {formatSigned(selectedSymbolInfo.position, 4)}
              </p>
            ) : (
              <p className="hint">当前没有可操作交易对。</p>
            )}

            {formError ? <p className="form-error">{formError}</p> : null}

            <div className="action-row">
              <button className="btn btn-secondary" type="submit" disabled={isBusy}>
                更新参数
              </button>
              <button className="btn btn-danger-outline" type="button" onClick={() => void onFlattenClick()} disabled={isBusy}>
                一键平仓
              </button>
            </div>
          </form>
        </section>

        <section className="panel event-panel">
          <div className="panel-title">
            <h2>事件日志</h2>
            <small>最近 {events.length} 条</small>
          </div>
          <ul className="event-list">
            {events.length === 0 ? (
              <li className="event-empty">暂无事件。等待后端推送或手动刷新。</li>
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
    </div>
  );
}
