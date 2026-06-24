"""
回测运行器：封装 BacktestEngine，提供面向前端的简洁 API。
"""
import json
import numpy as np
from pathlib import Path
from typing import Optional

from canopy.engine.backtest.engine import BacktestEngine
from canopy.engine.backtest.metrics import PerformanceMetrics
from canopy.engine.fallback import generate_fallback_test_data


class BacktestRunner:
    """回测运行器——面向前端的简洁 API"""

    def __init__(self):
        self._last_result: Optional[dict] = None

    def run_strategy(self, strategy_type: str, symbol: str = 'BTC/USDT',
                     timeframe: str = '1h', initial_capital: float = 10000,
                     params: dict = None) -> dict:
        """
        运行单个策略回测，返回完整结果（净值曲线、绩效指标、交易记录）。
        """
        # 生成模拟数据（200 根 K 线）
        df = generate_fallback_test_data(symbol, timeframe, 200)

        # 创建引擎并运行
        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run(strategy_type, df, params or {})

        # 计算绩效指标
        metrics = PerformanceMetrics(result.equity_curve, result.trades)
        perf = metrics.calculate_all()

        # 提取净值曲线（采样，保留 100 个点）
        equity = result.equity_curve
        ratio = max(1, len(equity) // 100)
        sampled = equity[::ratio]
        sampled_list = list(sampled)
        # 确保最后一个点在
        if len(equity) > 0 and (len(equity) - 1) % ratio != 0:
            sampled_list.append(equity[-1])

        # 提取交易记录（最近 50 条）
        trades = []
        for t in result.trades[-50:]:
            trades.append({
                'time': str(t.get('timestamp', '')),
                'action': t.get('action', 'HOLD'),
                'price': t.get('price', 0),
                'size': t.get('size', 0),
                'pnl': t.get('pnl', 0),
                'reason': t.get('reason', '')
            })

        self._last_result = {
            'strategy': strategy_type,
            'symbol': symbol,
            'timeframe': timeframe,
            'initial_capital': initial_capital,
            'final_equity': round(perf.get('final_equity', 0), 2),
            'total_return_pct': round(perf.get('total_return', 0) * 100, 2),
            'max_drawdown_pct': round(perf.get('max_drawdown', 0) * 100, 2),
            'sharpe_ratio': round(perf.get('sharpe_ratio', 0), 2),
            'sortino_ratio': round(perf.get('sortino_ratio', 0), 2),
            'calmar_ratio': round(perf.get('calmar_ratio', 0), 2),
            'win_rate': round(perf.get('win_rate', 0) * 100, 2),
            'profit_factor': round(perf.get('profit_factor', 0), 2),
            'total_trades': perf.get('total_trades', 0),
            'equity_curve': sampled_list,
            'trades': trades
        }
        return self._last_result

    def compare(self, symbol: str = 'BTC/USDT', timeframe: str = '1h',
                initial_capital: float = 10000) -> list:
        """对全部 5 种内置策略逐一遍历，返回对比表格。"""
        strategies = ['trend', 'grid', 'arbitrage', 'momentum', 'mean_reversion']
        results = []
        for s in strategies:
            r = self.run_strategy(s, symbol, timeframe, initial_capital)
            results.append({
                'strategy': s,
                'total_return_pct': r['total_return_pct'],
                'max_drawdown_pct': r['max_drawdown_pct'],
                'sharpe_ratio': r['sharpe_ratio'],
                'win_rate': r['win_rate'],
                'total_trades': r['total_trades'],
                'final_equity': r['final_equity']
            })
        return results

    def get_last_result(self) -> Optional[dict]:
        return self._last_result
