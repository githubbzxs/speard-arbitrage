# 跨所价差套利系统（Paradex + GRVT）

这是一个可运行的跨交易所价差套利系统，核心目标：

- 支持 **Paradex + GRVT** 双所套利。
- 严格参考 `cross-exchange-arbitrage` 的模块化思路，并做增强。
- 支持动态开平仓（MA + Rolling Std）、分批开平仓、仓位再平衡。
- 提供 Web 风控与控制台。

## 核心特性

- 动态信号：基于 rolling mean / rolling std 的 z-score 开平仓。
- 双模式：
  - `normal_arb`：常规套利。
  - `zero_wear`：零磨损刷量模式（手动开关，自动参数执行）。
- 分批执行：按 z-score 强度分 1~3 批执行。
- 风控能力：
  - WS 活性监督与断连状态感知。
  - 订单簿新鲜度检查。
  - REST / WS 一致性校验。
  - 下单频率令牌桶限流。
  - 净仓偏差再平衡与硬阈值减仓。
- 存储：SQLite + CSV 双写。
- WebUI：行情页 / 下单页 / API 配置页分离，支持真实行情 Top10 名义价差看板。

## 项目结构

```text
backend/
  arbbot/
    config.py
    models.py
    exchanges/
    strategy/
    risk/
    storage/
    web/
    main.py
  tests/
  main.py
web/
  ui/
requirements.txt
.env.example
```

## 快速开始

### 1) 安装依赖

```bash
pip install -r requirements.txt
```

### 2) 配置环境变量

```bash
cp .env.example .env
```

策略交易可继续使用 `ARB_SYMBOLS` 指定的币对清单；
行情页会独立扫描两所可交易永续合约的交集，并展示名义价差 Top10。
如需自定义策略交易币对：

- 修改 `ARB_SYMBOLS` / `PARADEX_MARKETS` / `GRVT_MARKETS`
- 可选设置 `ARB_RECOMMENDED_LEVERAGES`（与币对顺序一一对应）

### 3) 启动后端

```bash
python backend/main.py
```

后端默认监听：`http://0.0.0.0:8000`

### 4) 启动前端

```bash
cd web/ui
npm install
npm run dev
```

前端默认：`http://localhost:5173`

## 线上部署（Linux + Nginx）

以下示例以单机部署为目标，假设项目目录为 `/opt/spread-arbitrage`，并使用 `systemd + nginx`。

### 1) 安装依赖并准备项目

```bash
cd /opt
git clone <your_repo_url> spread-arbitrage
cd /opt/spread-arbitrage

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，填入交易所 API 参数等配置
```

### 2) 构建前端静态文件

```bash
cd /opt/spread-arbitrage/web/ui
npm ci
npm run build
```

构建结果目录：`/opt/spread-arbitrage/web/ui/dist`

### 3) 配置并启动后端（systemd）

复制服务模板：

```bash
sudo cp /opt/spread-arbitrage/deploy/arbbot.service /etc/systemd/system/arbbot.service
```

创建环境变量文件（`EnvironmentFile`）：

```bash
sudo tee /etc/default/arbbot > /dev/null <<'EOF'
ARB_WEB_HOST=127.0.0.1
ARB_WEB_PORT=8000
ARB_WEB_LOG_LEVEL=info
ARB_SIMULATED_MARKET_DATA=false
ARB_LIVE_ORDER_ENABLED=false
ARB_ENABLE_LIVE_ORDER_CONFIRM_TEXT=ENABLE_LIVE_ORDER
PYTHONUNBUFFERED=1
EOF
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now arbbot
sudo systemctl status arbbot --no-pager
```

说明：若你使用虚拟环境，请把 `/etc/systemd/system/arbbot.service` 里的 `ExecStart` 改成虚拟环境 python 的绝对路径（例如 `/opt/spread-arbitrage/.venv/bin/python`）。

### 4) 配置并重载 Nginx

```bash
sudo cp /opt/spread-arbitrage/deploy/nginx.conf /etc/nginx/sites-available/arbbot.conf
sudo ln -sf /etc/nginx/sites-available/arbbot.conf /etc/nginx/sites-enabled/arbbot.conf
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t
sudo systemctl reload nginx
```

