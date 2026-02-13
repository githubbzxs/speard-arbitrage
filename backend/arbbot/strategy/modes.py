"""策略模式管理。"""

from __future__ import annotations

from ..models import StrategyMode


class ModeController:
    """支持手动切换 normal_arb / zero_wear。"""

    def __init__(self, initial_mode: StrategyMode) -> None:
        self._mode = initial_mode

    @property
    def mode(self) -> StrategyMode:
        return self._mode

    def set_mode(self, mode: StrategyMode) -> None:
        self._mode = mode
