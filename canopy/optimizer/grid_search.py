"""网格搜索参数优化 — 穷举参数组合、并行回测、按 Sharpe 排序输出 Top N。"""

from __future__ import annotations

import itertools
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

from canopy.backtest.engine import BacktestEngine
from canopy.engine.factory import factory as strategy_factory

logger = logging.getLogger(__name__)


def _backtest_worker(
    task: tuple[str, dict[str, Any], list[dict], dict[str, Any]],
) -> dict[str, Any]:
    """Worker 函数：创建策略并执行单次回测。

    Args:
        task: (strategy_name, params, candles, engine_kwargs) 元组。

    Returns:
        含 params / metrics 的字典。异常时返回 error 字段。
    """
    strategy_name, params, candles, engine_kwargs = task
    try:
        strategy = strategy_factory.create(strategy_name, **params)
        engine = BacktestEngine(**engine_kwargs)
        result = engine.run(strategy, candles)
        return {
            "params": params,
            "metrics": result["metrics"],
        }
    except Exception as e:
        return {"params": params, "error": str(e)}


class GridSearchOptimizer:
    """网格搜索参数优化器。

    对参数空间取笛卡尔积，并行回测所有组合，按指定指标排序输出最优结果。

    Attributes:
        strategy_name: 策略名称（如 'mean_reversion'）。
        param_space:   参数空间 dict，key=参数名，value=候选值列表。
        candles:       OHLCV 数据列表。
        engine_kwargs: 回测引擎参数（initial_capital / commission / slippage）。
        max_workers:   并行 worker 数上限。
    """

    def __init__(
        self,
        strategy_name: str,
        param_space: dict[str, list[Any]],
        candles: list[dict],
        engine_kwargs: dict[str, Any] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.strategy_name = strategy_name
        self.param_space = param_space
        self.candles = candles
        self.engine_kwargs = engine_kwargs or {}
        self.max_workers = max_workers

        self._results: list[dict[str, Any]] = []
        self._total_combinations: int = 0

    # ── 笛卡尔积展开 ──

    def _generate_combinations(self) -> list[dict[str, Any]]:
        """展开参数空间为所有组合列表。

        Returns:
            params 组合列表。
        """
        keys = list(self.param_space.keys())
        values = list(self.param_space.values())
        combinations = []
        for combo in itertools.product(*values):
            combinations.append(dict(zip(keys, combo)))
        return combinations

    # ── 运行优化 ──

    def run(self, sort_by: str = "sharpe_ratio", top_n: int = 20) -> dict[str, Any]:
        """执行网格搜索优化。

        Args:
            sort_by: 排序指标（默认 sharpe_ratio）。
            top_n:   返回前 N 名结果。

        Returns:
            {
                'strategy': str,
                'total_combinations': int,
                'top_results': list[dict],
                'all_results': list[dict],
                'best_params': dict,
                'best_metrics': dict,
            }
        """
        combinations = self._generate_combinations()
        self._total_combinations = len(combinations)
        logger.info(
            "网格搜索 %s: %d 个参数组合，最大 %d worker",
            self.strategy_name,
            self._total_combinations,
            self.max_workers,
        )

        tasks = [
            (self.strategy_name, combo, self.candles, self.engine_kwargs)
            for combo in combinations
        ]

        results: list[dict[str, Any]] = []
        workers = min(self.max_workers, len(tasks))

        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(_backtest_worker, t): t for t in tasks}
            for future in as_completed(future_map):
                result = future.result()
                results.append(result)

        # 分离成功与失败
        success = [r for r in results if "error" not in r]
        failed = [r for r in results if "error" in r]
        if failed:
            logger.warning("%d/%d 组合执行失败", len(failed), self._total_combinations)

        # 按指标排序
        success.sort(key=lambda r: r["metrics"].get(sort_by, 0), reverse=True)
        self._results = success

        best = success[0] if success else {"params": {}, "metrics": {}}

        return {
            "strategy": self.strategy_name,
            "total_combinations": self._total_combinations,
            "top_results": success[:top_n],
            "all_results": success,
            "best_params": best["params"],
            "best_metrics": best["metrics"],
            "failed_count": len(failed),
        }

    # ── 便捷方法 ──

    def print_summary(self, top_n: int = 10) -> None:
        """打印 Top N 结果摘要。"""
        if not self._results:
            print("暂无优化结果。")
            return

        print(f"\n{'='*80}")
        print(f"  网格搜索结果 — {self.strategy_name} (共 {self._total_combinations} 组合)")
        print(f"{'='*80}")
        print(f"{'排名':<4} {'Sharpe':>8} {'Sortino':>8} {'MaxDD':>8} {'WinRate':>8} 参数")
        print(f"{'-'*80}")

        for i, r in enumerate(self._results[:top_n], 1):
            m = r["metrics"]
            params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
            print(
                f"{i:<4} {m.get('sharpe_ratio', 0):>8.4f} "
                f"{m.get('sortino_ratio', 0):>8.4f} "
                f"{m.get('max_drawdown', 0):>8.4f} "
                f"{m.get('win_rate', 0):>8.4f}  "
                f"{params_str}"
            )

        print(f"{'='*80}\n")