`deploy/nginx.conf` 已包含：

- 前端静态站点（`/`）
- 同域 API 反代（`/api/ -> 127.0.0.1:8000`）
- 同域 WebSocket 反代（`/ws/ -> 127.0.0.1:8000`）

### 5) 验证接口与页面连通性

```bash
# 后端直连
curl -i http://127.0.0.1:8000/api/status

# 经过 Nginx 反代
curl -i http://127.0.0.1/api/status

# 前端首页
curl -I http://127.0.0.1/
```

可选：验证 WebSocket（安装 `websocat` 后）：

```bash
websocat ws://127.0.0.1/ws/stream
```

### 6) 重部署（更新代码后）

```bash
cd /opt/spread-arbitrage
git pull

source .venv/bin/activate
pip install -r requirements.txt

cd /opt/spread-arbitrage/web/ui
npm ci
npm run build

sudo systemctl restart arbbot
sudo nginx -t && sudo systemctl reload nginx
curl -fsS http://127.0.0.1/api/status
```

### 前端环境变量（可选）

- `VITE_API_BASE_URL`：前端请求 API 的基地址。留空时默认走同域路径（例如 `/api/status`）。
- `VITE_WS_URL`：前端 WebSocket 地址。留空时自动推导为同域 `ws(s)://<host>/ws/stream`。

如果你需要跨域部署前后端，可在 `web/ui/.env.production` 配置后重新构建：

```bash
cat > /opt/spread-arbitrage/web/ui/.env.production <<'EOF'
VITE_API_BASE_URL=https://your-domain.example
VITE_WS_URL=wss://your-domain.example/ws/stream
EOF
```

### 故障排查（例如 `/api/status Failed to fetch`）

1. 检查后端服务是否正常：
   `sudo systemctl status arbbot --no-pager`  
   `sudo journalctl -u arbbot -n 200 --no-pager`
2. 检查后端监听地址与端口：
   `sudo ss -lntp | grep 8000`  
   确认监听值与 `/etc/default/arbbot` 中 `ARB_WEB_HOST/ARB_WEB_PORT` 一致。
3. 检查 Nginx 配置与日志：
   `sudo nginx -t`  
   `sudo tail -n 200 /var/log/nginx/error.log`
4. 检查前端构建环境变量：
   如果设置了 `VITE_API_BASE_URL` 或 `VITE_WS_URL`，确认地址可达且协议匹配（HTTPS 页面必须使用 `wss://`）。
5. 做最小链路验证：
   先保证 `curl http://127.0.0.1:8000/api/status` 正常，再检查 `curl http://127.0.0.1/api/status`。

## API 约定

- `GET /api/status`
- `GET /api/symbols`
- `GET /api/events?limit=100`
- `GET /api/market/top-spreads?limit=10&paradex_fallback_leverage=2&grvt_fallback_leverage=2&force_refresh=false`
- `POST /api/runtime/order-execution` body: `{ "live_order_enabled": boolean, "confirm_text"?: string }`
- `POST /api/runtime/market-data-mode` body: `{ "simulated_market_data": boolean }`
- `POST /api/engine/start`
- `POST /api/engine/stop`
- `POST /api/mode` body: `{ "mode": "normal_arb" | "zero_wear" }`
- `POST /api/symbol/{symbol}/params` body: `{ "params": { ... } }`
- `POST /api/symbol/{symbol}/flatten`
- `WS /ws/stream`

## 测试

```bash
python -m pytest backend/tests
python -m compileall backend
```

## 实盘提示

- 新版推荐使用双开关：
  - `ARB_SIMULATED_MARKET_DATA=false` 接入真实行情
  - `ARB_LIVE_ORDER_ENABLED=false` 先禁用下单，观察稳定后再在网页开启
- `ARB_DRY_RUN` 仍可兼容旧配置，但建议逐步迁移到双开关。
- 实盘前请确认交易所 API 权限、杠杆、最小下单量与精度。
- 名义价差使用 `|实际价差| × min(两所杠杆)` 计算，GRVT 若无公开杠杆字段则使用页面回退杠杆。
- 风控参数请按交易对波动分层配置，不要直接套默认值。
