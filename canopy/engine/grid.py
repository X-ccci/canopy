"""网格交易策略 — 在预设价格区间内布设买卖网格，价格穿越网格线自动触发交易。"""

from typing import Any

import numpy as np

from canopy.engine.base import Strategy


class GridStrategy(Strategy):
    """网格交易策略。

    核心逻辑:
        1. 在 upper_price 和 lower_price 之间生成等距或等比网格线。
        2. 价格向上穿越网格线 → 卖出（做空方向则买入）。
        3. 价格向下穿越网格线 → 买入（做空方向则卖出）。
        4. 维护已触发网格集合，避免重复触发同一层网格。

    默认参数:
        grid_count (int):      网格层数（默认 10）。
        upper_price (float):   网格上限。
        lower_price (float):   网格下限。
        order_amount (float):  每格下单量（默认 0.01）。
        mode (str):            网格模式 'arithmetic' | 'geometric'。
    """

    default_params = {
        "grid_count": 10,
        "upper_price": 0.0,
        "lower_price": 0.0,
        "order_amount": 0.01,
        "mode": "arithmetic",
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="GridStrategy", **kwargs)
        self._initialized: bool = False
        self._grid_lines: np.ndarray | None = None
        self._triggered: set[int] = set()
        self._last_price: float | None = None

    def _init_grid(self) -> None:
        """根据参数生成网格线数组。"""
        upper = self.params["upper_price"]
        lower = self.params["lower_price"]
        count = self.params["grid_count"]
        mode = self.params["mode"]

        if upper <= lower or count < 2:
            raise ValueError(f"无效网格参数: upper={upper}, lower={lower}, count={count}")

        if mode == "arithmetic":
            self._grid_lines = np.linspace(lower, upper, count + 1)
        elif mode == "geometric":
            self._grid_lines = np.geomspace(max(lower, 1e-8), upper, count + 1)
        else:
            raise ValueError(f"不支持的网格模式: {mode}")

        self._initialized = True

    def on_tick(self, ticker: dict) -> None:
        """网格策略不使用 tick 数据。"""
        pass

    def on_bar(self, candle: dict) -> dict:
        """处理每根 K 线，返回交易信号。

        Args:
            candle: OHLCV 字典，包含 timestamp/open/high/low/close/volume。

        Returns:
            信号字典: {'action': 'BUY'|'SELL'|'HOLD', 'price': float,
                      'stop_loss': float|None, 'reason': str}
        """
        if not self._initialized:
            try:
                self._init_grid()
            except ValueError as e:
                return {"action": "HOLD", "price": candle["close"], "stop_loss": None, "reason": str(e)}

        close = candle["close"]
        high = candle["high"]
        low = candle["low"]

        if self._last_price is None:
            self._last_price = close
            return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "初始化完毕，等待下一次价格变动"}

        # 检测价格穿越网格线
        for i, grid_price in enumerate(self._grid_lines if self._grid_lines is not None else []):
            if i in self._triggered:
                continue

            # 价格向上穿过网格线
            if self._last_price < grid_price <= high:
                self._triggered.add(i)
                return {
                    "action": "SELL",
                    "price": grid_price,
                    "stop_loss": None,
                    "reason": f"价格向上穿越网格线 {grid_price:.2f}",
                }

            # 价格向下穿过网格线
            if self._last_price > grid_price >= low:
                self._triggered.add(i)
                return {
                    "action": "BUY",
                    "price": grid_price,
                    "stop_loss": None,
                    "reason": f"价格向下穿越网格线 {grid_price:.2f}",
                }

        self._last_price = close
        return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "未触发任何网格线"}

    def on_order(self, order: dict) -> None:
        """订单状态更新（回测中不使用）。"""
        pass
