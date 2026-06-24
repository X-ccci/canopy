"""
WebSocket 实时行情客户端 — 基于 websocket-client 实现 Binance/OKX 的多流订阅。

功能：
  - 订阅 ticker（24hr 行情）、kline（K 线）、trade（逐笔成交）
  - 异步回调机制：on_ticker / on_kline / on_trade，策略可注册回调
  - 自动重连（指数退避，max 30s）
  - 心跳保活（ping/pong）
  - 线程安全的数据缓存（最新 ticker/kline 可通过属性读取）
  - 优雅关闭（close 方法清理连接）
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import websocket

logger = logging.getLogger(__name__)

# ── 交易所 WS 端点 ──
WS_ENDPOINTS = {
    "binance": "wss://stream.binance.com:9443/ws",
    "okx": "wss://ws.okx.com:8443/ws/v5/public",
}

# ── 指数退避参数 ──
RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0
RECONNECT_BACKOFF_FACTOR = 2.0
RECONNECT_JITTER = 0.3


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class WSTicker:
    """WebSocket 实时 ticker 数据。"""
    symbol: str = ""
    last: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    change_pct: float = 0.0         # 24h 涨跌幅（百分比）
    volume_24h: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    timestamp: int = 0


@dataclass
class WSKline:
    """WebSocket 实时 K 线数据。"""
    symbol: str = ""
    interval: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    timestamp: int = 0
    closed: bool = False


@dataclass
class WSTrade:
    """WebSocket 逐笔成交数据。"""
    symbol: str = ""
    price: float = 0.0
    quantity: float = 0.0
    side: str = ""                   # buy / sell
    timestamp: int = 0
    trade_id: str = ""


# ═══════════════════════════════════════════════════════════════
# 回调注册表
# ═══════════════════════════════════════════════════════════════

@dataclass
class CallbackRegistry:
    """按交易对路由回调：symbol → callback_list。"""
    on_ticker: dict[str, list[Callable[[WSTicker], None]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    on_kline: dict[str, list[Callable[[WSKline], None]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    on_trade: dict[str, list[Callable[[WSTrade], None]]] = field(
        default_factory=lambda: defaultdict(list)
    )


# ═══════════════════════════════════════════════════════════════
# 线程安全缓存
# ═══════════════════════════════════════════════════════════════

class DataCache:
    """线程安全的最新行情缓存。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._tickers: dict[str, WSTicker] = {}
        self._klines: dict[tuple[str, str], WSKline] = {}   # (symbol, interval) -> kline
        self._trades: dict[str, list[WSTrade]] = defaultdict(list)
        self._trade_maxlen = 50

    # ── Ticker ──

    def set_ticker(self, symbol: str, ticker: WSTicker):
        with self._lock:
            self._tickers[symbol] = ticker

    def get_ticker(self, symbol: str) -> WSTicker | None:
        with self._lock:
            return self._tickers.get(symbol)

    @property
    def all_tickers(self) -> dict[str, WSTicker]:
        with self._lock:
            return dict(self._tickers)

    # ── Kline ──

    def set_kline(self, symbol: str, interval: str, kline: WSKline):
        with self._lock:
            self._klines[(symbol, interval)] = kline

    def get_kline(self, symbol: str, interval: str) -> WSKline | None:
        with self._lock:
            return self._klines.get((symbol, interval))

    # ── Trade ──

    def push_trade(self, symbol: str, trade: WSTrade):
        with self._lock:
            buf = self._trades[symbol]
            buf.append(trade)
            if len(buf) > self._trade_maxlen:
                self._trades[symbol] = buf[-self._trade_maxlen:]

    def get_recent_trades(self, symbol: str, count: int = 20) -> list[WSTrade]:
        with self._lock:
            buf = self._trades.get(symbol, [])
            return buf[-count:]


# ═══════════════════════════════════════════════════════════════
# 消息解析器 — 交易所 → 统一模型
# ═══════════════════════════════════════════════════════════════

