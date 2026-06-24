"""
策略运行器：管理多个策略的并行运行、数据分发、信号汇总。
"""
import threading
import time
from typing import Optional
from datetime import datetime
import pandas as pd

from canopy.engine.base import Strategy
from canopy.engine.factory import StrategyFactory
from canopy.engine.risk import RiskManager, RiskConfig
from canopy.engine.executor import OrderExecutor
from canopy.exchange.ccxt_adapter import ExchangeAdapter
from canopy.data.fetcher import DataFetcher


class StrategyRunner:
    """
    管理多个策略实例的生命周期。
    每个策略在独立线程中运行，共享交易所和数据层。
    """
    def __init__(self, adapter: ExchangeAdapter, fetcher: DataFetcher):
        self.adapter = adapter
        self.fetcher = fetcher
        self.strategies: dict[str, Strategy] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._running = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._signal_log: list[dict] = []  # 最近的信号日志
        self._max_log_len = 100
        self.risk_mgr = RiskManager(initial_balance=10000.0)
        self.executor = OrderExecutor(adapter, self.risk_mgr)
        self.executor.start()
    
    def add_strategy(self, name: str, strategy_type: str, symbol: str, 
                     timeframe: str = '1h', **params) -> str:
        """添加并启动一个策略。返回策略 ID（即 name）。"""
        factory = StrategyFactory()
        strategy = factory.create(strategy_type, **params)
        strategy.name = name
        strategy.symbol = symbol
        strategy.timeframe = timeframe
        
        with self._lock:
            self.strategies[name] = strategy
        
        if self._running:
            self._start_strategy_thread(name)
        
        return name
    
    def remove_strategy(self, name: str) -> bool:
        """停止并移除一个策略"""
        with self._lock:
            if name not in self.strategies:
                return False
            # 标记停止
            if name in self.strategies:
                strategy = self.strategies[name]
                strategy.stop()
            del self.strategies[name]
        return True
    
    def start_all(self):
        """启动所有策略"""
        self._running = True
        self._stop_event.clear()
        with self._lock:
            for name in self.strategies:
                self._start_strategy_thread(name)
    
    def stop_all(self):
        """停止所有策略"""
        self._running = False
        self._stop_event.set()
        with self._lock:
            for name, thread in list(self._threads.items()):
                if thread and thread.is_alive():
                    # 线程会在检查 stop_event 后自然退出
                    pass
            for name in self.strategies:
                self.strategies[name].stop()
    
    def _start_strategy_thread(self, name: str):
        """为单个策略启动工作线程"""
        if name in self._threads and self._threads[name].is_alive():
            return
        
        thread = threading.Thread(
            target=self._strategy_loop,
            args=(name,),
            daemon=True,
            name=f'strategy-{name}'
        )
        self._threads[name] = thread
        thread.start()
    
    def _strategy_loop(self, name: str):
        """策略主循环：拉取数据 → 逐根K线调用 on_bar → 记录信号"""
        strategy = self.strategies.get(name)
        if not strategy:
            return
        
        strategy.start()
        
        while not self._stop_event.is_set():
            try:
                # 拉取最新数据
                df = self.fetcher.get_ohlcv(
                    symbol=strategy.symbol,
                    timeframe=strategy.timeframe,
                    limit=50,
                    force_refresh=True
                )
                
                if df is not None and len(df) > 0:
                    # 只处理最后几根新K线（增量更新）
                    # 简单实现：取最后 3 根避免重复处理
                    recent = df.tail(3)
                    for _, row in recent.iterrows():
                        candle = {
                            'timestamp': row['timestamp'],
                            'open': float(row['open']),
                            'high': float(row['high']),
                            'low': float(row['low']),
                            'close': float(row['close']),
                            'volume': float(row['volume'])
                        }
                        signal = strategy.on_bar(candle)
                        if signal and signal.get('action') != 'HOLD':
                            signal['symbol'] = strategy.symbol
                            # 风险审批
                            approved, reason, order = self.risk_mgr.approve(
                                signal, candle.get('close'), account_balance=None
                            )
                            if approved and order:
                                self.executor.submit(order)
                                self._log_signal(name, signal, candle)
                            else:
                                # 记录被拒绝的信号
                                self._log_signal(name, {**signal, 'action': 'REJECTED', 'reason': reason}, candle)
                
                # 按 timeframe 等待
                wait_seconds = self._timeframe_to_seconds(strategy.timeframe)
                self._stop_event.wait(wait_seconds)
                
            except Exception as e:
                print(f"[Runner] Error in strategy '{name}': {e}")
                self._stop_event.wait(10)  # 出错后等待 10 秒重试
    
    def _timeframe_to_seconds(self, tf: str) -> int:
        """转换 timeframe 为秒"""
        mapping = {'1m': 60, '5m': 300, '15m': 900, '30m': 1800,
                   '1h': 3600, '4h': 14400, '1d': 86400}
        return mapping.get(tf, 3600)
    
    def _log_signal(self, strategy_name: str, signal: dict, candle: dict):
        """记录信号到日志"""
        entry = {
            'time': datetime.now().isoformat(),
            'strategy': strategy_name,
            'action': signal.get('action'),
            'price': signal.get('price', candle.get('close')),
            'reason': signal.get('reason', ''),
            'close': candle.get('close'),
            'volume': candle.get('volume')
        }
        self._signal_log.append(entry)
        if len(self._signal_log) > self._max_log_len:
            self._signal_log = self._signal_log[-self._max_log_len:]
    
    def get_status(self) -> dict:
        """获取运行器状态"""
        with self._lock:
            strategies_status = []
            for name, s in self.strategies.items():
                strategies_status.append({
                    'name': name,
                    'type': s.__class__.__name__,
                    'symbol': getattr(s, 'symbol', 'N/A'),
                    'running': s.is_running,
                    'params': s.params
                })
        
        return {
            'running': self._running,
            'strategy_count': len(self.strategies),
            'strategies': strategies_status,
            'recent_signals': self._signal_log[-10:],  # 最近 10 条信号
            'risk': self.risk_mgr.get_status(),
            'pending_orders': self.executor.get_pending_count()
        }
    
    def get_strategies(self) -> list[dict]:
        """获取策略列表（供前端使用）"""
        with self._lock:
            result = []
            for name, s in self.strategies.items():
                result.append({
                    'name': name,
                    'type': s.__class__.__name__,
                    'symbol': getattr(s, 'symbol', 'N/A'),
                    'running': s.is_running,
                    'params': s.params
                })
            return result
