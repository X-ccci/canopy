"""套利策略 — 跨交易所价差套利，低买高卖同时执行。"""

from typing import Any

import numpy as np

from canopy.engine.base import Strategy


class ArbitrageStrategy(Strategy):
    """跨交易所套利策略。

    核心逻辑:
        1. 接收两个交易所的 ticker 数据（通过 on_dual_ticker）。
        2. 计算跨所价差百分比。
        3. 价差超过 min_spread_pct 时，在低价所买入、高价所卖出。
        4. 控制最大持仓量防止风险过度暴露。

    默认参数:
        min_spread_pct (float): 最小价差百分比（默认 0.5，即 0.5%）。
        max_position (float):   单边最大持仓量（默认 1.0）。
    """

    default_params = {
        "min_spread_pct": 0.5,
        "max_position": 1.0,
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="ArbitrageStrategy", **kwargs)
        self._in_position: bool = False

    def on_tick(self, ticker: dict) -> None:
        """套利策略使用 on_dual_ticker 而非 on_tick。"""
        pass

    def on_bar(self, candle: dict) -> dict:
        """套利策略使用 on_dual_ticker 而非 on_bar。"""
        return {"action": "HOLD", "price": candle["close"], "stop_loss": None,
                "reason": "请使用 on_dual_ticker 方法"}

    def on_dual_ticker(self, ticker_a: dict, ticker_b: dict) -> dict:
        """处理两个交易所的行情，生成套利信号。

        Args:
            ticker_a: 交易所 A 的 ticker，包含 'exchange'/'bid'/'ask'/'last'。
            ticker_b: 交易所 B 的 ticker，包含 'exchange'/'bid'/'ask'/'last'。

        Returns:
            信号字典: {'action': 'ARB_BUY_SELL'|'HOLD', 'buy_exchange': str,
                      'sell_exchange': str, 'buy_price': float,
                      'sell_price': float, 'spread_pct': float, 'amount': float}
        """
        min_spread = self.params["min_spread_pct"]
        max_pos = self.params["max_position"]

        if self._in_position:
            return {
                "action": "HOLD",
                "buy_exchange": "",
                "sell_exchange": "",
                "buy_price": 0.0,
                "sell_price": 0.0,
                "spread_pct": 0.0,
                "amount": 0.0,
            }

        price_a = ticker_a.get("last", ticker_a.get("bid", 0))
        price_b = ticker_b.get("last", ticker_b.get("ask", 0))

        if price_a <= 0 or price_b <= 0:
            return {
                "action": "HOLD",
                "buy_exchange": "",
                "sell_exchange": "",
                "buy_price": 0.0,
                "sell_price": 0.0,
                "spread_pct": 0.0,
                "amount": 0.0,
            }

        # 计算价差百分比（卖价-买价）/ 买价 * 100
        if price_a < price_b:
            spread_pct = (price_b - price_a) / price_a * 100
            if spread_pct >= min_spread:
                self._in_position = True
                return {
                    "action": "ARB_BUY_SELL",
                    "buy_exchange": ticker_a.get("exchange", "A"),
                    "sell_exchange": ticker_b.get("exchange", "B"),
                    "buy_price": price_a,
                    "sell_price": price_b,
                    "spread_pct": spread_pct,
                    "amount": max_pos,
                }
        else:
            spread_pct = (price_a - price_b) / price_b * 100
            if spread_pct >= min_spread:
                self._in_position = True
                return {
                    "action": "ARB_BUY_SELL",
                    "buy_exchange": ticker_b.get("exchange", "B"),
                    "sell_exchange": ticker_a.get("exchange", "A"),
                    "buy_price": price_b,
                    "sell_price": price_a,
                    "spread_pct": spread_pct,
                    "amount": max_pos,
                }

        return {
            "action": "HOLD",
            "buy_exchange": "",
            "sell_exchange": "",
            "buy_price": 0.0,
            "sell_price": 0.0,
            "spread_pct": 0.0,
            "amount": 0.0,
        }

    def on_order(self, order: dict) -> None:
        """订单成交后释放持仓标记。"""
        if order.get("status") == "filled":
            self._in_position = False