class MessageParser:
    """将各交易所原始 JSON 消息解析为统一 WSTicker / WSKline / WSTrade。"""

    @staticmethod
    def parse(exchange_id: str, raw: dict) -> tuple[str | None, Any]:
        """解析原始消息，返回 (event_type, data) 或 (None, None)。"""
        if exchange_id == "binance":
            return MessageParser._parse_binance(raw)
        elif exchange_id == "okx":
            return MessageParser._parse_okx(raw)
        return None, None

    @staticmethod
    def _parse_binance(raw: dict) -> tuple[str | None, Any]:
        """解析 Binance WebSocket 消息。

        Binance 支持组合流 (streams)，也支持单一流。
        消息结构：
          - 单一流: {"e":"24hrTicker","s":"BTCUSDT","c":"...", ...}
          - 组合流: {"stream":"btcusdt@ticker","data":{...}}
        """
        if "stream" in raw:
            raw["stream"]
            data: dict = raw.get("data", {})
        else:
            raw.get("e", "")
            data = raw

        if not data:
            return None, None

        # 通过 e 字段判断事件类型
        event_type = data.get("e", "")

        if event_type == "24hrTicker":
            symbol = data.get("s", "").upper()
            ticker = WSTicker(
                symbol=symbol,
                last=float(data.get("c", 0.0)),
                bid=float(data.get("b", 0.0)),
                ask=float(data.get("a", 0.0)),
                change_pct=float(data.get("P", 0.0)),
                volume_24h=float(data.get("v", 0.0)),
                high_24h=float(data.get("h", 0.0)),
                low_24h=float(data.get("l", 0.0)),
                timestamp=int(data.get("E", 0)),
            )
            return "ticker", ticker

        elif event_type == "kline":
            k = data.get("k", {})
            symbol = data.get("s", "").upper()
            interval = k.get("i", "")
            kline = WSKline(
                symbol=symbol,
                interval=interval,
                open=float(k.get("o", 0.0)),
                high=float(k.get("h", 0.0)),
                low=float(k.get("l", 0.0)),
                close=float(k.get("c", 0.0)),
                volume=float(k.get("v", 0.0)),
                timestamp=int(k.get("t", 0)),
                closed=k.get("x", False),
            )
            return "kline", kline

        elif event_type == "trade":
            symbol = data.get("s", "").upper()
            trade = WSTrade(
                symbol=symbol,
                price=float(data.get("p", 0.0)),
                quantity=float(data.get("q", 0.0)),
                side="buy" if data.get("m", False) is False else "sell",
                timestamp=int(data.get("T", 0)),
                trade_id=str(data.get("t", "")),
            )
            return "trade", trade

        return None, None

    @staticmethod
    def _parse_okx(raw: dict) -> tuple[str | None, Any]:
        """解析 OKX WebSocket 消息。

        OKX V5 公共频道消息格式：
          {"arg":{"channel":"tickers","instId":"BTC-USDT"},"data":[...]}
        """
        arg = raw.get("arg", {})
        channel = arg.get("channel", "")
        inst_id = arg.get("instId", "")

        data_list = raw.get("data", [])
        if not data_list:
            return None, None
        item = data_list[0]

        if channel == "tickers":
            symbol = inst_id.replace("-", "")
            ticker = WSTicker(
                symbol=symbol,
                last=float(item.get("last", 0.0)),
                bid=float(item.get("bidPx", 0.0)),
                ask=float(item.get("askPx", 0.0)),
                change_pct=float(item.get("sodUtc8", 0.0)) or 0.0,
                volume_24h=float(item.get("vol24h", 0.0)),
                high_24h=float(item.get("high24h", 0.0)),
                low_24h=float(item.get("low24h", 0.0)),
                timestamp=int(item.get("ts", 0)),
            )
            return "ticker", ticker

        elif channel == "candle1m" or channel.startswith("candle"):
            # OKX candle channel: candle1m, candle5m, candle1H 等
            interval_map = {
                "candle1m": "1m", "candle3m": "3m", "candle5m": "5m",
                "candle15m": "15m", "candle30m": "30m",
                "candle1H": "1h", "candle2H": "2h", "candle4H": "4h",
                "candle1D": "1d", "candle1W": "1w",
            }
            interval = interval_map.get(channel, channel.replace("candle", ""))
            symbol = inst_id.replace("-", "")
            kline = WSKline(
                symbol=symbol,
                interval=interval,
                open=float(item[1]) if len(item) > 1 else 0.0,
                high=float(item[2]) if len(item) > 2 else 0.0,
                low=float(item[3]) if len(item) > 3 else 0.0,
                close=float(item[4]) if len(item) > 4 else 0.0,
                volume=float(item[5]) if len(item) > 5 else 0.0,
                timestamp=int(item[0]) if len(item) > 0 else 0,
                closed=True if len(item) > 7 and item[7] == "1" else False,
            )
            return "kline", kline

        elif channel == "trades":
            symbol = inst_id.replace("-", "")
            trade = WSTrade(
                symbol=symbol,
                price=float(item.get("px", 0.0)),
                quantity=float(item.get("sz", 0.0)),
                side=item.get("side", ""),
                timestamp=int(item.get("ts", 0)),
                trade_id=str(item.get("tradeId", "")),
            )
            return "trade", trade

        return None, None


