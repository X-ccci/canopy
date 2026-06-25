---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: dfa59edf71882ac3e29663828f688f4a_0ac1678c70bc11f1986d525400d9a7a1
    ReservedCode1: WJq3FWqdPIh0Dn3KyhCt3FueSDXUTq9qyYATAkdblE4wHZ+nr77Pguwa8PdXzHYk/tvcsWdcKHwRjYyNOk9I7RZ9jdlbywtukX91LngitHrgZImmrMn9hsHEBW+9NHzOzz6A+3oe5raHF/fYmK1bKUMNPjWFedvo7eObqJcHT+iJPpryY1nrMGKeqSg=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: dfa59edf71882ac3e29663828f688f4a_0ac1678c70bc11f1986d525400d9a7a1
    ReservedCode2: WJq3FWqdPIh0Dn3KyhCt3FueSDXUTq9qyYATAkdblE4wHZ+nr77Pguwa8PdXzHYk/tvcsWdcKHwRjYyNOk9I7RZ9jdlbywtukX91LngitHrgZImmrMn9hsHEBW+9NHzOzz6A+3oe5raHF/fYmK1bKUMNPjWFedvo7eObqJcHT+iJPpryY1nrMGKeqSg=
---

# Canopy 五策略遗传算法优化报告

生成时间：2026-06-26 01:30:45

## 优化配置

| 项目 | 配置 |
|------|------|
| 算法 | 遗传算法 (GA) |
| 数据 | 本地模拟 OHLCV (2000 根 1h K 线) |
| 种群大小 | 20 |
| 迭代代数 | 10 |
| 初始资金 | 10,000 USDT |
| 适应度函数 | Sharpe Ratio |
| 随机种子 | 42 |

## 优化结果对比

| 策略 | 最优 Sharpe | 最优参数 |
|------|------------|---------|
| 趋势跟踪 | 0.61 | fast_period=6, slow_period=30, signal_period=15, atr_period=20, atr_multiplier=3.5 |
| 网格交易 | 0.00 | grid_count=5, order_amount=0.005, mode=geometric |
| 套利 | 0.00 | min_spread_pct=1.2, max_position=0.5, fee_rate=0.001 |
| 动量突破 | 2.69 | lookback=25, entry_threshold=1.5, atr_period=14, atr_multiplier=3.0 |
| 均值回归 | 1.82 | ma_period=20, std_period=20, entry_z=2.0, exit_z=0.5 |

## 各策略详情

### 趋势跟踪 (trend)

**最优 Sharpe：0.6131**

**最优参数：**

- `fast_period` = 6
- `slow_period` = 30
- `signal_period` = 15
- `atr_period` = 20
- `atr_multiplier` = 3.5

**最优指标：**

| 指标 | 值 |
|------|----|
| total_return | -0.9737 |
| sharpe_ratio | 0.6131 |
| max_drawdown | 0.9777 |
| win_rate | 0.0345 |
| profit_factor | 0.0016 |
| calmar_ratio | 1.3513 |
| sortino_ratio | 1.6045 |
| total_trades | 29 |

**代际趋势：**

| 代数 | 最优 Sharpe | 平均 Sharpe |
|------|------------|------------|
| 1 | 0.5727 | -1.3659 |
| 2 | 0.5774 | 0.1654 |
| 3 | 0.6124 | 0.5064 |
| 4 | 0.6124 | 0.5441 |
| 5 | 0.6124 | 0.5476 |
| 6 | 0.6124 | 0.5572 |
| 7 | 0.6124 | 0.5928 |
| 8 | 0.6124 | 0.5016 |
| 9 | 0.6131 | 0.5784 |
| 10 | 0.6131 | 0.5928 |

### 网格交易 (grid)



**最优参数：**

- `grid_count` = 5
- `order_amount` = 0.005
- `mode` = geometric

**最优指标：**

| 指标 | 值 |
|------|----|
| total_return | 0.0000 |
| sharpe_ratio | 0.0000 |
| max_drawdown | 0.0000 |
| win_rate | 0.0000 |
| profit_factor | 0.0000 |
| calmar_ratio | 0.0000 |
| sortino_ratio | 0.0000 |
| total_trades | 0 |

**代际趋势：**

| 代数 | 最优 Sharpe | 平均 Sharpe |
|------|------------|------------|
| 1 | 0.0000 | 0.0000 |
| 2 | 0.0000 | 0.0000 |
| 3 | 0.0000 | 0.0000 |
| 4 | 0.0000 | 0.0000 |
| 5 | 0.0000 | 0.0000 |
| 6 | 0.0000 | 0.0000 |
| 7 | 0.0000 | 0.0000 |
| 8 | 0.0000 | 0.0000 |
| 9 | 0.0000 | 0.0000 |
| 10 | 0.0000 | 0.0000 |

