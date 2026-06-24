"""
回测引擎：模拟策略在历史数据上的运行，追踪净值曲线和交易记录。
"""
from dataclasses import dataclass, field

import pandas as pd

from canopy.engine.factory import StrategyFactory


@dataclass
class BacktestResult:
    """回测结果容器。"""
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    initial_capital: float = 10000
    final_equity: float = 10000


class BacktestEngine:
    """简易回测引擎。

    遍历 OHLCV DataFrame，逐根 K 线调用策略 on_bar()，
    根据返回的信号模拟成交并更新净值和交易记录。
    """

    def __init__(self, initial_capital: float = 10000):
        self.initial_capital = initial_capital

    def run(self, strategy_type: str, df: pd.DataFrame,
            params: dict | None = None) -> BacktestResult:
        """运行回测。

        Args:
            strategy_type: 策略类型名（已注册在 StrategyFactory 中）。
            df:            OHLCV DataFrame，列必须包含 timestamp/open/high/low/close/volume。
            params:        策略参数。

        Returns:
            BacktestResult。
        """
        params = params or {}

        factory = StrategyFactory()
        factory._register_builtins()
        strategy = factory.create(strategy_type, **params)

        result = BacktestResult(initial_capital=self.initial_capital)
        equity = self.initial_capital
        position = 0  # 持仓数量（正：多头，负：空头）
        entry_price = 0

        for _, row in df.iterrows():
            candle = {
                'timestamp': str(row.get('timestamp', '')),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row.get('volume', 0))
            }

            signal = strategy.on_bar(candle)
            close = candle['close']
            action = signal.get('action', 'HOLD')
            price = signal.get('price', close)

            trade_pnl = 0

            if action == 'BUY' and position <= 0:
                # 平空仓（如有）再开多仓
                if position < 0:
                    trade_pnl = (entry_price - price) * abs(position)
                    equity += trade_pnl
                position = equity * 0.5 / price
                entry_price = price
            elif action == 'SELL' and position >= 0:
                if position > 0:
                    trade_pnl = (price - entry_price) * position
                    equity += trade_pnl
                position = -equity * 0.5 / price
                entry_price = price

            # 逐根记录净值（未实现盈亏浮动计入）
            unrealized = 0
            if position > 0:
                unrealized = (close - entry_price) * position  # type: ignore[operator]
            elif position < 0:
                unrealized = (entry_price - close) * abs(position)  # type: ignore[operator]

            current_equity = equity + unrealized
            result.equity_curve.append(round(current_equity, 2))

            if action != 'HOLD':
                result.trades.append({
                    'timestamp': candle['timestamp'],
                    'action': action,
                    'price': price,
                    'size': round(abs(position), 4),
                    'pnl': round(trade_pnl, 2),
                    'reason': signal.get('reason', '')
                })

        # 最终平仓
        if position != 0 and len(df) > 0 and len(result.trades) > 0:
            last_close = float(df.iloc[-1]['close'])
            if position > 0:
                final_pnl = (last_close - entry_price) * position
            else:
                final_pnl = (entry_price - last_close) * abs(position)
            equity += final_pnl
            result.trades.append({
                'timestamp': str(df.iloc[-1].get('timestamp', '')),
                'action': 'CLOSE',
                'price': last_close,
                'size': round(abs(position), 4),
                'pnl': round(final_pnl, 2),
                'reason': 'End of backtest'
            })

        result.final_equity = round(equity, 2)
        return result
