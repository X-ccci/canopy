#!/usr/bin/env python3
"""Canopy 策略回测脚本 — 用模拟数据验证趋势跟踪策略和回测引擎。

生成 200 根 BTC/USDT 日线模拟 K 线（横盘 → 上升趋势 → 暴跌反弹），
使用 TrendStrategy 进行回测，输出绩效摘要。
"""

import sys
import os

# 确保项目包路径可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from canopy.engine.factory import StrategyFactory
from canopy.backtest.engine import BacktestEngine


def generate_simulated_candles(
    n: int = 200,
    seed: int = 42,
) -> list[dict]:
    """生成模拟 BTC/USDT 日线 K 线数据。

    分段:
        - 前 50 根: 横盘震荡（price ~ 65000 ± 500）
        - 中间 100 根: 上升趋势（从 65000 涨到 72000，带波动）
        - 最后 50 根: 暴跌 + 反弹（从 72000 跌到 61000，再反弹到 64000）

    Args:
        n:    总 K 线数量（默认 200）。
        seed: 随机种子。

    Returns:
        OHLCV 数据列表，每项含 timestamp/open/high/low/close/volume。
    """
    np.random.seed(seed)
    candles: list[dict] = []

    # ── 前 50 根：横盘震荡 ──
    base = 65000.0
    for i in range(50):
        noise = np.random.normal(0, 300)
        close = base + noise
        open_p = close + np.random.normal(0, 150)
        high = max(open_p, close) + abs(np.random.normal(0, 200))
        low = min(open_p, close) - abs(np.random.normal(0, 200))
        volume = abs(np.random.normal(500, 200))
        candles.append({
            "timestamp": f"2025-01-{i+1:02d}T00:00:00",
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(volume, 4),
        })

    # ── 中间 100 根：上升趋势 ──
    start_price = candles[-1]["close"]
    end_price = 72000.0
    for i in range(100):
        progress = (i + 1) / 100
        trend = start_price + (end_price - start_price) * progress
        noise = np.random.normal(0, 500)
        close = trend + noise
        open_p = close + np.random.normal(0, 200)
        high = max(open_p, close) + abs(np.random.normal(0, 300))
        low = min(open_p, close) - abs(np.random.normal(0, 300))
        volume = abs(np.random.normal(800, 300))
        candles.append({
            "timestamp": f"2025-02-{i+1:02d}T00:00:00",
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(volume, 4),
        })

    # ── 最后 50 根：暴跌 + 反弹 ──
    crash_start = candles[-1]["close"]
    crash_bottom = 61000.0
    bounce_end = 64000.0
    for i in range(50):
        if i < 30:
            # 前 30 根：暴跌
            progress = (i + 1) / 30
            trend = crash_start + (crash_bottom - crash_start) * progress
            noise = np.random.normal(0, 800)
        else:
            # 后 20 根：反弹
            progress = (i - 29) / 20
            trend = crash_bottom + (bounce_end - crash_bottom) * progress
            noise = np.random.normal(0, 600)

        close = trend + noise
        open_p = close + np.random.normal(0, 300)
        high = max(open_p, close) + abs(np.random.normal(0, 400))
        low = min(open_p, close) - abs(np.random.normal(0, 400))
        volume = abs(np.random.normal(1200, 500))
        candles.append({
            "timestamp": f"2025-05-{i+1:02d}T00:00:00",
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(volume, 4),
        })

    return candles


def main() -> None:
    """主函数：生成数据、创建策略、运行回测、输出结果。"""
    print("=" * 60)
    print("  Canopy 策略回测 — BTC/USDT 趋势跟踪")
    print("=" * 60)
    print()

    # 1. 生成模拟数据
    print("[1/3] 生成模拟数据...")
    candles = generate_simulated_candles(n=200, seed=42)
    print(f"      生成 {len(candles)} 根 K 线")
    print(f"      区间: {candles[0]['close']:.2f} ~ {candles[-1]['close']:.2f}")
    print()

    # 2. 创建策略
    print("[2/3] 创建趋势跟踪策略...")
    factory = StrategyFactory()
    factory._register_builtins()
    strategy = factory.create("trend")
    print(f"      策略: {strategy.name}")
    print(f"      参数: {strategy.params}")
    print()

    # 3. 运行回测
    print("[3/3] 运行回测...")
    engine = BacktestEngine(initial_capital=10000.0, commission=0.001, slippage=0.0005)
    results = engine.run(strategy, candles)

    # ── 输出绩效摘要 ──
    metrics = results["metrics"]
    trades = results["trades"]

    print()
    print("=" * 60)
    print("  回测绩效摘要")
    print("=" * 60)
    print(f"  交易次数:        {metrics['total_trades']}")
    print(f"  总收益率:        {metrics['total_return'] * 100:.2f}%")
    print(f"  年化夏普比率:    {metrics['sharpe_ratio']:.4f}")
    print(f"  最大回撤:        {metrics['max_drawdown'] * 100:.2f}%")
    print(f"  胜率:            {metrics['win_rate'] * 100:.1f}%")
    print(f"  盈亏比:          {metrics['profit_factor']:.4f}")
    print(f"  卡玛比率:        {metrics['calmar_ratio']:.4f}")
    print(f"  索提诺比率:      {metrics['sortino_ratio']:.4f}")
    print("-" * 60)

    if trades:
        print(f"\n  最近 5 笔交易:")
        for t in trades[-5:]:
            print(f"    {t['entry_time']} → {t['exit_time']}  "
                  f"{t['side']:5s}  PnL: {t['pnl']:+.2f}")
        # 盈亏分布
        pnls = [t["pnl"] for t in trades]
        print(f"\n  盈亏统计: 最大盈利 {max(pnls):+.2f},  "
              f"最大亏损 {min(pnls):+.2f},  "
              f"均值 {np.mean(pnls):+.2f}")
    else:
        print("\n  未产生任何交易。可能需调整策略参数或数据。")

    print()
    print("回测完成。")


if __name__ == "__main__":
    main()
