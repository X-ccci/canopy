"""动量突破策略 — Donchian 通道突破 + 成交量确认 + ATR 动态止损。"""

from typing import Any

import numpy as np

from canopy.engine.base import Strategy


class MomentumStrategy(Strategy):
    """动量突破策略。

    核心逻辑:
        1. 计算过去 lookback 根 K 线最高价和最低价作为 Donchian 通道。
        2. 价格突破上轨且成交量放大（可选）→ 做多。
        3. 价格跌破下轨且成交量放大（可选）→ 做空。
        4. 以 ATR 动态止损跟踪持仓。

    默认参数:
        lookback (int):          回溯周期（默认 20）。
        entry_threshold (float): 突破阈值比例（默认 0.6）。
        volume_confirm (bool):   是否启用成交量确认（默认 True）。
        atr_period (int):        ATR 周期（默认 14）。
        atr_multiplier (float):  ATR 止损倍数（默认 2.5）。
    """

    default_params = {
        "lookback": 20,
        "entry_threshold": 0.6,
        "volume_confirm": True,
        "atr_period": 14,
        "atr_multiplier": 2.5,
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="MomentumStrategy", **kwargs)
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._volumes: list[float] = []
        self._position: int = 0
        self._stop_loss: float | None = None

    @staticmethod
    def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
        """计算 Average True Range。"""
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
        """动量策略不使用 tick 数据。"""
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
        volume = candle.get("volume", 0)

        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)
        self._volumes.append(volume)

        lookback = self.params["lookback"]
        entry_th = self.params["entry_threshold"]
        vol_confirm = self.params["volume_confirm"]
        atr_p = self.params["atr_period"]
        atr_m = self.params["atr_multiplier"]

        min_len = lookback + atr_p + 2
        if len(self._closes) < min_len:
            return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "数据不足，等待积累"}

        highs_arr = np.array(self._highs)
        lows_arr = np.array(self._lows)
        closes_arr = np.array(self._closes)
        volumes_arr = np.array(self._volumes)
        atr = self._atr(highs_arr, lows_arr, closes_arr, atr_p)

        # ── 止损检查 ──
        if self._position == 1:
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

        # ── Donchian Channel ──
        upper_channel = np.max(highs_arr[-lookback - 1 : -1])
        lower_channel = np.min(lows_arr[-lookback - 1 : -1])
        # 突破阈值缓冲：价格需超过通道一定比例
        upper_threshold = upper_channel * (1.0 + entry_th / 100.0)
        lower_threshold = lower_channel * (1.0 - entry_th / 100.0)

        # 成交量确认
        avg_vol = np.mean(volumes_arr[-lookback - 1 : -1]) if len(volumes_arr) >= lookback + 1 else 0
        vol_ok = not vol_confirm or (avg_vol > 0 and volume >= avg_vol)

        # 突破上轨
        if close > upper_threshold and vol_ok:
            self._position = 1
            self._stop_loss = close - atr_m * atr[-1]
            return {
                "action": "BUY",
                "price": close,
                "stop_loss": self._stop_loss,
                "reason": f"突破上轨 {upper_channel:.2f} (阈值 {upper_threshold:.2f}, 成交量确认: {vol_ok})",
            }

        # 跌破下轨
        if close < lower_threshold and vol_ok:
            self._position = -1
            self._stop_loss = close + atr_m * atr[-1]
            return {
                "action": "SELL",
                "price": close,
                "stop_loss": self._stop_loss,
                "reason": f"跌破下轨 {lower_channel:.2f} (阈值 {lower_threshold:.2f}, 成交量确认: {vol_ok})",
            }

        return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "无突破信号"}

    def on_order(self, order: dict) -> None:
        """订单状态更新（回测中不使用）。"""
        pass
