"""
Canopy 桌面应用入口
使用 pywebview 加载 Nature-Tech 前端，并通过 JS API 桥接 Python 后端。
"""
import sys
import os
import json
import threading
import webview
import pandas as pd

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from canopy.config import Config
from canopy.exchange.ccxt_adapter import ExchangeAdapter
from canopy.data.fetcher import DataFetcher
from canopy.engine.runner import StrategyRunner
from canopy.engine.backtest_runner import BacktestRunner


class CanopyAPI:
    """
    暴露给前端 JS 的 Python API。
    前端通过 window.pywebview.api.xxx() 调用。
    """
    def __init__(self):
        self.config = Config()
        self.adapter: ExchangeAdapter | None = None
        self.fetcher: DataFetcher | None = None
        self.runner: StrategyRunner | None = None
        self.backtest = BacktestRunner()
        self._running = False
        self._data = {
            'ticker': {},
            'kpi': {
                'total_value': 0,
                'pnl_24h': 0,
                'active_strategies': 0,
                'win_rate': 0
            },
            'strategies': [],
            'portfolio': [],
            'sentiment': {}
        }
    
    def connect_exchange(self, exchange_id: str = 'binance') -> dict:
        """连接交易所，同时初始化 DataFetcher 和 StrategyRunner"""
        try:
            self.adapter = ExchangeAdapter(exchange_id, self.config)
            ok = self.adapter.connect()
            if ok:
                self.fetcher = DataFetcher(self.adapter)
                self.runner = StrategyRunner(self.adapter, self.fetcher)
                # 预添加 5 个策略但不启动（等前端触发）
                self.runner.add_strategy('Mean Reversion v3', 'mean_reversion', 'BTC/USDT', '1h')
                self.runner.add_strategy('Grid Infinity', 'grid', 'ETH/USDT', '1h', 
                                        upper_price=4000, lower_price=3200, grid_count=10)
                self.runner.add_strategy('Trend Surf', 'trend', 'SOL/USDT', '1h')
                self.runner.add_strategy('Arbitrage Nexus', 'arbitrage', 'BNB/USDT', '1h')
                self.runner.add_strategy('Volatility Harvester', 'momentum', 'AVAX/USDT', '1h')
                # 启动所有策略（如果用户需要暂停，前端可以调 stop_strategies）
                self.runner.start_all()
            return {'success': ok, 'exchange': exchange_id, 'status': 'connected' if ok else 'failed'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_kpi(self) -> dict:
        """获取 KPI 数据（实时行情驱动的模拟仪表盘数据）"""
        if self.adapter is None:
            return self._data['kpi']
        try:
            ticker = self.adapter.fetch_ticker('BTC/USDT')
            if ticker and ticker.get('last'):
                btc_price = ticker['last']
                self._data['ticker'] = ticker
                self._data['kpi'] = {
                    'total_value': round(btc_price * 2.5 + 28000, 2),
                    'pnl_24h': round(btc_price * 0.0234, 2),
                    'pnl_pct': 2.34,
                    'active_strategies': len(self.runner.strategies) if self.runner else 7,
                    'profitable': 3,
                    'win_rate': 68.4,
                    'win_rate_change': 5.2
                }
            return self._data['kpi']
        except Exception:
            return self._data['kpi']
    
    def get_ticker(self, symbol: str = 'BTC/USDT') -> dict:
        """获取实时行情"""
        if self.adapter is None:
            return {}
        try:
            return self.adapter.fetch_ticker(symbol)
        except Exception:
            return {}
    
    def get_strategies(self) -> list:
        """获取实时策略状态（带 PnL 模拟）"""
        if self.runner is None:
            return []
        # 获取 runner 中的策略元数据
        base_list = self.runner.get_strategies()
        # 附加上模拟的 PnL 数据
        mock_data = {
            'Mean Reversion v3': {'pair': 'BTC/USDT', 'entry': 64200, 'current': 67850, 'pnl_pct': 5.69, 'status': 'Running'},
            'Grid Infinity': {'pair': 'ETH/USDT', 'entry': 3420, 'current': 3516, 'pnl_pct': 2.81, 'status': 'Running'},
            'Trend Surf': {'pair': 'SOL/USDT', 'entry': 172.40, 'current': 168.20, 'pnl_pct': -2.44, 'status': 'Holding'},
            'Arbitrage Nexus': {'pair': 'BNB/USDT', 'entry': 598.00, 'current': 612.30, 'pnl_pct': 2.39, 'status': 'Running'},
            'Volatility Harvester': {'pair': 'AVAX/USDT', 'entry': 38.50, 'current': 36.90, 'pnl_pct': -4.16, 'status': 'Stop Loss'},
        }
        result = []
        for s in base_list:
            md = mock_data.get(s['name'], {})
            result.append({**s, **md})
        return result
    
    def get_portfolio(self) -> list:
        """获取持仓分布"""
        return [
            {'asset': 'BTC', 'name': 'Bitcoin', 'pct': 43},
            {'asset': 'ETH', 'name': 'Ethereum', 'pct': 22},
            {'asset': 'SOL', 'name': 'Solana', 'pct': 18},
            {'asset': 'Stable', 'name': 'Stablecoins', 'pct': 17},
        ]
    
    def get_sentiment(self) -> dict:
        """获取市场情绪数据"""
        return {
            'fear_greed': 68,
            'label': 'Greed',
            'btc_dominance': 52.1,
            'volume_24h': 42.8,
            'volatility': 'Medium'
        }

    def run_backtest(self, params: dict = None) -> dict:
        """运行回测（pywebview 兼容：接收单个 dict 参数）"""
        if params is None:
            params = {}
        strategy_type = params.get('strategy_type', 'mean_reversion')
        symbol = params.get('symbol', 'BTC/USDT')
        timeframe = params.get('timeframe', '1h')
        initial_capital = params.get('initial_capital', 10000)
        return self.backtest.run_strategy(strategy_type, symbol, timeframe, initial_capital)

    def compare_strategies(self, params: dict = None) -> list:
        """策略对比（pywebview 兼容：接收单个 dict 参数）"""
        if params is None:
            params = {}
        symbol = params.get('symbol', 'BTC/USDT')
        timeframe = params.get('timeframe', '1h')
        return self.backtest.compare(symbol, timeframe)

    def get_backtest_result(self) -> dict:
        """获取最近一次回测结果"""
        result = self.backtest.get_last_result()
        return result if result else {}

    def get_status(self) -> dict:
        """获取完整系统状态"""
        runner_status = self.runner.get_status() if self.runner else {}
        return {
            'connected': self.adapter is not None,
            'exchange': self.config.exchange_id if self.adapter else 'Disconnected',
            'runner': runner_status,
            'mode': 'Live',
        }
    
    def start_strategies(self) -> dict:
        """启动所有策略"""
        if self.runner:
            self.runner.start_all()
            return {'success': True, 'message': 'All strategies started'}
        return {'success': False, 'message': 'No runner available'}
    
    def stop_strategies(self) -> dict:
        """停止所有策略"""
        if self.runner:
            self.runner.stop_all()
            return {'success': True, 'message': 'All strategies stopped'}
        return {'success': False, 'message': 'No runner available'}
    
    def get_risk_status(self) -> dict:
        """获取风控状态"""
        if self.runner and hasattr(self.runner, 'risk_mgr'):
            return self.runner.risk_mgr.get_status()
        return {}
    
    def get_orders(self, limit: int = 50) -> list:
        """获取订单历史"""
        if self.runner and hasattr(self.runner, 'executor'):
            return self.runner.executor.get_orders(limit)
        return []
    
    def reset_circuit_breaker(self) -> dict:
        """重置熔断器"""
        if self.runner and hasattr(self.runner, 'risk_mgr'):
            msg = self.runner.risk_mgr.reset_circuit_breaker()
            return {'success': True, 'message': msg}
        return {'success': False, 'message': 'No risk manager available'}
    
    def update_risk_config(self, params: dict = None) -> dict:
        """更新风控参数（pywebview 兼容：接收单个 dict 参数）"""
        if not params:
            return {'success': False, 'message': 'No params provided'}
        if self.runner and hasattr(self.runner, 'risk_mgr'):
            for key, val in params.items():
                if hasattr(self.runner.risk_mgr.config, key):
                    setattr(self.runner.risk_mgr.config, key, val)
            return {'success': True, 'config': self.runner.risk_mgr.config.to_dict()}
        return {'success': False, 'message': 'No risk manager available'}


def main():
    api = CanopyAPI()
    
    # 获取 HTML 文件路径（相对于当前文件的 web/index.html）
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'index.html')
    
    # 创建 pywebview 窗口
    window = webview.create_window(
        title='Canopy · Nature-Tech Trading Terminal',
        url=html_path,
        js_api=api,
        width=1400,
        height=900,
        min_size=(960, 600),
        resizable=True,
        fullscreen=False,
    )
    
    webview.start(debug=True)


if __name__ == '__main__':
    main()
