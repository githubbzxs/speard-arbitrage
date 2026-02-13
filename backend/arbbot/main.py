"""应用入口。"""

from __future__ import annotations

from .config import AppConfig
from .web.api import create_app


def build_app() -> object:
    """构建 FastAPI 应用。"""
    config = AppConfig.from_env()
    return create_app(config)
