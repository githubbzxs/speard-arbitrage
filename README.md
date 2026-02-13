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
- WebUI：实时状态、事件日志、参数热更新、一键平仓。

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

## API 约定

- `GET /api/status`
- `GET /api/symbols`
- `GET /api/events?limit=100`
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

- 首次建议 `ARB_DRY_RUN=true` 做联调。
- 实盘前请确认交易所 API 权限、杠杆、最小下单量与精度。
- 风控参数请按交易对波动分层配置，不要直接套默认值。
