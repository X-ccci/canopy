"""
test_backtest_runner.py — 单元测试：BacktestRunner
覆盖正向路径和异常/边界路径。使用 mock 隔离底层引擎依赖。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ── Helper: 构建 mock result 对象 ───────────────────────────
def _mock_result():
    result = MagicMock()
    # 200 点净值曲线
    result.equity_curve = [10000.0 + i * 10 for i in range(200)]
    # 模拟交易记录
    result.trades = [
        {'timestamp': '2025-01-01', 'action': 'BUY', 'price': 50000,
         'size': 0.01, 'pnl': 0, 'reason': 'signal'},
        {'timestamp': '2025-01-02', 'action': 'SELL', 'price': 51000,
         'size': 0.01, 'pnl': 10, 'reason': 'take_profit'},
        {'timestamp': '2025-01-03', 'action': 'BUY', 'price': 50500,
         'size': 0.01, 'pnl': 0, 'reason': 'dip'},
    ]
    return result


def _mock_perf():
    return {
        'final_equity': 11980.0,
        'total_return': 0.198,
        'max_drawdown': 0.05,
        'sharpe_ratio': 1.52,
        'sortino_ratio': 2.10,
        'calmar_ratio': 3.96,
        'win_rate': 0.62,
        'profit_factor': 1.8,
        'total_trades': 45,
    }


# ── BacktestRunner 测试 ─────────────────────────────────────
@patch('canopy.engine.backtest_runner.PerformanceMetrics')
@patch('canopy.engine.backtest_runner.BacktestEngine')
@patch('canopy.engine.backtest_runner.generate_fallback_test_data')
class TestBacktestRunner:
    """用 mock 隔离 BacktestEngine / PerformanceMetrics / fallback data"""

    def test_run_strategy_returns_valid_dict(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()  # DataFrame stub
        mock_engine = mock_engine_cls.return_value
        mock_engine.run.return_value = _mock_result()

        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        result = runner.run_strategy('trend', symbol='ETH/USDT', timeframe='4h',
                                     initial_capital=20000, params={'ma_short': 5})

        assert isinstance(result, dict)
        assert result['strategy'] == 'trend'
        assert result['symbol'] == 'ETH/USDT'
        assert result['timeframe'] == '4h'
        assert result['initial_capital'] == 20000
        assert 'final_equity' in result
        assert 'total_return_pct' in result
        assert 'sharpe_ratio' in result
        assert 'equity_curve' in result
        assert isinstance(result['equity_curve'], list)
        assert len(result['equity_curve']) >= 2
        assert 'trades' in result
        assert isinstance(result['trades'], list)

    def test_run_strategy_truncates_trades_to_50(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()
        mock_engine = mock_engine_cls.return_value
        res = _mock_result()
        # 构造 100 条交易
        res.trades = [{'timestamp': '', 'action': 'BUY', 'price': 1,
                       'size': 0, 'pnl': 0, 'reason': ''}] * 100
        mock_engine.run.return_value = res
        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        result = runner.run_strategy('momentum')
        assert len(result['trades']) == 50

    def test_run_strategy_default_params(self, mock_fallback, mock_engine_cls,
                                         mock_perf_cls):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()
        mock_engine = mock_engine_cls.return_value
        mock_engine.run.return_value = _mock_result()
        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        result = runner.run_strategy('grid')
        assert result['symbol'] == 'BTC/USDT'
        assert result['timeframe'] == '1h'
        assert result['initial_capital'] == 10000

    def test_compare_runs_all_five_strategies(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()
        mock_engine = mock_engine_cls.return_value
        mock_engine.run.return_value = _mock_result()
        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        results = runner.compare()
        assert isinstance(results, list)
        assert len(results) == 5
        strategies = [r['strategy'] for r in results]
        expected = ['trend', 'grid', 'arbitrage', 'momentum', 'mean_reversion']
        assert strategies == expected
        for r in results:
            assert 'total_return_pct' in r
            assert 'sharpe_ratio' in r

    def test_get_last_result_after_run(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()
        mock_engine = mock_engine_cls.return_value
        mock_engine.run.return_value = _mock_result()
        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        assert runner.get_last_result() is None
        runner.run_strategy('trend')
        last = runner.get_last_result()
        assert last is not None
        assert last['strategy'] == 'trend'

    def test_get_last_result_initial_none(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner
        runner = BacktestRunner()
        assert runner.get_last_result() is None

    def test_equity_curve_sampling_preserves_last(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()
        mock_engine = mock_engine_cls.return_value
        res = _mock_result()
        res.equity_curve = list(range(1, 201))  # 200 points
        mock_engine.run.return_value = res
        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        result = runner.run_strategy('trend')
        curve = result['equity_curve']
        assert curve[-1] == 200  # last point preserved

    def test_equity_curve_short_sequence(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()
        mock_engine = mock_engine_cls.return_value
        res = _mock_result()
        res.equity_curve = [10000.0, 10010.0, 10020.0]  # only 3 points
        mock_engine.run.return_value = res
        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        result = runner.run_strategy('trend')
        curve = result['equity_curve']
        assert len(curve) == 3  # ratio=1 for short sequences
        assert curve == [10000.0, 10010.0, 10020.0]

    def test_empty_equity_curve_no_crash(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()
        mock_engine = mock_engine_cls.return_value
        res = _mock_result()
        res.equity_curve = []
        mock_engine.run.return_value = res
        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        result = runner.run_strategy('trend')
        assert result['equity_curve'] == []

    def test_trade_with_missing_keys_uses_defaults(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()
        mock_engine = mock_engine_cls.return_value
        res = _mock_result()
        res.trades = [{}]  # empty dict
        mock_engine.run.return_value = res
        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        result = runner.run_strategy('trend')
        t = result['trades'][0]
        assert t['action'] == 'HOLD'
        assert t['pnl'] == 0

    def test_run_strategy_passes_params_to_engine(
        self, mock_fallback, mock_engine_cls, mock_perf_cls
    ):
        from canopy.engine.backtest_runner import BacktestRunner

        mock_fallback.return_value = MagicMock()
        mock_engine = mock_engine_cls.return_value
        mock_engine.run.return_value = _mock_result()
        mock_perf = mock_perf_cls.return_value
        mock_perf.calculate_all.return_value = _mock_perf()

        runner = BacktestRunner()
        custom_params = {'threshold': 0.02, 'lookback': 20}
        runner.run_strategy('mean_reversion', params=custom_params)
        mock_engine.run.assert_called_once_with('mean_reversion', mock_fallback.return_value,
                                                 custom_params)
