# AGENTS 记忆

## Facts
- 项目目标：构建 Paradex + GRVT 跨所价差套利系统，提供后端执行引擎与 Web 控制台。
- 后端框架：FastAPI（入口 `backend/main.py`，应用构建 `backend/arbbot/main.py`）。
- 前端框架：React + Vite（目录 `web/ui`）。
- 数据存储：SQLite + CSV。

## Decisions
- [2026-02-13] 行情与候选统一过滤为仅保留 50x 及以上有效杠杆币对
  - Why：用户明确要求“只要有 50x 杠杆的币”，并避免前端显示与实际候选口径不一致。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/tests/test_market_scanner_leverage_filter.py`、`web/ui/src/pages/TradePage.tsx`、`web/ui/src/pages/MarketPage.tsx`。
  - Verify：`python -m pytest backend/tests/test_market_scanner_leverage_filter.py`、`python -m pytest backend/tests`、`cd web/ui && npm run build`。

- [2026-02-13] 套利口径统一为 Paradex taker + GRVT maker
  - Why：对齐目标执行模型（Paradex 吃单、GRVT 挂单），避免扫描口径与实际执行不一致。
  - Impact：`backend/arbbot/strategy/execution_engine.py`、`backend/arbbot/strategy/orchestrator.py`、`backend/arbbot/market/scanner.py`、`backend/tests/test_execution_engine_order_gate.py`、`web/ui/src/api/client.ts`、`web/ui/src/pages/MarketPage.tsx`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`。

- [2026-02-13] 开仓主腿改为 Paradex taker，取消 Paradex post-only maker
  - Why：Paradex 侧为 0 手续费时，优先吃单可提高成交确定性与刷量效率，避免 maker 挂单不成交导致机会流失。
  - Impact：`backend/arbbot/strategy/execution_engine.py`、`backend/tests/test_execution_engine_order_gate.py`。
  - Verify：`python -m pytest backend/tests/test_execution_engine_order_gate.py`。

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

- [2026-02-13] 修复 GRVT 真实行情深度参数不兼容
  - Why：`fetch_order_book(limit=5)` 在 GRVT 返回 `Depth is invalid`，导致 `ws_ok=false`、盘口不可用。
  - Impact：`backend/arbbot/exchanges/grvt_adapter.py`、`backend/tests/test_grvt_adapter_depth.py`。
  - Verify：`python -m pytest backend/tests/test_grvt_adapter_depth.py`，以及线上 `GET /api/status` 的 `ws_ok=true`。

- [2026-02-13] 标准符号默认映射为交易所可用 market symbol
  - Why：`BTC-PERP/ETH-PERP` 不是 Paradex ccxt 可用 symbol，会导致真实行情抓取失败。
  - Impact：`backend/arbbot/config.py`、`.env.example`、`backend/tests/test_runtime_config.py`。
  - Verify：`python -m pytest backend/tests/test_runtime_config.py`，并确认 `GET /api/config` 中 `paradex_market` 为 `BTC/USD:USDC, ETH/USD:USDC`。

- [2026-02-13] 兼容 GRVT 盘口返回的 dict 结构
  - Why：GRVT SDK 的 `fetch_order_book` 返回层级可能为 `{"price": ...}`，旧逻辑按数组下标解析会吞异常并导致 `盘口不可用`。
  - Impact：`backend/arbbot/exchanges/grvt_adapter.py`、`backend/tests/test_grvt_adapter_depth.py`。
  - Verify：`python -m pytest backend/tests/test_grvt_adapter_depth.py`，并线上确认 `GET /api/symbols` 不再全为 0。

- [2026-02-13] 生产入口绑定子域名 spread.0xpsyche.me（含 HTTPS）
  - Why：按项目域名约定，统一使用 `xxx.0xpsyche.me` 作为对外入口，避免仅用 IP 访问。
  - Impact：VPS `nginx` 站点 `/etc/nginx/sites-available/arbbot.conf`（server_name/certbot 证书与跳转）。
  - Verify：`curl -I http://spread.0xpsyche.me` 返回 301，`curl -I https://spread.0xpsyche.me` 返回 200，`curl https://spread.0xpsyche.me/api/status` 正常。

