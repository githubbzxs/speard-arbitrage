from pathlib import Path

from arbbot.storage.repository import Repository


def test_market_spread_history_crud_and_trim(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "repo-market-history.db"
    repo = Repository(str(sqlite_path))
    try:
        for idx in range(5):
            repo.add_market_spread_point(
                ts=f"2026-02-13T00:00:{idx:02d}+00:00",
                symbol="BTC-PERP",
                signed_edge_bps=str(10 + idx),
                tradable_edge_pct=str((10 + idx) / 100),
                source="unit_test",
            )

        assert repo.count_market_spread_points("BTC-PERP") == 5
        recent = repo.list_recent_market_spread_points("BTC-PERP", limit=3)
        assert len(recent) == 3
        assert recent[0]["signed_edge_bps"] == "14"

        repo.trim_market_spread_history("BTC-PERP", max_rows=2)
        assert repo.count_market_spread_points("BTC-PERP") == 2
    finally:
        repo.close()
