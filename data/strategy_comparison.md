# Canopy 5 策略横向对比报告

**数据**: BTC/USDT 1h K 线
**时间范围**: 2026-05-15 06:00:00 ~ 2026-06-25 21:00:00
**K 线条数**: 1000
**初始资金**: $10,000

## 绩效总览

| 策略 | 最终权益 | 总收益率 | 最大回撤 | Sharpe | Sortino | Calmar | 胜率 | 盈亏比 | 交易次数 |
|------|---------|---------|---------|--------|---------|--------|------|--------|---------|
| trend | $10,514.83 | +5.15% | 5.55% | 0.37 | 0.51 | 0.93 | 28.6% | 1.44 | 35 |
| grid | $10,000.00 | +0.00% | 0.00% | 0.00 | 0.00 | 0.00 | 0.0% | 0.00 | 0 |
| arbitrage | $10,000.00 | +0.00% | 0.00% | 0.00 | 0.00 | 0.00 | 0.0% | 0.00 | 0 |
| momentum | $9,658.40 | -3.42% | 5.66% | -0.46 | -0.54 | -0.60 | 0.0% | 0.00 | 3 |
| mean_reversion | $11,722.18 | +17.22% | 5.86% | 1.05 | 1.74 | 2.94 | 53.9% | 2.18 | 78 |

## 最佳策略
- **最高收益**: mean_reversion (+17.22%)
- **最高 Sharpe**: mean_reversion (1.05)
- **最小回撤**: grid (0.00%)

## 各策略参数

### trend
```
  fast_period: 6
  slow_period: 30
  signal_period: 15
  atr_period: 20
  atr_multiplier: 3.5
```

### grid
```
  grid_count: 5
  order_amount: 0.005
  mode: geometric
```

### arbitrage
```
  min_spread_pct: 1.2
  max_position: 0.5
  fee_rate: 0.001
```

### momentum
```
  lookback: 25
  entry_threshold: 1.5
  atr_period: 14
  atr_multiplier: 3.0
```

### mean_reversion
```
  ma_period: 20
  std_period: 20
  entry_z: 2.0
  exit_z: 0.5
```
