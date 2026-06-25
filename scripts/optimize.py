#!/usr/bin/env python
"""Canopy 策略参数优化器 — 命令行入口。

用法:
    python scripts/optimize.py --strategy mean_reversion --method grid \\
        --symbol BTC/USDT --timeframe 1h

    选项:
        --method 可选 grid / genetic / both
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import cast

# 确保项目根在 sys.path
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from canopy.config import Config  # noqa: E402
from canopy.data.fetcher import DataFetcher  # noqa: E402
from canopy.exchange.ccxt_adapter import ExchangeAdapter  # noqa: E402
from canopy.optimizer.analyzer import OptimizationAnalyzer  # noqa: E402
from canopy.optimizer.genetic import GeneticOptimizer  # noqa: E402
from canopy.optimizer.grid_search import GridSearchOptimizer  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("canopy.optimize")

# ── 各策略默认参数搜索空间 ──

DEFAULT_PARAM_SPACES: dict[str, dict[str, list]] = {
    "mean_reversion": {
        "ma_period": [10, 15, 20, 25, 30],
        "std_period": [10, 15, 20, 25, 30],
        "entry_z": [1.0, 1.5, 2.0, 2.5, 3.0],
        "exit_z": [0.3, 0.5, 0.8, 1.0],
    },
    "trend": {
        "fast_period": [8, 10, 12, 16],
        "slow_period": [20, 24, 26, 30, 34],
        "signal_period": [6, 9, 12],
        "atr_period": [10, 14, 20],
        "atr_multiplier": [1.5, 2.0, 2.5, 3.0],
    },
    "momentum": {
        "lookback": [10, 15, 20, 25, 30],
        "entry_threshold": [0.3, 0.6, 1.0, 1.5],
        "atr_period": [10, 14, 20],
        "atr_multiplier": [1.5, 2.0, 2.5, 3.0],
    },
    "grid": {
        "grid_count": [5, 8, 10, 15, 20],
        "order_amount": [0.005, 0.01, 0.02, 0.05],
        "mode": ["arithmetic", "geometric"],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Canopy 策略参数优化器")
    parser.add_argument("--strategy", required=True, help="策略名称 (mean_reversion / trend / momentum / grid)")
    parser.add_argument("--method", default="both", choices=["grid", "genetic", "both"],
                        help="优化方法 (默认 both)")
    parser.add_argument("--symbol", default="BTC/USDT", help="交易对 (默认 BTC/USDT)")
    parser.add_argument("--timeframe", default="1h", help="K 线周期 (默认 1h)")
    parser.add_argument("--since", default=None, help="起始时间 ISO 格式 (默认 90 天前)")
    parser.add_argument("--limit", type=int, default=1000, help="K 线条数上限 (默认 1000)")
    parser.add_argument("--param-space", default=None, help="自定义参数空间 JSON 文件路径")
    parser.add_argument("--top-n", type=int, default=20, help="网格搜索 Top N (默认 20)")
    parser.add_argument("--pop-size", type=int, default=50, help="GA 种群大小 (默认 50)")
    parser.add_argument("--generations", type=int, default=30, help="GA 代数 (默认 30)")
    parser.add_argument("--max-workers", type=int, default=4, help="并行 worker 数 (默认 4)")
    parser.add_argument("--capital", type=float, default=10000.0, help="初始资金 (默认 10000)")
    parser.add_argument("--output", default=None, help="结果输出 JSON 文件路径")
    return parser.parse_args()


def get_param_space(args: argparse.Namespace) -> dict[str, list]:
    """获取参数搜索空间。"""
    if args.param_space:
        with open(args.param_space) as f:
            return cast(dict, json.load(f))
    if args.strategy in DEFAULT_PARAM_SPACES:
        return DEFAULT_PARAM_SPACES[args.strategy]
    raise ValueError(f"未知策略 '{args.strategy}'，请通过 --param-space 指定参数空间")


def fetch_candles(args: argparse.Namespace) -> list[dict]:
    """获取 OHLCV 数据。"""
    config = Config()
    if not config.api_key or not config.api_secret:
        logger.warning("未配置 API 密钥，使用测试网或公共接口")

    adapter = ExchangeAdapter(
        exchange_id=config.exchange,
        config=config,
    )
    fetcher = DataFetcher(adapter, cache_dir=config.data_cache_dir)

    since = args.since
    if since is None:
        since = (datetime.now() - timedelta(days=90)).isoformat()

    logger.info("获取 %s %s 数据 (since=%s, limit=%d)...", args.symbol, args.timeframe, since, args.limit)
    df = fetcher.get_ohlcv(args.symbol, args.timeframe, since=since, limit=args.limit)

    if df.empty:
        logger.error("未获取到 OHLCV 数据")
        sys.exit(1)

    candles = df.to_dict(orient="records")
    logger.info("共 %d 根 K 线", len(candles))
    return cast(list, candles)


def run_grid_search(args: argparse.Namespace, param_space: dict, candles: list[dict]) -> dict:
    """执行网格搜索。"""
    logger.info("=" * 60)
    logger.info("网格搜索优化: %s", args.strategy)
    logger.info("=" * 60)

    optimizer = GridSearchOptimizer(
        strategy_name=args.strategy,
        param_space=param_space,
        candles=candles,
        engine_kwargs={
            "initial_capital": args.capital,
        },
        max_workers=args.max_workers,
    )

    result = optimizer.run(top_n=args.top_n)
    optimizer.print_summary(top_n=args.top_n)
    return result


def run_genetic(args: argparse.Namespace, param_space: dict, candles: list[dict]) -> dict:
    """执行遗传算法。"""
    logger.info("=" * 60)
    logger.info("遗传算法优化: %s", args.strategy)
    logger.info("=" * 60)

    optimizer = GeneticOptimizer(
        strategy_name=args.strategy,
        param_space=param_space,
        candles=candles,
        engine_kwargs={
            "initial_capital": args.capital,
        },
        pop_size=args.pop_size,
        generations=args.generations,
        max_workers=args.max_workers,
    )

    result = optimizer.run()
    optimizer.print_summary()

    # Pareto 前沿
    pareto = result.get("pareto_front", [])
    if pareto:
        print(f"\n  Pareto 前沿 ({len(pareto)} 个非支配解):")
        print(f"  {'Sharpe':>8}  {'MaxDD':>8}  {'Sortino':>8}  参数")
        print(f"  {'-'*60}")
        for p in pareto:
            params_str = ", ".join(f"{k}={v}" for k, v in p["params"].items())
            print(f"  {p['sharpe']:>8.4f}  {p['max_drawdown']:>8.4f}  {p['sortino']:>8.4f}  {params_str}")
        print()

    # 代际趋势
    history = result.get("generation_history", [])
    if history:
        print("\n  代际趋势:")
        print(f"  {'代':>4}  {'最优Sharpe':>12}  {'平均Sharpe':>12}")
        print(f"  {'-'*34}")
        for h in history:
            print(f"  {h['generation']:>4}  {h['best_fitness']:>12.4f}  {h['avg_fitness']:>12.4f}")
        print()

    return result


def run_analysis(grid_result: dict | None, genetic_result: dict | None) -> None:
    """运行结果分析。"""
    all_results = []
    if grid_result:
        all_results.extend(grid_result.get("all_results", []))
    if genetic_result:
        all_results.extend(genetic_result.get("final_population", []))

    if not all_results:
        return

    analyzer = OptimizationAnalyzer(all_results)
    analyzer.print_importance()

    # 若只有两个参数，输出热力图概览
    if all_results and all_results[0].get("params"):
        param_names = list(all_results[0]["params"].keys())
        if len(param_names) >= 2:
            hm = analyzer.sensitivity_heatmap(param_names[0], param_names[1], bins=5)
            matrix = hm.get("matrix", [])
            if matrix:
                print(f"\n  热力图 ({hm['param_x']} vs {hm['param_y']}, metric={hm['metric']}):")
                print(f"  X 轴: {hm['x_edges']}")
                for iy, row in enumerate(matrix):
                    print(f"  y={hm['y_edges'][iy]:.2f}~{hm['y_edges'][iy+1]:.2f}: {row}")
                print()


def main() -> None:
    args = parse_args()

    # 验证策略是否已注册
    from canopy.engine.factory import factory  # noqa: E402
    available = factory.list_strategies()
    if args.strategy not in available:
        logger.error("未注册的策略 '%s'。可用: %s", args.strategy, available)
        sys.exit(1)

    param_space = get_param_space(args)
    logger.info("参数空间: %s", json.dumps({k: v for k, v in param_space.items()}, indent=2))

    candles = fetch_candles(args)

    grid_result: dict | None = None
    genetic_result: dict | None = None

    if args.method in ("grid", "both"):
        grid_result = run_grid_search(args, param_space, candles)

    if args.method in ("genetic", "both"):
        genetic_result = run_genetic(args, param_space, candles)

    # 分析
    run_analysis(grid_result, genetic_result)

    # 输出结果文件
    output = {
        "strategy": args.strategy,
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "method": args.method,
        "grid_result": grid_result,
        "genetic_result": genetic_result,
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2, default=str)
        logger.info("结果已写入 %s", args.output)

    # 复制到当前目录
    result_path = os.path.join(os.getcwd(), "optimize_result.json")
    with open(result_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("结果已写入 %s", result_path)


if __name__ == "__main__":
    main()
