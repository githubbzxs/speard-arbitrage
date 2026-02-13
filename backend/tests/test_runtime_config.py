from __future__ import annotations

from arbbot.config import AppConfig


def test_runtime_config_compat_with_dry_run_true(monkeypatch) -> None:
    monkeypatch.setenv("ARB_DRY_RUN", "true")
    monkeypatch.delenv("ARB_SIMULATED_MARKET_DATA", raising=False)
    monkeypatch.delenv("ARB_LIVE_ORDER_ENABLED", raising=False)

    config = AppConfig.from_env(env_path=None)

    assert config.runtime.simulated_market_data is True
    assert config.runtime.live_order_enabled is False


def test_runtime_config_compat_with_dry_run_false(monkeypatch) -> None:
    monkeypatch.setenv("ARB_DRY_RUN", "false")
    monkeypatch.delenv("ARB_SIMULATED_MARKET_DATA", raising=False)
    monkeypatch.delenv("ARB_LIVE_ORDER_ENABLED", raising=False)

    config = AppConfig.from_env(env_path=None)

    assert config.runtime.simulated_market_data is False
    assert config.runtime.live_order_enabled is True


def test_runtime_config_new_flags_override_dry_run(monkeypatch) -> None:
    monkeypatch.setenv("ARB_DRY_RUN", "true")
    monkeypatch.setenv("ARB_SIMULATED_MARKET_DATA", "false")
    monkeypatch.setenv("ARB_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("ARB_ENABLE_LIVE_ORDER_CONFIRM_TEXT", "CONFIRM-LIVE")

    config = AppConfig.from_env(env_path=None)

    assert config.runtime.simulated_market_data is False
    assert config.runtime.live_order_enabled is True
    assert config.runtime.enable_order_confirmation_text == "CONFIRM-LIVE"


def test_default_market_mapping_for_standard_symbols(monkeypatch) -> None:
    monkeypatch.setenv("ARB_SYMBOLS", "BTC-PERP,ETH-PERP")
    monkeypatch.delenv("PARADEX_MARKETS", raising=False)
    monkeypatch.delenv("GRVT_MARKETS", raising=False)

    config = AppConfig.from_env(env_path=None)

    assert [item.paradex_market for item in config.symbols] == ["BTC/USD:USDC", "ETH/USD:USDC"]
    assert [item.grvt_market for item in config.symbols] == ["BTC_USDT_Perp", "ETH_USDT_Perp"]


def test_default_symbols_expand_to_ten_pairs(monkeypatch) -> None:
    monkeypatch.delenv("ARB_SYMBOLS", raising=False)
    monkeypatch.delenv("PARADEX_MARKETS", raising=False)
    monkeypatch.delenv("GRVT_MARKETS", raising=False)
    monkeypatch.delenv("ARB_RECOMMENDED_LEVERAGES", raising=False)

    config = AppConfig.from_env(env_path=None)

    assert len(config.symbols) == 10
    assert [item.symbol for item in config.symbols] == [
        "BTC-PERP",
        "ETH-PERP",
        "SOL-PERP",
        "XRP-PERP",
        "DOGE-PERP",
        "ADA-PERP",
        "LINK-PERP",
        "AVAX-PERP",
        "DOT-PERP",
        "LTC-PERP",
    ]
    assert all(item.recommended_leverage == 2 for item in config.symbols)
