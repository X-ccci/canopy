"""
订单执行器：将 RiskManager 审批通过的订单通过 ExchangeAdapter 发送到交易所。
支持限价单/市价单，以及订单状态跟踪和回调。
"""
import threading
import time
from typing import Optional, Callable
from datetime import datetime

from canopy.exchange.ccxt_adapter import ExchangeAdapter


class Order:
    """订单对象"""
    def __init__(self, order_dict: dict):
        self.id: str = ''
        self.symbol: str = order_dict.get('symbol', '')
        self.side: str = order_dict.get('side', 'buy')
        self.type: str = order_dict.get('type', 'LIMIT')
        self.price: float = order_dict.get('price', 0.0)
        self.quantity: float = order_dict.get('quantity', 0.0)
        self.status: str = 'PENDING'     # PENDING → OPEN → FILLED / CANCELLED / REJECTED
        self.filled_qty: float = 0.0
        self.avg_fill_price: float = 0.0
        self.created_at: str = order_dict.get('approved_at', datetime.now().isoformat())
        self.filled_at: Optional[str] = None
        self.error: str = ''


class OrderExecutor:
    """
    订单执行器线程——从队列中取订单并发往交易所。
    """
    
    def __init__(self, adapter: ExchangeAdapter, risk_manager=None):
        self.adapter = adapter
        self.risk_manager = risk_manager
        self._order_queue: list[Order] = []
        self._order_history: list[Order] = []
        self._running = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._on_fill_callbacks: list[Callable] = []
    
    def submit(self, order_dict: dict) -> Order:
        """提交订单到执行队列"""
        order = Order(order_dict)
        with self._lock:
            self._order_queue.append(order)
        return order
    
    def start(self):
        """启动执行线程"""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name='order-executor')
        self._thread.start()
    
    def stop(self):
        """停止执行线程"""
        self._running = False
        self._stop_event.set()
    
    def _run_loop(self):
        """主循环——从队列取订单并执行"""
        while not self._stop_event.is_set():
            order = None
            with self._lock:
                if self._order_queue:
                    order = self._order_queue.pop(0)
            
            if order:
                self._execute_order(order)
            else:
                self._stop_event.wait(0.5)
    
    def _execute_order(self, order: Order):
        """执行单个订单"""
        try:
            order.status = 'OPEN'
            
            # 通过 CCXT 下单
            if order.type == 'LIMIT':
                result = self.adapter.create_limit_order(
                    symbol=order.symbol, side=order.side,
                    amount=order.quantity, price=order.price
                )
            else:
                result = self.adapter.create_market_order(
                    symbol=order.symbol, side=order.side,
                    amount=order.quantity
                )
            
            if result and result.get('id'):
                order.id = result['id']
                order.status = 'FILLED'
                order.filled_qty = result.get('filled', order.quantity)
                order.avg_fill_price = result.get('price', order.price)
                order.filled_at = datetime.now().isoformat()
                
                # 回调：更新风险控制器的持仓
                if self.risk_manager:
                    side = 'LONG' if order.side == 'buy' else 'SHORT'
                    self.risk_manager.update_position(
                        order.symbol, side, order.avg_fill_price,
                        order.filled_qty, order.avg_fill_price
                    )
                
                # 触发 on_fill 回调
                for cb in self._on_fill_callbacks:
                    try:
                        cb(order)
                    except Exception:
                        pass
            else:
                order.status = 'REJECTED'
                order.error = result.get('error', 'Unknown error') if result else 'No response'
                
        except Exception as e:
            order.status = 'REJECTED'
            order.error = str(e)
        finally:
            with self._lock:
                self._order_history.append(order)
                if len(self._order_history) > 500:
                    self._order_history = self._order_history[-500:]
    
    def on_fill(self, callback: Callable):
        """注册成交回调"""
        self._on_fill_callbacks.append(callback)
    
    def get_orders(self, limit: int = 50) -> list:
        """获取最近的订单"""
        with self._lock:
            orders = list(self._order_history[-limit:])
        return [
            {
                'id': o.id,
                'symbol': o.symbol,
                'side': o.side,
                'type': o.type,
                'price': o.price,
                'quantity': o.quantity,
                'status': o.status,
                'filled_qty': o.filled_qty,
                'avg_fill_price': o.avg_fill_price,
                'created_at': o.created_at,
                'error': o.error
            }
            for o in orders
        ]
    
    def get_pending_count(self) -> int:
        with self._lock:
            return len(self._order_queue)