# ═══════════════════════════════════════════════════════════════
# 订阅构造器
# ═══════════════════════════════════════════════════════════════

class SubscriptionBuilder:
    """根据 exchange_id 构造订阅请求。"""

    OKX_INTERVAL_MAP = {
        "1m": "candle1m", "3m": "candle3m", "5m": "candle5m",
        "15m": "candle15m", "30m": "candle30m",
        "1h": "candle1H", "2h": "candle2H", "4h": "candle4H",
        "1d": "candle1D", "1w": "candle1W",
    }

    @staticmethod
    def build(exchange_id: str, subscriptions: list[dict]) -> str:
        """构造订阅 JSON 字符串。

        subscriptions: [{"type":"ticker","symbol":"BTC/USDT"}, ...]
        """
        if exchange_id == "binance":
            return SubscriptionBuilder._build_binance(subscriptions)
        elif exchange_id == "okx":
            return SubscriptionBuilder._build_okx(subscriptions)
        return "{}"

    @staticmethod
    def _build_binance(subscriptions: list[dict]) -> str:
        streams = []
        for sub in subscriptions:
            symbol = sub["symbol"].replace("/", "").lower()
            stream_type = sub["type"]
            if stream_type == "ticker":
                streams.append(f"{symbol}@ticker")
            elif stream_type == "kline":
                interval = sub.get("interval", "1h")
                streams.append(f"{symbol}@kline_{interval}")
            elif stream_type == "trade":
                streams.append(f"{symbol}@trade")
        # 使用组合流
        "/".join(streams)
        # 如果是多流组合，修改端点
        # 但我们统一用单连接多订阅的方式，Binance 支持在单连接中发送多条 SUBSCRIBE
        params = streams
        return json.dumps({"method": "SUBSCRIBE", "params": params, "id": 1})

    @staticmethod
    def _build_okx(subscriptions: list[dict]) -> str:
        args = []
        for sub in subscriptions:
            inst_id = sub["symbol"].replace("/", "-")
            stream_type = sub["type"]
            if stream_type == "ticker":
                args.append({"channel": "tickers", "instId": inst_id})
            elif stream_type == "kline":
                interval = sub.get("interval", "1h")
                okx_channel = SubscriptionBuilder.OKX_INTERVAL_MAP.get(interval, f"candle{interval}")
                args.append({"channel": okx_channel, "instId": inst_id})
            elif stream_type == "trade":
                args.append({"channel": "trades", "instId": inst_id})
        return json.dumps({"op": "subscribe", "args": args})


# ═══════════════════════════════════════════════════════════════
# WebSocket 核心客户端
# ═══════════════════════════════════════════════════════════════

