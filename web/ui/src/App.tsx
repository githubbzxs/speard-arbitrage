import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  DEFAULT_CREDENTIALS_STATUS,
  apiClient,
  getErrorMessage
} from "./api/client";
import type {
  CredentialsPayload,
  CredentialsStatus,
  GrvtCredentialsInput,
  ParadexCredentialsInput
} from "./api/client";
import { useDashboard } from "./hooks/useDashboard";
import type { PublicConfig, SymbolParamsPayload, TradingMode } from "./types";
import { formatNumber, formatSigned, formatTimestamp } from "./utils/format";

type ThemeMode = "dark" | "light";

const THEME_STORAGE_KEY = "spread-arbitrage-theme";

const EMPTY_PARADEX_FORM: ParadexCredentialsInput = {
  api_key: "",
  api_secret: "",
  passphrase: ""
};

const EMPTY_GRVT_FORM: GrvtCredentialsInput = {
  api_key: "",
  private_key: "",
  trading_account_id: ""
};

type CredentialField<T> = {
  key: keyof T;
  label: string;
  placeholder: string;
  optional?: boolean;
};

const PARADEX_BASIC_FIELDS: Array<CredentialField<ParadexCredentialsInput>> = [
  { key: "api_key", label: "API Key", placeholder: "请输入 Paradex API Key" },
  { key: "api_secret", label: "API Secret", placeholder: "请输入 Paradex API Secret" }
];

const PARADEX_ADVANCED_FIELDS: Array<CredentialField<ParadexCredentialsInput>> = [
  { key: "passphrase", label: "Passphrase（可选）", placeholder: "请输入 Paradex Passphrase", optional: true }
];

const PARADEX_ALL_FIELDS = [...PARADEX_BASIC_FIELDS, ...PARADEX_ADVANCED_FIELDS];

const GRVT_BASIC_FIELDS: Array<CredentialField<GrvtCredentialsInput>> = [
  { key: "private_key", label: "Private Key", placeholder: "请输入 GRVT Private Key" },
  { key: "trading_account_id", label: "Trading Account ID", placeholder: "请输入 GRVT Trading Account ID" }
];

const GRVT_ADVANCED_FIELDS: Array<CredentialField<GrvtCredentialsInput>> = [
  { key: "api_key", label: "API Key（可选）", placeholder: "请输入 GRVT API Key", optional: true }
];

const GRVT_ALL_FIELDS = [...GRVT_BASIC_FIELDS, ...GRVT_ADVANCED_FIELDS];

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

function readThemePreference(): ThemeMode {
  if (typeof window === "undefined") {
    return "dark";
  }

  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  return storedTheme === "light" ? "light" : "dark";
}

function collectParadexPayload(form: ParadexCredentialsInput): Partial<ParadexCredentialsInput> {
  const payload: Partial<ParadexCredentialsInput> = {};
  for (const field of PARADEX_ALL_FIELDS) {
    const value = form[field.key].trim();
    if (value) {
      payload[field.key] = value;
    }
  }
  return payload;
}

function collectGrvtPayload(form: GrvtCredentialsInput): Partial<GrvtCredentialsInput> {
  const payload: Partial<GrvtCredentialsInput> = {};
  for (const field of GRVT_ALL_FIELDS) {
    const value = form[field.key].trim();
    if (value) {
      payload[field.key] = value;
    }
  }
  return payload;
}

function hasAnyCredential(payload: CredentialsPayload): boolean {
  return Boolean(
    (payload.paradex && Object.keys(payload.paradex).length > 0) ||
      (payload.grvt && Object.keys(payload.grvt).length > 0)
  );
}

