"""订单簿管理。"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import BBO, ExchangeName, utc_ms


@dataclass(slots=True)
class SymbolBooks:
    """单标的盘口缓存。"""

    paradex_ws: BBO | None = None
    grvt_ws: BBO | None = None
    paradex_rest: BBO | None = None
    grvt_rest: BBO | None = None


class OrderBookManager:
    """集中维护 WS/REST 两路盘口。"""

    def __init__(self) -> None:
        self._books: dict[str, SymbolBooks] = {}

    def _ensure(self, symbol: str) -> SymbolBooks:
        return self._books.setdefault(symbol, SymbolBooks())

    def update_ws(self, exchange: ExchangeName, symbol: str, bbo: BBO) -> None:
        books = self._ensure(symbol)
        if exchange == ExchangeName.PARADEX:
            books.paradex_ws = bbo
        else:
            books.grvt_ws = bbo

    def update_rest(self, exchange: ExchangeName, symbol: str, bbo: BBO) -> None:
        books = self._ensure(symbol)
        if exchange == ExchangeName.PARADEX:
            books.paradex_rest = bbo
        else:
            books.grvt_rest = bbo

    def get_ws_pair(self, symbol: str) -> tuple[BBO | None, BBO | None]:
        books = self._ensure(symbol)
        return books.paradex_ws, books.grvt_ws

    def get_rest_pair(self, symbol: str) -> tuple[BBO | None, BBO | None]:
        books = self._ensure(symbol)
        return books.paradex_rest, books.grvt_rest

    def get_effective_pair(self, symbol: str) -> tuple[BBO | None, BBO | None]:
        books = self._ensure(symbol)
        paradex = books.paradex_ws if books.paradex_ws is not None else books.paradex_rest
        grvt = books.grvt_ws if books.grvt_ws is not None else books.grvt_rest
        return paradex, grvt

    def is_stale(self, symbol: str, stale_ms: int) -> bool:
        paradex, grvt = self.get_ws_pair(symbol)
        now_ms = utc_ms()
        if paradex is None or grvt is None:
            return True
        if now_ms - paradex.timestamp_ms > stale_ms:
            return True
        if now_ms - grvt.timestamp_ms > stale_ms:
            return True
        return False

    def snapshot(self, symbol: str) -> dict[str, dict[str, float] | None]:
        books = self._ensure(symbol)

        def to_dict(bbo: BBO | None) -> dict[str, float] | None:
            if bbo is None:
                return None
            return {
                "bid": float(bbo.bid),
                "ask": float(bbo.ask),
                "ts": float(bbo.timestamp_ms),
            }

        return {
            "paradex_ws": to_dict(books.paradex_ws),
            "grvt_ws": to_dict(books.grvt_ws),
            "paradex_rest": to_dict(books.paradex_rest),
            "grvt_rest": to_dict(books.grvt_rest),
        }
