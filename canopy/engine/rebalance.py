"""
Canopy 投资组合再平衡引擎

输入目标配置 → 偏离度检测 → 生成调仓建议。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TargetAllocation:
    """目标配置项。"""
    symbol: str
    target_pct: float       # 目标占比（如 40 表示 40%）
    current_value: float = 0.0
    current_pct: float = 0.0

    @property
    def drift_pct(self) -> float:
        """偏离度（百分点）。"""
        return self.current_pct - self.target_pct


@dataclass
class RebalanceSuggestion:
    """调仓建议条目。"""
    symbol: str
    action: str             # BUY | SELL | HOLD
    amount_usdt: float
    quantity_estimate: float
    reason: str


class RebalanceEngine:
    """
    投资组合再平衡引擎。

    目标配置示例:
        {"BTC/USDT": 40, "ETH/USDT": 30, "SOL/USDT": 15, "USDT": 15}
    """

    def __init__(
        self,
        target_config: dict[str, float],
        drift_threshold: float = 5.0,      # 偏离阈值（百分点），超过即调仓
        min_trade_usdt: float = 20.0,       # 最小调仓金额
    ):
        self.target_config = target_config
        self.drift_threshold = drift_threshold
        self.min_trade_usdt = min_trade_usdt
        self._history: list[dict[str, Any]] = []

    def assess(
        self,
        current_holdings: dict[str, float],   # symbol → USDT 价值
        current_prices: dict[str, float],     # symbol → 当前价格
    ) -> list[RebalanceSuggestion]:
        """
        评估当前持仓并生成调仓建议。

        参数:
            current_holdings: 各资产当前持仓价值（USDT）。
            current_prices: 各资产当前价格。

        返回: 调仓建议列表。
        """
        total_value = sum(current_holdings.values())
        if total_value <= 0:
            return []

        # 计算当前占比
        current_pcts: dict[str, float] = {}
        for sym in self.target_config:
            current_pcts[sym] = (current_holdings.get(sym, 0) / total_value) * 100

        suggestions: list[RebalanceSuggestion] = []
        drift_details: list[dict] = []

        for symbol, target_pct in self.target_config.items():
            current_pct = current_pcts.get(symbol, 0)
            drift = current_pct - target_pct

            drift_details.append({
                "symbol": symbol,
                "target_pct": target_pct,
                "current_pct": round(current_pct, 2),
                "drift_pct": round(drift, 2),
            })

            if abs(drift) < self.drift_threshold:
                continue

            delta_usdt = (drift / 100) * total_value
            if abs(delta_usdt) < self.min_trade_usdt:
                continue

            # 稳定币或现金仓位仅在超出阈值时调整
            price = current_prices.get(symbol, 1.0)
            if price <= 0:
                price = 1.0

            if drift < 0:
                # 占比不足 → 买入
                buy_amount = abs(delta_usdt)
                suggestions.append(RebalanceSuggestion(
                    symbol=symbol,
                    action="BUY",
                    amount_usdt=round(buy_amount, 2),
                    quantity_estimate=round(buy_amount / price, 6) if symbol != "USDT" else buy_amount,
                    reason=f"占比 {current_pct:.1f}% < 目标 {target_pct:.0f}%，偏差 {abs(drift):.1f}%",
                ))
            else:
                # 占比过多 → 卖出
                sell_amount = delta_usdt
                suggestions.append(RebalanceSuggestion(
                    symbol=symbol,
                    action="SELL",
                    amount_usdt=round(sell_amount, 2),
                    quantity_estimate=round(sell_amount / price, 6) if symbol != "USDT" else sell_amount,
                    reason=f"占比 {current_pct:.1f}% > 目标 {target_pct:.0f}%，偏差 {drift:.1f}%",
                ))

        # 记录快照
        self._history.append({
            "total_value": round(total_value, 2),
            "drift_details": drift_details,
            "suggestions": [s.__dict__ for s in suggestions],
        })
        if len(self._history) > 200:
            self._history = self._history[-200:]

        return suggestions

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """返回历史评估记录。"""
        return self._history[-limit:]