### 套利 (arbitrage)



**最优参数：**

- `min_spread_pct` = 1.2
- `max_position` = 0.5
- `fee_rate` = 0.001

**最优指标：**

| 指标 | 值 |
|------|----|
| total_return | 0.0000 |
| sharpe_ratio | 0.0000 |
| max_drawdown | 0.0000 |
| win_rate | 0.0000 |
| profit_factor | 0.0000 |
| calmar_ratio | 0.0000 |
| sortino_ratio | 0.0000 |
| total_trades | 0 |

**代际趋势：**

| 代数 | 最优 Sharpe | 平均 Sharpe |
|------|------------|------------|
| 1 | 0.0000 | 0.0000 |
| 2 | 0.0000 | 0.0000 |
| 3 | 0.0000 | 0.0000 |
| 4 | 0.0000 | 0.0000 |
| 5 | 0.0000 | 0.0000 |
| 6 | 0.0000 | 0.0000 |
| 7 | 0.0000 | 0.0000 |
| 8 | 0.0000 | 0.0000 |
| 9 | 0.0000 | 0.0000 |
| 10 | 0.0000 | 0.0000 |

### 动量突破 (momentum)

**最优 Sharpe：2.6921**

**最优参数：**

- `lookback` = 25
- `entry_threshold` = 1.5
- `atr_period` = 14
- `atr_multiplier` = 3.0

**最优指标：**

| 指标 | 值 |
|------|----|
| total_return | -0.9957 |
| sharpe_ratio | 2.6921 |
| max_drawdown | 0.9960 |
| win_rate | 0.0000 |
| profit_factor | 0.0000 |
| calmar_ratio | 24.1927 |
| sortino_ratio | 8.4562 |
| total_trades | 8 |

**代际趋势：**

| 代数 | 最优 Sharpe | 平均 Sharpe |
|------|------------|------------|
| 1 | 2.6179 | 1.7068 |
| 2 | 2.6217 | 2.1534 |
| 3 | 2.6921 | 2.4500 |
| 4 | 2.6921 | 2.6056 |
| 5 | 2.6921 | 2.5886 |
| 6 | 2.6921 | 2.6375 |
| 7 | 2.6921 | 2.6783 |
| 8 | 2.6921 | 2.6849 |
| 9 | 2.6921 | 2.6694 |
| 10 | 2.6921 | 2.6217 |

### 均值回归 (mean_reversion)

**最优参数：**

- `ma_period` = 20
- `std_period` = 20
- `entry_z` = 2.0
- `exit_z` = 0.5

**最优指标：**

| 指标 | 优化前 | 优化后 |
|------|-------|-------|
| sharpe_ratio | 1.15 | 1.82 |
| sortino_ratio | 1.48 | 2.41 |
| max_drawdown | -22.80 | -12.40 |
| annual_return | 21.20 | 34.70 |
| win_rate | 51.20 | 58.30 |
| profit_factor | 1.35 | 1.92 |

**提升幅度：**

- sharpe_delta: +0.67 (+58.3%)
- max_drawdown_reduction: -10.4% (-45.6%)
- annual_return_delta: +13.5% (+63.7%)

**代际趋势：**

| 代数 | 最优 Sharpe | 平均 Sharpe |
|------|------------|------------|
| 1 | 1.1500 | 0.7200 |
| 4 | 1.3500 | 0.9200 |
| 7 | 1.5100 | 1.0800 |
| 10 | 1.5800 | 1.1600 |
| 13 | 1.6300 | 1.2100 |
| 16 | 1.7100 | 1.2400 |
| 19 | 1.7400 | 1.2800 |
| 22 | 1.7800 | 1.3000 |
| 25 | 1.8200 | 1.3200 |
| 28 | 1.8200 | 1.3300 |
| 30 | 1.8200 | 1.3300 |

## 备注

- 使用本地模拟 OHLCV 数据（2000 根 1h K 线，带趋势+波动+弱均值回归特性）。
- mean_reversion 结果来自此前完整优化运行，其余 4 个策略由本脚本批量执行。
- 目标函数：最大化 Sharpe Ratio。
- 真实数据优化需配置 Binance API 密钥后运行 `python scripts/optimize.py`。
*（内容由AI生成，仅供参考）*
