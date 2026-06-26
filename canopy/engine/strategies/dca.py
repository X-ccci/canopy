"""
Canopy DCA 定投策略 — 固定额度 + 智能定投（波动率加权）

两种模式：
  1. fixed: 固定额度，每隔 interval_hours 买入 amount_per_order 金额
  2. smart: 波动率加权，波动低时多投、波动高时少投
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class DCAConfig:
    """DCA 定投参数配置。"""
    symbol: str = "BTC/USDT"
    interval_hours: int = 24
    amount_per_order: float = 100.0      # 固定额度（USDT）
    mode: str = "fixed"                   # fixed | smart
    volatility_weight: float = 1.0        # smart 模式波动率加权系数
    volatility_window: int = 24           # 波动率计算窗口（K 线数）
    min_order: float = 10.0               # 最小定投金额
    max_order: float = 500.0              # 最大定投金额


class DCAStrategy:
    """DCA 定投策略执行器。"""

    def __init__(self, config: DCAConfig | None = None):
        self.config = config or DCAConfig()
        self._last_order_at: str | None = None
        self._orders: list[dict[str, Any]] = []

    def next(self, df: pd.DataFrame, current_time: datetime | None = None) -> dict[str, Any] | None:
        """
        根据当前 K 线数据判断是否触发定投。

        参数:
            df: 历史 OHLCV DataFrame（至少包含 close）。
            current_time: 当前时间（默认取 df 最后一根 K 线时间）。

        返回: 订单字典 或 None（不触发）。
        """
        if df.empty or len(df) < 2:
            return None

        now = current_time or datetime.now()
        last_close = float(df["close"].iloc[-1])

        # 检查时间间隔
        if self._last_order_at:
            try:
                last_dt = datetime.fromisoformat(self._last_order_at)
                hours_elapsed = (now - last_dt).total_seconds() / 3600
                if hours_elapsed < self.config.interval_hours:
                    return None
            except (ValueError, TypeError):
                pass

        # 计算定投金额
        if self.config.mode == "smart" and len(df) >= self.config.volatility_window:
            amount = self._smart_amount(df)
        else:
            amount = self.config.amount_per_order

        quantity = amount / last_close

        order: dict[str, Any] = {
            "symbol": self.config.symbol,
            "action": "BUY",
            "price": last_close,
            "quantity": round(quantity, 6),
            "amount_usdt": round(amount, 2),
            "mode": self.config.mode,
            "type": "DCA",
            "created_at": now.isoformat(),
        }

        self._last_order_at = now.isoformat()
        self._orders.append(order)
        if len(self._orders) > 200:
            self._orders = self._orders[-200:]

        return order

    def _smart_amount(self, df: pd.DataFrame) -> float:
        """波动率加权定投金额计算。"""
        window = min(self.config.volatility_window, len(df))
        recent = df["close"].iloc[-window:]
        returns = recent.pct_change().dropna()
        if returns.empty:
            return self.config.amount_per_order

        vol = float(returns.std())
        avg_vol = 0.02  # 基准波动率 2%

        # 波动越低投越多，波动越高投越少
        weight = avg_vol / (vol + 1e-8) * self.config.volatility_weight
        weight = max(0.3, min(3.0, weight))
        amount = self.config.amount_per_order * weight
        return float(np.clip(amount, self.config.min_order, self.config.max_order))

    def get_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        """返回历史订单列表。"""
        return self._orders[-limit:]
