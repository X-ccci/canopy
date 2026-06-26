"""
策略运行器：管理多个策略的并行运行、数据分发、信号汇总。
"""
import threading
import time
from datetime import datetime

from canopy.config import Config
from canopy.data.fetcher import DataFetcher
from canopy.engine.base import Strategy
from canopy.engine.executor import OrderExecutor
from canopy.engine.factory import StrategyFactory
from canopy.engine.risk import RiskManager
from canopy.exchange.ccxt_adapter import ExchangeAdapter
from canopy.exchange.ws_client import WSClient, WSKline, WSTicker


class StrategyRunner:
    """
    管理多个策略实例的生命周期。
    每个策略在独立线程中运行，共享交易所和数据层。
    """
    def __init__(self, adapter: ExchangeAdapter, fetcher: DataFetcher,
                 config: Config | None = None):
        self.adapter = adapter
        self.fetcher = fetcher
        self.config = config
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

        # ── WebSocket 模式 ──
        self._ws_client: WSClient | None = None
        self._ws_mode: bool = False
        if config and config.ws_enabled:
            self._ws_client = WSClient(config.exchange)
            self._ws_mode = True

    def add_strategy(self, name: str, strategy_type: str, symbol: str,
                     timeframe: str = '1h', **params) -> str:
        """添加并启动一个策略。返回策略 ID（即 name）。"""
        factory = StrategyFactory()
        factory._register_builtins()
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
        """启动所有策略。WS 模式下先连接 WebSocket 并注册回调。"""
        self._running = True
        self._stop_event.clear()

        if self._ws_mode and self._ws_client:
            self._register_ws_channels()
            ws_thread = threading.Thread(
                target=self._ws_client.connect,
                daemon=True,
                name="ws-client",
            )
            ws_thread.start()
            # 等待 WS 连接就绪
            time.sleep(2)

        with self._lock:
            for name in self.strategies:
                self._start_strategy_thread(name)

    def stop_all(self):
        """停止所有策略并关闭 WebSocket。"""
        self._running = False
        self._stop_event.set()
        with self._lock:
            for name, thread in list(self._threads.items()):
                if thread and thread.is_alive():
                    pass
            for name in self.strategies:
                self.strategies[name].stop()

        if self._ws_client:
            self._ws_client.close()

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
        """策略主循环：WS 模式下由回调驱动，REST 模式下轮询拉取。"""
        strategy = self.strategies.get(name)
        if not strategy:
            return

        strategy.start()

        if self._ws_mode:
            # WS 模式：策略线程仅等待停止信号，数据由 WS 回调推送
            while not self._stop_event.is_set():
                self._stop_event.wait(5)
        else:
            # REST 模式：轮询拉取 K 线数据
            while not self._stop_event.is_set():
                try:
                    df = self.fetcher.get_ohlcv(
                        symbol=strategy.symbol,
                        timeframe=strategy.timeframe,
                        limit=50,
                        force_refresh=True
                    )

                    if df is not None and len(df) > 0:
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
                                approved, reason, order = self.risk_mgr.approve(
                                    signal, float(candle.get('close') or 0), account_balance=None
                                )
                                if approved and order:
                                    self.executor.submit(order)
                                    self._log_signal(name, signal, candle)
                                else:
                                    self._log_signal(
                                        name,
                                        {**signal, 'action': 'REJECTED', 'reason': reason},
                                        candle
                                    )

                    wait_seconds = self._timeframe_to_seconds(strategy.timeframe)
                    self._stop_event.wait(wait_seconds)

                except Exception as e:
                    print(f"[Runner] 策略 '{name}' 出错: {e}")
                    self._stop_event.wait(10)

    def _register_ws_channels(self):
        """根据策略配置自动注册 WebSocket 订阅频道。"""
        if not self._ws_client:
            return

        # 1) 加载 config.ws_channels 显式配置
        subscribed = set()
        if self.config and self.config.ws_channels:
            for ch in self.config.ws_channels:
                ch_type = ch.get("type")
                symbol = ch.get("symbol", "")
                interval = ch.get("interval", "1h")
                if ch_type == "ticker":
                    self._ws_client.subscribe_ticker(symbol)
                elif ch_type == "kline":
                    self._ws_client.subscribe_kline(symbol, interval)
                elif ch_type == "trade":
                    self._ws_client.subscribe_trade(symbol)
                subscribed.add((ch_type, symbol.replace("/", "").lower(), interval))

        # 2) 根据策略自动补充 kline 订阅
        for name, s in self.strategies.items():
            key = ("kline", s.symbol.replace("/", "").lower(), s.timeframe)
            if key not in subscribed:
                self._ws_client.subscribe_kline(s.symbol, s.timeframe)
                subscribed.add(key)

        # 3) 注册全局回调（所有交易对的数据都由这两个回调统一分发）
        self._ws_client.on_kline("*", self._ws_on_kline)
        self._ws_client.on_ticker("*", self._ws_on_ticker)

    def _ws_on_kline(self, kline: WSKline):
        """WS K线 回调：将 WSKline 转为 candle dict，分发给匹配的策略。"""
        candle = {
            'timestamp': kline.timestamp,
            'open': kline.open,
            'high': kline.high,
            'low': kline.low,
            'close': kline.close,
            'volume': kline.volume,
        }

        with self._lock:
            strategies = dict(self.strategies)

        for name, s in strategies.items():
            if not s.is_running:
                continue
            sym_match = s.symbol.replace("/", "").lower() == kline.symbol.lower()
            tf_match = s.timeframe == kline.interval
            if not (sym_match and tf_match):
                continue
            try:
                signal = s.on_bar(candle)
                if signal and signal.get('action') != 'HOLD':
                    signal['symbol'] = s.symbol
                    approved, reason, order = self.risk_mgr.approve(
                        signal, float(candle.get('close') or 0), account_balance=None
                    )
                    if approved and order:
                        self.executor.submit(order)
                        self._log_signal(name, signal, candle)
                    else:
                        self._log_signal(
                            name,
                            {**signal, 'action': 'REJECTED', 'reason': reason},
                            candle
                        )
            except Exception as e:
                print(f"[Runner] WS K线 在策略 '{name}' 中出错: {e}")

    def _ws_on_ticker(self, ticker: WSTicker):
        """WS 行情 回调：将 WSTicker 转为 dict，分发给匹配的策略 on_tick。"""
        ticker_dict = {
            'symbol': ticker.symbol,
            'bid': ticker.bid,
            'ask': ticker.ask,
            'last': ticker.last,
            'change_pct': ticker.change_pct,
            'volume_24h': ticker.volume_24h,
            'timestamp': ticker.timestamp,
        }

        with self._lock:
            strategies = dict(self.strategies)

        for name, s in strategies.items():
            if not s.is_running:
                continue
            sym_match = s.symbol.replace("/", "").lower() == ticker.symbol.lower()
            if not sym_match:
                continue
            try:
                s.on_tick(ticker_dict)
            except Exception as e:
                print(f"[Runner] WS 行情 在策略 '{name}' 中出错: {e}")

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