class WSClient:
    """WebSocket 实时行情客户端。

    在独立线程中运行，通过回调机制向策略推送数据，
    同时维护线程安全的缓存供外部随时读取最新行情。

    Usage:
        client = WSClient("binance")
        client.on_ticker("BTC/USDT", my_callback)
        client.subscribe_ticker("BTC/USDT")
        client.subscribe_kline("ETH/USDT", "1h")
        client.connect()
        # ... 运行中 ...
        btc_price = client.get_ticker("BTC/USDT")
        client.close()
    """

    def __init__(self, exchange_id: str):
        if exchange_id not in WS_ENDPOINTS:
            raise ValueError(f"不支持的交易所: {exchange_id}，可选: {list(WS_ENDPOINTS)}")

        self.exchange_id = exchange_id
        self.url = WS_ENDPOINTS[exchange_id]
        self._ws: websocket.WebSocketApp | None = None
        self._ws_thread: threading.Thread | None = None

        # 订阅清单
        self._subscriptions: list[dict] = []

        # 回调注册
        self._callbacks = CallbackRegistry()
        self._cache = DataCache()

        # 线程控制
        self._running = False
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

        # 重连
        self._reconnect_attempt = 0
        self._last_pong = time.time()

    # ── 公开 API：注册回调 ──

    def on_ticker(self, symbol: str, callback: Callable[[WSTicker], None]):
        """注册 ticker 回调。symbol 为 'BTC/USDT' 或 '*'（通配全部）。"""
        with self._lock:
            self._callbacks.on_ticker[symbol.upper()].append(callback)

    def on_kline(self, symbol: str, callback: Callable[[WSKline], None]):
        """注册 kline 回调。symbol 为 'BTC/USDT' 或 '*'（通配全部）。"""
        with self._lock:
            self._callbacks.on_kline[symbol.upper()].append(callback)

    def on_trade(self, symbol: str, callback: Callable[[WSTrade], None]):
        """注册 trade 回调。symbol 为 'BTC/USDT' 或 '*'（通配全部）。"""
        with self._lock:
            self._callbacks.on_trade[symbol.upper()].append(callback)

    # ── 公开 API：订阅 ──

    def subscribe_ticker(self, symbol: str):
        """订阅交易对的 24hr ticker。"""
        self._subscriptions.append({"type": "ticker", "symbol": symbol})

    def subscribe_kline(self, symbol: str, interval: str = "1h"):
        """订阅交易对的 K 线。"""
        self._subscriptions.append({"type": "kline", "symbol": symbol, "interval": interval})

    def subscribe_trade(self, symbol: str):
        """订阅交易对的逐笔成交。"""
        self._subscriptions.append({"type": "trade", "symbol": symbol})

    # ── 公开 API：读取缓存 ──

    def get_ticker(self, symbol: str) -> WSTicker | None:
        """获取指定交易对的最新 ticker（从缓存）。"""
        return self._cache.get_ticker(symbol.upper())

    def get_kline(self, symbol: str, interval: str = "1h") -> WSKline | None:
        """获取指定交易对的最新 K 线（从缓存）。"""
        return self._cache.get_kline(symbol.upper(), interval)

    def get_recent_trades(self, symbol: str, count: int = 20) -> list[WSTrade]:
        """获取指定交易对的最近逐笔成交（从缓存）。"""
        return self._cache.get_recent_trades(symbol.upper(), count)

    @property
    def all_tickers(self) -> dict[str, WSTicker]:
        """所有已订阅交易对的最新 ticker 快照。"""
        return self._cache.all_tickers

    # ── 连接管理 ──

    def connect(self):
        """启动 WebSocket 连接（阻塞当前线程直到 close）。

        如果需要在后台运行，请在独立线程中调用。
        """
        if self._running:
            logger.warning("WebSocket 已在运行中")
            return

        self._running = True
        self._stop_event.clear()

        # 构造订阅消息
        if not self._subscriptions:
            logger.warning("没有已注册的订阅，连接后不会收到数据")

        self._connect_ws()

    def _connect_ws(self):
        """建立 WebSocket 连接并启动事件循环。"""
        logger.info(f"正在连接 {self.exchange_id} WebSocket: {self.url}")
        self._ws = websocket.WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_pong=self._on_pong,
        )

        # 设置 ping 间隔
        ping_interval = 30  # 秒
        self._ws.run_forever(
            ping_interval=ping_interval,
            ping_timeout=10,
        )

    def _on_open(self, ws):
        """连接建立回调：发送订阅消息。"""
        logger.info(f"WebSocket 已连接 ({self.exchange_id})，发送 {len(self._subscriptions)} 条订阅")
        self._reconnect_attempt = 0

        if self._subscriptions:
            sub_msg = SubscriptionBuilder.build(self.exchange_id, self._subscriptions)
            ws.send(sub_msg)
            logger.debug(f"订阅消息: {sub_msg}")

    def _on_message(self, ws, message: str):
        """消息回调：解析并分发。"""
        try:
            raw = json.loads(message)
        except json.JSONDecodeError:
            logger.debug(f"无法解析消息: {message[:200]}")
            return

        # 忽略 OKX 的连接确认
        if self.exchange_id == "okx" and raw.get("event") == "subscribe":
            logger.debug(f"OKX 订阅确认: {raw}")
            return

        event_type, data = MessageParser.parse(self.exchange_id, raw)
        if event_type is None or data is None:
            return

        self._dispatch(event_type, data)

    def _on_error(self, ws, error):
        """错误回调。"""
        logger.error(f"WebSocket 错误: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """连接关闭回调：触发重连逻辑。"""
        logger.warning(
            f"WebSocket 断开 (code={close_status_code}, msg={close_msg})"
        )
        if self._running and not self._stop_event.is_set():
            self._schedule_reconnect()

    def _on_pong(self, ws, message):
        """Pong 回调：更新最后活动时间。"""
        self._last_pong = time.time()

    # ── 消息分发 ──

    def _dispatch(self, event_type: str, data: Any):
        """将解析后的数据写入缓存并触发回调。"""
        if event_type == "ticker":
            ticker: WSTicker = data
            self._cache.set_ticker(ticker.symbol, ticker)
            self._fire_callbacks("on_ticker", ticker.symbol, ticker)

        elif event_type == "kline":
            kline: WSKline = data
            self._cache.set_kline(kline.symbol, kline.interval, kline)
            # K 线回调仅在闭合时触发（或每根都触发，取决于策略需求）
            # 默认：每根 K 线更新都回调，策略可自行判断 closed 标志
            self._fire_callbacks("on_kline", kline.symbol, kline)

        elif event_type == "trade":
            trade: WSTrade = data
            self._cache.push_trade(trade.symbol, trade)
            self._fire_callbacks("on_trade", trade.symbol, trade)

    def _fire_callbacks(self, cb_attr: str, symbol: str, data: Any):
        """触发指定交易对的回调 + 通配回调。"""
        callbacks_map = getattr(self._callbacks, cb_attr)

        # 精确匹配
        for cb in callbacks_map.get(symbol, []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"回调异常 ({cb_attr}/{symbol}): {e}")

        # 通配回调
        for cb in callbacks_map.get("*", []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"通配回调异常 ({cb_attr}/*): {e}")

    # ── 重连逻辑 ──

    def _schedule_reconnect(self):
        """指数退避重连。"""
        delay = min(
            RECONNECT_BASE_DELAY * (RECONNECT_BACKOFF_FACTOR ** self._reconnect_attempt),
            RECONNECT_MAX_DELAY,
        )
        # 加入 jitter 避免惊群
        jitter = delay * RECONNECT_JITTER * (2 * (hash(str(time.time())) % 100) / 100 - 1)
        delay = max(0.5, delay + jitter)

        self._reconnect_attempt += 1
        logger.info(f"将在 {delay:.1f}s 后重连 (attempt #{self._reconnect_attempt})")

        # 在独立线程中等待后重连
        def _delayed_reconnect():
            self._stop_event.wait(delay)
            if self._running and not self._stop_event.is_set():
                logger.info("正在重连 WebSocket...")
                try:
                    self._connect_ws()
                except Exception as e:
                    logger.error(f"重连失败: {e}")
                    if self._running:
                        self._schedule_reconnect()

        t = threading.Thread(target=_delayed_reconnect, daemon=True)
        t.start()

    # ── 优雅关闭 ──

    def close(self):
        """关闭 WebSocket 连接，清理资源。"""
        logger.info("正在关闭 WebSocket 客户端...")
        self._running = False
        self._stop_event.set()

        if self._ws:
            try:
                self._ws.close()
            except Exception as e:
                logger.debug(f"关闭 WS 时异常: {e}")

        self._ws = None
        logger.info("WebSocket 客户端已关闭")

    # ── 状态 ──

    @property
    def is_connected(self) -> bool:
        """WebSocket 是否处于连接状态。"""
        return self._ws is not None and self._ws.sock is not None and self._ws.sock.connected

    def get_connection_status(self) -> dict:
        """获取连接状态详情。"""
        return {
            "exchange": self.exchange_id,
            "connected": self.is_connected,
            "running": self._running,
            "subscriptions": len(self._subscriptions),
            "reconnect_attempts": self._reconnect_attempt,
            "last_pong_ago": round(time.time() - self._last_pong, 1),
        }
