import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { DEFAULT_CREDENTIALS_STATUS, apiClient, getErrorMessage } from "../api/client";
import type {
  CredentialsPayload,
  CredentialsStatus,
  CredentialsValidationResponse,
  GrvtCredentialsInput,
  ParadexCredentialsInput
} from "../api/client";

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

const PARADEX_FIELDS: Array<CredentialField<ParadexCredentialsInput>> = [
  { key: "api_key", label: "API Key", placeholder: "请输入 Paradex API Key" },
  { key: "api_secret", label: "API Secret", placeholder: "请输入 Paradex API Secret" },
  { key: "passphrase", label: "Passphrase（可选）", placeholder: "请输入 Paradex Passphrase", optional: true }
];

const GRVT_FIELDS: Array<CredentialField<GrvtCredentialsInput>> = [
  { key: "private_key", label: "Private Key", placeholder: "请输入 GRVT Private Key" },
  { key: "trading_account_id", label: "Trading Account ID", placeholder: "请输入 GRVT Trading Account ID" },
  { key: "api_key", label: "API Key", placeholder: "请输入 GRVT API Key" }
];

function collectParadexPayload(form: ParadexCredentialsInput): Partial<ParadexCredentialsInput> {
  const payload: Partial<ParadexCredentialsInput> = {};
  for (const field of PARADEX_FIELDS) {
    const value = form[field.key].trim();
    if (value) {
      payload[field.key] = value;
    }
  }
  return payload;
}