- [2026-02-13] Symbol 表格新增双交易所实时价格字段
  - Why：用户需要在页面直接查看 Paradex 与 GRVT 的实际盘口价格，而不只看价差。
  - Impact：`backend/arbbot/models.py`、`backend/arbbot/strategy/orchestrator.py`、`web/ui/src/types.ts`、`web/ui/src/api/client.ts`、`web/ui/src/App.tsx`、`web/ui/src/utils/format.ts`、`backend/tests/test_symbol_snapshot_prices.py`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并确认页面出现 `Paradex Bid/Ask` 与 `GRVT Bid/Ask` 列。

- [2026-02-13] 默认币对扩展到 10 个并透出杠杆信息
  - Why：需要统一支持 10 个主流币对，并在页面明确币对市场映射与建议杠杆，提升可读性与可运维性。
  - Impact：`backend/arbbot/config.py`、`.env.example`、`backend/tests/test_runtime_config.py`、`web/ui/src/types.ts`、`web/ui/src/api/client.ts`、`web/ui/src/App.tsx`、`README.md`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并检查页面“支持币对信息”表格显示 10 个币对及建议杠杆。

- [2026-02-13] 新增真实行情全市场扫描与 Top10 名义价差接口
  - Why：满足“支持全部币对并按名义价差排序展示前十”的需求，且价格必须来自两所真实盘口。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/arbbot/market/__init__.py`、`backend/arbbot/web/api.py`、`backend/tests/test_api_market_top_spreads.py`。
  - Verify：`python -m pytest backend/tests`，并访问 `GET /api/market/top-spreads` 确认返回 Paradex/GRVT 实际价格与 `nominal_spread`。

- [2026-02-13] 前端改为三页面路由（行情/下单/API配置）
  - Why：满足页面分离要求，并移除冗余文案与“支持币对信息”区块。
  - Impact：`web/ui/src/App.tsx`、`web/ui/src/main.tsx`、`web/ui/src/pages/MarketPage.tsx`、`web/ui/src/pages/TradePage.tsx`、`web/ui/src/pages/ApiConfigPage.tsx`、`web/ui/src/api/client.ts`、`web/ui/src/types.ts`、`web/ui/src/styles.css`、`web/ui/package.json`。
  - Verify：`cd web/ui && npm run build`，并检查 `/market` `/trade` `/api-config` 三个路由页面。

- [2026-02-13] GRVT 杠杆改为私有接口强制获取并移除回退杠杆
  - Why：用户要求不再使用回退杠杆，避免杠杆信息不准导致名义价差失真。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/arbbot/web/api.py`、`backend/tests/test_api_market_top_spreads.py`、`web/ui/src/api/client.ts`、`web/ui/src/pages/MarketPage.tsx`。
  - Verify：`python -m pytest backend/tests`，访问 `GET /api/market/top-spreads` 不再接受 `*_fallback_leverage` 参数。

- [2026-02-13] 名义价差改为可执行价差口径并按 Top10 展示
  - Why：避免“价差乱跳/不科学”的观感，使用可执行买卖一价差（bid/ask）与最小最大杠杆计算名义价差。
  - Impact：`backend/arbbot/market/scanner.py`、`web/ui/src/pages/MarketPage.tsx`、`web/ui/src/types.ts`、`web/ui/src/api/client.ts`。
  - Verify：`cd web/ui && npm run build`，页面显示两所真实买卖价、实际价差、名义价差、净名义价差。

- [2026-02-13] API 配置页新增凭证掩码展示与凭证有效性检测
  - Why：解决“明明配置了但看起来空白”的问题，并允许用户直接在页面检测 key 是否有效。
  - Impact：`backend/arbbot/storage/credentials_repository.py`、`backend/arbbot/security/credentials_validator.py`、`backend/arbbot/web/api.py`、`backend/tests/test_api_credentials.py`、`web/ui/src/pages/ApiConfigPage.tsx`、`web/ui/src/api/client.ts`、`web/ui/src/styles.css`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，页面可看到 `****xxxx` 掩码并可执行“检测已保存凭证/检测当前填写凭证”。

