"""遗传算法参数优化 — 纯 Python 实现，不依赖 DEAP 等第三方库。

核心机制：
- 种群大小 50，迭代 30 代。
- 锦标赛选择（tournament size=3）。
- 均匀交叉（每基因独立选择父代）。
- 高斯变异（连续参数）或离散选择变异（离散参数）。
- 适应度 = Sharpe ratio。
- 输出 Pareto 前沿（Sharpe vs MaxDD）。
"""

from __future__ import annotations

import copy
import logging
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import numpy as np

from canopy.backtest.engine import BacktestEngine
from canopy.engine.factory import factory as strategy_factory

logger = logging.getLogger(__name__)

# ── 类型定义 ──
Individual = dict[str, Any]           # {"params": {...}, "fitness": float, "metrics": {...}}
ParamMeta = dict[str, dict[str, Any]] # {"param_name": {"type": "int"|"float", "candidates": list}}


def _backtest_worker_ga(
    task: tuple[str, dict[str, Any], list[dict], dict[str, Any]],
) -> dict[str, Any]:
    """GA 专用 worker，同 grid_search._backtest_worker。"""
    strategy_name, params, candles, engine_kwargs = task
    try:
        strategy = strategy_factory.create(strategy_name, **params)
        engine = BacktestEngine(**engine_kwargs)
        result = engine.run(strategy, candles)
        return {
            "params": params,
            "fitness": result["metrics"].get("sharpe_ratio", 0.0),
            "metrics": result["metrics"],
        }
    except Exception as e:
        return {"params": params, "error": str(e), "fitness": float("-inf")}


