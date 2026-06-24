---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: dfa59edf71882ac3e29663828f688f4a_abd4619c6f7911f184585254007bceed
    ReservedCode1: n6ss+xz8iyJpsj3HNH12EzUFtcLo9tY2Efs9unQtfPHJSLYYQK5CDpc0lVQjSDf7mp5Feg5Z1TFOlcFW1F3CO+Rfuab2s3ArRpjC3AH3QRsMc5Ma4pXSll9aTqhJA+VThjKkaoRagqioGlB2WuOPEa1oqh7utF5eCHcEpyMYrkxkv2g2FBbOEHWiMHU=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: dfa59edf71882ac3e29663828f688f4a_abd4619c6f7911f184585254007bceed
    ReservedCode2: n6ss+xz8iyJpsj3HNH12EzUFtcLo9tY2Efs9unQtfPHJSLYYQK5CDpc0lVQjSDf7mp5Feg5Z1TFOlcFW1F3CO+Rfuab2s3ArRpjC3AH3QRsMc5Ma4pXSll9aTqhJA+VThjKkaoRagqioGlB2WuOPEa1oqh7utF5eCHcEpyMYrkxkv2g2FBbOEHWiMHU=
---

# Canopy · Nature-Tech Trading Terminal

轻量化加密量化交易软件 — Python + pywebview + CCXT。

## 架构总览

```
canopy/
├── main.py                      # 应用入口 + CanopyAPI (16 方法 JS-Python 桥)
├── config.py                    # 全局配置（交易所/数据路径/日志）
├── exchange/
│   └── ccxt_adapter.py          # CCXT 交易所适配器
├── data/
│   └── fetcher.py               # 数据获取 + Parquet 缓存
├── engine/
│   ├── base.py                  # 策略基类 (on_bar/signal)
│   ├── factory.py               # 策略工厂
│   ├── trend.py                 # 趋势跟踪策略
│   ├── grid.py                  # 网格交易策略
│   ├── arbitrage.py             # 套利策略
│   ├── momentum.py              # 动量策略
│   ├── mean_reversion.py        # 均值回归策略
│   ├── runner.py                # StrategyRunner (多线程管理)
│   ├── risk.py                  # RiskManager (6 步审批链+熔断器)
│   ├── executor.py              # OrderExecutor (订单执行队列)
│   ├── backtest_runner.py       # BacktestRunner (回测封装)
│   ├── fallback.py              # GBM 模拟数据生成
│   └── backtest/
│       ├── engine.py            # 回测引擎核心
│       └── metrics.py           # 绩效指标 (Sharpe/MaxDD/WinRate)
├── backtest/
│   └── cases/
│       └── crash_scenarios.py   # 极端行情案例库
└── web/
    └── index.html               # Nature-Tech Glass UI (4 色彩×2 模式)
```

## 交易链路

```
策略信号 → RiskManager.approve() → OrderExecutor.submit() → CCXT 下单 → 成交回调 → 更新持仓
                │
                ├─ 1.熔断检查  (CircuitBreaker)
                ├─ 2.日亏损上限 (max_daily_loss=5%)
                ├─ 3.回撤限制  (max_drawdown=15%)
                ├─ 4.信号有效期 (signal_ttl=60s)
                ├─ 5.仓位检查  (max_position_pct=5%)
                └─ 6.敞口检查  (max_total_exposure=80%)
                                   │
                              被拒 → 信号标记 REJECTED
```

## 风控配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_position_pct | 5% | 单币最大仓位 |
| max_total_exposure | 80% | 总敞口上限 |
| max_drawdown | 15% | 最大回撤 |
| max_daily_loss | 5% | 日亏损上限 |
| signal_ttl | 60s | 信号有效期 |
| circuit_breaker_cooldown | 300s | 熔断冷却时间 |

## CanopyAPI 方法 (16)

| # | 方法 | 说明 |
|---|------|------|
| 1 | connect_exchange(exchange_id) | 连接交易所，初始化 StrategyRunner |
| 2 | get_kpi() | 实时 KPI 数据 |
| 3 | get_ticker(symbol) | 实时行情 |
| 4 | get_strategies() | 策略状态+模拟 PnL |
| 5 | get_portfolio() | 持仓分布 |
| 6 | get_sentiment() | 市场情绪 |
| 7 | run_backtest(params) | 运行单策略回测 |
| 8 | compare_strategies(params) | 多策略对比回测 |
| 9 | get_backtest_result() | 获取最近回测结果 |
| 10 | get_status() | 完整系统状态 |
| 11 | start_strategies() | 启动所有策略 |
| 12 | stop_strategies() | 停止所有策略 |
| 13 | get_risk_status() | 风控状态 |
| 14 | get_orders(limit) | 订单历史 |
| 15 | reset_circuit_breaker() | 重置熔断器 |
| 16 | update_risk_config(params) | 更新风控参数 |

## 策略引擎 (5 种)

| 策略 | 文件 | 类型 |
|------|------|------|
| Trend Surf | trend.py | 趋势跟踪 |
| Grid Infinity | grid.py | 网格交易 |
| Arbitrage Nexus | arbitrage.py | 价差套利 |
| Volatility Harvester | momentum.py | 动量交易 |
| Mean Reversion v3 | mean_reversion.py | 均值回归 |

## 启动

```bash
cd /Users/cccc/Desktop/canopy
pip install -r requirements.txt
python canopy/main.py
```

## 技术栈

- **后端**: Python 3.x, CCXT, pandas, pywebview
- **前端**: Vanilla JS + Canvas, Nature-Tech Glass Design System (Emerald/Amber/Amethyst/Rose × Dark/Light)
- **数据**: Parquet 本地缓存
*（内容由AI生成，仅供参考）*