- [2026-02-13] 前端补充移动端适配（底部导航与响应式表格）
  - Why：满足手机端可用性要求，避免桌面布局在小屏下难以操作。
  - Impact：`web/ui/src/styles.css`、`web/ui/src/pages/MarketPage.tsx`。
  - Verify：浏览器移动端模式下可通过底部导航切页，行情表格可读。

- [2026-02-13] 行情扫描前自动注入已保存凭证
  - Why：避免“网页已保存凭证但 TopSpreads 仍空白”，减少手动修改 `.env` 或重复“应用凭证”步骤。
  - Impact：`backend/arbbot/web/api.py`、`backend/tests/test_api_market_top_spreads.py`。
  - Verify：仅保存凭证后访问 `GET /api/market/top-spreads` 可直接返回真实扫描结果。

- [2026-02-13] Paradex 凭证改为 L2 私钥 + L2 地址，并去除浅色切换
  - Why：Paradex 当前接入以 L2 账户签名为主，旧 `api_secret/passphrase` 口径不匹配；界面固定深色可减少配置歧义。
  - Impact：`backend/arbbot/config.py`、`backend/arbbot/web/api.py`、`backend/arbbot/strategy/orchestrator.py`、`backend/arbbot/storage/credentials_repository.py`、`backend/arbbot/exchanges/paradex_adapter.py`、`backend/arbbot/security/credentials_validator.py`、`.env.example`、`web/ui/src/pages/ApiConfigPage.tsx`、`web/ui/src/api/client.ts`、`web/ui/src/App.tsx`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并确认 API 配置页 Paradex 仅有两项字段。

- [2026-02-13] 行情页新增“配置/可比/可执行”计数并统一套利空间为 `% + bps`
  - Why：解释“下单页 10 个币对但行情页仅显示 7 个”的过滤差异，提升跨币种可比性与可读性。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/arbbot/web/api.py`、`backend/tests/test_api_market_top_spreads.py`、`web/ui/src/pages/MarketPage.tsx`、`web/ui/src/types.ts`、`web/ui/src/api/client.ts`。
  - Verify：`GET /api/market/top-spreads` 返回 `configured_symbols/comparable_symbols/executable_symbols` 与 `tradable_edge_pct`，前端行情页显示 `% + bps`。

- [2026-02-13] GRVT 私钥非十六进制报错改为可读提示
  - Why：原始异常 `Non-hexadecimal digit found` 对用户不可定位，需明确字段与修复方向。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/arbbot/security/credentials_validator.py`、`backend/tests/test_market_scanner_private_key_validation.py`、`backend/tests/test_api_credentials.py`、`web/ui/src/pages/ApiConfigPage.tsx`。
  - Verify：填写非法 GRVT `private_key` 时，凭证校验与行情扫描都返回“GRVT private_key 格式错误：必须是十六进制字符串（可带 0x 前缀）”。

- [2026-02-13] Paradex 凭证校验增加私钥类型容错（string/int 双候选）
  - Why：修复 `Paradex 校验失败: %x format: an integer is required, not str`，避免“凭证填写正确但校验失败”。
  - Impact：`backend/arbbot/exchanges/paradex_auth.py`、`backend/arbbot/exchanges/paradex_adapter.py`、`backend/arbbot/security/credentials_validator.py`、`backend/tests/test_paradex_auth.py`。
  - Verify：`python -m pytest backend/tests`，并在 API 配置页执行凭证检测不再出现 `%x format` 原始错误。

