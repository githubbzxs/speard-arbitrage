from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import arbbot.market.scanner as scanner_module
from arbbot.config import AppConfig, ExchangeConfig, ExchangeCredentials, StorageConfig, SymbolConfig
from arbbot.market.scanner import NominalSpreadScanner


def _build_test_config(tmp_path: Path, *, trading_account_id: str) -> AppConfig:
    sqlite_path = tmp_path / "grvt-leverage-diag.db"
    csv_dir = tmp_path / "csv"
    return AppConfig(
        symbols=[
            SymbolConfig(
                symbol="BTC-PERP",
                paradex_market="BTC/USD:USDC",
                grvt_market="BTC_USDT_Perp",
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
            credentials=ExchangeCredentials(
                api_key="grvt-key",
                private_key="0x" + "11" * 32,
                trading_account_id=trading_account_id,
            ),
        ),
        storage=StorageConfig(sqlite_path=str(sqlite_path), csv_dir=str(csv_dir)),
    )


class _FakeCookie:
    def __init__(self, account_id: str | None) -> None:
        self.grvt_account_id = account_id


class _FakeCookieJar:
    def __init__(self) -> None:
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.headers: dict[str, str] = {"X-Grvt-Account-Id": "present"}
        self.cookie_jar = _FakeCookieJar()

    async def close(self) -> None:
        self.closed = True


def _make_fake_grvt_raw_async(*, cookie_account_id: str, responses: list[object] | None = None):
    """构造一个可控的 GrvtRawAsync 替身，用于验证鉴权诊断与重试逻辑。"""

    class _FakeGrvtRawAsync:
        created = 0
        calls = 0
        last_instance: "_FakeGrvtRawAsync | None" = None

        def __init__(self, config):  # type: ignore[no-untyped-def]
            type(self).created += 1
            type(self).last_instance = self
            self.config = config
            self._session = _FakeSession()
            self._cookie: _FakeCookie | None = None
            self._cookie_account_id = cookie_account_id
            self._responses = list(responses or [])

        async def _refresh_cookie(self) -> None:
            self._cookie = _FakeCookie(self._cookie_account_id)

        async def get_all_initial_leverage_v1(self, req):  # type: ignore[no-untyped-def]
            type(self).calls += 1
            if self._responses:
                return self._responses.pop(0)
            return SimpleNamespace(
                results=[SimpleNamespace(instrument="BTC_USDT_Perp", max_leverage=100)]
            )

    return _FakeGrvtRawAsync


@pytest.mark.asyncio
async def test_grvt_leverage_map_cached_within_ttl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cls = _make_fake_grvt_raw_async(
        cookie_account_id="acc-1234",
        responses=[
            SimpleNamespace(
                results=[SimpleNamespace(instrument="BTC_USDT_Perp", max_leverage=100)]
            )
        ],
    )
    monkeypatch.setattr(scanner_module, "GrvtRawAsync", fake_cls)

    scanner = NominalSpreadScanner(_build_test_config(tmp_path, trading_account_id="acc-1234"), scan_interval_sec=60)

    first = await scanner._fetch_grvt_leverage_map()  # type: ignore[attr-defined]
    second = await scanner._fetch_grvt_leverage_map()  # type: ignore[attr-defined]

    assert fake_cls.created == 1
    assert first == second
    assert first["BTC_USDT_Perp"] == 100.0


@pytest.mark.asyncio
async def test_grvt_leverage_map_reports_account_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cls = _make_fake_grvt_raw_async(cookie_account_id="acc-1234")
    monkeypatch.setattr(scanner_module, "GrvtRawAsync", fake_cls)

    scanner = NominalSpreadScanner(_build_test_config(tmp_path, trading_account_id="acc-5678"), scan_interval_sec=60)

    with pytest.raises(ValueError) as exc_info:
        await scanner._fetch_grvt_leverage_map()  # type: ignore[attr-defined]

    message = str(exc_info.value)
    assert "env=prod" in message
    assert "X-Grvt-Account-Id" in message
    assert "...1234" in message
    assert "...5678" in message


@pytest.mark.asyncio
async def test_grvt_leverage_map_retries_on_auth_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(scanner_module.asyncio, "sleep", _no_sleep)

    auth_error = scanner_module.GrvtError(
        code=1000,
        message="You need to authenticate prior to using this functionality",
        status=401,
    )
    success = SimpleNamespace(
        results=[SimpleNamespace(instrument="BTC_USDT_Perp", max_leverage=100)]
    )
    fake_cls = _make_fake_grvt_raw_async(cookie_account_id="acc-1234", responses=[auth_error, success])
    monkeypatch.setattr(scanner_module, "GrvtRawAsync", fake_cls)

    scanner = NominalSpreadScanner(_build_test_config(tmp_path, trading_account_id="acc-1234"), scan_interval_sec=60)

    result = await scanner._fetch_grvt_leverage_map()  # type: ignore[attr-defined]
    assert result["BTC_USDT_Perp"] == 100.0
    assert fake_cls.calls == 2

    instance = fake_cls.last_instance
    assert instance is not None
    assert "X-Grvt-Account-Id" not in instance._session.headers
    assert instance._session.cookie_jar.cleared is True
    assert instance._session.closed is True

