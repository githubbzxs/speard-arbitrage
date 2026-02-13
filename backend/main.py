"""本地启动脚本。"""

from __future__ import annotations

import uvicorn

from arbbot.config import AppConfig
from arbbot.main import build_app


if __name__ == "__main__":
    config = AppConfig.from_env()
    app = build_app()
    uvicorn.run(
        app,
        host=config.web.host,
        port=config.web.port,
        log_level=config.web.log_level,
    )
