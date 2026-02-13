from decimal import Decimal

import pytest

from backend.arbbot.config import ExchangeConfig, ExchangeCredentials, SymbolConfig
from backend.arbbot.exchanges.grvt_adapter import GRVT_ORDERBOOK_LIMIT, GrvtAdapter


class FakeGrvtClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    async def fetch_order_book(self, market: str, limit: int | None = None) -> dict[str, list[list[float]]]:
        self.calls.append((market, limit))
        return {
            "bids": [[100.0, 1.0]],
            "asks": [[101.0, 1.5]],
        }


class FakeGrvtClientWithDictLevels(FakeGrvtClient):
    async def fetch_order_book(self, market: str, limit: int | None = None) -> dict[str, list[dict[str, str]]]:
        self.calls.append((market, limit))
        return {
            "bids": [{"price": "100.2", "size": "1.0"}],
            "asks": [{"price": "100.8", "size": "1.4"}],
        }


def _build_adapter() -> GrvtAdapter:
    config = ExchangeConfig(
        name="grvt",
        environment="prod",
        rest_url="https://edge.grvt.io",
        ws_url="wss://market-data.grvt.io/ws/full",
        credentials=ExchangeCredentials(),
    )
    return GrvtAdapter(config=config, simulate_market_data=False)


def _build_symbol() -> SymbolConfig:
    return SymbolConfig(symbol="BTC-PERP", paradex_market="BTC-PERP", grvt_market="BTC_USDT_Perp")


@pytest.mark.asyncio
async def test_fetch_bbo_uses_supported_grvt_depth_limit() -> None:
    adapter = _build_adapter()
    client = FakeGrvtClient()
    adapter._client = client

    bbo = await adapter.fetch_bbo(_build_symbol())

    assert bbo is not None
    assert bbo.bid == Decimal("100.0")
    assert bbo.ask == Decimal("101.0")
    assert client.calls == [("BTC_USDT_Perp", GRVT_ORDERBOOK_LIMIT)]


@pytest.mark.asyncio
async def test_fetch_rest_bbo_uses_supported_grvt_depth_limit() -> None:
    adapter = _build_adapter()
    client = FakeGrvtClient()
    adapter._client = client

    bbo = await adapter.fetch_rest_bbo(_build_symbol())

    assert bbo is not None
    assert bbo.bid == Decimal("100.0")
    assert bbo.ask == Decimal("101.0")
    assert client.calls == [("BTC_USDT_Perp", GRVT_ORDERBOOK_LIMIT)]


@pytest.mark.asyncio
async def test_fetch_bbo_supports_dict_levels_from_grvt_sdk() -> None:
    adapter = _build_adapter()
    client = FakeGrvtClientWithDictLevels()
    adapter._client = client

    bbo = await adapter.fetch_bbo(_build_symbol())

    assert bbo is not None
    assert bbo.bid == Decimal("100.2")
    assert bbo.ask == Decimal("100.8")
    assert client.calls == [("BTC_USDT_Perp", GRVT_ORDERBOOK_LIMIT)]
