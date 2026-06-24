"""优化结果分析 — 参数敏感性热力图数据、Pareto 前沿可视化数据。

仅生成结构化数据（矩阵/列表），供前端或 matplotlib 消费渲染。
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class OptimizationAnalyzer:
    """优化结果分析器。

    接收一组优化结果（每项含 params + metrics），产出：
    - 敏感性热力图数据：任意两个参数的 Sharpe 均值矩阵。
    - Pareto 前沿散点数据：Sharpe vs MaxDD。
    """

    def __init__(self, results: list[dict[str, Any]]) -> None:
        """
        Args:
            results: 优化器输出中的 all_results 或 final_population，
                     每项含 'params' (dict) 和 'metrics' (dict)。
        """
        self.results = results
        self._valid_results: list[dict[str, Any]] = []

    def _filter_valid(self) -> None:
        """过滤合法结果：params 非空、metrics 含 sharpe_ratio。"""
        self._valid_results = [
            r for r in self.results
            if r.get("params") and r.get("metrics") is not None
            and "sharpe_ratio" in (r["metrics"] or {})
        ]

    # ── 敏感性热力图数据 ──

    def sensitivity_heatmap(
        self,
        param_x: str,
        param_y: str,
        metric: str = "sharpe_ratio",
        bins: int = 10,
    ) -> dict[str, Any]:
        """生成两参数对指标的热力图矩阵。

        将 param_x 和 param_y 的取值区间分别等分为 bins 格，
        统计每格中结果的平均指标值，形成 bins × bins 矩阵。

        Args:
            param_x: X 轴参数名。
            param_y: Y 轴参数名。
            metric:  统计指标（默认 sharpe_ratio，也可用 sortino_ratio / max_drawdown / win_rate）。
            bins:    分桶数（默认 10）。

        Returns:
            {
                'param_x': str,
                'param_y': str,
                'metric': str,
                'x_edges': list[float],
                'y_edges': list[float],
                'matrix': list[list[float | None]],  # bins × bins，无数据为 None
                'counts': list[list[int]],
            }
        """
        self._filter_valid()

        if not self._valid_results:
            return {
                "param_x": param_x, "param_y": param_y, "metric": metric,
                "x_edges": [], "y_edges": [], "matrix": [], "counts": [],
            }

        # 提取两组参数值
        x_vals = []
        y_vals = []
        z_vals = []
        for r in self._valid_results:
            if param_x in r["params"] and param_y in r["params"]:
                x_vals.append(r["params"][param_x])
                y_vals.append(r["params"][param_y])
                z_vals.append(r["metrics"].get(metric, 0))

        if not x_vals:
            return {
                "param_x": param_x, "param_y": param_y, "metric": metric,
                "x_edges": [], "y_edges": [], "matrix": [], "counts": [],
            }

        x_arr = np.array(x_vals, dtype=float)
        y_arr = np.array(y_vals, dtype=float)
        z_arr = np.array(z_vals, dtype=float)

        # 等距分桶
        x_min, x_max = x_arr.min(), x_arr.max()
        y_min, y_max = y_arr.min(), y_arr.max()

        # 边界微扩以避免端点数据落在桶外
        x_pad = (x_max - x_min) * 0.001 if x_max > x_min else 0.1
        y_pad = (y_max - y_min) * 0.001 if y_max > y_min else 0.1
        x_edges = np.linspace(x_min - x_pad, x_max + x_pad, bins + 1)
        y_edges = np.linspace(y_min - y_pad, y_max + y_pad, bins + 1)

        matrix: list[list[float | None]] = [[None] * bins for _ in range(bins)]
        counts: list[list[int]] = [[0] * bins for _ in range(bins)]
        sum_matrix: list[list[float]] = [[0.0] * bins for _ in range(bins)]

        for xi, yi, zi in zip(x_arr, y_arr, z_arr):
            ix = np.digitize(xi, x_edges) - 1
            iy = np.digitize(yi, y_edges) - 1
            if 0 <= ix < bins and 0 <= iy < bins:
                sum_matrix[iy][ix] += zi
                counts[iy][ix] += 1

        for iy in range(bins):
            for ix in range(bins):
                if counts[iy][ix] > 0:
                    matrix[iy][ix] = round(sum_matrix[iy][ix] / counts[iy][ix], 6)

        return {
            "param_x": param_x,
            "param_y": param_y,
            "metric": metric,
            "x_edges": [round(v, 6) for v in x_edges.tolist()],
            "y_edges": [round(v, 6) for v in y_edges.tolist()],
            "matrix": matrix,
            "counts": counts,
        }

    # ── 所有参数对热力图 ──

    def all_heatmaps(self, metric: str = "sharpe_ratio", bins: int = 10) -> list[dict[str, Any]]:
        """生成所有参数对的热力图数据。

        Args:
            metric: 统计指标。
            bins:   分桶数。

        Returns:
            热力图数据列表，每项为 sensitivity_heatmap 的输出。
        """
        self._filter_valid()
        if not self._valid_results:
            return []

        param_names = list(self._valid_results[0]["params"].keys())
        heatmaps = []
        for i, p1 in enumerate(param_names):
            for p2 in param_names[i + 1:]:
                hm = self.sensitivity_heatmap(p1, p2, metric=metric, bins=bins)
                heatmaps.append(hm)
        return heatmaps

    # ── Pareto 前沿数据 ──

    def pareto_data(self, x_metric: str = "sharpe_ratio", y_metric: str = "max_drawdown") -> dict[str, Any]:
        """提取 Pareto 前沿散点数据（用于 Sharpe vs MaxDD 可视化）。

        Args:
            x_metric: X 轴指标（越大越好）。
            y_metric: Y 轴指标（越小越好）。

        Returns:
            {
                'points': [{'x': float, 'y': float, 'params': dict, 'metrics': dict}, ...],
                'pareto_points': [...],  # 非支配前沿
                'x_label': str,
                'y_label': str,
            }
        """
        self._filter_valid()

        def _get_x(r):
            return r["metrics"].get(x_metric, float("-inf"))

        def _get_y(r):
            return r["metrics"].get(y_metric, float("inf"))

        points = [
            {
                "x": round(_get_x(r), 6),
                "y": round(_get_y(r), 6),
                "params": r["params"],
                "metrics": r["metrics"],
            }
            for r in self._valid_results
        ]

        # 计算 Pareto 前沿
        n = len(points)
        dominated = [False] * n
        for i in range(n):
            xi, yi = points[i]["x"], points[i]["y"]
            for j in range(n):
                if i == j:
                    continue
                xj, yj = points[j]["x"], points[j]["y"]
                if xj >= xi and yj <= yi and (xj > xi or yj < yi):
                    dominated[i] = True
                    break

        pareto = [points[i] for i in range(n) if not dominated[i]]
        pareto.sort(key=lambda p: p["x"], reverse=True)

        return {
            "points": points,
            "pareto_points": pareto,
            "x_label": x_metric,
            "y_label": y_metric,
        }

    # ── 参数重要性排序 ──

    def param_importance(self, metric: str = "sharpe_ratio") -> list[dict[str, Any]]:
        """基于方差分析评估各参数对指标的影响程度。

        对于每个参数，按分位数分组计算组间指标差异，汇总为重要性分数。

        Args:
            metric: 目标指标。

        Returns:
            列表，每项含 param / importance / group_stats，按 importance 降序。
        """
        self._filter_valid()
        if not self._valid_results:
            return []

        param_names = list(self._valid_results[0]["params"].keys())
        results = []

        for pname in param_names:
            # 按参数值排序后分 3 组
            sorted_results = sorted(self._valid_results, key=lambda r: r["params"].get(pname, 0))
            n = len(sorted_results)
            if n < 3:
                continue

            groups = [
                sorted_results[: n // 3],
                sorted_results[n // 3 : 2 * n // 3],
                sorted_results[2 * n // 3 :],
            ]

            group_means = []
            for g in groups:
                vals = [r["metrics"].get(metric, 0) for r in g]
                group_means.append(sum(vals) / len(vals))

            # 重要性 = 组间标准差
            importance = float(np.std(group_means))
            results.append({
                "param": pname,
                "importance": round(importance, 6),
                "group_means": [round(m, 6) for m in group_means],
            })

        results.sort(key=lambda r: r["importance"], reverse=True)
        return results

    # ── 便捷方法 ──

    def print_importance(self) -> None:
        """打印参数重要性排名。"""
        imp = self.param_importance()
        if not imp:
            print("暂无足够数据计算参数重要性。")
            return

        print(f"\n{'='*60}")
        print("  参数重要性排名 (按 Sharpe 方差)")
        print(f"{'='*60}")
        print(f"{'排名':<4} {'参数':<20} {'重要性':>10}  {'低组':>8}  {'中组':>8}  {'高组':>8}")
        print(f"{'-'*60}")
        for i, item in enumerate(imp, 1):
            gm = item["group_means"]
            print(
                f"{i:<4} {item['param']:<20} {item['importance']:>10.6f}  "
                f"{gm[0]:>8.4f}  {gm[1]:>8.4f}  {gm[2]:>8.4f}"
            )
        print(f"{'='*60}\n")
