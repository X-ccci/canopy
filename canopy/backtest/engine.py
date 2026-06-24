"""回测引擎 — 事件驱动循环、撮合模拟、交易记录与权益曲线。"""

from typing import Any

import numpy as np

from canopy.engine.base import Strategy
from canopy.backtest import metrics as bt_metrics


class BacktestEngine:
    """事件驱动回测引擎。

    遍历历史 K 线，调用策略生成信号，模拟成交（含手续费和滑点），
    记录每笔完整交易和每日权益曲线，最终输出绩效报告。

    Attributes:
        initial_capital: 初始资金。
        commission:      手续费率（入场和出场各收一次）。
        slippage:        滑点比例（市价单成交价恶化比例）。
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission: float = 0.001,
        slippage: float = 0.0005,
    ) -> None:
        """初始化回测引擎。

        Args:
            initial_capital: 初始资金。
            commission:      手续费率（小数，默认 0.1%）。
            slippage:        滑点比例（小数，默认 0.05%）。
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.capital = initial_capital
        self._trades: list[dict] = []
        self._equity_curve: list[float] = []
        self._position: int = 0
        self._entry_price: float = 0.0
        self._entry_time: str = ""
        self._amount: float = 0.0

    def run(self, strategy: Strategy, candles: list[dict]) -> dict:
        """运行回测。

        Args:
            strategy: 策略实例。
            candles:  OHLCV 数据列表，每项含 timestamp/open/high/low/close/volume。

        Returns:
            结果字典: {'trades': [...], 'equity_curve': [...], 'metrics': {...}}。
        """
        strategy.start()

        for candle in sorted(candles, key=lambda c: c["timestamp"]):
            signal = strategy.on_bar(candle)
            self._process_signal(signal, candle)
            self._record_equity(candle)

        strategy.stop()
        return self.get_results()

    def _process_signal(self, signal: dict, candle: dict) -> None:
        """处理策略信号，模拟成交。"""
        action = signal.get("action", "HOLD")
        close = candle["close"]
        timestamp = candle["timestamp"]

        if action == "HOLD":
            return

        if action == "BUY":
            if self._position == -1:
                self._close_position(close, timestamp)
            if self._position == 0:
                self._open_position("LONG", signal.get("price", close), timestamp)

        elif action == "SELL":
            if self._position == 1:
                self._close_position(close, timestamp)
            if self._position == 0:
                self._open_position("SHORT", signal.get("price", close), timestamp)

        elif action == "ARB_BUY_SELL":
            self._process_arb(signal, timestamp)

    def _open_position(self, side: str, price: float, timestamp: str) -> None:
        """开仓。

        Args:
            side:      'LONG' 或 'SHORT'。
            price:     信号价格（滑点前的参考价）。
            timestamp: 当前时间戳。
        """
        position_pct = 0.5
        self._amount = (self.capital * position_pct) / price
        if self._amount <= 0:
            return

        if side == "LONG":
            fill_price = price * (1.0 + self.slippage)
            cost = self._amount * fill_price * (1.0 + self.commission)
            self.capital -= cost
            self._position = 1
        else:
            fill_price = price * (1.0 - self.slippage)
            proceeds = self._amount * fill_price * (1.0 - self.commission)
            self.capital += proceeds
            self._position = -1

        self._entry_price = fill_price
        self._entry_time = timestamp

    def _close_position(self, price: float, timestamp: str) -> None:
        """平仓并记录交易。

        Args:
            price:     平仓参考价格（滑点前）。
            timestamp: 当前时间戳。
        """
        if self._position == 0 or self._amount <= 0:
            return

        if self._position == 1:
            # 多头平仓：卖出
            fill_price_exit = price * (1.0 - self.slippage)
            exit_proceeds = self._amount * fill_price_exit * (1.0 - self.commission)
            entry_cost = self._amount * self._entry_price * (1.0 + self.commission)
            pnl = exit_proceeds - entry_cost
            self.capital += exit_proceeds
        else:
            # 空头平仓：买入回补
            fill_price_exit = price * (1.0 + self.slippage)
            exit_cost = self._amount * fill_price_exit * (1.0 + self.commission)
            entry_proceeds = self._amount * self._entry_price * (1.0 - self.commission)
            pnl = entry_proceeds - exit_cost
            self.capital -= exit_cost

        side_str = "LONG" if self._position == 1 else "SHORT"
        self._trades.append({
            "entry_time": self._entry_time,
            "exit_time": timestamp,
            "entry_price": round(self._entry_price, 4),
            "exit_price": round(fill_price_exit, 4),
            "side": side_str,
            "amount": round(self._amount, 6),
            "pnl": round(pnl, 4),
        })

        self._position = 0
        self._entry_price = 0.0
        self._amount = 0.0

    def _process_arb(self, signal: dict, timestamp: str) -> None:
        """处理套利信号。"""
        buy_price = signal.get("buy_price", 0)
        sell_price = signal.get("sell_price", 0)
        amount = signal.get("amount", 0)

        if buy_price <= 0 or sell_price <= 0 or amount <= 0:
            return

        buy_fill = buy_price * (1.0 + self.slippage)
        buy_cost = amount * buy_fill * (1.0 + self.commission)
        sell_fill = sell_price * (1.0 - self.slippage)
        sell_proceeds = amount * sell_fill * (1.0 - self.commission)

        pnl = sell_proceeds - buy_cost
        self.capital += pnl

        self._trades.append({
            "entry_time": timestamp,
            "exit_time": timestamp,
            "entry_price": round(buy_fill, 4),
            "exit_price": round(sell_fill, 4),
            "side": "ARB",
            "amount": round(amount, 6),
            "pnl": round(pnl, 4),
        })

    def _record_equity(self, candle: dict) -> None:
        """记录当前权益（含未平仓市值）。"""
        equity = self.capital
        if self._position != 0 and self._amount > 0:
            close = candle["close"]
            if self._position == 1:
                equity += self._amount * close
            else:
                equity -= self._amount * close
        self._equity_curve.append(equity)

    def get_results(self) -> dict:
        """计算并返回回测结果。"""
        if not self._trades:
            return {
                "trades": [],
                "equity_curve": self._equity_curve,
                "metrics": {
                    "total_return": 0.0, "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0, "win_rate": 0.0,
                    "profit_factor": 0.0, "calmar_ratio": 0.0,
                    "sortino_ratio": 0.0, "total_trades": 0,
                },
            }

        equity_arr = np.array(self._equity_curve)
        returns_arr = np.diff(equity_arr) / equity_arr[:-1] if len(equity_arr) > 1 else np.array([0.0])
        final_equity = self._equity_curve[-1] if self._equity_curve else self.capital
        total_return = (final_equity - self.initial_capital) / self.initial_capital

        return {
            "trades": self._trades,
            "equity_curve": self._equity_curve,
            "metrics": {
                "total_return": round(total_return, 6),
                "sharpe_ratio": round(bt_metrics.sharpe_ratio(returns_arr, risk_free_rate=0.02), 4),
                "max_drawdown": round(bt_metrics.max_drawdown(equity_arr), 4),
                "win_rate": round(bt_metrics.win_rate(self._trades), 4),
                "profit_factor": round(bt_metrics.profit_factor(self._trades), 4),
                "calmar_ratio": round(bt_metrics.calmar_ratio(returns_arr, equity_arr), 4),
                "sortino_ratio": round(bt_metrics.sortino_ratio(returns_arr, risk_free_rate=0.02), 4),
                "total_trades": len(self._trades),
            },
        }
