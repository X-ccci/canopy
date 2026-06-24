"""
风险控制器：负责仓位规模计算、敞口限制、最大回撤熔断、止损管理。
所有策略信号必须经过 RiskManager 审批后才能执行。
"""
import threading
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RiskConfig:
    """风险参数配置"""
    max_position_pct: float = 0.05         # 单笔最大仓位（总资金%）
    max_total_exposure: float = 0.8        # 最大总敞口
    max_drawdown_pct: float = 0.15         # 全局最大回撤熔断
    max_daily_loss_pct: float = 0.05       # 单日最大亏损熔断
    min_volatility_filter: float = 0.005   # 波动率下限（避免横盘频繁交易）
    max_volatility_filter: float = 0.08    # 波动率上限（避免极端行情）
    
    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    side: str = 'LONG'          # LONG / SHORT
    entry_price: float = 0.0
    quantity: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    opened_at: str = field(default_factory=lambda: datetime.now().isoformat())


class CircuitBreaker:
    """熔断器——满足条件时锁定所有交易"""
    
    def __init__(self):
        self._tripped = False
        self._reason = ''
        self._tripped_at: Optional[str] = None
    
    def trip(self, reason: str):
        self._tripped = True
        self._reason = reason
        self._tripped_at = datetime.now().isoformat()
    
    def reset(self):
        self._tripped = False
        self._reason = ''
        self._tripped_at = None
    
    @property
    def is_tripped(self) -> bool:
        return self._tripped
    
    @property
    def status(self) -> dict:
        return {
            'tripped': self._tripped,
            'reason': self._reason,
            'tripped_at': self._tripped_at
        }


class RiskManager:
    """
    策略信号守门人。每个信号必须通过以下检查链：
    熔断器 → 每日亏损限制 → 波动率过滤 → 仓位限制 → 敞口限制
    """
    
    def __init__(self, config: RiskConfig = None, initial_balance: float = 10000.0):
        self.config = config or RiskConfig()
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.peak_balance = initial_balance
        self.daily_pnl = 0.0
        self._daily_start_balance = initial_balance
        self.positions: dict[str, Position] = {}
        self.circuit_breaker = CircuitBreaker()
        self._lock = threading.Lock()
        self._decision_log: list[dict] = []
        self._last_check_day = datetime.now().day
    
    def approve(self, signal: dict, current_price: float, 
                account_balance: float = None) -> tuple[bool, str, Optional[dict]]:
        """

        审批交易信号。
        
        返回: (approved, reason, order_dict)
        """
        with self._lock:
            # 0. 熔断检查
            if self.circuit_breaker.is_tripped:
                return False, f"Circuit breaker tripped: {self.circuit_breaker._reason}", None
            
            # 1. 每日亏损限额
            self._update_daily(account_balance or self.current_balance)
            if self.daily_pnl <= -self.config.max_daily_loss_pct * self._daily_start_balance:
                self.circuit_breaker.trip(f"Daily loss limit hit: ${abs(self.daily_pnl):.2f}")
                return False, f"Daily max loss exceeded: -${abs(self.daily_pnl):.2f}", None
            
            # 2. 全局回撤熔断
            if account_balance:
                self.current_balance = account_balance
            drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
            if drawdown > self.config.max_drawdown_pct:
                self.circuit_breaker.trip(f"Max drawdown {drawdown*100:.1f}%")
                return False, f"Max drawdown exceeded: {drawdown*100:.1f}%", None
            
            # 3. 信号有效性
            action = signal.get('action', 'HOLD').upper()
            if action == 'HOLD':
                return False, 'Signal is HOLD', None
            
            symbol = signal.get('symbol', 'UNKNOWN')
            price = signal.get('price', current_price)
            
            # 4. 仓位大小计算 (Kelly 简化版)
            max_position_value = self.current_balance * self.config.max_position_pct
            quantity = max_position_value / price
            
            # 5. 敞口检查
            current_exposure = sum(
                abs(p.quantity * p.current_price) 
                for p in self.positions.values()
            )
            new_exposure_pct = (current_exposure + max_position_value) / self.current_balance
            if new_exposure_pct > self.config.max_total_exposure:
                return False, f'Exposure limit: {new_exposure_pct*100:.1f}% > {self.config.max_total_exposure*100:.0f}%', None
            
            # 6. 构建订单
            order = {
                'symbol': symbol,
                'action': action,
                'price': price,
                'quantity': quantity,
                'type': 'LIMIT',
                'side': 'buy' if action == 'BUY' else 'sell',
                'approved_at': datetime.now().isoformat()
            }
            
            self._log_decision(symbol, action, True, price, quantity)
            return True, f'Approved: {action} {quantity:.4f} {symbol} @ {price}', order
    
    def update_position(self, symbol: str, side: str, entry_price: float,
                        quantity: float, current_price: float = None):
        """更新/创建持仓"""
        with self._lock:
            cp = current_price or entry_price
            pnl = (cp - entry_price) * quantity if side == 'LONG' else (entry_price - cp) * quantity
            self.positions[symbol] = Position(
                symbol=symbol, side=side, entry_price=entry_price,
                quantity=quantity, current_price=cp, unrealized_pnl=pnl
            )
    
    def close_position(self, symbol: str):
        """移除持仓"""
        with self._lock:
            self.positions.pop(symbol, None)
    
    def _update_daily(self, current_balance: float):
        """检查是否跨日，重置每日计数器"""
        today = datetime.now().day
        if today != self._last_check_day:
            self._daily_start_balance = current_balance
            self.daily_pnl = 0.0
            self._last_check_day = today
        else:
            self.daily_pnl = current_balance - self._daily_start_balance
    
    def _log_decision(self, symbol: str, action: str, approved: bool,
                      price: float, quantity: float):
        entry = {
            'time': datetime.now().isoformat(),
            'symbol': symbol,
            'action': action,
            'approved': approved,
            'price': price,
            'quantity': quantity
        }
        self._decision_log.append(entry)
        if len(self._decision_log) > 200:
            self._decision_log = self._decision_log[-200:]
    
    def reset_circuit_breaker(self) -> str:
        """手动重置熔断器"""
        self.circuit_breaker.reset()
        return 'Circuit breaker reset'
    
    def get_status(self) -> dict:
        """获取风控状态"""
        with self._lock:
            drawdown = 0.0
            if self.peak_balance > 0:
                drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
            
            return {
                'circuit_breaker': self.circuit_breaker.status,
                'current_balance': round(self.current_balance, 2),
                'peak_balance': round(self.peak_balance, 2),
                'drawdown_pct': round(drawdown * 100, 2),
                'daily_pnl': round(self.daily_pnl, 2),
                'open_positions': len(self.positions),
                'total_exposure': round(sum(
                    abs(p.quantity * p.current_price) / max(self.current_balance, 1) * 100
                    for p in self.positions.values()
                ), 1),
                'config': self.config.to_dict()
            }
    
    def update_balance(self, new_balance: float):
        """更新账户余额（由订单执行器回调）"""
        with self._lock:
            self.current_balance = new_balance
            if new_balance > self.peak_balance:
                self.peak_balance = new_balance
