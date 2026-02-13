# AGENTS 记忆

## Facts
- 项目目标：构建 Paradex + GRVT 跨所价差套利系统，提供后端执行引擎与 Web 控制台。
- 后端框架：FastAPI（入口 `backend/main.py`，应用构建 `backend/arbbot/main.py`）。
- 前端框架：React + Vite（目录 `web/ui`）。
- 数据存储：SQLite + CSV。

## Decisions
- [2026-02-13] 凭证配置改为后端持久化（SQLite）
  - Why：需要在网页填写 API Key 后可在服务端保留状态，避免仅前端本地存储。
  - Impact：`backend/arbbot/storage/credentials_repository.py`、`backend/arbbot/web/api.py`、`web/ui/src/App.tsx`、`web/ui/src/api/client.ts`。
  - Verify：`python -m pytest backend/tests`。

- [2026-02-13] 新增“应用凭证”接口（仅引擎停止时执行）
  - Why：避免每次修改 API Key 都要手改 `.env` 或重启整套服务。
  - Impact：`backend/arbbot/strategy/orchestrator.py`、`backend/arbbot/web/api.py`、`backend/arbbot/storage/credentials_repository.py`、`web/ui/src/App.tsx`、`web/ui/src/api/client.ts`。
  - Verify：`python -m pytest backend/tests`，以及前端点击“应用凭证”按钮。

- [2026-02-13] Spread 拆分为 bps 与绝对价差，并增加 dry-run 标识
  - Why：避免把 `bps` 误当成“价格差”，并解释 dry-run 下价差剧烈抖动是预期现象。
  - Impact：`backend/arbbot/models.py`、`backend/arbbot/strategy/spread_engine.py`、`backend/arbbot/strategy/orchestrator.py`、`web/ui/src/App.tsx`、`web/ui/src/types.ts`。
  - Verify：页面表格展示 `Spread(bps)` 与 `Spread(price)` 两列，并显示 `DRY-RUN/LIVE`。

- [2026-02-13] 优化 dry-run 模拟行情锚定价格，并对 WebSocket symbol 更新做节流
  - Why：避免 dry-run 的随机游走长期漂移，导致价差“像疯狗一样乱跳”，并降低前端频繁重绘。
  - Impact：`backend/arbbot/exchanges/paradex_adapter.py`、`backend/arbbot/exchanges/grvt_adapter.py`、`web/ui/src/hooks/useDashboard.ts`。
  - Verify：dry-run 启动引擎后，`Spread(price)` 通常保持在合理区间（不会轻易出现 100+），页面刷新更平滑。

- [2026-02-13] 拆分运行时双开关：行情模式与下单权限
  - Why：`ARB_DRY_RUN` 将“行情来源”和“下单行为”绑定，无法满足“真实行情 + 可控下单”。
  - Impact：`backend/arbbot/config.py`、`backend/arbbot/strategy/execution_engine.py`、`backend/arbbot/strategy/orchestrator.py`、`backend/arbbot/web/api.py`、`web/ui/src/App.tsx`、`web/ui/src/api/client.ts`、`web/ui/src/types.ts`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并验证 `POST /api/runtime/order-execution` / `POST /api/runtime/market-data-mode`。

- [2026-02-13] 前端默认深色主题并支持手动切换
  - Why：满足界面深色模式诉求，同时保留可切换性。
  - Impact：`web/ui/src/styles.css`、`web/ui/src/App.tsx`。
  - Verify：`cd web/ui && npm run build`，浏览器刷新后主题记忆生效。

- [2026-02-13] 线上推荐同域反代（Nginx）解决 `/api/*` 与 `/ws/*` 连通
  - Why：减少跨域与地址配置复杂度，避免 `Failed to fetch`。
  - Impact：`deploy/nginx.conf`、`deploy/arbbot.service`、`README.md`。
  - Verify：`curl -i http://127.0.0.1/api/status` 与页面实时数据加载。

## Commands
- 后端测试：`python -m pytest backend/tests`
- 后端启动：`python backend/main.py`
- 前端开发：`cd web/ui && npm install && npm run dev`
- 前端构建：`cd web/ui && npm run build`
- 部署重载：`sudo systemctl restart arbbot && sudo nginx -t && sudo systemctl reload nginx`

## Status / Next
- 当前状态：
  - 已完成深色主题、API 凭证表单、凭证状态接口与持久化、Linux + Nginx 部署文档。
  - 已新增 `GET /api/credentials/status`、`POST /api/credentials`、`POST /api/credentials/apply`。
  - `SymbolSnapshot` 增加 `spread_price` 字段，用于前端展示绝对价差。
  - 已新增运行时双开关接口：`POST /api/runtime/order-execution`、`POST /api/runtime/market-data-mode`。
- 下一步建议：
  - 为凭证接口增加鉴权（当前默认无鉴权）。
  - 将 FastAPI `on_event` 迁移到 lifespan，消除弃用警告。

## Known Issues
- 现象：测试日志出现 FastAPI `on_event` 弃用警告。
  - 原因：应用仍使用 `@app.on_event("startup"/"shutdown")`。
  - 修复：后续迁移至 lifespan handlers。
  - 验证：迁移后运行 `python -m pytest backend/tests`，警告应减少。
