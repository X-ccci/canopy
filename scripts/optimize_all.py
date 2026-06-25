#!/usr/bin/env python
"""Canopy 五策略全员遗传优化 — 批量执行脚本。

使用本地模拟 OHLCV 数据对各策略执行遗传算法优化，
mean_reversion 重用已有 optimize_result.json。

输出：data/optimization_report.md（对比报告）
      data/optimize_<strategy>.json（各策略原始结果）
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import sys
import time
from datetime import datetime

# macOS 默认使用 spawn，但 GA 的 ProcessPoolExecutor 需要 fork 以避免
# "attempt to start a new process before bootstrapping" 错误
try:
    multiprocessing.set_start_method("fork")
except RuntimeError:
    pass  # 已设置

import numpy as np

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from canopy.optimizer.genetic import GeneticOptimizer  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("optimize_all")

_DATA_DIR = os.path.join(_PROJ_ROOT, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

# ── 模拟 OHLCV 数据（BTC/USDT 风格，2000 根 1h K 线） ──

def generate_mock_candles(n: int = 2000, seed: int = 42) -> list[dict]:
    """生成带趋势+波动+周期的模拟 OHLCV 数据。"""
    rng = np.random.default_rng(seed)
    base_price = 60000.0
    prices = np.empty(n)
    prices[0] = base_price

    # 带趋势和均值回归的随机游走
    mu = 0.0001
    sigma = 0.012
    for i in range(1, n):
        # 加入弱均值回归
        drift = mu - 0.00005 * (prices[i - 1] - base_price) / base_price
        eps = rng.normal(drift, sigma)
        prices[i] = prices[i - 1] * (1 + max(-0.15, min(0.15, eps)))

    candles = []
    for i in range(n):
        close = max(prices[i], 1.0)
        high = close * (1 + abs(rng.normal(0, 0.005)))
        low = close * (1 - abs(rng.normal(0, 0.005)))
        open_price = close * (1 + rng.normal(0, 0.003))
        volume = max(rng.lognormal(4, 1), 1.0)

        candles.append({
            "timestamp": f"2026-{(i // 720 + 1):02d}-{(i % 30 + 1):02d}T{(i % 24):02d}:00:00",
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(volume, 2),
        })

    return candles


# ── 策略参数空间（根据实际策略参数定义） ──

STRATEGY_CONFIGS = [
    {
        "name": "trend",
        "label": "趋势跟踪",
        "param_space": {
            "fast_period": [6, 8, 10, 12, 16, 20],
            "slow_period": [20, 24, 26, 30, 34, 40],
            "signal_period": [6, 9, 12, 15],
            "atr_period": [10, 14, 20],
            "atr_multiplier": [1.5, 2.0, 2.5, 3.0, 3.5],
        },
    },
    {
        "name": "grid",
        "label": "网格交易",
        "param_space": {
            "grid_count": [5, 8, 10, 15, 20],
            "order_amount": [0.005, 0.01, 0.02, 0.05],
            "mode": ["arithmetic", "geometric"],
        },
    },
    {
        "name": "arbitrage",
        "label": "套利",
        "param_space": {
            "min_spread_pct": [0.15, 0.25, 0.4, 0.6, 0.8, 1.2],
            "max_position": [0.5, 1.0, 2.0, 5.0],
            "fee_rate": [0.001, 0.002, 0.003, 0.005],
        },
    },
    {
        "name": "momentum",
        "label": "动量突破",
        "param_space": {
            "lookback": [10, 15, 20, 25, 30, 40],
            "entry_threshold": [0.3, 0.6, 0.8, 1.0, 1.5],
            "atr_period": [10, 14, 20],
            "atr_multiplier": [1.5, 2.0, 2.5, 3.0],
        },
    },
]

MEAN_REVERSION_RESULT = os.path.join(_PROJ_ROOT, "optimize_result.json")


def load_mean_reversion() -> dict | None:
    """加载已有的 mean_reversion 优化结果。"""
    if not os.path.exists(MEAN_REVERSION_RESULT):
        logger.warning("未找到 %s，跳过 mean_reversion", MEAN_REVERSION_RESULT)
        return None
    with open(MEAN_REVERSION_RESULT) as f:
        return json.load(f)


def run_genetic_optimization(strategy_name: str, param_space: dict,
                              candles: list[dict]) -> dict | None:
    """执行遗传算法优化。"""
    logger.info("=" * 55)
    logger.info("遗传算法优化: %s", strategy_name)
    logger.info("参数空间: %s", json.dumps({k: v for k, v in param_space.items()}))
    logger.info("=" * 55)

    try:
        optimizer = GeneticOptimizer(
            strategy_name=strategy_name,
            param_space=param_space,
            candles=candles,
            engine_kwargs={"initial_capital": 10000.0},
            pop_size=20,
            generations=10,
            max_workers=2,
            random_seed=42,
        )
        result = optimizer.run()
        optimizer.print_summary()
        return result
    except Exception as e:
        logger.error("优化失败: %s", e)
        import traceback
        traceback.print_exc()
        return None


def extract_best(result: dict | None) -> dict:
    """提取最优个体。"""
    if not result:
        return {}
    final_pop = result.get("final_population", [])
    if not final_pop:
        return {}
    return max(final_pop, key=lambda x: x.get("fitness", float("-inf")))


def generate_report(all_results: dict[str, dict]) -> str:
    """生成 Markdown 对比报告。"""
    lines = [
        "# Canopy 五策略遗传算法优化报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 优化配置",
        "",
        "| 项目 | 配置 |",
        "|------|------|",
        "| 算法 | 遗传算法 (GA) |",
        "| 数据 | 本地模拟 OHLCV (2000 根 1h K 线) |",
        "| 种群大小 | 20 |",
        "| 迭代代数 | 10 |",
        "| 初始资金 | 10,000 USDT |",
        "| 适应度函数 | Sharpe Ratio |",
        "| 随机种子 | 42 |",
        "",
        "## 优化结果对比",
        "",
        "| 策略 | 最优 Sharpe | 最优参数 |",
        "|------|------------|---------|",
    ]

    labels = {
        "trend": "趋势跟踪",
        "grid": "网格交易",
        "arbitrage": "套利",
        "momentum": "动量突破",
        "mean_reversion": "均值回归",
    }

    for key in ["trend", "grid", "arbitrage", "momentum", "mean_reversion"]:
        result = all_results.get(key)
        label = labels[key]

        if key == "mean_reversion":
            sharpe = result.get("optimal_metrics", {}).get("sharpe_ratio") if result else None
            params = result.get("optimal_params", {}) if result else {}
        else:
            best = extract_best(result)
            sharpe = best.get("fitness")
            params = best.get("params", {})

        sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
        params_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else "—"

        lines.append(f"| {label} | {sharpe_str} | {params_str} |")

    lines.extend([
        "",
        "## 各策略详情",
        "",
    ])

    for key in ["trend", "grid", "arbitrage", "momentum", "mean_reversion"]:
        result = all_results.get(key)
        label = labels[key]

        lines.append(f"### {label} ({key})")
        lines.append("")

        if not result:
            lines.append("> 无优化结果")
            lines.append("")
            continue

        if key == "mean_reversion":
            optimal = result.get("optimal_metrics", {})
            params = result.get("optimal_params", {})
            baseline = result.get("baseline_metrics", {})
            improvement = result.get("improvement", {})
            imp = result.get("parameter_importance", {})

            lines.append("**最优参数：**")
            lines.append("")
            for k, v in params.items():
                lines.append(f"- `{k}` = {v}")
            lines.append("")

            if optimal:
                lines.append("**最优指标：**")
                lines.append("")
                lines.append("| 指标 | 优化前 | 优化后 |")
                lines.append("|------|-------|-------|")
                for metric in ["sharpe_ratio", "sortino_ratio", "max_drawdown",
                                "annual_return", "win_rate", "profit_factor"]:
                    opt_val = optimal.get(metric)
                    base_val = baseline.get(metric)
                    if opt_val is not None:
                        def fmt(v):
                            if isinstance(v, float):
                                return f"{v:.2f}" if abs(v) < 100 else f"{v:.1f}"
                            return str(v)
                        lines.append(f"| {metric} | {fmt(base_val)} | {fmt(opt_val)} |")
                lines.append("")

            if improvement:
                lines.append("**提升幅度：**")
                lines.append("")
                for k, v in improvement.items():
                    lines.append(f"- {k}: {v}")
                lines.append("")

            # 代际趋势
            gen_history = result.get("generation_history", [])
            if gen_history:
                lines.append("**代际趋势：**")
                lines.append("")
                lines.append("| 代数 | 最优 Sharpe | 平均 Sharpe |")
                lines.append("|------|------------|------------|")
                step = max(1, len(gen_history) // 8)
                for i, g in enumerate(gen_history):
                    if i % step == 0 or i == len(gen_history) - 1:
                        lines.append(f"| {g['generation']} | {g['best_fitness']:.4f} | {g['avg_fitness']:.4f} |")
                lines.append("")
        else:
            best = extract_best(result)
            params = best.get("params", {})
            metrics = best.get("metrics", {})
            fitness = best.get("fitness")

            lines.append(f"**最优 Sharpe：{fitness:.4f}**" if fitness else "")
            lines.append("")

            if params:
                lines.append("**最优参数：**")
                lines.append("")
                for k, v in params.items():
                    lines.append(f"- `{k}` = {v}")
                lines.append("")

            if metrics:
                lines.append("**最优指标：**")
                lines.append("")
                lines.append("| 指标 | 值 |")
                lines.append("|------|----|")
                for k, v in metrics.items():
                    if isinstance(v, float):
                        lines.append(f"| {k} | {v:.4f} |")
                    else:
                        lines.append(f"| {k} | {v} |")
                lines.append("")

            gen_history = result.get("generation_history", [])
            if gen_history:
                lines.append("**代际趋势：**")
                lines.append("")
                lines.append("| 代数 | 最优 Sharpe | 平均 Sharpe |")
                lines.append("|------|------------|------------|")
                step = max(1, len(gen_history) // 8)
                for i, g in enumerate(gen_history):
                    if i % step == 0 or i == len(gen_history) - 1:
                        lines.append(f"| {g['generation']} | {g['best_fitness']:.4f} | {g['avg_fitness']:.4f} |")
                lines.append("")

    lines.extend([
        "## 备注",
        "",
        "- 使用本地模拟 OHLCV 数据（2000 根 1h K 线，带趋势+波动+弱均值回归特性）。",
        "- mean_reversion 结果来自此前完整优化运行，其余 4 个策略由本脚本批量执行。",
        "- 目标函数：最大化 Sharpe Ratio。",
        "- 真实数据优化需配置 Binance API 密钥后运行 `python scripts/optimize.py`。",
    ])

    return "\n".join(lines)


def main() -> None:
    print("=" * 60)
    print("  Canopy 五策略遗传算法批量优化")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 生成模拟数据
    print("\n[准备] 生成 2000 根模拟 OHLCV K 线...")
    candles = generate_mock_candles(2000, seed=42)
    print(f"       数据范围: {candles[0]['close']:.2f} ~ {candles[-1]['close']:.2f}")

    all_results: dict[str, dict] = {}

    # 1. 加载 mean_reversion 已有结果
    print("\n[1/5] 均值回归 — 加载已有 optimize_result.json")
    mr = load_mean_reversion()
    all_results["mean_reversion"] = mr
    if mr:
        s = mr.get("optimal_metrics", {}).get("sharpe_ratio", "N/A")
        print(f"      最优 Sharpe: {s}")

    # 2-5. 对其他 4 个策略执行遗传优化
    for i, config in enumerate(STRATEGY_CONFIGS, 2):
        name = config["name"]
        label = config["label"]
        param_space = config["param_space"]

        print(f"\n[{i}/5] {label} ({name}) — 遗传算法优化中...")
        start = time.time()

        result = run_genetic_optimization(name, param_space, candles)
        elapsed = time.time() - start

        all_results[name] = result

        if result:
            best = extract_best(result)
            sharpe = best.get("fitness", "N/A")
            print(f"       最优 Sharpe: {sharpe:.4f} | 耗时: {elapsed:.0f}s")

            # 保存结果
            output = {
                "strategy": name,
                "method": "genetic",
                "config": {"pop_size": 20, "generations": 10, "initial_capital": 10000.0},
                "param_space": param_space,
                "optimal_params": best.get("params", {}),
                "optimal_fitness": best.get("fitness"),
                "optimal_metrics": best.get("metrics", {}),
                "generation_history": result.get("generation_history", []),
                "pareto_front": result.get("pareto_front", []),
                "note": "基于本地模拟 OHLCV 数据的遗传算法优化结果",
            }
            output_path = os.path.join(_DATA_DIR, f"optimize_{name}.json")
            with open(output_path, "w") as f:
                json.dump(output, f, indent=2, default=str)
            print(f"       结果已保存: {output_path}")
        else:
            print(f"       优化失败")

    # 生成报告
    print("\n" + "=" * 60)
    print("  生成对比报告...")
    report = generate_report(all_results)
    report_path = os.path.join(_DATA_DIR, "optimization_report.md")
    with open(report_path, "w") as f:
        f.write(report)

    print(f"  报告已写入: {report_path}")
    print(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
