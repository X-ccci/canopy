"""
strategy_comparison.py — 5 策略横向对比，使用真实历史数据（BTC/USDT 1h）。

用法:
    python scripts/strategy_comparison.py

输出:
    data/strategy_comparison.md
"""

import sys
from pathlib import Path

import pandas as pd

# 确保项目根目录在 path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canopy.engine.backtest.engine import BacktestEngine
from canopy.engine.backtest.metrics import PerformanceMetrics

# ── 最优参数（来自历史优化结果）──
OPTIMAL_PARAMS = {
    "trend": {
        "fast_period": 6, "slow_period": 30, "signal_period": 15,
        "atr_period": 20, "atr_multiplier": 3.5,
    },
    "grid": {
        "grid_count": 5, "order_amount": 0.005, "mode": "geometric",
    },
    "arbitrage": {
        "min_spread_pct": 1.2, "max_position": 0.5, "fee_rate": 0.001,
    },
    "momentum": {
        "lookback": 25, "entry_threshold": 1.5,
        "atr_period": 14, "atr_multiplier": 3.0,
    },
    "mean_reversion": {
        "ma_period": 20, "std_period": 20, "entry_z": 2.0, "exit_z": 0.5,
    },
}

SYMBOL = "BTC/USDT"
CACHE_PATH = Path("/Users/cccc/Desktop/canopy/data/cache/BTC_USDT_1h.parquet")
OUTPUT_PATH = Path("/Users/cccc/Desktop/canopy/data/strategy_comparison.md")
INITIAL_CAPITAL = 10000.0


def load_data() -> pd.DataFrame:
    df = pd.read_parquet(CACHE_PATH)
    # 确保列类型正确
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


def run_one(strategy_type: str, df: pd.DataFrame, params: dict) -> dict:
    engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
    result = engine.run(strategy_type, df, params)
    metrics = PerformanceMetrics(result.equity_curve, result.trades)
    perf = metrics.calculate_all()
    return {
        "strategy": strategy_type,
        "final_equity": round(result.final_equity, 2),
        "total_return_pct": round(perf.get("total_return", 0) * 100, 2),
        "max_drawdown_pct": round(perf.get("max_drawdown", 0) * 100, 2),
        "sharpe_ratio": round(perf.get("sharpe_ratio", 0), 2),
        "sortino_ratio": round(perf.get("sortino_ratio", 0), 2),
        "calmar_ratio": round(perf.get("calmar_ratio", 0), 2),
        "win_rate": round(perf.get("win_rate", 0) * 100, 2),
        "profit_factor": round(perf.get("profit_factor", 0), 2),
        "total_trades": perf.get("total_trades", 0),
    }


def generate_markdown(results: list[dict], df: pd.DataFrame) -> str:
    date_range = f"{df['timestamp'].min()} ~ {df['timestamp'].max()}"
    n_bars = len(df)

    lines = [
        "# Canopy 5 策略横向对比报告",
        "",
        f"**数据**: {SYMBOL} 1h K 线",
        f"**时间范围**: {date_range}",
        f"**K 线条数**: {n_bars}",
        f"**初始资金**: ${INITIAL_CAPITAL:,.0f}",
        "",
        "## 绩效总览",
        "",
        "| 策略 | 最终权益 | 总收益率 | 最大回撤 | Sharpe | Sortino | Calmar | 胜率 | 盈亏比 | 交易次数 |",
        "|------|---------|---------|---------|--------|---------|--------|------|--------|---------|",
    ]

    for r in results:
        lines.append(
            f"| {r['strategy']} | ${r['final_equity']:,.2f} | {r['total_return_pct']:+.2f}% "
            f"| {r['max_drawdown_pct']:.2f}% | {r['sharpe_ratio']:.2f} "
            f"| {r['sortino_ratio']:.2f} | {r['calmar_ratio']:.2f} "
            f"| {r['win_rate']:.1f}% | {r['profit_factor']:.2f} "
            f"| {r['total_trades']} |"
        )

    # 排序找出最佳
    lines.append("")
    lines.append("## 最佳策略")
    best_return = max(results, key=lambda x: x["total_return_pct"])
    best_sharpe = max(results, key=lambda x: x["sharpe_ratio"])
    best_drawdown = min(results, key=lambda x: x["max_drawdown_pct"])
    lines.append(f"- **最高收益**: {best_return['strategy']} ({best_return['total_return_pct']:+.2f}%)")
    lines.append(f"- **最高 Sharpe**: {best_sharpe['strategy']} ({best_sharpe['sharpe_ratio']:.2f})")
    lines.append(f"- **最小回撤**: {best_drawdown['strategy']} ({best_drawdown['max_drawdown_pct']:.2f}%)")

    lines.append("")
    lines.append("## 各策略参数")
    lines.append("")
    for r in results:
        params = OPTIMAL_PARAMS.get(r["strategy"], {})
        lines.append(f"### {r['strategy']}")
        lines.append("```")
        for k, v in params.items():
            lines.append(f"  {k}: {v}")
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def main():
    print(f"加载数据: {CACHE_PATH}")
    df = load_data()
    print(f"数据范围: {df['timestamp'].min()} ~ {df['timestamp'].max()} ({len(df)} 条)")

    strategies = ["trend", "grid", "arbitrage", "momentum", "mean_reversion"]
    results = []

    for stype in strategies:
        params = OPTIMAL_PARAMS.get(stype, {})
        print(f"回测 {stype} ...", end=" ", flush=True)
        try:
            r = run_one(stype, df, params)
            results.append(r)
            print(f"收益 {r['total_return_pct']:+.2f}%, Sharpe {r['sharpe_ratio']:.2f}")
        except Exception as e:
            print(f"失败: {e}")

    md = generate_markdown(results, df)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(md, encoding="utf-8")
    print(f"\n报告已生成: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
