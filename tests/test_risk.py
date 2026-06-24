"""
test_risk.py — 单元测试：RiskConfig / CircuitBreaker / RiskManager
覆盖正向路径和异常/边界路径。
"""
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from canopy.engine.risk import RiskConfig, CircuitBreaker, RiskManager, Position


# ── RiskConfig ──────────────────────────────────────────────
class TestRiskConfig:
    def test_default_values(self):
        config = RiskConfig()
        assert config.max_position_pct == 0.05
        assert config.max_total_exposure == 0.8
        assert config.max_drawdown_pct == 0.15
        assert config.max_daily_loss_pct == 0.05
        assert config.min_volatility_filter == 0.005
        assert config.max_volatility_filter == 0.08

    def test_custom_values(self):
        config = RiskConfig(
            max_position_pct=0.1,
            max_total_exposure=0.5,
            max_drawdown_pct=0.2
        )
        assert config.max_position_pct == 0.1
        assert config.max_total_exposure == 0.5
        assert config.max_drawdown_pct == 0.2

    def test_to_dict(self):
        config = RiskConfig()
        d = config.to_dict()
        assert d['max_position_pct'] == 0.05
        assert 'max_total_exposure' in d


# ── CircuitBreaker ──────────────────────────────────────────
class TestCircuitBreaker:
    def test_initial_state_not_tripped(self):
        cb = CircuitBreaker()
        assert cb.is_tripped is False
        assert cb.status['tripped'] is False

    def test_trip_sets_state_and_reason(self):
        cb = CircuitBreaker()
        cb.trip("Max drawdown exceeded")
        assert cb.is_tripped is True
        assert "Max drawdown" in cb.status['reason']
        assert cb.status['tripped_at'] is not None

    def test_reset_clears_state(self):
        cb = CircuitBreaker()
        cb.trip("Test trip")
        cb.reset()
        assert cb.is_tripped is False
        assert cb.status['reason'] == ''
        assert cb.status['tripped_at'] is None

    def test_status_dict_structure(self):
        cb = CircuitBreaker()
        s = cb.status
        assert 'tripped' in s
        assert 'reason' in s
        assert 'tripped_at' in s


