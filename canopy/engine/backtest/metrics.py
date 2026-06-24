"""
绩效指标计算：基于净值和交易记录计算 Sharpe / Sortino / Calmar / 胜率等。
"""
import math
from typing import Optional


class PerformanceMetrics:
    """绩效指标计算器。"""

    def __init__(self, equity_curve: list[float], trades: list[dict],
                 risk_free_rate: float = 0.0):
        self.equity = [float(e) for e in equity_curve]
        self.trades = trades
        self.rf = risk_free_rate

    def calculate_all(self) -> dict:
        """计算所有指标。"""
        returns = self._daily_returns()
        losing_trades = [t for t in self.trades if t.get('pnl', 0) < 0]
        winning_trades = [t for t in self.trades if t.get('pnl', 0) > 0]

        total_return = self._total_return()
        max_dd = self._max_drawdown()
        sharpe = self._sharpe_ratio(returns)
        sortino = self._sortino_ratio(returns)
        calmar = self._calmar_ratio(total_return, max_dd)
        win_rate = self._win_rate()
        profit_factor = self._profit_factor(winning_trades, losing_trades)

        return {
            'final_equity': round(self.equity[-1], 2) if self.equity else 10000,
            'total_return': round(total_return, 4),
            'max_drawdown': round(max_dd, 4),
            'sharpe_ratio': round(sharpe, 2),
            'sortino_ratio': round(sortino, 2),
            'calmar_ratio': round(calmar, 2),
            'win_rate': round(win_rate, 4),
            'profit_factor': round(profit_factor, 2),
            'total_trades': len(self.trades)
        }

    def _daily_returns(self) -> list[float]:
        """从净值曲线推导逐日收益率。"""
        if len(self.equity) < 2:
            return []
        returns = []
        for i in range(1, len(self.equity)):
            if self.equity[i - 1] == 0:
                returns.append(0.0)
            else:
                returns.append(self.equity[i] / self.equity[i - 1] - 1)
        return returns

    def _total_return(self) -> float:
        if not self.equity or self.equity[0] == 0:
            return 0
        return self.equity[-1] / self.equity[0] - 1

    def _max_drawdown(self) -> float:
        if not self.equity:
            return 0
        peak = self.equity[0]
        max_dd = 0.0
        for v in self.equity:
            if v > peak:
                peak = v
            if peak > 0:
                dd = (peak - v) / peak
                max_dd = max(max_dd, dd)
        return max_dd

    def _sharpe_ratio(self, returns: list[float]) -> float:
        n = len(returns)
        if n < 2:
            return 0
        mean_r = sum(returns) / n
        var = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(var) if var > 0 else 0
        if std == 0:
            return 0
        return (mean_r - self.rf / 252) / std * math.sqrt(252)

    def _sortino_ratio(self, returns: list[float]) -> float:
        n = len(returns)
        if n < 2:
            return 0
        mean_r = sum(returns) / n
        downside = [r for r in returns if r < 0]
        if not downside:
            return 999 if mean_r > 0 else 0
        dvar = sum(r ** 2 for r in downside) / n
        dstd = math.sqrt(dvar) if dvar > 0 else 0
        if dstd == 0:
            return 0
        return (mean_r - self.rf / 252) / dstd * math.sqrt(252)

    def _calmar_ratio(self, total_return: float, max_drawdown: float) -> float:
        if max_drawdown == 0:
            return 999 if total_return > 0 else 0
        return total_return / max_drawdown

    def _win_rate(self) -> float:
        if not self.trades:
            return 0
        wins = sum(1 for t in self.trades if t.get('pnl', 0) > 0)
        return wins / len(self.trades)

    def _profit_factor(self, winning: list[dict], losing: list[dict]) -> float:
        gross_profit = sum(t.get('pnl', 0) for t in winning)
        gross_loss = abs(sum(t.get('pnl', 0) for t in losing))
        if gross_loss == 0:
            return 999 if gross_profit > 0 else 0
        return gross_profit / gross_loss
