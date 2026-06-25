"""
Canopy 桌面应用入口
使用 pywebview 加载 Nature-Tech 前端，并通过 JS API 桥接 Python 后端。

双模式支持：
  - 桌面模式（默认）：pywebview 原生窗口
  - Web 模式（--web）：FastAPI 服务器（配合浏览器访问）
"""
import argparse
import json
import os
import sys
import threading

import webview

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from canopy.config import Config
from canopy.data.fetcher import DataFetcher
from canopy.engine.backtest_runner import BacktestRunner
from canopy.engine.runner import StrategyRunner
from canopy.exchange.ccxt_adapter import ExchangeAdapter
from canopy.exchange.multi_adapter import MultiExchangeManager
from canopy.web.server import create_app, set_api


class CanopyAPI:
    """
    暴露给前端 JS 的 Python API。
    前端通过 window.pywebview.api.xxx() 调用。
    """
    def __init__(self):
        self.config = Config()
        self.adapter: ExchangeAdapter | None = None
        self.multi_adapter: MultiExchangeManager | None = None
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
        """连接交易所。

        支持两种模式：
        - 单所：exchange_id 为单个标识（如 'binance'）。
        - 多所：exchange_id 为逗号分隔列表（如 'binance,okx,bybit'），
          启用 MultiExchangeManager 并发连接所有交易所。
        """
        try:
            # 检测多所模式
            if ',' in exchange_id:
                return self._connect_multi(exchange_id)

            # 单所模式（向后兼容）
            self.adapter = ExchangeAdapter(exchange_id, self.config)
            ok = self.adapter.connect()
            if ok:
                self.fetcher = DataFetcher(self.adapter)  # type: ignore[arg-type]
                self.runner = StrategyRunner(self.adapter, self.fetcher)  # type: ignore[arg-type]
                self.runner.add_strategy('Mean Reversion v3', 'mean_reversion', 'BTC/USDT', '1h')
                self.runner.add_strategy('Grid Infinity', 'grid', 'ETH/USDT', '1h',
                                        upper_price=4000, lower_price=3200, grid_count=10)
                self.runner.add_strategy('Trend Surf', 'trend', 'SOL/USDT', '1h')
                self.runner.add_strategy('Arbitrage Nexus', 'arbitrage', 'BNB/USDT', '1h')
                self.runner.add_strategy('Momentum Hunter', 'momentum', 'XRP/USDT', '1h')
                self.runner.start_all()
            return {'success': ok, 'exchange': exchange_id, 'status': '已连接' if ok else '连接失败'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _connect_multi(self, exchange_ids: str) -> dict:
        """多所并发连接。"""
        ids = [e.strip() for e in exchange_ids.split(",") if e.strip()]
        self.multi_adapter = MultiExchangeManager(self.config)
        results = {}
        for ex_id in ids:
            results[ex_id] = self.multi_adapter.add_exchange(ex_id)

        connected = [k for k, v in results.items() if v]
        failed = [k for k, v in results.items() if not v]

        if connected:
            # 用第一个成功连接的交易所初始化单所兼容层
            self.adapter = self.multi_adapter.adapters.get(connected[0])
            self.fetcher = DataFetcher(self.adapter)  # type: ignore[arg-type]
            self.runner = StrategyRunner(self.adapter, self.fetcher)  # type: ignore[arg-type]
            self.runner.add_strategy('Arbitrage Nexus', 'arbitrage', 'BNB/USDT', '1h')
            self.runner.start_all()

        return {
            'success': len(connected) > 0,
            'mode': 'multi',
            'connected': connected,
            'failed': failed,
            'total': len(ids),
        }

    def get_kpi(self) -> dict:
        """获取 KPI 数据（从 runner 和 risk_mgr 实时读取）"""
        if self.runner is None:
            return {
                'total_value': 0,
                'pnl_24h': 0,
                'pnl_pct': 0,
                'active_strategies': 0,
                'profitable': 0,
                'win_rate': 0,
            }

        # 风控状态
        risk_status = self.runner.risk_mgr.get_status() if self.runner.risk_mgr else {}
        current_balance = risk_status.get('current_balance', 0)

        # 策略统计
        strategies = self.runner.get_strategies()
        active_count = sum(1 for s in strategies if s.get('running'))

        # 信号统计：从 runner 的信号日志计算通过率
        signal_log = getattr(self.runner, '_signal_log', [])
        total_signals = len(signal_log)
        approved = sum(1 for s in signal_log if s.get('action') not in ('REJECTED', 'HOLD'))
        pass_rate = round(approved / max(total_signals, 1) * 100, 2)
        profitable = approved  # 通过信号数作为活跃盈利策略参考

        # BTC 行情（用于 total_value 参考）
        try:
            ticker = self.adapter.fetch_ticker('BTC/USDT') if self.adapter else {}
            ticker.get('last', 0) if ticker else 0
        except Exception:
            pass

        return {
            'total_value': round(current_balance, 2),
            'pnl_24h': round(risk_status.get('daily_pnl', 0), 2),
            'pnl_pct': round(abs(current_balance - 10000) / 100, 2) if current_balance else 0,
            'active_strategies': active_count,
            'profitable': profitable,
            'win_rate': round(pass_rate, 1),
        }

    def get_ticker(self, symbol: str = 'BTC/USDT') -> dict:
        """获取实时行情"""
        if self.adapter is None:
            return {}
        try:
            return self.adapter.fetch_ticker(symbol)
        except Exception:
            return {}

    def get_strategies(self) -> list:
        """获取实时策略状态（从 runner 读取真实信号统计）"""
        if self.runner is None:
            return []  # type: ignore[no-any-return]

        base_list = self.runner.get_strategies()

        # 从信号日志按策略统计
        signal_log = getattr(self.runner, '_signal_log', [])
        strat_stats: dict = {}
        for s in signal_log:
            name = s.get('strategy_name', '')
            if name not in strat_stats:
                strat_stats[name] = {'signal_count': 0, 'pass_count': 0, 'last_signal': ''}
            strat_stats[name]['signal_count'] += 1
            if s.get('action') not in ('REJECTED', 'HOLD'):
                strat_stats[name]['pass_count'] += 1
            strat_stats[name]['last_signal'] = s.get('action', '')

        result = []
        for s in base_list:
            stats = strat_stats.get(s.get('name', ''), {})
            symbol = s.get('symbol', '')
            # 尝试获取该交易对的当前价
            current_price = 0
            try:
                ticker = self.adapter.fetch_ticker(symbol) if self.adapter and symbol else {}
                current_price = ticker.get('last', 0) if ticker else 0
            except Exception:
                pass

            result.append({
                **s,
                'pair': symbol,
                'current': round(current_price, 2),
                'entry': 0,
                'pnl_pct': 0,
                'status': '运行中' if s.get('running') else '空闲',
                'signal_count': stats.get('signal_count', 0),
                'pass_count': stats.get('pass_count', 0),
                'last_signal': stats.get('last_signal', ''),
            })

        return result

    def get_portfolio(self) -> list:
        """获取真实持仓分布（从 RiskManager 读取）"""
        if self.runner is None or self.runner.risk_mgr is None:
            return []

        risk_mgr = self.runner.risk_mgr
        positions = getattr(risk_mgr, 'positions', {})
        balance = getattr(risk_mgr, 'balance', 0) or 10000

        result = []

        # 真实持仓
        for symbol, pos in positions.items():
            base = symbol.split('/')[0] if '/' in symbol else symbol
            pos_value_approx = getattr(pos, 'quantity', 0) * getattr(pos, 'avg_entry_price', 0)
            pct = round(pos_value_approx / max(balance, 1) * 100, 1)

            asset_names = {
                'BTC': '比特币', 'ETH': '以太坊', 'SOL': '索拉纳',
                'BNB': 'BNB', 'XRP': '瑞波币', 'AVAX': '雪崩',
                'ADA': '艾达币', 'DOT': '波卡', 'LINK': '链环',
            }
            result.append({
                'asset': base,
                'name': asset_names.get(base, base),
                'pct': min(pct, 100),
            })

        # 剩余现金
        total_allocated = sum(r['pct'] for r in result)
        if total_allocated < 100:
            result.append({
                'asset': 'CASH',
                'name': '现金储备',
                'pct': round(100 - total_allocated, 1),
            })

        return result

    def get_ws_status(self) -> dict:
        """获取 WebSocket 连接状态"""
        if self.runner is None:
            return {'connected': False, 'status': '未连接', 'status_label': '离线'}

        ws = getattr(self.runner, '_ws_client', None)
        if ws is None:
            return {'connected': False, 'status': '未连接', 'status_label': '离线'}

        is_connected = ws.is_connected() if hasattr(ws, 'is_connected') else False
        ws_status = ws.get_status() if hasattr(ws, 'get_status') else {}

        status_label = '在线' if is_connected else '已断开'

        return {
            'connected': is_connected,
            'status': '已连接' if is_connected else '未连接',
            'status_label': status_label,
            'channels': list(ws_status.get('subscriptions', [])),
        }

    def get_sentiment(self) -> dict:
        """获取市场情绪数据"""
        return {
            'fear_greed': 68,
            'label': '贪婪',
            'btc_dominance': 52.1,
            'volume_24h': 42.8,
            'volatility': '中等'
        }

    def run_backtest(self, params: dict | None = None) -> dict:
        """运行回测（pywebview 兼容：接收单个 dict 参数）"""
        if params is None:
            params = {}
        strategy_type = params.get('strategy_type', 'mean_reversion')
        symbol = params.get('symbol', 'BTC/USDT')
        timeframe = params.get('timeframe', '1h')
        initial_capital = params.get('initial_capital', 10000)
        return self.backtest.run_strategy(strategy_type, symbol, timeframe, initial_capital)  # type: ignore[no-any-return]

    def compare_strategies(self, params: dict | None = None) -> list:
        """策略对比（pywebview 兼容：接收单个 dict 参数）"""
        if params is None:
            params = {}
        symbol = params.get('symbol', 'BTC/USDT')
        timeframe = params.get('timeframe', '1h')
        return self.backtest.compare(symbol, timeframe)  # type: ignore[no-any-return]

    def get_backtest_result(self) -> dict:
        """获取最近一次回测结果"""
        result = self.backtest.get_last_result()
        return result if result else {}

    def get_status(self) -> dict:
        """获取完整系统状态"""
        runner_status = self.runner.get_status() if self.runner else {}
        multi_status = self.multi_adapter.get_all_status() if self.multi_adapter else {}
        return {  # type: ignore[no-any-return]
            'connected': self.adapter is not None,
            'exchange': self.config.exchange if self.adapter else '已断开',
            'runner': runner_status,
            'mode': '实盘',
            'multi_exchange': multi_status,
        }

    def get_arbitrage_opportunities(self, params: dict | None = None) -> list:
        """获取跨所套利机会。

        Args:
            params: 可选字典，支持:
                - symbol (str): 交易对，默认 'BTC/USDT'。
                - min_spread_pct (float): 最小价差百分比，默认 0.5。

        Returns:
            ArbitrageOpportunity 列表，每项包含:
                symbol, buy_exchange, sell_exchange, buy_price, sell_price,
                spread_pct, net_profit_pct, timestamp
        """
        if params is None:
            params = {}
        if self.multi_adapter is None:
            return []

        symbol = params.get('symbol', 'BTC/USDT')
        min_spread_pct = params.get('min_spread_pct', 0.5)

        opportunities = self.multi_adapter.detect_arbitrage(
            symbol=symbol,
            min_spread_pct=min_spread_pct,
        )
        import dataclasses
        return [dataclasses.asdict(o) for o in opportunities]

    def get_exchange_status(self) -> dict:
        """获取所有交易所连接状态和延迟。"""
        if self.multi_adapter:
            return self.multi_adapter.get_all_status()
        if self.adapter:
            return {
                'total': 1,
                'connected': 1 if self.adapter._connected else 0,
                'exchanges': {
                    self.adapter.exchange_id: {
                        'connected': self.adapter._connected,
                        'latency_ms': 0.0,
                        'error': '',
                    }
                }
            }
        return {'total': 0, 'connected': 0, 'exchanges': {}}

    def start_strategies(self) -> dict:
        """启动所有策略"""
        if self.runner:
            self.runner.start_all()
            return {'success': True, 'message': '所有策略已启动'}
        return {'success': False, 'message': '无可用的策略运行器'}

    def stop_strategies(self) -> dict:
        """停止所有策略"""
        if self.runner:
            self.runner.stop_all()
            return {'success': True, 'message': '所有策略已停止'}
        return {'success': False, 'message': '无可用运行器'}

    def get_risk_status(self) -> dict:
        """获取风控状态"""
        if self.runner and hasattr(self.runner, 'risk_mgr'):
            return self.runner.risk_mgr.get_status()
        return {}  # type: ignore[no-any-return]

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
        return {'success': False, 'message': '无可用风控管理器'}

    def update_risk_config(self, params: dict | None = None) -> dict:
        """更新风控参数（pywebview 兼容：接收单个 dict 参数）"""
        if not params:
            return {'success': False, 'message': '未提供参数'}
        if self.runner and hasattr(self.runner, 'risk_mgr'):
            for key, val in params.items():
                if hasattr(self.runner.risk_mgr.config, key):
                    setattr(self.runner.risk_mgr.config, key, val)
            return {'success': True, 'config': self.runner.risk_mgr.config.to_dict()}
        return {'success': False, 'message': '无可用风控管理器'}


# ── 窗口尺寸记忆 ──

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

_default_window_config = {
    "window_x": 100,
    "window_y": 100,
    "window_width": 1400,
    "window_height": 900,
}


def load_window_config() -> dict:
    """从 config.json 加载窗口位置和大小。"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            cfg = {k: data.get(k, _default_window_config[k]) for k in _default_window_config}
            # 确保窗口不超出屏幕边界
            cfg['window_x'] = max(0, cfg['window_x'])
            cfg['window_y'] = max(0, cfg['window_y'])
            return cfg
    except Exception:
        pass
    return dict(_default_window_config)


def save_window_config(window):
    """保存当前窗口位置和大小到 config.json。"""
    try:
        cfg = load_window_config()
        cfg['window_x'] = window.x
        cfg['window_y'] = window.y
        cfg['window_width'] = window.width
        cfg['window_height'] = window.height
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ── macOS 系统托盘 ──

_tray_app = None
_window_ref = None


def _setup_tray():
    """在 macOS 上创建系统托盘（使用 rumps）。"""
    global _tray_app
    try:
        import rumps
        import AppKit
    except ImportError:
        return False

    class CanopyTray(rumps.App):
        def __init__(self):
            super().__init__("🌿", title=None, quit_button=None)

        @rumps.clicked("显示 Canopy")
        def show_window(self, _):
            global _window_ref
            if _window_ref is not None:
                try:
                    # macOS: 恢复窗口到前台
                    ns_app = AppKit.NSApplication.sharedApplication()
                    ns_app.activateIgnoringOtherApps_(True)
                except Exception:
                    pass

        @rumps.clicked("退出")
        def quit_app(self, _):
            global _window_ref
            if _window_ref is not None:
                try:
                    _window_ref.destroy()
                except Exception:
                    pass
            try:
                import rumps
                rumps.quit_application()
            except Exception:
                pass

    _tray_app = CanopyTray()
    tray_thread = threading.Thread(target=_tray_app.run, daemon=True)
    tray_thread.start()
    return True


def _on_closing():
    """窗口关闭时的回调：隐藏到托盘而非退出。"""
    global _window_ref
    if _tray_app is not None and _window_ref is not None:
        try:
            _window_ref.hide()
            return False  # 阻止窗口销毁
        except Exception:
            pass
    return True


def _on_moved_or_resized(window):
    """窗口移动/缩放时保存配置。"""
    save_window_config(window)


def _create_window(api, html_path: str, cfg: dict, title: str = 'Canopy · Nature-Tech 交易终端'):
    """创建 pywebview 窗口（从 config 读取尺寸）。"""
    global _window_ref
    _window_ref = webview.create_window(
        title=title,
        url=html_path,
        js_api=api,
        width=cfg['window_width'],
        height=cfg['window_height'],
        x=cfg['window_x'],
        y=cfg['window_y'],
        min_size=(960, 600),
        resizable=True,
        fullscreen=False,
        easy_drag=False,
    )
    # 绑定关闭事件
    _window_ref.events.closing += _on_closing
    # macOS 特有：窗口移动/缩放时保存
    try:
        _window_ref.events.moved += _on_moved_or_resized
        _window_ref.events.resized += _on_moved_or_resized
    except Exception:
        pass
    return _window_ref


def main():
    parser = argparse.ArgumentParser(
        description="Canopy · Nature-Tech 交易终端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--web", action="store_true",
                        help="启动 Web Dashboard 模式（FastAPI 服务器）")
    parser.add_argument("--port", type=int, default=8080,
                        help="Web 模式端口（默认 8080）")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="Web 模式监听地址（默认 0.0.0.0）")
    parser.add_argument("--no-desktop", action="store_true",
                        help="Web 模式下不启动 pywebview 桌面窗口")
    parser.add_argument("--no-tray", action="store_true",
                        help="禁用 macOS 系统托盘")

    args = parser.parse_args()

    api = CanopyAPI()

    # 加载窗口配置
    win_cfg = load_window_config()

    # macOS 系统托盘
    if not args.no_tray and sys.platform == 'darwin':
        _setup_tray()

    # ── Web 模式：启动 FastAPI 服务器 ──
    if args.web:
        import uvicorn
        set_api(api)                          # 注入 CanopyAPI 实例
        app = create_app()

        # 如果同时启动桌面窗口
        if not args.no_desktop:

            def start_web():
                uvicorn.run(app, host=args.host, port=args.port, log_level="info")

            web_thread = threading.Thread(target=start_web, daemon=True)
            web_thread.start()
            print(f"[Web] FastAPI 服务器已启动: http://localhost:{args.port}")

            # 启动 pywebview 桌面窗口（同时运行）
            html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'index.html')
            _create_window(api, html_path, win_cfg)
            webview.start(debug=True)
        else:
            # 纯 Web 模式，无桌面窗口
            print(f"[Web] Canopy 仪表盘 启动: http://localhost:{args.port}")
            uvicorn.run(app, host=args.host, port=args.port, log_level="info")

    else:
        # ── 桌面模式（默认）：pywebview 原生窗口 ──
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'index.html')
        _create_window(api, html_path, win_cfg)
        webview.start(debug=True)


if __name__ == '__main__':
    main()