# ── RiskManager ─────────────────────────────────────────────
class TestRiskManager:
    SAMPLE_SIGNAL = {
        'action': 'BUY',
        'symbol': 'BTC/USDT',
        'price': 50000.0,
        'quantity': 0.01
    }

    def test_approve_normal_signal(self):
        rm = RiskManager(initial_balance=100000.0)
        approved, reason, order = rm.approve(self.SAMPLE_SIGNAL, current_price=50000.0)
        assert approved is True
        assert 'Approved' in reason
        assert order is not None
        assert order['symbol'] == 'BTC/USDT'
        assert order['action'] == 'BUY'
        assert order['quantity'] > 0

    def test_approve_hold_signal_rejected(self):
        rm = RiskManager()
        hold_signal = {'action': 'HOLD', 'symbol': 'BTC/USDT', 'price': 50000.0}
        approved, reason, order = rm.approve(hold_signal, current_price=50000.0)
        assert approved is False
        assert 'HOLD' in reason.upper()
        assert order is None

    def test_circuit_breaker_blocks_all(self):
        rm = RiskManager()
        rm.circuit_breaker.trip("Test trip")
        approved, reason, order = rm.approve(self.SAMPLE_SIGNAL, current_price=50000.0)
        assert approved is False
        assert "Circuit breaker" in reason
        assert order is None

    def test_drawdown_exceeds_limit_trips_breaker(self):
        # Disable daily loss to isolate drawdown check
        config = RiskConfig(max_daily_loss_pct=0.99, max_drawdown_pct=0.15)
        rm = RiskManager(config=config, initial_balance=100000.0)
        rm.peak_balance = 100000.0
        rm.current_balance = 80000.0  # 20% drawdown, exceeds 15% limit
        approved, reason, order = rm.approve(self.SAMPLE_SIGNAL, current_price=50000.0)
        assert approved is False
        assert "drawdown" in reason.lower()
        assert rm.circuit_breaker.is_tripped is True

    def test_drawdown_within_limit_pass(self):
        # Disable daily loss to isolate drawdown check
        config = RiskConfig(max_daily_loss_pct=0.99, max_drawdown_pct=0.15)
        rm = RiskManager(config=config, initial_balance=100000.0)
        rm.peak_balance = 100000.0
        rm.current_balance = 95000.0  # 5% drawdown
        approved, _, _ = rm.approve(self.SAMPLE_SIGNAL, current_price=50000.0)
        assert approved is True

    def test_daily_loss_exceeds_limit_trips_breaker(self):
        config = RiskConfig(max_daily_loss_pct=0.03, max_drawdown_pct=0.99)  # disable drawdown
        rm = RiskManager(config=config, initial_balance=100000.0)
        rm._daily_start_balance = 100000.0
        rm.current_balance = 96000.0
        rm.daily_pnl = -4000.0
        approved, reason, _ = rm.approve(self.SAMPLE_SIGNAL, current_price=50000.0)
        assert approved is False
        assert "daily" in reason.lower()

    def test_exposure_limit_blocks(self):
        config = RiskConfig(max_total_exposure=0.01, max_position_pct=0.05)
        rm = RiskManager(config=config, initial_balance=100000.0)
        # 已有 5000 敞口时，再开 5000 就超 1% 限额
        rm.update_position('ETH/USDT', 'LONG', 2000.0, 2.5, 2000.0)
        approved, reason, _ = rm.approve(self.SAMPLE_SIGNAL, current_price=50000.0)
        assert approved is False
        assert "Exposure" in reason

    def test_approve_with_account_balance_override(self):
        rm = RiskManager(initial_balance=10000.0)
        approved, _, order = rm.approve(
            self.SAMPLE_SIGNAL, current_price=50000.0, account_balance=50000.0
        )
        assert approved is True
        expected_qty = 50000.0 * 0.05 / 50000.0  # max_position_pct=0.05
        assert order['quantity'] == pytest.approx(expected_qty)

    def test_update_position_creates_entry(self):
        rm = RiskManager()
        rm.update_position('BTC/USDT', 'LONG', 50000.0, 0.01, 51000.0)
        pos = rm.positions.get('BTC/USDT')
        assert pos is not None
        assert pos.side == 'LONG'
        assert pos.unrealized_pnl == pytest.approx(10.0)

    def test_update_position_short_pnl(self):
        rm = RiskManager()
        rm.update_position('BTC/USDT', 'SHORT', 50000.0, 0.01, 49000.0)
        pos = rm.positions.get('BTC/USDT')
        assert pos.unrealized_pnl == pytest.approx(10.0)

    def test_close_position_removes(self):
        rm = RiskManager()
        rm.update_position('BTC/USDT', 'LONG', 50000.0, 0.01)
        assert 'BTC/USDT' in rm.positions
        rm.close_position('BTC/USDT')
        assert 'BTC/USDT' not in rm.positions

    def test_close_nonexistent_position_no_error(self):
        rm = RiskManager()
        rm.close_position('NONEXISTENT')

    def test_reset_circuit_breaker(self):
        rm = RiskManager()
        rm.circuit_breaker.trip("test")
        result = rm.reset_circuit_breaker()
        assert result == 'Circuit breaker reset'
        assert rm.circuit_breaker.is_tripped is False

    def test_get_status_returns_valid_dict(self):
        rm = RiskManager()
        status = rm.get_status()
        assert 'circuit_breaker' in status
        assert 'current_balance' in status
        assert 'drawdown_pct' in status
        assert 'daily_pnl' in status
        assert 'open_positions' in status
        assert 'config' in status

    def test_get_status_zero_balance_no_div0(self):
        rm = RiskManager(initial_balance=0.0)
        rm.current_balance = 0.0
        rm.peak_balance = 0.0
        status = rm.get_status()
        assert isinstance(status['total_exposure'], (int, float))

    def test_update_balance_updates_peak(self):
        rm = RiskManager(initial_balance=10000.0)
        rm.update_balance(12000.0)
        assert rm.peak_balance == 12000.0
        assert rm.current_balance == 12000.0

    def test_update_balance_does_not_lower_peak(self):
        rm = RiskManager(initial_balance=10000.0)
        rm.update_balance(12000.0)
        rm.update_balance(9000.0)
        assert rm.peak_balance == 12000.0
        assert rm.current_balance == 9000.0

    def test_decision_log_accumulates(self):
        rm = RiskManager(initial_balance=100000.0)
        for i in range(5):
            rm.approve(self.SAMPLE_SIGNAL, current_price=50000.0)
        assert len(rm._decision_log) == 5

    def test_daily_reset_on_new_day(self):
        rm = RiskManager(initial_balance=100000.0)
        rm._daily_start_balance = 100000.0
        rm.daily_pnl = -3000.0
        rm._last_check_day = 99  # different from real today
        # running _update_daily via approve updates the day counter
        approved, _, _ = rm.approve(self.SAMPLE_SIGNAL, current_price=50000.0)
        # daily should have reset
        assert approved is True

    def test_sell_signal_creates_correct_order(self):
        rm = RiskManager(initial_balance=100000.0)
        signal = {'action': 'SELL', 'symbol': 'BTC/USDT', 'price': 60000.0}
        approved, _, order = rm.approve(signal, current_price=60000.0)
        assert approved is True
        assert order['side'] == 'sell'

    def test_signal_without_price_uses_current(self):
        rm = RiskManager(initial_balance=100000.0)
        signal = {'action': 'BUY', 'symbol': 'ETH/USDT'}
        approved, _, order = rm.approve(signal, current_price=2000.0)
        assert approved is True
        assert order['price'] == 2000.0

    def test_signal_without_symbol_defaults(self):
        rm = RiskManager(initial_balance=100000.0)
        signal = {'action': 'BUY'}
        approved, _, order = rm.approve(signal, current_price=100.0)
        assert approved is True
        assert order['symbol'] == 'UNKNOWN'
