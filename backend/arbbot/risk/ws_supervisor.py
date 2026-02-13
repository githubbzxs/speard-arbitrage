"""WebSocket 状态监督器。"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import utc_ms


@dataclass(slots=True)
class WsState:
    """单连接状态。"""

    connected: bool = False
    reconnect_count: int = 0
    last_message_ms: int = 0
    last_disconnect_ms: int = 0


class WsSupervisor:
    """跟踪 WS 活性并给出暂停建议。"""

    def __init__(self, idle_timeout_sec: int) -> None:
        self.idle_timeout_ms = idle_timeout_sec * 1000
        self._states: dict[str, WsState] = {}

    def mark_connected(self, exchange: str) -> None:
        state = self._states.setdefault(exchange, WsState())
        state.connected = True

    def mark_message(self, exchange: str) -> None:
        state = self._states.setdefault(exchange, WsState())
        state.connected = True
        state.last_message_ms = utc_ms()

    def mark_disconnected(self, exchange: str) -> None:
        state = self._states.setdefault(exchange, WsState())
        state.connected = False
        state.reconnect_count += 1
        state.last_disconnect_ms = utc_ms()

    def is_ok(self) -> bool:
        if not self._states:
            return False
        now = utc_ms()
        for state in self._states.values():
            if not state.connected:
                return False
            if state.last_message_ms and now - state.last_message_ms > self.idle_timeout_ms:
                return False
        return True

    def snapshot(self) -> dict[str, dict[str, int | bool]]:
        return {
            exchange: {
                "connected": state.connected,
                "reconnect_count": state.reconnect_count,
                "last_message_ms": state.last_message_ms,
                "last_disconnect_ms": state.last_disconnect_ms,
            }
            for exchange, state in self._states.items()
        }