function collectGrvtPayload(form: GrvtCredentialsInput): Partial<GrvtCredentialsInput> {
  const payload: Partial<GrvtCredentialsInput> = {};
  for (const field of GRVT_FIELDS) {
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

function checkLabel(checkName: string): string {
  const mapping: Record<string, string> = {
    required_fields: "必填字段",
    load_markets: "拉取市场",
    fetch_balance: "拉取余额",
    fetch_positions: "拉取持仓",
    fetch_max_leverage: "拉取杠杆"
  };
  return mapping[checkName] ?? checkName;
}

function buildDraftPayload(paradexForm: ParadexCredentialsInput, grvtForm: GrvtCredentialsInput): CredentialsPayload {
  const draft: CredentialsPayload = {};
  const paradexPayload = collectParadexPayload(paradexForm);
  const grvtPayload = collectGrvtPayload(grvtForm);

  if (Object.keys(paradexPayload).length > 0) {
    draft.paradex = paradexPayload;
  }
  if (Object.keys(grvtPayload).length > 0) {
    draft.grvt = grvtPayload;
  }
  return draft;
}

export default function ApiConfigPage() {
  const [credentialsStatus, setCredentialsStatus] = useState<CredentialsStatus>(DEFAULT_CREDENTIALS_STATUS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [validatingSaved, setValidatingSaved] = useState(false);
  const [validatingDraft, setValidatingDraft] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [validationResult, setValidationResult] = useState<CredentialsValidationResponse | null>(null);
  const [validationSource, setValidationSource] = useState<"saved" | "draft" | null>(null);

  const [paradexForm, setParadexForm] = useState<ParadexCredentialsInput>(EMPTY_PARADEX_FORM);
  const [grvtForm, setGrvtForm] = useState<GrvtCredentialsInput>(EMPTY_GRVT_FORM);
  const [visibleFields, setVisibleFields] = useState<Record<string, boolean>>({});

  const loadStatus = useCallback(async (silent: boolean) => {
    if (!silent) {
      setLoading(true);
    }

    try {
      const response = await apiClient.getCredentialsStatus();
      setCredentialsStatus(response);
      setErrorMessage("");
    } catch (error) {
      setErrorMessage(`加载凭证状态失败：${getErrorMessage(error)}`);
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadStatus(false);
  }, [loadStatus]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage("");
    setSuccessMessage("");

    const payload = buildDraftPayload(paradexForm, grvtForm);
    if (!hasAnyCredential(payload)) {
      setErrorMessage("请至少填写一个凭证字段后再保存");
      return;
    }

    setSaving(true);
    try {
      const result = await apiClient.saveCredentials(payload);
      if (!result.ok) {
        throw new Error(result.message || "保存失败");
      }
      setSuccessMessage(result.message || "凭证已保存");
      setParadexForm(EMPTY_PARADEX_FORM);
      setGrvtForm(EMPTY_GRVT_FORM);
      await loadStatus(true);
    } catch (error) {
      setErrorMessage(`保存凭证失败：${getErrorMessage(error)}`);
    } finally {
      setSaving(false);
    }
  };

  const onApplyClick = async () => {
    setErrorMessage("");
    setSuccessMessage("");
    setApplying(true);

    try {
      const result = await apiClient.applyCredentials();
      if (!result.ok) {
        setErrorMessage(result.message || "应用凭证失败");
        return;
      }
      setSuccessMessage(result.message || "凭证已应用");
      await loadStatus(true);
    } catch (error) {
      setErrorMessage(`应用凭证失败：${getErrorMessage(error)}`);
    } finally {
      setApplying(false);
    }
  };

  const runValidation = useCallback(
    async (source: "saved" | "draft") => {
      setErrorMessage("");
      setSuccessMessage("");
      setValidationSource(source);

      if (source === "saved") {
        setValidatingSaved(true);
      } else {
        setValidatingDraft(true);
      }

      try {
        const draftPayload = buildDraftPayload(paradexForm, grvtForm);
        const response = await apiClient.validateCredentials({
          source,
          payload: source === "draft" ? draftPayload : undefined
        });

        setValidationResult(response);
        if (response.ok) {
          setSuccessMessage(response.message || "凭证检测通过");
        } else {
          setErrorMessage(response.message || "凭证检测未通过");
        }
      } catch (error) {
        setValidationResult(null);
        setErrorMessage(`凭证检测失败：${getErrorMessage(error)}`);
      } finally {
        if (source === "saved") {
          setValidatingSaved(false);
        } else {
          setValidatingDraft(false);
        }
      }
    },
    [grvtForm, paradexForm]
  );

  const toggleFieldVisibility = (fieldKey: string) => {
    setVisibleFields((previous) => ({
      ...previous,
      [fieldKey]: !previous[fieldKey]
    }));
  };

  const validationSourceLabel = useMemo(() => {
    if (validationSource === "saved") {
      return "已保存凭证";
    }
    if (validationSource === "draft") {
      return "当前填写内容";
    }
    return "";
  }, [validationSource]);

  return (
    <div className="page-grid">
      {errorMessage ? <div className="banner banner-error">{errorMessage}</div> : null}
      {successMessage ? <div className="banner banner-success">{successMessage}</div> : null}

      <section className="panel page-panel">
        <div className="panel-title">
          <h2>API 配置页</h2>
          <small>{loading ? "加载中..." : "保存后可在引擎停止时应用"}</small>
        </div>

        <form className="form-block credential-form" onSubmit={onSubmit}>
          <div className="credential-status-grid">
            <article className="credential-status-card">
              <h4>Paradex 状态</h4>
              <ul>
                {PARADEX_FIELDS.map((field) => {
                  const status = credentialsStatus.paradex[field.key];
                  return (
                    <li key={`paradex-status-${field.key}`}>
                      <div className="status-meta">
                        <span>{field.label}</span>
                        <small className="muted-inline">{status.masked || "未保存"}</small>
                      </div>
                      <span className={`status-pill ${status.configured ? "configured" : "missing"}`}>
                        {fieldStatusLabel(status.configured)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </article>

            <article className="credential-status-card">
              <h4>GRVT 状态</h4>
              <ul>
                {GRVT_FIELDS.map((field) => {
                  const status = credentialsStatus.grvt[field.key];
                  return (
                    <li key={`grvt-status-${field.key}`}>
                      <div className="status-meta">
                        <span>{field.label}</span>
                        <small className="muted-inline">{status.masked || "未保存"}</small>
                      </div>
                      <span className={`status-pill ${status.configured ? "configured" : "missing"}`}>
                        {fieldStatusLabel(status.configured)}
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
              {PARADEX_FIELDS.map((field) => {
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
          </div>

          <div className="credential-group">
            <h4>GRVT</h4>
            <div className="credential-grid">
              {GRVT_FIELDS.map((field) => {
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
          </div>

          <p className="hint">
            必填建议：Paradex 需要 API Key + API Secret，GRVT 需要 API Key + Private Key + Trading Account ID。
          </p>

          <div className="action-row action-row-3">
            <button className="btn btn-primary" type="submit" disabled={saving}>
              保存凭证
            </button>
            <button
              className="btn btn-secondary"
              type="button"
              onClick={() => void onApplyClick()}
              disabled={saving || applying}
            >
              应用凭证
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => void loadStatus(false)}
              disabled={saving || applying || loading}
            >
              刷新状态
            </button>
          </div>

          <div className="action-row action-row-2">
            <button
              className="btn btn-secondary"
              type="button"
              onClick={() => void runValidation("saved")}
              disabled={saving || applying || validatingDraft || validatingSaved}
            >
              {validatingSaved ? "检测中..." : "检测已保存凭证"}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => void runValidation("draft")}
              disabled={saving || applying || validatingDraft || validatingSaved}
            >
              {validatingDraft ? "检测中..." : "检测当前填写凭证"}
            </button>
          </div>
        </form>
      </section>

      {validationResult ? (
        <section className="panel page-panel validation-panel">
          <div className="panel-title">
            <h2>凭证检测结果</h2>
            <small>{validationSourceLabel}</small>
          </div>
          <div className={`validation-summary ${validationResult.ok ? "ok" : "fail"}`}>
            {validationResult.message || "无返回信息"}
          </div>

          <div className="validation-grid">
            <article className="validation-card">
              <h4>Paradex</h4>
              <p className={validationResult.data?.paradex.valid ? "form-success" : "form-error"}>
                {validationResult.data?.paradex.reason || "无返回"}
              </p>
              <ul>
                {Object.entries(validationResult.data?.paradex.checks ?? {}).map(([key, value]) => (
                  <li key={`paradex-check-${key}`}>
                    <span>{checkLabel(key)}</span>
                    <strong className={value ? "state-ok" : "state-danger"}>{value ? "通过" : "失败"}</strong>
                  </li>
                ))}
              </ul>
            </article>

            <article className="validation-card">
              <h4>GRVT</h4>
              <p className={validationResult.data?.grvt.valid ? "form-success" : "form-error"}>
                {validationResult.data?.grvt.reason || "无返回"}
              </p>
              <ul>
                {Object.entries(validationResult.data?.grvt.checks ?? {}).map(([key, value]) => (
                  <li key={`grvt-check-${key}`}>
                    <span>{checkLabel(key)}</span>
                    <strong className={value ? "state-ok" : "state-danger"}>{value ? "通过" : "失败"}</strong>
                  </li>
                ))}
              </ul>
            </article>
          </div>
        </section>
      ) : null}
    </div>
  );
}