- [2026-02-13] 新增 Top10 单标的手动选择并强制启动前选择
  - Why：确保“实际交易标的”与 Top10 候选一致，避免下单页和行情页标的口径分离。
  - Impact：`backend/arbbot/web/api.py`、`backend/arbbot/strategy/orchestrator.py`、`backend/tests/test_api_trade_selection.py`、`web/ui/src/api/client.ts`、`web/ui/src/types.ts`、`web/ui/src/pages/TradePage.tsx`、`web/ui/src/pages/MarketPage.tsx`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并确认未选标的时无法启动引擎、下单页仅可选择 Top10 候选。

- [2026-02-13] 行情与下单展示改为纯百分比极简视图
  - Why：用户要求去掉方向、两所买卖价、复杂市场映射与 bps，仅保留百分比价差视图。
  - Impact：`web/ui/src/pages/MarketPage.tsx`、`web/ui/src/pages/TradePage.tsx`。
  - Verify：`cd web/ui && npm run build`，并确认页面仅显示 `%` 口径，且不再出现方向、买卖价、`bps`、`paradex/grvt market` 文案。

- [2026-02-13] 行情页补回净名义价差百分比列
  - Why：对齐“名义价差和净名义价差都按百分比显示”的交互要求，避免仅展示单列名义价差。
  - Impact：`web/ui/src/pages/MarketPage.tsx`。
  - Verify：`cd web/ui && npm run build`，并确认 Top10 表格包含 `名义价差(%)` 与 `净名义价差(%)` 两列。

- [2026-02-13] 行情页新增 Top10 专用 WS 实时流（含轮询兜底）
  - Why：解决“价差不实时变动”的体验问题，避免仅依赖 HTTP + 缓存周期导致页面长时间不刷新。
  - Impact：`backend/arbbot/web/api.py`、`backend/tests/test_api_ws_market_top_spreads.py`、`web/ui/src/ws/client.ts`、`web/ui/src/types.ts`、`web/ui/src/pages/MarketPage.tsx`、`web/ui/src/hooks/useDashboard.ts`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并确认 `/ws/stream` 会推送 `market_top_spreads`，行情页在 WS 连接时自动更新。

- [2026-02-13] 下单页改为“选择后手动应用交易标的”，停机态指标统一显示 `--`
  - Why：修复“看起来已选中但启动按钮灰色”的误导，并避免引擎停止时 0 值被误认为实时信号。
  - Impact：`web/ui/src/pages/TradePage.tsx`。
  - Verify：`cd web/ui && npm run build`，确认点击“应用交易标的”后才可启动；引擎未运行时交易对指标显示 `--`。

- [2026-02-13] 降低 Top10 首次加载超时风险并加强零值提示
  - Why：修复下单页启动时偶发 `Top10 交易候选请求超时`，并解释 `Z-score` 全 0 常见于预热/盘口暂不可用。
  - Impact：`backend/arbbot/web/api.py`、`web/ui/src/api/client.ts`、`web/ui/src/pages/TradePage.tsx`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并确认下单页不再频繁出现 8s 超时，运行中若全 0 会出现提示文案。

- [2026-02-13] Top10 新增 Z-score 并按 `|Z-score|` 排序
  - Why：用户要求 Top10 展示并使用 Z-score 排序，避免仅按名义价差筛选导致“信号强弱”不可见。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/arbbot/web/api.py`、`backend/tests/test_market_scanner_zscore.py`、`web/ui/src/api/client.ts`、`web/ui/src/types.ts`、`web/ui/src/pages/MarketPage.tsx`、`web/ui/src/pages/TradePage.tsx`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并确认行情页 Top10 增加 `Z-score` 列且排序以 `|Z-score|` 为主。

- [2026-02-13] 下单页交易标的选择区改为稳定栅格，消除左右跳动
  - Why：修复下单页操作区“按钮一会左一会右”的布局抖动，提升操作稳定性。
  - Impact：`web/ui/src/pages/TradePage.tsx`、`web/ui/src/styles.css`。
  - Verify：`cd web/ui && npm run build`，并在下单页切换/刷新时确认交易标的操作区不再抖动。

- [2026-02-13] 下单页交易标的改为“分步选择/分步应用”并增加启动前一致性校验
  - Why：修复“选择和应用挤在一起看不出差异”的可用性问题，避免未应用新选择却按旧标的启动引擎。
  - Impact：`web/ui/src/pages/TradePage.tsx`、`web/ui/src/styles.css`。
  - Verify：`cd web/ui && npm run build`，并确认未完成“应用交易标的”时启动按钮禁用且有明确提示。

- [2026-02-13] Top 展示口径改为仅保留 `Z-score > 0`
  - Why：按用户要求屏蔽负向 Z-score 标的，避免进入展示与下单候选。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/tests/test_market_scanner_zscore.py`、`web/ui/src/api/client.ts`。
  - Verify：`python -m pytest backend/tests`，并确认 `/api/market/top-spreads` 与下单候选不再包含 `zscore <= 0`。