class GeneticOptimizer:
    """遗传算法参数优化器。

    属性:
        strategy_name: 策略名称。
        param_space:   参数搜索空间（key=参数名，value=候选值列表）。
        candles:       OHLCV 数据。
        engine_kwargs: 回测引擎参数。
        pop_size:      种群大小（默认 50）。
        generations:   迭代代数（默认 30）。
        mutation_rate: 变异概率（默认 0.1）。
        crossover_rate: 交叉概率（默认 0.9）。
        tournament_size: 锦标赛选择规模（默认 3）。
        max_workers:   并行 worker 数。
    """

    def __init__(
        self,
        strategy_name: str,
        param_space: dict[str, list[Any]],
        candles: list[dict],
        engine_kwargs: dict[str, Any] | None = None,
        pop_size: int = 50,
        generations: int = 30,
        mutation_rate: float = 0.1,
        crossover_rate: float = 0.9,
        tournament_size: int = 3,
        max_workers: int = 4,
        random_seed: int | None = None,
    ) -> None:
        self.strategy_name = strategy_name
        self.param_space = param_space
        self.candles = candles
        self.engine_kwargs = engine_kwargs or {}
        self.pop_size = pop_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.tournament_size = tournament_size
        self.max_workers = max_workers

        if random_seed is not None:
            random.seed(random_seed)
            np.random.seed(random_seed)

        self._param_meta: ParamMeta = {}
        self._history: list[list[Individual]] = []  # 每代种群快照
        self._best: Individual = {}

    # ── 参数元信息 ──

    def _build_param_meta(self) -> None:
        """根据 param_space 构建参数元信息（类型、范围、候选值）。"""
        for name, candidates in self.param_space.items():
            if not candidates:
                raise ValueError(f"参数 {name} 候选列表为空")
            sample = candidates[0]
            if isinstance(sample, int):
                ptype = "int"
            elif isinstance(sample, float):
                ptype = "float"
            else:
                ptype = "str"
            self._param_meta[name] = {
                "type": ptype,
                "candidates": candidates,
                "min_val": min(candidates),
                "max_val": max(candidates),
            }

    # ── 个体生成 ──

    def _random_params(self) -> dict[str, Any]:
        """随机生成一组参数。"""
        params: dict[str, Any] = {}
        for name, meta in self._param_meta.items():
            params[name] = random.choice(meta["candidates"])
        return params

    def _random_individual(self) -> Individual:
        """生成一个随机个体（未评估）。"""
        return {"params": self._random_params(), "fitness": float("-inf"), "metrics": {}}

    # ── 种群评估 ──

    def _evaluate_population(self, population: list[Individual]) -> None:
        """并行评估种群中所有未评估个体。"""
        unevaluated = [ind for ind in population if ind["fitness"] == float("-inf") and "error" not in ind]
        if not unevaluated:
            return

        tasks = [
            (self.strategy_name, ind["params"], self.candles, self.engine_kwargs)
            for ind in unevaluated
        ]

        workers = min(self.max_workers, len(tasks))
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(_backtest_worker_ga, t): i for i, t in enumerate(tasks)}
            for future in as_completed(future_map):
                idx = future_map[future]
                result = future.result()
                if "error" in result:
                    unevaluated[idx]["error"] = result["error"]
                    unevaluated[idx]["fitness"] = float("-inf")
                else:
                    unevaluated[idx]["fitness"] = result["fitness"]
                    unevaluated[idx]["metrics"] = result["metrics"]

    # ── 选择 ──

    def _tournament_select(self, population: list[Individual]) -> Individual:
        """锦标赛选择：随机选 k 个个体，返回适应度最高的。"""
        candidates = random.sample(population, min(self.tournament_size, len(population)))
        return max(candidates, key=lambda ind: ind["fitness"])

    # ── 交叉 ──

    def _crossover(self, parent1: Individual, parent2: Individual) -> tuple[Individual, Individual]:
        """均匀交叉：每个基因独立随机选择来自父代 1 或父代 2。"""
        if random.random() > self.crossover_rate:
            return copy.deepcopy(parent1), copy.deepcopy(parent2)

        child1_params: dict[str, Any] = {}
        child2_params: dict[str, Any] = {}
        p1 = parent1["params"]
        p2 = parent2["params"]

        for name in self._param_meta:
            if random.random() < 0.5:
                child1_params[name] = p1[name]
                child2_params[name] = p2[name]
            else:
                child1_params[name] = p2[name]
                child2_params[name] = p1[name]

        return (
            {"params": child1_params, "fitness": float("-inf"), "metrics": {}},
            {"params": child2_params, "fitness": float("-inf"), "metrics": {}},
        )

    # ── 变异 ──

    def _mutate(self, individual: Individual) -> Individual:
        """高斯变异：每个基因以 mutation_rate 概率变异。

        - 连续参数（float）：在原值上加高斯噪声 σ = (max-min) * 0.1，并裁剪到 [min, max]。
        - 离散参数（int）：从候选值列表中随机重选。
        - 字符串参数：从候选值列表中随机重选。
        """
        params = copy.deepcopy(individual["params"])
        for name, meta in self._param_meta.items():
            if random.random() >= self.mutation_rate:
                continue

            ptype = meta["type"]
            if ptype == "float":
                current = params[name]
                sigma = (meta["max_val"] - meta["min_val"]) * 0.1
                new_val = current + random.gauss(0, sigma)
                new_val = max(meta["min_val"], min(meta["max_val"], new_val))
                # 适当精度保留
                params[name] = round(new_val, 6)
            elif ptype == "int":
                params[name] = random.choice(meta["candidates"])
            else:
                params[name] = random.choice(meta["candidates"])

        return {"params": params, "fitness": float("-inf"), "metrics": {}}

    # ── Pareto 前沿 ──

    @staticmethod
    def _compute_pareto_front(individuals: list[Individual]) -> list[Individual]:
        """计算 Pareto 前沿（Sharpe 越大越好，MaxDD 越小越好）。

        Args:
            individuals: 已评估的个体列表。

        Returns:
            非支配个体列表。
        """
        valid = [
            ind for ind in individuals
            if ind["metrics"] and "error" not in ind
        ]

        if not valid:
            return []

        n = len(valid)
        dominated = [False] * n

        for i in range(n):
            si = valid[i]["metrics"].get("sharpe_ratio", float("-inf"))
            di = valid[i]["metrics"].get("max_drawdown", float("inf"))
            for j in range(n):
                if i == j:
                    continue
                sj = valid[j]["metrics"].get("sharpe_ratio", float("-inf"))
                dj = valid[j]["metrics"].get("max_drawdown", float("inf"))
                # j 支配 i：j 在两方面都不差，且至少一方面严格更好
                if sj >= si and dj <= di and (sj > si or dj < di):
                    dominated[i] = True
                    break

        return [valid[i] for i in range(n) if not dominated[i]]

    # ── 运行进化 ──

    def run(self) -> dict[str, Any]:
        """执行遗传算法优化。

        Returns:
            {
                'strategy': str,
                'generations': int,
                'pop_size': int,
                'best_params': dict,
                'best_metrics': dict,
                'best_fitness': float,
                'pareto_front': list[dict],
                'generation_history': list[dict],   # 每代最优
                'final_population': list[dict],
            }
        """
        self._build_param_meta()

        # 初始化种群
        population = [self._random_individual() for _ in range(self.pop_size)]
        self._evaluate_population(population)
        population.sort(key=lambda ind: ind["fitness"], reverse=True)

        gen_history: list[dict[str, Any]] = []

        for gen in range(1, self.generations + 1):
            logger.info("遗传算法 %s 第 %d/%d 代...", self.strategy_name, gen, self.generations)

            # 精英保留：前 2 名直接进入下一代
            new_population: list[Individual] = population[:2]

            # 生成后代
            while len(new_population) < self.pop_size:
                p1 = self._tournament_select(population)
                p2 = self._tournament_select(population)
                c1, c2 = self._crossover(p1, p2)
                c1 = self._mutate(c1)
                c2 = self._mutate(c2)
                new_population.append(c1)
                if len(new_population) < self.pop_size:
                    new_population.append(c2)

            # 评估
            self._evaluate_population(new_population)
            new_population.sort(key=lambda ind: ind["fitness"], reverse=True)
            population = new_population

            best = population[0]
            gen_history.append({
                "generation": gen,
                "best_params": best["params"],
                "best_fitness": best["fitness"],
                "best_metrics": best["metrics"],
                "avg_fitness": np.mean([ind["fitness"] for ind in population if ind["fitness"] != float("-inf")]),
            })

        self._best = population[0]
        pareto = self._compute_pareto_front(population)

        return {
            "strategy": self.strategy_name,
            "generations": self.generations,
            "pop_size": self.pop_size,
            "best_params": self._best["params"],
            "best_metrics": self._best["metrics"],
            "best_fitness": self._best["fitness"],
            "pareto_front": [
                {
                    "params": ind["params"],
                    "sharpe": ind["metrics"].get("sharpe_ratio", 0),
                    "max_drawdown": ind["metrics"].get("max_drawdown", 0),
                    "sortino": ind["metrics"].get("sortino_ratio", 0),
                    "win_rate": ind["metrics"].get("win_rate", 0),
                }
                for ind in pareto
            ],
            "generation_history": gen_history,
            "final_population": [
                {
                    "params": ind["params"],
                    "fitness": ind["fitness"],
                    "metrics": ind["metrics"],
                }
                for ind in population
            ],
        }

    # ── 便捷方法 ──

    def print_summary(self) -> None:
        """打印进化结果摘要。"""
        best = self._best
        if not best or not best.get("metrics"):
            print("暂无优化结果。")
            return

        m = best["metrics"]
        print(f"\n{'='*80}")
        print(f"  遗传算法结果 — {self.strategy_name}")
        print(f"  种群 {self.pop_size} × {self.generations} 代")
        print(f"{'='*80}")
        print("  最优参数:")
        for k, v in best["params"].items():
            print(f"    {k}: {v}")
        print(f"  最优适应度 (Sharpe): {best['fitness']:.4f}")
        print(f"  Sortino: {m.get('sortino_ratio', 0):.4f}")
        print(f"  MaxDD:   {m.get('max_drawdown', 0):.4f}")
        print(f"  WinRate: {m.get('win_rate', 0):.4f}")
        print(f"  总交易:  {m.get('total_trades', 0)}")
        print(f"{'='*80}\n")