function fieldStatusLabel(configured: boolean): string {
  return configured ? "已配置" : "未配置";
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

  const [theme, setTheme] = useState<ThemeMode>(readThemePreference);
  const [publicConfig, setPublicConfig] = useState<PublicConfig | null>(null);
  const [publicConfigLoading, setPublicConfigLoading] = useState(true);
  const [publicConfigError, setPublicConfigError] = useState("");

  const [modeDraft, setModeDraft] = useState<TradingMode>("normal_arb");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [zEntry, setZEntry] = useState("");
  const [zExit, setZExit] = useState("");
  const [maxPosition, setMaxPosition] = useState("");
  const [formError, setFormError] = useState("");

  const [credentialsStatus, setCredentialsStatus] = useState<CredentialsStatus>(DEFAULT_CREDENTIALS_STATUS);
  const [credentialsLoading, setCredentialsLoading] = useState(true);
  const [credentialsSaving, setCredentialsSaving] = useState(false);
  const [credentialsApplying, setCredentialsApplying] = useState(false);
  const [credentialsError, setCredentialsError] = useState("");
  const [credentialsMessage, setCredentialsMessage] = useState("");
  const [paradexForm, setParadexForm] = useState<ParadexCredentialsInput>(EMPTY_PARADEX_FORM);
  const [grvtForm, setGrvtForm] = useState<GrvtCredentialsInput>(EMPTY_GRVT_FORM);
  const [visibleFields, setVisibleFields] = useState<Record<string, boolean>>({});

  useEffect(() => {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const loadPublicConfig = useCallback(async () => {
    setPublicConfigLoading(true);
    try {
      const config = await apiClient.getPublicConfig();
      setPublicConfig(config);
      setPublicConfigError("");
    } catch (error) {
      setPublicConfigError(`加载运行配置失败：${getErrorMessage(error)}`);
    } finally {
      setPublicConfigLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPublicConfig();
  }, [loadPublicConfig]);

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

  const loadCredentialsStatus = useCallback(async (silent: boolean) => {
    if (!silent) {
      setCredentialsLoading(true);
    }

    try {
      const response = await apiClient.getCredentialsStatus();
      setCredentialsStatus(response);
      setCredentialsError("");
    } catch (error) {
      setCredentialsError(`加载凭证状态失败：${getErrorMessage(error)}`);
    } finally {
      if (!silent) {
        setCredentialsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadCredentialsStatus(false);
  }, [loadCredentialsStatus]);

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

  const onCredentialsSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCredentialsError("");
    setCredentialsMessage("");

    const payload: CredentialsPayload = {};
    const paradexPayload = collectParadexPayload(paradexForm);
    const grvtPayload = collectGrvtPayload(grvtForm);

    if (Object.keys(paradexPayload).length > 0) {
      payload.paradex = paradexPayload;
    }
    if (Object.keys(grvtPayload).length > 0) {
      payload.grvt = grvtPayload;
    }

    if (!hasAnyCredential(payload)) {
      setCredentialsError("请至少填写一个凭证字段后再保存");
      return;
    }

    setCredentialsSaving(true);

    try {
      const result = await apiClient.saveCredentials(payload);
      if (!result.ok) {
        throw new Error(result.message || "保存凭证失败");
      }

      setCredentialsMessage(result.message || "凭证已保存");
      setParadexForm(EMPTY_PARADEX_FORM);
      setGrvtForm(EMPTY_GRVT_FORM);
      await loadCredentialsStatus(true);
    } catch (error) {
      setCredentialsError(`保存凭证失败：${getErrorMessage(error)}`);
    } finally {
      setCredentialsSaving(false);
    }
  };

  const onApplyCredentialsClick = async () => {
    setCredentialsError("");
    setCredentialsMessage("");
    setCredentialsApplying(true);

    try {
      const result = await apiClient.applyCredentials();
      if (!result.ok) {
        setCredentialsError(result.message || "应用凭证失败");
        return;
      }

      setCredentialsMessage(result.message || "凭证已应用");
      await loadCredentialsStatus(true);
    } catch (error) {
      setCredentialsError(`应用凭证失败：${getErrorMessage(error)}`);
    } finally {
      setCredentialsApplying(false);
    }
  };

  const toggleFieldVisibility = (fieldKey: string) => {
    setVisibleFields((previous) => ({
      ...previous,
      [fieldKey]: !previous[fieldKey]
    }));
  };

  const toggleTheme = () => {
    setTheme((previous) => (previous === "dark" ? "light" : "dark"));
  };

  const isDryRun = publicConfig?.runtime.dryRun ?? true;

  return (
    <div className="app-shell">
      <header className="panel topbar">
        <div className="brand">
          <p className="eyebrow">跨所套利系统</p>
          <h1>前端控制台</h1>
          <p className="subtitle">
            实时观察引擎、风险与交易对状态
            <span className={`runtime-pill ${isDryRun ? "runtime-dry" : "runtime-live"}`}>
              {publicConfigLoading ? "加载中" : isDryRun ? "DRY-RUN" : "LIVE"}
            </span>
          </p>
        </div>

        <div className="topbar-right">
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
          </div>

          <div className="top-actions">
            <button className="btn btn-ghost" onClick={() => void refresh()} disabled={loading || isBusy}>
              手动刷新
            </button>
            <button className="btn btn-secondary theme-toggle" onClick={toggleTheme}>
              {theme === "dark" ? "切换浅色" : "切换深色"}
            </button>
          </div>
        </div>
      </header>

      {errorMessage ? <div className="banner banner-error">{errorMessage}</div> : null}
      {actionMessage ? <div className="banner banner-success">{actionMessage}</div> : null}
      {publicConfigError ? <div className="banner banner-error">{publicConfigError}</div> : null}
      {!publicConfigLoading && isDryRun ? (
        <div className="banner banner-warning">
          当前为 dry-run（模拟行情）模式，价差与仓位变化可能剧烈抖动，且不会真实下单。
        </div>
      ) : null}

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
                  <th>Spread (bps)</th>
                  <th>Spread (price)</th>
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
                    <td colSpan={8} className="empty-cell">
                      当前没有交易对数据
                    </td>
                  </tr>
                ) : (
                  symbols.map((item) => (
                    <tr key={item.symbol}>
                      <td>{item.symbol}</td>
                      <td>{formatSigned(item.spreadBps, 2)}</td>
                      <td>{formatSigned(item.spreadPrice, 2)}</td>
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
                当前 {selectedSymbolInfo.symbol}：spread(bps) {formatSigned(selectedSymbolInfo.spreadBps, 2)} / spread(price){" "}
                {formatSigned(selectedSymbolInfo.spreadPrice, 2)} / zscore {formatNumber(selectedSymbolInfo.zscore, 3)} / 仓位{" "}
                {formatSigned(selectedSymbolInfo.position, 4)}
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

          <form className="form-block credential-form" onSubmit={onCredentialsSubmit}>
            <div className="form-title">
              <h3>API凭证配置</h3>
              <small>
                {credentialsSaving
                  ? "正在保存..."
                  : credentialsApplying
                    ? "正在应用..."
                    : "保存：/api/credentials / 应用：/api/credentials/apply"}
              </small>
            </div>

            <div className="credential-status-grid">
              <article className="credential-status-card">
                <h4>Paradex 状态</h4>
                <ul>
                  {PARADEX_ALL_FIELDS.map((field) => {
                    const configured = credentialsStatus.paradex[field.key].configured;
                    return (
                      <li key={`paradex-status-${field.key}`}>
                        <span>{field.label}</span>
                        <span className={`status-pill ${configured ? "configured" : "missing"}`}>
                          {fieldStatusLabel(configured)}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </article>

              <article className="credential-status-card">
                <h4>GRVT 状态</h4>
                <ul>
                  {GRVT_ALL_FIELDS.map((field) => {
                    const configured = credentialsStatus.grvt[field.key].configured;
                    return (
                      <li key={`grvt-status-${field.key}`}>
                        <span>{field.label}</span>
                        <span className={`status-pill ${configured ? "configured" : "missing"}`}>
                          {fieldStatusLabel(configured)}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </article>
            </div>

            <div className="credential-group">
              <h4>Paradex</h4>
              <div className="credential-grid">
                {PARADEX_BASIC_FIELDS.map((field) => {
                  const fieldKey = `paradex.${field.key}`;
                  const visible = Boolean(visibleFields[fieldKey]);
                  return (
                    <div key={`paradex-input-${field.key}`} className="credential-field">
                      <label htmlFor={`paradex-${field.key}`}>{field.label}</label>
                      <div className="secret-input">
                        <input
                          id={`paradex-${field.key}`}
                          type={visible ? "text" : "password"}
                          value={paradexForm[field.key]}
                          onChange={(event) =>
                            setParadexForm((previous) => ({
                              ...previous,
                              [field.key]: event.target.value
                            }))
                          }
                          placeholder={field.placeholder}
                          autoComplete="off"
                        />
                        <button
                          type="button"
                          className="btn btn-ghost btn-inline"
                          onClick={() => toggleFieldVisibility(fieldKey)}
                        >
                          {visible ? "隐藏" : "显示"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>

              <details className="credential-advanced">
                <summary>高级可选</summary>
                <div className="credential-grid">
                  {PARADEX_ADVANCED_FIELDS.map((field) => {
                    const fieldKey = `paradex.${field.key}`;
                    const visible = Boolean(visibleFields[fieldKey]);
                    return (
                      <div key={`paradex-input-${field.key}`} className="credential-field">
                        <label htmlFor={`paradex-${field.key}`}>{field.label}</label>
                        <div className="secret-input">
                          <input
                            id={`paradex-${field.key}`}
                            type={visible ? "text" : "password"}
                            value={paradexForm[field.key]}
                            onChange={(event) =>
                              setParadexForm((previous) => ({
                                ...previous,
                                [field.key]: event.target.value
                              }))
                            }
                            placeholder={field.placeholder}
                            autoComplete="off"
                          />
                          <button
                            type="button"
                            className="btn btn-ghost btn-inline"
                            onClick={() => toggleFieldVisibility(fieldKey)}
                          >
                            {visible ? "隐藏" : "显示"}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </details>
            </div>

            <div className="credential-group">
              <h4>GRVT</h4>
              <div className="credential-grid">
                {GRVT_BASIC_FIELDS.map((field) => {
                  const fieldKey = `grvt.${field.key}`;
                  const visible = Boolean(visibleFields[fieldKey]);
                  return (
                    <div key={`grvt-input-${field.key}`} className="credential-field">
                      <label htmlFor={`grvt-${field.key}`}>{field.label}</label>
                      <div className="secret-input">
                        <input
                          id={`grvt-${field.key}`}
                          type={visible ? "text" : "password"}
                          value={grvtForm[field.key]}
                          onChange={(event) =>
                            setGrvtForm((previous) => ({
                              ...previous,
                              [field.key]: event.target.value
                            }))
                          }
                          placeholder={field.placeholder}
                          autoComplete="off"
                        />
                        <button
                          type="button"
                          className="btn btn-ghost btn-inline"
                          onClick={() => toggleFieldVisibility(fieldKey)}
                        >
                          {visible ? "隐藏" : "显示"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>

              <details className="credential-advanced">
                <summary>高级可选</summary>
                <div className="credential-grid">
                  {GRVT_ADVANCED_FIELDS.map((field) => {
                    const fieldKey = `grvt.${field.key}`;
                    const visible = Boolean(visibleFields[fieldKey]);
                    return (
                      <div key={`grvt-input-${field.key}`} className="credential-field">
                        <label htmlFor={`grvt-${field.key}`}>{field.label}</label>
                        <div className="secret-input">
                          <input
                            id={`grvt-${field.key}`}
                            type={visible ? "text" : "password"}
                            value={grvtForm[field.key]}
                            onChange={(event) =>
                              setGrvtForm((previous) => ({
                                ...previous,
                                [field.key]: event.target.value
                              }))
                            }
                            placeholder={field.placeholder}
                            autoComplete="off"
                          />
                          <button
                            type="button"
                            className="btn btn-ghost btn-inline"
                            onClick={() => toggleFieldVisibility(fieldKey)}
                          >
                            {visible ? "隐藏" : "显示"}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </details>
            </div>

            <p className="hint">状态接口：GET /api/credentials/status（不回显明文）</p>
            {status.engineStatus !== "stopped" ? (
              <p className="hint">提示：应用凭证前建议先停止引擎，避免运行中热切换。</p>
            ) : null}
            {credentialsLoading ? <p className="hint">正在加载凭证状态...</p> : null}
            {credentialsError ? <p className="form-error">{credentialsError}</p> : null}
            {credentialsMessage ? <p className="form-success">{credentialsMessage}</p> : null}

            <div className="action-row action-row-3">
              <button className="btn btn-primary" type="submit" disabled={credentialsSaving}>
                保存凭证
              </button>
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => void onApplyCredentialsClick()}
                disabled={credentialsSaving || credentialsApplying || status.engineStatus !== "stopped"}
              >
                应用凭证
              </button>
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => void loadCredentialsStatus(false)}
                disabled={credentialsSaving || credentialsApplying || credentialsLoading}
              >
                刷新凭证状态
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