- [2026-02-13] 行情页与下单页合并为单页面，统一使用一个行情表
  - Why：按用户要求简化操作路径，减少跨页切换成本。
  - Impact：`web/ui/src/App.tsx`、`web/ui/src/pages/TradePage.tsx`、`web/ui/src/styles.css`。
  - Verify：`cd web/ui && npm run build`，并确认导航仅保留“行情/下单页面 + API 配置页面”，且单页包含下单操作与唯一行情表格。

- [2026-02-13] 候选范围从 Top10 改为全量可比币对
  - Why：用户要求显示全部币对，去除 Top10 截断与正向 Z-score 过滤。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/arbbot/web/api.py`、`backend/tests/test_api_trade_selection.py`、`backend/tests/test_api_market_top_spreads.py`、`web/ui/src/api/client.ts`、`web/ui/src/pages/TradePage.tsx`。
  - Verify：`python -m pytest backend/tests`，并确认 `/api/market/spreads` 与下单候选返回全量可比币对。

- [2026-02-13] 新增价差浮动速度指标（速度+波动率）
  - Why：用户需要衡量价差变化速度与潜在获利空间，避免只看静态价差。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/tests/test_market_scanner_zscore.py`、`web/ui/src/types.ts`、`web/ui/src/api/client.ts`、`web/ui/src/pages/TradePage.tsx`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并确认行情表展示“速度(%/分钟)”与“波动率(%)”。

- [2026-02-13] 新增本次运行绩效统计（盈亏/交易量/回撤/最大回撤）与两所余额仓位
  - Why：满足用户对策略收益质量与账户状态的实时观测诉求。
  - Impact：`backend/arbbot/strategy/performance_tracker.py`、`backend/arbbot/strategy/execution_engine.py`、`backend/arbbot/strategy/orchestrator.py`、`backend/arbbot/exchanges/base.py`、`backend/arbbot/exchanges/paradex_adapter.py`、`backend/arbbot/exchanges/grvt_adapter.py`、`backend/tests/test_performance_tracker.py`、`backend/tests/test_status_metrics.py`、`web/ui/src/types.ts`、`web/ui/src/api/client.ts`、`web/ui/src/pages/TradePage.tsx`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并确认 `/api/status` 包含 `performance/balances/positions_summary` 且前端总览卡片显示对应值。

- [2026-02-13] 修复行情/下单页桌面端比例失衡（左右列解耦）
  - Why：原布局在桌面端会出现左侧大面积空白、表格展示空间不足，观感为“比例不对”。
  - Impact：`web/ui/src/pages/TradePage.tsx`、`web/ui/src/styles.css`。
  - Verify：`cd web/ui && npm run build`，并在 `/trade` 验证“左列行情表 + 右列策略控制/仓位明细”比例稳定。

- [2026-02-13] 行情/下单页改为页面级紧凑密度（保留结构不重排）
  - Why：用户希望“一次搞定”并仅缩小空白与卡片/表格占用，不接受再次大幅重排布局。
  - Impact：`web/ui/src/pages/TradePage.tsx`、`web/ui/src/styles.css`。
  - Verify：`cd web/ui && npm run build`，并确认 `/trade` 在桌面端显示更紧凑、移动端仍保持单列可读。

