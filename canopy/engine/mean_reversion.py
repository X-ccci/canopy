"""均值回归策略 — Z-Score 偏离度检测 + 布林带辅助确认。"""

from typing import Any

import numpy as np

from canopy.engine.base import Strategy


class MeanReversionStrategy(Strategy):
    """均值回归策略。

    核心逻辑:
        1. 计算移动均线 (MA) 和标准差 (Std)。
        2. Z-Score = (price - MA) / Std。
        3. Z > +entry_z → 超买，做空。
        4. Z < -entry_z → 超卖，做多。
        5. |Z| < exit_z → 平仓。
        6. 布林带辅助确认（价格触碰外轨时增强信号可信度）。

    默认参数:
        ma_period (int):   均线周期（默认 20）。
        std_period (int):  标准差计算周期（默认 20）。
        entry_z (float):   入场 Z-Score 阈值（默认 2.0）。
        exit_z (float):    出场 Z-Score 阈值（默认 0.5）。
    """

    default_params = {
        "ma_period": 20,
        "std_period": 20,
        "entry_z": 2.0,
        "exit_z": 0.5,
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="MeanReversionStrategy", **kwargs)
        self._closes: list[float] = []
        self._position: int = 0  # 1=做多, -1=做空

    def on_tick(self, ticker: dict) -> None:
        """均值回归策略不使用 tick 数据。"""
        pass

    def on_bar(self, candle: dict) -> dict:
        """处理每根 K 线，返回交易信号。

        Args:
            candle: OHLCV 字典，包含 timestamp/open/high/low/close/volume。

        Returns:
            信号字典: {'action': 'BUY'|'SELL'|'HOLD', 'price': float,
                      'stop_loss': float|None, 'reason': str}
        """
        close = candle["close"]
        self._closes.append(close)

        ma_p = self.params["ma_period"]
        std_p = self.params["std_period"]
        entry_z = self.params["entry_z"]
        exit_z = self.params["exit_z"]

        period = max(ma_p, std_p)
        if len(self._closes) < period + 1:
            return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "数据不足，等待积累"}

        closes_arr = np.array(self._closes)
        ma = np.mean(closes_arr[-ma_p:])
        std = np.std(closes_arr[-std_p:], ddof=1)

        if std == 0 or np.isclose(std, 0.0):
            return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "标准差为零，无法计算 Z-Score"}

        z_score = (close - ma) / std
        bollinger_upper = ma + 2.0 * std
        bollinger_lower = ma - 2.0 * std

        # ── 持仓平仓检查 ──
        if self._position != 0:
            if abs(z_score) <= exit_z:
                action = "SELL" if self._position == 1 else "BUY"
                self._position = 0
                return {
                    "action": action,
                    "price": close,
                    "stop_loss": None,
                    "reason": f"Z-Score 回归至 {z_score:.3f}，触发平仓 (阈值 ±{exit_z})",
                }
            return {
                "action": "HOLD",
                "price": close,
                "stop_loss": None,
                "reason": f"持仓中，Z={z_score:.3f}，未触及出场阈值 ±{exit_z}",
            }

        # ── 入场信号 ──
        if z_score > entry_z:
            self._position = -1
            bb_touch = "，触碰布林上轨" if close >= bollinger_upper else ""
            return {
                "action": "SELL",
                "price": close,
                "stop_loss": None,
                "reason": f"Z-Score={z_score:.3f} > +{entry_z}，超买做空{bb_touch}",
            }

        if z_score < -entry_z:
            self._position = 1
            bb_touch = "，触碰布林下轨" if close <= bollinger_lower else ""
            return {
                "action": "BUY",
                "price": close,
                "stop_loss": None,
                "reason": f"Z-Score={z_score:.3f} < -{entry_z}，超卖做多{bb_touch}",
            }

        return {"action": "HOLD", "price": close, "stop_loss": None, "reason": f"Z-Score={z_score:.3f}，未触发入场"}

    def on_order(self, order: dict) -> None:
        """订单状态更新（回测中不使用）。"""
        pass
