from decimal import Decimal

from arbbot.models import RiskState, SymbolSnapshot


def test_symbol_snapshot_includes_exchange_prices() -> None:
    snapshot = SymbolSnapshot(
        symbol="BTC-PERP",
        status="running",
        signal="hold",
        paradex_bid=Decimal("66100.1"),
        paradex_ask=Decimal("66100.9"),
        paradex_mid=Decimal("66100.5"),
        grvt_bid=Decimal("66102.2"),
        grvt_ask=Decimal("66103.0"),
        grvt_mid=Decimal("66102.6"),
        spread_bps=Decimal("2.1"),
        spread_price=Decimal("1.4"),
        zscore=Decimal("0.2"),
        net_position=Decimal("0"),
        target_position=Decimal("0"),
        paradex_position=Decimal("0"),
        grvt_position=Decimal("0"),
        updated_at="2026-02-13T06:00:00+00:00",
        risk=RiskState(
            stale=False,
            consistency_ok=True,
            health_ok=True,
            ws_ok=True,
            can_open=True,
            reason="ok",
        ),
    )

    data = snapshot.to_dict()

    assert data["paradex_bid"] == 66100.1
    assert data["paradex_ask"] == 66100.9
    assert data["paradex_mid"] == 66100.5
    assert data["grvt_bid"] == 66102.2
    assert data["grvt_ask"] == 66103.0
    assert data["grvt_mid"] == 66102.6
