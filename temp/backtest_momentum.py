#!/usr/bin/env python3
"""Canopy 动量策略回测 — 验证最优 Sharpe 2.69 在历史数据上的真实表现

用模拟 BTC/USDT 1H K 线数据（800 根）跑 MomentumStrategy 回测。
参数: lookback=25, entry_threshold=1.5, atr_period=14, atr_multiplier=3.0
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from canopy.backtest.engine import BacktestEngine
from canopy.engine.factory import StrategyFactory


def generate_hourly_candles(n: int = 800, seed: int = 42) -> list[dict]:
    """生成模拟 BTC/USDT 1H K 线数据，包含趋势、震荡、暴跌等市场状态。"""
    np.random.seed(seed)
    candles = []
    base = 65000.0
    for i in range(n):
        if i < 200:
            trend = base + np.random.normal(0, 200)
        elif i < 400:
            trend = base + (i - 200) * 15 + np.random.normal(0, 300)
        elif i < 550:
            trend = 68000 + (i - 400) * 3 + np.random.normal(0, 250)
        elif i < 700:
            trend = 68450 - (i - 550) * 40 + np.random.normal(0, 500)
        else:
            trend = 62450 + (i - 700) * 25 + np.random.normal(0, 350)

        close = max(trend, 100)
        open_p = close + np.random.normal(0, 100)
        high = max(open_p, close) + abs(np.random.normal(0, 150))
        low = min(open_p, close) - abs(np.random.normal(0, 150))
        volume = abs(np.random.normal(300, 100))
        hour = i % 24
        day = i // 24 + 1
        candles.append({
            "timestamp": f"2025-01-{day:02d}T{hour:02d}:00:00",
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(volume, 4),
        })
    return candles


def main():
    print("=" * 64)
    print("  Canopy 动量策略回测 — BTC/USDT 1H")
    print("=" * 64)
    print(f"  参数: lookback=25, entry_threshold=1.5, atr_period=14, atr_multiplier=3.0")
    print()

    # 1. 生成模拟数据
    print("[1/3] 生成模拟 1H K 线数据...")
    candles = generate_hourly_candles(n=800, seed=42)
    print(f"      生成 {len(candles)} 根小时 K 线")
    print(f"      区间: {candles[0]['close']:.2f} ~ {candles[-1]['close']:.2f}")
    print()

    # 2. 创建动量策略
    print("[2/3] 创建动量策略...")
    factory = StrategyFactory()
    factory._register_builtins()
    strategy = factory.create("momentum")
    strategy.params["lookback"] = 25
    strategy.params["entry_threshold"] = 1.5
    strategy.params["atr_period"] = 14
    strategy.params["atr_multiplier"] = 3.0
    print(f"      策略: {strategy.name}")
    print(f"      参数: {strategy.params}")
    print()

    # 3. 运行回测
    print("[3/3] 运行回测...")
    engine = BacktestEngine(initial_capital=10000.0, commission=0.001, slippage=0.0005)
    results = engine.run(strategy, candles)

    metrics = results["metrics"]
    trades = results["trades"]

    print()
    print("=" * 64)
    print("  动量策略回测绩效摘要")
    print("=" * 64)
    print(f"  交易次数:        {metrics['total_trades']}")
    print(f"  总收益率:        {metrics['total_return'] * 100:.2f}%")
    print(f"  年化夏普比率:    {metrics['sharpe_ratio']:.4f}")
    print(f"  最大回撤:        {metrics['max_drawdown'] * 100:.2f}%")
    print(f"  胜率:            {metrics['win_rate'] * 100:.1f}%")
    print(f"  盈亏比:          {metrics['profit_factor']:.4f}")
    print(f"  卡玛比率:        {metrics['calmar_ratio']:.4f}")
    print(f"  索提诺比率:      {metrics['sortino_ratio']:.4f}")
    print("-" * 64)

    if trades:
        print(f"\n  最近 5 笔交易:")
        for t in trades[-5:]:
            print(f"    {t['entry_time']} → {t['exit_time']}  "
                  f"{t['side']:5s}  PnL: {t['pnl']:+.2f}")
        pnls = [t["pnl"] for t in trades]
        print(f"\n  盈亏统计: 最大盈利 {max(pnls):+.2f},  "
              f"最大亏损 {min(pnls):+.2f},  "
              f"均值 {np.mean(pnls):+.2f}")
    else:
        print("\n  未产生任何交易。")

    print()
    print("回测完成。")
    return metrics, trades


if __name__ == "__main__":
    main()
