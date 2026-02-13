import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  DEFAULT_CREDENTIALS_STATUS,
  apiClient,
  getErrorMessage
} from "../api/client";
import type {
  CredentialsPayload,
  CredentialsStatus,
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
  { key: "api_key", label: "API Key（可选）", placeholder: "请输入 GRVT API Key", optional: true }
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

export default function ApiConfigPage() {
  const [credentialsStatus, setCredentialsStatus] = useState<CredentialsStatus>(DEFAULT_CREDENTIALS_STATUS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

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

  const toggleFieldVisibility = (fieldKey: string) => {
    setVisibleFields((previous) => ({
      ...previous,
      [fieldKey]: !previous[fieldKey]
    }));
  };

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
                {GRVT_FIELDS.map((field) => {
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

          <p className="hint">必填建议：Paradex 需要 API Key + API Secret，GRVT 需要 Private Key + Trading Account ID。</p>

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
        </form>
      </section>
    </div>
  );
}