- [2026-02-13] 交易页紧凑度再次提升为“肉眼可见”档
  - Why：上一版紧凑化反馈“不明显”，需在不改结构前提下进一步压缩顶部卡片与表格纵向占用。
  - Impact：`web/ui/src/styles.css`。
  - Verify：`cd web/ui && npm run build`，并确认 `/trade` 顶部指标卡在桌面端为 4 列、表格行高与控制区高度明显下降。

- [2026-02-13] 交易页布局改为全竖向单列
  - Why：用户明确要求“全部竖着来”，减少横向分栏与多列栅格。
  - Impact：`web/ui/src/styles.css`。
  - Verify：`cd web/ui && npm run build`，并确认 `/trade` 的指标卡、主区块、操作区与参数区均按单列纵向堆叠。

- [2026-02-13] 交易页改为并排窄版（顶部卡片多列 + 主区左右分栏）
  - Why：用户反馈单列过长，要求“并排展示、窄一点”。
  - Impact：`web/ui/src/styles.css`。
  - Verify：`cd web/ui && npm run build`，并确认 `/trade` 顶部卡片恢复多列、主区恢复左右并排，移动端仍为单列。

- [2026-02-13] 主内容区回调为竖排（行情表在上、策略控制在下）
  - Why：用户明确要求“这两个要竖着”，指“当前行情(单表)”与“策略控制”不要左右并排。
  - Impact：`web/ui/src/styles.css`。
  - Verify：`cd web/ui && npm run build`，并确认 `/trade` 中“当前行情(单表)”与“策略控制”上下堆叠显示。

- [2026-02-13] z-score 历史改为扫描器独立库并新增启动预热门禁
  - Why：`symbol_snapshots` 历史覆盖不足会导致部分币对长期 `zscore=0`，需改为“按币对持续积累历史 + 缺口自动补齐”。
  - Impact：`backend/arbbot/market/scanner.py`、`backend/arbbot/storage/repository.py`、`backend/arbbot/web/api.py`、`backend/arbbot/config.py`、`.env.example`、`web/ui/src/types.ts`、`web/ui/src/api/client.ts`、`web/ui/src/pages/TradePage.tsx`、`web/ui/src/pages/MarketPage.tsx`、`backend/tests/test_api_market_warmup.py`、`backend/tests/test_repository_market_history.py`、`backend/tests/test_market_scanner_zscore.py`。
  - Verify：`python -m pytest backend/tests`、`cd web/ui && npm run build`，并确认 `GET /api/market/top-spreads` 返回 `warmup_done/warmup_progress`，且 `zscore_ready=false` 时前端显示 `--`。

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
  - 已新增 `GET /api/market/top-spreads`，默认按全市场名义价差返回 Top10。
  - 前端已拆分为 `行情页面 / 下单页面 / API配置页面` 三路由，并保留深色主题切换。
  - API 配置页已支持凭证掩码状态与在线校验；行情页已移除回退杠杆输入并显示可执行价差口径。
- 下一步建议：
  - 为凭证接口增加鉴权（当前默认无鉴权）。
  - 将 FastAPI `on_event` 迁移到 lifespan，消除弃用警告。

## Known Issues
- 现象：测试日志出现 FastAPI `on_event` 弃用警告。
  - 原因：应用仍使用 `@app.on_event("startup"/"shutdown")`。
  - 修复：后续迁移至 lifespan handlers。
  - 验证：迁移后运行 `python -m pytest backend/tests`，警告应减少。
- 现象：`/api/market/top-spreads` 依赖 GRVT 私有凭证。
  - 原因：GRVT 最大杠杆仅可通过私有接口获取，已移除回退杠杆。
  - 修复：在 API 配置页保存 `grvt.api_key/private_key/trading_account_id`（扫描前会自动注入运行时）。
  - 验证：`GET /api/market/top-spreads` 返回 `rows` 且 `last_error` 为空。