# ── 多交易所并行运行器 ──

class MultiExchangeRunner:
    """
    多交易所并行运行器：为每个交易所创建独立的 StrategyRunner 实例，
    支持 Binance / OKX / Bybit 三所同时运行，跨所价差检测。
    """

    SUPPORTED_EXCHANGES = {
        "binance": {"adapter_class": "ExchangeAdapter", "sandbox": True},
        "okx": {"adapter_class": "ExchangeAdapter", "sandbox": True},
        "bybit": {"adapter_class": "ExchangeAdapter", "sandbox": True},
    }

    def __init__(self, exchange_ids: list[str], config: Config | None = None):
        self.exchange_ids = exchange_ids
        self.config = config
        self.runners: dict[str, StrategyRunner] = {}
        self._running = False
        self._lock = threading.Lock()

    def start_all(self, strategies: list[dict] | None = None):
        """
        启动所有交易所的策略运行器。
        strategies: [{"type": "grid", "name": "grid_btc", "symbol": "BTC/USDT"}, ...]
        """
        self._running = True

        for ex_id in self.exchange_ids:
            try:
                adapter = ExchangeAdapter(ex_id, sandbox=True)
                adapter.connect()

                fetcher = DataFetcher(exchange=ex_id)
                runner = StrategyRunner(adapter, fetcher, self.config)
                runner.exchange_id = ex_id  # 标记所属交易所

                # 为每个交易所注册策略
                if strategies:
                    for s_cfg in strategies:
                        runner.add_strategy(
                            name=f"{ex_id}_{s_cfg.get('name', s_cfg['type'])}",
                            strategy_type=s_cfg["type"],
                            symbol=s_cfg.get("symbol", "BTC/USDT"),
                            timeframe=s_cfg.get("timeframe", "1h"),
                            **(s_cfg.get("params", {})),
                        )

                runner.start_all()
                with self._lock:
                    self.runners[ex_id] = runner
                print(f"[MultiRunner] {ex_id} 已启动，{len(runner.strategies)} 个策略")
            except Exception as e:
                print(f"[MultiRunner] {ex_id} 启动失败: {e}")

    def stop_all(self):
        """停止所有交易所的运行器"""
        self._running = False
        with self._lock:
            for ex_id, runner in list(self.runners.items()):
                try:
                    runner.stop_all()
                    print(f"[MultiRunner] {ex_id} 已停止")
                except Exception as e:
                    print(f"[MultiRunner] {ex_id} 停止异常: {e}")
        self.runners.clear()

    def get_cross_exchange_spread(self, symbol: str = "BTC/USDT") -> dict:
        """获取跨所价差（套利检测用）。"""
        result = {}
        prices = {}
        with self._lock:
            for ex_id, runner in self.runners.items():
                try:
                    ticker = runner.adapter.get_ticker(symbol)
                    if ticker:
                        prices[ex_id] = float(ticker.get("last", 0))
                except Exception:
                    pass

        if len(prices) >= 2:
            sorted_exs = sorted(prices.items(), key=lambda x: x[1])
            low_ex, low_price = sorted_exs[0]
            high_ex, high_price = sorted_exs[-1]
            spread = high_price - low_price
            spread_pct = (spread / low_price * 100) if low_price > 0 else 0
            result = {
                "low_exchange": low_ex,
                "low_price": round(low_price, 2),
                "high_exchange": high_ex,
                "high_price": round(high_price, 2),
                "spread": round(spread, 2),
                "spread_pct": round(spread_pct, 4),
                "all_prices": {k: round(v, 2) for k, v in prices.items()},
            }

        return result

    def get_status(self) -> dict:
        """获取多交易所运行状态"""
        status = {"running": self._running, "exchanges": {}}
        with self._lock:
            for ex_id, runner in self.runners.items():
                status["exchanges"][ex_id] = {
                    "strategies": len(runner.strategies),
                    "pending_orders": runner.executor.get_pending_count(),
                }
        return status
