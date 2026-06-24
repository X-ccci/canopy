"""趋势跟踪策略 — 双均线交叉 + MACD 信号线 + ATR 动态止损。"""

from typing import Any

import numpy as np

from canopy.engine.base import Strategy


class TrendStrategy(Strategy):
    """趋势跟踪策略。

    核心逻辑:
        1. 计算快速 EMA 和慢速 EMA（即 MACD 的快慢线）。
        2. 快线上穿慢线（金叉）→ 做多；快线下穿慢线（死叉）→ 做空。
        3. 持仓期间以 ATR 动态跟踪止损。
        4. 无持仓时生成入场信号，有持仓时仅检查止损，不重复入场。

    默认参数:
        fast_period (int):      快线周期（默认 12）。
        slow_period (int):      慢线周期（默认 26）。
        signal_period (int):    信号线周期（默认 9）。
        atr_period (int):       ATR 周期（默认 14）。
        atr_multiplier (float): ATR 止损倍数（默认 2.0）。
    """

    default_params = {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "atr_period": 14,
        "atr_multiplier": 2.0,
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="TrendStrategy", **kwargs)
        self._closes: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        # 持仓状态：0=空仓，1=做多，-1=做空
        self._position: int = 0
        self._entry_price: float = 0.0
        self._stop_loss: float | None = None

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        """计算指数移动平均。

        Args:
            data:   价格序列。
            period: 周期。

        Returns:
            EMA 序列（与输入等长）。
        """
        alpha = 2.0 / (period + 1)
        result = np.zeros_like(data)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1.0 - alpha) * result[i - 1]
        return result

    @staticmethod
    def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
        """计算 Average True Range。

        Args:
            highs:  最高价序列。
            lows:   最低价序列。
            closes: 收盘价序列。
            period: ATR 周期。

        Returns:
            ATR 序列（与输入等长）。
        """
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        atr = np.zeros(len(closes))
        atr[0] = tr[0] if len(tr) > 0 else 0.0
        alpha = 1.0 / period
        for i in range(1, len(tr) + 1):
            atr[i] = alpha * tr[i - 1] + (1.0 - alpha) * atr[i - 1]
        return atr

    def on_tick(self, ticker: dict) -> None:
        """趋势策略不使用 tick 数据。"""
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
        high = candle["high"]
        low = candle["low"]

        self._closes.append(close)
        self._highs.append(high)
        self._lows.append(low)

        fp = self.params["fast_period"]
        sp = self.params["slow_period"]
        sig_p = self.params["signal_period"]
        atr_p = self.params["atr_period"]
        atr_m = self.params["atr_multiplier"]

        min_len = max(sp, atr_p) + sig_p + 2
        if len(self._closes) < min_len:
            return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "数据不足，等待积累"}

        closes_arr = np.array(self._closes)
        highs_arr = np.array(self._highs)
        lows_arr = np.array(self._lows)

        fast_ema = self._ema(closes_arr, fp)
        slow_ema = self._ema(closes_arr, sp)
        atr = self._atr(highs_arr, lows_arr, closes_arr, atr_p)

        # ── 持仓止损检查 ──
        if self._position == 1:
            # 更新止损位：追踪最高价 - ATR * 倍数
            trail_stop = np.max(highs_arr[-atr_p:]) - atr_m * atr[-1]
            self._stop_loss = max(self._stop_loss or 0, trail_stop)
            if low <= self._stop_loss:
                triggered_sl = self._stop_loss
                self._position = 0
                self._stop_loss = None
                return {
                    "action": "SELL",
                    "price": close,
                    "stop_loss": None,
                    "reason": f"多头 ATR 止损触发 (止损价 {triggered_sl:.2f})",
                }
            return {
                "action": "HOLD",
                "price": close,
                "stop_loss": self._stop_loss,
                "reason": "持仓中，未触发止损",
            }

        if self._position == -1:
            trail_stop = np.min(lows_arr[-atr_p:]) + atr_m * atr[-1]
            self._stop_loss = min(self._stop_loss or float("inf"), trail_stop)
            if high >= self._stop_loss:
                triggered_sl = self._stop_loss
                self._position = 0
                self._stop_loss = None
                return {
                    "action": "BUY",
                    "price": close,
                    "stop_loss": None,
                    "reason": f"空头 ATR 止损触发 (止损价 {triggered_sl:.2f})",
                }
            return {
                "action": "HOLD",
                "price": close,
                "stop_loss": self._stop_loss,
                "reason": "持仓中，未触发止损",
            }

        # ── 无持仓时检测入场信号 ──
        # 金叉：快线上穿慢线
        if fast_ema[-2] <= slow_ema[-2] and fast_ema[-1] > slow_ema[-1]:
            self._position = 1
            self._entry_price = close
            self._stop_loss = close - atr_m * atr[-1]
            return {
                "action": "BUY",
                "price": close,
                "stop_loss": self._stop_loss,
                "reason": f"金叉信号 (快线 {fast_ema[-1]:.2f} > 慢线 {slow_ema[-1]:.2f})",
            }

        # 死叉：快线下穿慢线
        if fast_ema[-2] >= slow_ema[-2] and fast_ema[-1] < slow_ema[-1]:
            self._position = -1
            self._entry_price = close
            self._stop_loss = close + atr_m * atr[-1]
            return {
                "action": "SELL",
                "price": close,
                "stop_loss": self._stop_loss,
                "reason": f"死叉信号 (快线 {fast_ema[-1]:.2f} < 慢线 {slow_ema[-1]:.2f})",
            }

        return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "无信号"}

    def on_order(self, order: dict) -> None:
        """订单状态更新（回测中不使用）。"""
        pass
