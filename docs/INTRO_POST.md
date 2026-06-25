---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: dfa59edf71882ac3e29663828f688f4a_12a144f4707111f1986d525400d9a7a1
    ReservedCode1: UQfkvW02bgg2RQpalDpusWTzI97bH/dnHVaCxBB8VfydxfuRTaijZu8lx4wtKf8VmWySLn5Q6c+I3zQ8WrCNIc1iUrpUVPOW7TshI+7u+0pORME5xkFySPIlH86Ev0nEwPZgM/TaLQI0crFiNq5vtiIpOpqVCBKmfCIVX2psjve6x1AtfkynDBKH/XE=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: dfa59edf71882ac3e29663828f688f4a_12a144f4707111f1986d525400d9a7a1
    ReservedCode2: UQfkvW02bgg2RQpalDpusWTzI97bH/dnHVaCxBB8VfydxfuRTaijZu8lx4wtKf8VmWySLn5Q6c+I3zQ8WrCNIc1iUrpUVPOW7TshI+7u+0pORME5xkFySPIlH86Ev0nEwPZgM/TaLQI0crFiNq5vtiIpOpqVCBKmfCIVX2psjve6x1AtfkynDBKH/XE=
---

# Canopy: Nature-Tech Autonomous Trading Terminal

> A biomimetic multi-strategy trading terminal blending forest-inspired UI with production-grade crypto automation.

---

## Project Highlights

Canopy 是一个以"自然科技"（Nature-Tech）为设计哲学的自动交易终端。它不只是一套策略框架——它是森林美学与量化交易的深度耦合。

- **Nature-Tech Glass UI** — 四种生物群落主题（Emerald Canopy / Amber Geo / Crystal Amethyst / Coral Bloom），Spring Bounce 弹性动画，萤火粒子背景，有机玻璃态仪表盘
- **5 大策略引擎** — Mean Reversion v3、Grid Infinity、Trend Surf、Arbitrage Nexus、Volatility Harvester，全部以 WebSocket 实时行情驱动
- **全链路风控** — RiskManager 包含仓位敞口限制、最大回撤熔断、信号审批流水线
- **真实回测** — 基于 OHLCV 历史数据，输出 Sharpe / Sortino / Calmar / Profit Factor 等多项绩效指标
- **WebSocket 实时推送** — ticker、kline 两级 WS 订阅，延迟 < 100ms
- **双端应用** — pywebview 桌面端 + FastAPI 网页端，一套代码双环境运行
- **SQLite 持久化** — 全量信号、风控决策、模拟订单写入本地数据库

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Exchange** | CCXT — Binance Testnet (sandbox) |
| **Strategy Engine** | Python 3.11+ |
| **Risk Management** | Custom RiskManager + Circuit Breaker |
| **Backend** | FastAPI + Uvicorn + WebSocket |
| **Desktop** | PyQt6 / pywebview |
| **Frontend** | Vanilla JS + Chart.js + Nature-Tech CSS |
| **Data** | SQLite + Pandas + NumPy |
| **DevOps** | Makefile + Vault (encrypted keys) |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/your-org/canopy.git
cd canopy

# 2. Install dependencies
pip install -r requirements.txt

# 3. Get Binance Testnet API Key
#    Visit https://testnet.binance.vision/ → GitHub login → API Management

# 4. Dry-run (5 minutes, no real orders)
python scripts/go_live.py --dry-run --duration 300

# 5. Launch web dashboard
python -m canopy.web.server --port 8080
#    Open http://localhost:8080
```

---

## Strategy Overview

| # | Strategy | Type | Timeframe | Description |
|---|----------|------|-----------|-------------|
| 1 | **Mean Reversion v3** | 均值回归 | 1h | 布林带 + RSI 双确认反转信号 |
| 2 | **Grid Infinity** | 网格交易 | 1h | 价格区间网格挂单，震荡市自动收割 |
| 3 | **Trend Surf** | 趋势跟踪 | 1h | EMA 金叉死叉 + ADX 趋势强度过滤 |
| 4 | **Arbitrage Nexus** | 套利 | 1h | 跨交易所/跨交易对价差监测 |
| 5 | **Volatility Harvester** | 动量突破 | 1h | ATR 波动率通道 + 成交量确认 |

---

## Architecture

```
┌─────────────┐    WebSocket    ┌──────────────────┐
│  Binance    │ ◄──────────────► │  Strategy Runner  │
│  Testnet    │    ticker/kline │  (5 strategies)   │
└─────────────┘                 └────────┬─────────┘
                                         │ signal
                                ┌────────▼─────────┐
                                │   RiskManager     │
                                │   + Circuit Breaker│
                                └────────┬─────────┘
                                         │ approved
                                ┌────────▼─────────┐
                                │  OrderExecutor    │
                                │  (Live/DryRun)    │
                                └────────┬─────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
             ┌──────────┐        ┌──────────┐        ┌──────────┐
             │  SQLite  │        │ FastAPI  │        │ PyQt6    │
             │  (orders)│        │  /api/*  │        │ Desktop  │
             └──────────┘        └────┬─────┘        └──────────┘
                                      │
                              ┌───────▼───────┐
                              │ Nature-Tech   │
                              │ Web Dashboard │
                              └───────────────┘
```

---

## Screenshots

*(Dashboard preview — four bioluminescent themes, real-time KPI pods, strategy table, portfolio donut chart, market sentiment gauge)*

---

## Links

- **GitHub**: [github.com/your-org/canopy](https://github.com/your-org/canopy)
- **Binance Testnet**: [testnet.binance.vision](https://testnet.binance.vision/)

---

*Built with care in the forest. Nature meets technology.*
*（内容由AI生成，仅供参考）*
