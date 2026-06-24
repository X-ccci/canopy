"""交易所适配层 — CCXT 统一封装：连接、行情、下单、账户管理。

屏蔽不同交易所 API 差异，为上层策略与回测引擎提供统一接口。
"""

from __future__ import annotations

import logging
from typing import Any

import ccxt
import pandas as pd

from canopy.config import Config

logger = logging.getLogger(__name__)


class ExchangeAdapter:
    """基于 CCXT 的交易所统一适配器。

    封装连接管理、行情获取、下单、余额查询等核心操作。
    所有 fetch_* 方法均包裹 try/except，失败时返回空数据结构而非抛出异常。
    """

    def __init__(self, exchange_id: str, config: Config):
        """
        Args:
            exchange_id: 交易所标识（如 'binance', 'okx', 'bybit'）。
            config:      Canopy 全局配置数据类实例。
        """
        self.exchange_id = exchange_id
        self.config = config
        self.exchange: ccxt.Exchange | None = None
        self._connected = False
        self._markets_cache: list[str] | None = None

    # ── 连接管理 ──

    def connect(self) -> bool:
        """初始化交易所实例并测试 API 连通性。

        通过交易所类的 getattr 动态获取，设置 sandbox 模式后
        用 fetch_ticker('BTC/USDT') 验证连接。

        Returns:
            True 表示连接成功，False 表示失败。
        """
        exchange_class = getattr(ccxt, self.exchange_id, None)
        if exchange_class is None:
            logger.error(f"不支持的交易所: {self.exchange_id}")
            return False

        self.exchange = exchange_class({
            "apiKey": self.config.api_key,
            "secret": self.config.api_secret,
            "enableRateLimit": True,
        })

        # 测试网配置
        if self.config.testnet and hasattr(self.exchange, "urls") and "test" in self.exchange.urls:
            self.exchange.set_sandbox_mode(True)

        try:
            # 用公开行情接口验证连通性（不需要 API Key）
            self.exchange.fetch_ticker("BTC/USDT")
            self._connected = True
            logger.info(f"已连接 {self.exchange_id}（testnet={self.config.testnet}）")
            return True
        except Exception as e:
            logger.error(f"连接 {self.exchange_id} 失败: {e}")
            return False

    # ── 行情 ──

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """获取单个交易对的最新行情。

        Args:
            symbol: 交易对（如 'BTC/USDT'）。

        Returns:
            标准化字典，键: symbol / bid / ask / last / volume_24h / timestamp。
            失败时返回空 dict。
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "bid": ticker.get("bid"),
                "ask": ticker.get("ask"),
                "last": ticker.get("last"),
                "volume_24h": ticker.get("baseVolume") or ticker.get("quoteVolume"),
                "timestamp": ticker.get("timestamp"),
            }
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning(f"fetch_ticker({symbol}) 失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"fetch_ticker({symbol}) 未知错误: {e}")
            return {}

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: str | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        """拉取 OHLCV K 线数据，返回 pandas DataFrame。

        Args:
            symbol:    交易对（如 'BTC/USDT'）。
            timeframe: K 线周期（'1m', '5m', '1h', '1d' 等）。
            since:     ISO 日期字符串（如 '2024-01-01'），或 None。
            limit:     返回条数上限。

        Returns:
            DataFrame，列: ['timestamp', 'open', 'high', 'low', 'close', 'volume']。
            失败时返回空 DataFrame（含相同列名）。
        """
        columns = ["timestamp", "open", "high", "low", "close", "volume"]

        # 将 ISO 字符串转为 Unix 毫秒时间戳
        since_ts: int | None = None
        if since is not None:
            try:
                since_ts = int(pd.Timestamp(since).timestamp() * 1000)
            except Exception:
                logger.warning(f"无法解析 since 参数: {since}，将忽略")
                since_ts = None

        try:
            raw = self.exchange.fetch_ohlcv(symbol, timeframe, since=since_ts, limit=limit)
            df = pd.DataFrame(raw, columns=columns)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning(f"fetch_ohlcv({symbol}, {timeframe}) 失败: {e}")
            return pd.DataFrame(columns=columns)
        except Exception as e:
            logger.error(f"fetch_ohlcv({symbol}, {timeframe}) 未知错误: {e}")
            return pd.DataFrame(columns=columns)

    # ── 账户 ──

    def fetch_balance(self) -> dict[str, dict[str, float]]:
        """获取账户余额。

        Returns:
            {'total': {symbol: amount, ...},
             'free':  {symbol: amount, ...},
             'used':  {symbol: amount, ...}}
            失败时返回三个空 dict。
        """
        try:
            balance = self.exchange.fetch_balance()
            return {
                "total": balance.get("total", {}),
                "free": balance.get("free", {}),
                "used": balance.get("used", {}),
            }
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning(f"fetch_balance 失败: {e}")
            return {"total": {}, "free": {}, "used": {}}
        except Exception as e:
            logger.error(f"fetch_balance 未知错误: {e}")
            return {"total": {}, "free": {}, "used": {}}

    # ── 下单 ──

    def create_market_order(self, symbol: str, side: str, amount: float) -> dict[str, Any]:
        """市价单。

        Args:
            symbol: 交易对。
            side:   'buy' 或 'sell'。
            amount: 下单数量。

        Returns:
            CCXT 订单结果字典，含 id / status / price / amount / cost / fee。
            失败时返回空 dict。
        """
        try:
            order = self.exchange.create_order(symbol, "market", side, amount)
            return {
                "id": order.get("id"),
                "status": order.get("status"),
                "price": order.get("price") or order.get("average"),
                "amount": order.get("amount") or order.get("filled"),
                "cost": order.get("cost"),
                "fee": order.get("fee"),
                "side": side,
                "symbol": symbol,
            }
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning(f"create_market_order({symbol}, {side}, {amount}) 失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"create_market_order 未知错误: {e}")
            return {}

    def create_limit_order(
        self, symbol: str, side: str, amount: float, price: float
    ) -> dict[str, Any]:
        """限价单。

        Args:
            symbol: 交易对。
            side:   'buy' 或 'sell'。
            amount: 下单数量。
            price:  限价。

        Returns:
            CCXT 订单结果字典，失败时返回空 dict。
        """
        try:
            order = self.exchange.create_order(symbol, "limit", side, amount, price)
            return {
                "id": order.get("id"),
                "status": order.get("status"),
                "price": order.get("price"),
                "amount": order.get("amount"),
                "cost": order.get("cost"),
                "fee": order.get("fee"),
                "side": side,
                "symbol": symbol,
            }
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning(f"create_limit_order({symbol}, {side}, {amount}, {price}) 失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"create_limit_order 未知错误: {e}")
            return {}

    # ── 订单管理 ──

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤销指定订单。

        Args:
            order_id: 订单 ID。
            symbol:   交易对。

        Returns:
            True 表示撤销成功，False 表示失败。
        """
        try:
            self.exchange.cancel_order(order_id, symbol)
            return True
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning(f"cancel_order({order_id}, {symbol}) 失败: {e}")
            return False
        except Exception as e:
            logger.error(f"cancel_order 未知错误: {e}")
            return False

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """获取未成交订单列表。

        Args:
            symbol: 交易对；None 表示全部交易对。

        Returns:
            订单字典列表，失败时返回空列表。
        """
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            return list(orders) if orders else []
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning(f"fetch_open_orders({symbol}) 失败: {e}")
            return []
        except Exception as e:
            logger.error(f"fetch_open_orders 未知错误: {e}")
            return []

    def fetch_order_status(self, order_id: str, symbol: str) -> dict[str, Any]:
        """查询指定订单状态。

        Args:
            order_id: 订单 ID。
            symbol:   交易对。

        Returns:
            订单状态字典，失败时返回空 dict。
        """
        try:
            order = self.exchange.fetch_order(order_id, symbol)
            return {
                "id": order.get("id"),
                "status": order.get("status"),
                "filled": order.get("filled"),
                "remaining": order.get("remaining"),
                "price": order.get("price"),
                "side": order.get("side"),
                "symbol": order.get("symbol"),
            }
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning(f"fetch_order_status({order_id}, {symbol}) 失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"fetch_order_status 未知错误: {e}")
            return {}

    # ── 市场信息 ──

    def get_supported_markets(self) -> list[str]:
        """返回交易所支持的所有交易对列表。

        首次调用时加载并缓存，后续调用直接返回缓存。

        Returns:
            交易对字符串列表，失败时返回空列表。
        """
        if self._markets_cache is not None:
            return self._markets_cache

        try:
            markets = self.exchange.load_markets()
            self._markets_cache = list(markets.keys())
            return self._markets_cache
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning(f"get_supported_markets 失败: {e}")
            return []
        except Exception as e:
            logger.error(f"get_supported_markets 未知错误: {e}")
            return []

    def get_min_amount(self, symbol: str) -> float:
        """获取交易对的最小下单量。

        Args:
            symbol: 交易对（如 'BTC/USDT'）。

        Returns:
            最小下单量，无法获取时返回 0.0。
        """
        try:
            markets = self.exchange.load_markets()
            market = markets.get(symbol)
            if market is None:
                logger.warning(f"未找到交易对: {symbol}")
                return 0.0
            limits = market.get("limits", {})
            amount_limits = limits.get("amount", {})
            return amount_limits.get("min", 0.0)
        except Exception as e:
            logger.warning(f"get_min_amount({symbol}) 失败: {e}")
            return 0.0
