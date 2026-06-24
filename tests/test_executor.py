"""
test_executor.py — 单元测试：Order / OrderExecutor
覆盖正向路径和异常/边界路径。使用 mock 隔离 ExchangeAdapter。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from canopy.engine.executor import Order, OrderExecutor


# ── Order ───────────────────────────────────────────────────
class TestOrder:
    def test_order_from_dict_basic(self):
        order_dict = {
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'type': 'LIMIT',
            'price': 50000.0,
            'quantity': 0.01,
            'approved_at': '2025-06-24T10:00:00'
        }
        o = Order(order_dict)
        assert o.symbol == 'BTC/USDT'
        assert o.side == 'buy'
        assert o.type == 'LIMIT'
        assert o.price == 50000.0
        assert o.quantity == 0.01
        assert o.status == 'PENDING'
        assert o.filled_qty == 0.0
        assert o.created_at == '2025-06-24T10:00:00'

    def test_order_default_values(self):
        o = Order({})
        assert o.symbol == ''
        assert o.side == 'buy'
        assert o.type == 'LIMIT'
        assert o.price == 0.0
        assert o.quantity == 0.0
        assert o.status == 'PENDING'

    def test_order_market_type(self):
        o = Order({'type': 'MARKET', 'symbol': 'ETH/USDT', 'side': 'sell'})
        assert o.type == 'MARKET'
        assert o.side == 'sell'

    def test_order_created_at_fallback(self):
        o = Order({})
        assert o.created_at is not None
        assert len(o.created_at) > 0


# ── OrderExecutor ───────────────────────────────────────────
class TestOrderExecutor:
    @pytest.fixture
    def mock_adapter(self):
        return MagicMock()

    @pytest.fixture
    def mock_risk(self):
        return MagicMock()

    @pytest.fixture
    def executor(self, mock_adapter, mock_risk):
        return OrderExecutor(adapter=mock_adapter, risk_manager=mock_risk)

    def test_submit_adds_to_queue(self, executor):
        order_dict = {'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                      'price': 50000.0, 'quantity': 0.01}
        order = executor.submit(order_dict)
        assert isinstance(order, Order)
        assert order.status == 'PENDING'
        assert executor.get_pending_count() == 1

    def test_submit_multiple_orders(self, executor):
        for i in range(3):
            executor.submit({'symbol': f'SYM{i}', 'side': 'buy'})
        assert executor.get_pending_count() == 3

    def test_get_orders_returns_history(self, executor, mock_adapter):
        mock_adapter.create_limit_order.return_value = {
            'id': 'order-1', 'filled': 0.01, 'price': 50000.0
        }
        executor.submit({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                         'price': 50000.0, 'quantity': 0.01})
        # Manually execute one tick
        executor._execute_order(executor._order_queue[0] if executor._order_queue else None)
        orders = executor.get_orders()
        assert len(orders) >= 1

    def test_execute_limit_order_filled(self, executor, mock_adapter):
        mock_adapter.create_limit_order.return_value = {
            'id': 'L123', 'filled': 0.01, 'price': 50000.0
        }
        order = Order({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                       'price': 50000.0, 'quantity': 0.01})
        executor._execute_order(order)
        assert order.status == 'FILLED'
        assert order.id == 'L123'
        assert order.filled_qty == 0.01
        assert order.avg_fill_price == 50000.0
        assert order.filled_at is not None

    def test_execute_market_order_filled(self, executor, mock_adapter):
        mock_adapter.create_market_order.return_value = {
            'id': 'M456', 'filled': 0.02, 'price': 2000.0
        }
        order = Order({'symbol': 'ETH/USDT', 'side': 'sell', 'type': 'MARKET',
                       'price': 2000.0, 'quantity': 0.02})
        executor._execute_order(order)
        assert order.status == 'FILLED'
        assert order.id == 'M456'

    def test_execute_order_rejected_no_id(self, executor, mock_adapter):
        mock_adapter.create_limit_order.return_value = {'error': 'Insufficient funds'}
        order = Order({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                       'price': 50000.0, 'quantity': 0.01})
        executor._execute_order(order)
        assert order.status == 'REJECTED'
        assert 'Insufficient funds' in order.error

    def test_execute_order_rejected_no_response(self, executor, mock_adapter):
        mock_adapter.create_limit_order.return_value = None
        order = Order({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                       'price': 50000.0, 'quantity': 0.01})
        executor._execute_order(order)
        assert order.status == 'REJECTED'
        assert order.error == 'No response'

    def test_execute_order_exception_caught(self, executor, mock_adapter):
        mock_adapter.create_limit_order.side_effect = RuntimeError("Connection lost")
        order = Order({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                       'price': 50000.0, 'quantity': 0.01})
        executor._execute_order(order)
        assert order.status == 'REJECTED'
        assert "Connection lost" in order.error

    def test_filled_order_updates_risk_manager(self, executor, mock_adapter, mock_risk):
        mock_adapter.create_limit_order.return_value = {
            'id': 'L789', 'filled': 0.01, 'price': 50000.0
        }
        order = Order({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                       'price': 50000.0, 'quantity': 0.01})
        executor._execute_order(order)
        mock_risk.update_position.assert_called_once_with(
            'BTC/USDT', 'LONG', 50000.0, 0.01, 50000.0
        )

    def test_filled_sell_updates_risk_short(self, executor, mock_adapter, mock_risk):
        mock_adapter.create_limit_order.return_value = {
            'id': 'S100', 'filled': 0.02, 'price': 3000.0
        }
        order = Order({'symbol': 'ETH/USDT', 'side': 'sell', 'type': 'LIMIT',
                       'price': 3000.0, 'quantity': 0.02})
        executor._execute_order(order)
        mock_risk.update_position.assert_called_once_with(
            'ETH/USDT', 'SHORT', 3000.0, 0.02, 3000.0
        )

    def test_on_fill_callback_called(self, executor, mock_adapter):
        mock_adapter.create_limit_order.return_value = {
            'id': 'CB1', 'filled': 0.01, 'price': 50000.0
        }
        callback = MagicMock()
        executor.on_fill(callback)
        order = Order({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                       'price': 50000.0, 'quantity': 0.01})
        executor._execute_order(order)
        callback.assert_called_once_with(order)

    def test_on_fill_callback_exception_swallowed(self, executor, mock_adapter):
        mock_adapter.create_limit_order.return_value = {
            'id': 'CB2', 'filled': 0.01, 'price': 50000.0
        }
        bad_cb = MagicMock(side_effect=ValueError("callback error"))
        good_cb = MagicMock()
        executor.on_fill(bad_cb)
        executor.on_fill(good_cb)
        order = Order({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                       'price': 50000.0, 'quantity': 0.01})
        executor._execute_order(order)
        # bad callback exception swallowed, good callback still called
        good_cb.assert_called_once()

    def test_start_stop_lifecycle(self, executor):
        executor.start()
        assert executor._running is True
        executor.stop()
        assert executor._running is False

    def test_double_start_no_op(self, executor):
        executor.start()
        executor.start()
        executor.stop()

    def test_history_truncation(self, executor, mock_adapter):
        mock_adapter.create_limit_order.return_value = {
            'id': 'H', 'filled': 0.01, 'price': 50000.0
        }
        # Pre-fill history to near limit
        executor._order_history = [MagicMock() for _ in range(500)]
        order = Order({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                       'price': 50000.0, 'quantity': 0.01})
        executor._execute_order(order)
        assert len(executor._order_history) == 500

    def test_get_pending_count_zero_initially(self, executor):
        assert executor.get_pending_count() == 0

    def test_executor_without_risk_manager(self, mock_adapter):
        executor = OrderExecutor(adapter=mock_adapter, risk_manager=None)
        mock_adapter.create_limit_order.return_value = {
            'id': 'NR', 'filled': 0.01, 'price': 50000.0
        }
        order = Order({'symbol': 'BTC/USDT', 'side': 'buy', 'type': 'LIMIT',
                       'price': 50000.0, 'quantity': 0.01})
        executor._execute_order(order)
        assert order.status == 'FILLED'
