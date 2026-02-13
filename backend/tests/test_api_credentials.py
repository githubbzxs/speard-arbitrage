from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from arbbot.config import AppConfig, ExchangeConfig, ExchangeCredentials, StorageConfig, SymbolConfig
from arbbot.web.api import create_app


def _build_test_config(tmp_path: Path) -> AppConfig:
    sqlite_path = tmp_path / "credentials.db"
    csv_dir = tmp_path / "csv"
    return AppConfig(
        symbols=[
            SymbolConfig(
                symbol="BTC-PERP",
                paradex_market="BTC-PERP",
                grvt_market="BTC-PERP",
            )
        ],
        paradex=ExchangeConfig(
            name="paradex",
            environment="prod",
            rest_url="https://api.prod.paradex.trade",
            ws_url="wss://ws.api.prod.paradex.trade/v1",
            credentials=ExchangeCredentials(),
        ),
        grvt=ExchangeConfig(
            name="grvt",
            environment="prod",
            rest_url="https://edge.grvt.io",
            ws_url="wss://market-data.grvt.io/ws/full",
            credentials=ExchangeCredentials(),
        ),
        storage=StorageConfig(sqlite_path=str(sqlite_path), csv_dir=str(csv_dir)),
    )


def test_post_credentials_api_success(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))
    payload = {
        "paradex": {
            "l2_private_key": "paradex-l2-private",
            "l2_address": "paradex-l2-address",
        },
        "grvt": {
            "api_key": "grvt-key",
            "api_secret": "grvt-secret",
            "private_key": "grvt-private-key",
            "trading_account_id": "acc-1",
        },
    }

    with TestClient(app) as client:
        response = client.post("/api/credentials", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["message"] == "凭证已保存，可在引擎停止时点击“应用凭证”生效"


def test_status_true_after_save(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))
    payload = {
        "paradex": {"l2_private_key": "pdx-l2-private"},
        "grvt": {"private_key": "grvt-private"},
    }

    with TestClient(app) as client:
        client.post("/api/credentials", json=payload)
        status_response = client.get("/api/credentials/status")

    assert status_response.status_code == 200
    status_body = status_response.json()
    data = status_body["data"]
    assert data["paradex"]["l2_private_key"]["configured"] is True
    assert isinstance(data["paradex"]["l2_private_key"]["updated_at"], str)
    assert data["paradex"]["l2_private_key"]["masked"].startswith("****")
    assert data["grvt"]["private_key"]["configured"] is True
    assert isinstance(data["grvt"]["private_key"]["updated_at"], str)
    assert data["grvt"]["private_key"]["masked"].startswith("****")


def test_status_false_after_clear(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        client.post("/api/credentials", json={"paradex": {"l2_private_key": "to-be-cleared"}})
        client.post("/api/credentials", json={"paradex": {"l2_private_key": ""}})
        status_response = client.get("/api/credentials/status")

    data = status_response.json()["data"]
    assert data["paradex"]["l2_private_key"]["configured"] is False
    assert data["paradex"]["l2_private_key"]["updated_at"] is None
    assert data["paradex"]["l2_private_key"]["masked"] == ""


def test_status_api_not_leak_plaintext(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))
    secrets = {
        "paradex": {
            "l2_private_key": "SECRET_PARADEX_L2_PRIVATE_123",
            "l2_address": "SECRET_PARADEX_L2_ADDRESS_456",
        },
        "grvt": {
            "api_key": "SECRET_GRVT_KEY_123",
            "api_secret": "SECRET_GRVT_SECRET_456",
            "private_key": "SECRET_GRVT_PRIVATE_789",
            "trading_account_id": "SECRET_ACC_ID_001",
        },
    }

    with TestClient(app) as client:
        client.post("/api/credentials", json=secrets)
        status_response = client.get("/api/credentials/status")

    status_text = status_response.text
    for secret in [
        "SECRET_PARADEX_L2_PRIVATE_123",
        "SECRET_PARADEX_L2_ADDRESS_456",
        "SECRET_GRVT_KEY_123",
        "SECRET_GRVT_SECRET_456",
        "SECRET_GRVT_PRIVATE_789",
        "SECRET_ACC_ID_001",
    ]:
        assert secret not in status_text

    data_text = json.dumps(status_response.json()["data"], ensure_ascii=False)
    assert '"value"' not in data_text


def test_validate_credentials_saved_source(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    payload = {
        "paradex": {"l2_private_key": "pdx-l2-private", "l2_address": "pdx-l2-address"},
        "grvt": {"api_key": "grvt-key", "private_key": "grvt-private", "trading_account_id": "acc-1"},
    }

    async def fake_validate(credentials: dict[str, dict[str, str]]) -> dict[str, object]:
        assert credentials["paradex"]["l2_private_key"] == "pdx-l2-private"
        assert credentials["grvt"]["trading_account_id"] == "acc-1"
        return {
            "ok": True,
            "message": "ok",
            "data": {"paradex": {"valid": True}, "grvt": {"valid": True}},
        }

    app.state.credentials_validator.validate = fake_validate

    with TestClient(app) as client:
        client.post("/api/credentials", json=payload)
        response = client.post("/api/credentials/validate", json={"source": "saved"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["message"] == "ok"


def test_validate_credentials_draft_source(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    async def fake_validate(credentials: dict[str, dict[str, str]]) -> dict[str, object]:
        assert credentials["paradex"]["l2_private_key"] == "draft-pdx-l2-private"
        assert credentials["grvt"]["api_key"] == "draft-grvt-key"
        return {
            "ok": False,
            "message": "draft-invalid",
            "data": {"paradex": {"valid": False}, "grvt": {"valid": False}},
        }

    app.state.credentials_validator.validate = fake_validate

    with TestClient(app) as client:
        response = client.post(
            "/api/credentials/validate",
            json={
                "source": "draft",
                "payload": {
                    "paradex": {"l2_private_key": "draft-pdx-l2-private"},
                    "grvt": {"api_key": "draft-grvt-key"},
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["message"] == "draft-invalid"


def test_validate_credentials_draft_requires_payload(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        response = client.post("/api/credentials/validate", json={"source": "draft"})

    assert response.status_code == 400


def test_validate_credentials_draft_invalid_grvt_private_key_format(tmp_path: Path) -> None:
    app = create_app(_build_test_config(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/api/credentials/validate",
            json={
                "source": "draft",
                "payload": {
                    "grvt": {
                        "api_key": "grvt-key",
                        "private_key": "not-a-hex-key",
                        "trading_account_id": "acc-1",
                    }
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "十六进制字符串" in body["data"]["grvt"]["reason"]
