"""多交易所并发管理器 — 并行连接 Binance/OKX/Bybit，跨所价差套利。

为上层策略与 CanopyAPI 提供统一多所行情聚合接口：
- 并行查询所有交易所，取最优价格。
- 跨所价差检测，识别套利机会。
- 统一状态监控（连接状态、延迟）。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from canopy.config import Config
from canopy.exchange.ccxt_adapter import ExchangeAdapter

logger = logging.getLogger(__name__)


@dataclass
class ExchangeStatus:
    """单个交易所的状态快照。"""
    exchange_id: str
    connected: bool = False
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class ArbitrageOpportunity:
    """跨所价差套利机会。"""
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float          # 在 buy_exchange 的 ask 价格
    sell_price: float         # 在 sell_exchange 的 bid 价格
    spread_pct: float         # 价差百分比 (sell - buy) / buy * 100
    net_profit_pct: float     # 扣除手续费后净利润百分比
    timestamp: int = 0


class MultiExchangeManager:
    """多交易所并发管理器。

    管理多个 ExchangeAdapter 实例，提供统一的并行行情查询与套利检测。

    Usage:
        cfg = Config()
        mgr = MultiExchangeManager(cfg)
        mgr.add_exchange("binance")
        mgr.add_exchange("okx")
        mgr.add_exchange("bybit")

        # 查最优价格
        best = mgr.fetch_ticker("BTC/USDT")

        # 套利检测
        opps = mgr.detect_arbitrage("BTC/USDT", min_spread_pct=0.5)
    """

    # 默认手续费率（taker fee），各交易所一般在 0.05%~0.1%
    DEFAULT_FEE_RATE = 0.001  # 0.1%

    def __init__(self, config: Config, fee_rate: float | None = None):
        """
        Args:
            config:    Canopy 全局配置。
            fee_rate:  手续费率（小数，如 0.001 = 0.1%）。None 则用默认值。
        """
        self.config = config
        self.fee_rate = fee_rate if fee_rate is not None else self.DEFAULT_FEE_RATE
        self.adapters: dict[str, ExchangeAdapter] = {}
        self._status_cache: dict[str, ExchangeStatus] = {}

    # ── 交易所管理 ──

    def add_exchange(self, exchange_id: str) -> bool:
        """创建并连接一个交易所实例。

        Args:
            exchange_id: 交易所标识（如 'binance', 'okx', 'bybit'）。

        Returns:
            True 表示连接成功，False 表示失败。
        """
        if exchange_id in self.adapters:
            logger.info(f"交易所 {exchange_id} 已存在，跳过")
            return self.adapters[exchange_id]._connected

        adapter = ExchangeAdapter(exchange_id, self.config)
        ok = adapter.connect()
        self.adapters[exchange_id] = adapter
        self._status_cache[exchange_id] = ExchangeStatus(
            exchange_id=exchange_id,
            connected=ok,
            latency_ms=0.0,
            error="" if ok else f"连接 {exchange_id} 失败",
        )
        return ok

    def remove_exchange(self, exchange_id: str) -> bool:
        """移除一个交易所实例。

        Args:
            exchange_id: 交易所标识。

        Returns:
            True 表示移除成功，False 表示该交易所不存在。
        """
        if exchange_id not in self.adapters:
            logger.warning(f"交易所 {exchange_id} 不存在，无法移除")
            return False
        del self.adapters[exchange_id]
        self._status_cache.pop(exchange_id, None)
        return True

    @property
    def exchange_ids(self) -> list[str]:
        return list(self.adapters.keys())

    @property
    def connected_count(self) -> int:
        return sum(1 for a in self.adapters.values() if a._connected)

    # ── 行情查询 ──

    def fetch_ticker(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        """获取行情。指定 exchange 则单所查询，None 则并行查所有取最优。

        Args:
            symbol:   交易对（如 'BTC/USDT'）。
            exchange: 交易所标识；None 表示查所有并返回最优。

        Returns:
            exchange=None 时返回 {'exchange', 'price', 'bid', 'ask', 'all_tickers': [...]}。
            指定 exchange 时返回该所 ticker dict，失败返回 {}。
        """
        if exchange is not None:
            adapter = self.adapters.get(exchange)
            if adapter is None:
                logger.warning(f"交易所 {exchange} 未注册")
                return {}
            return self._fetch_with_latency(adapter, symbol)

        # 并行查询所有交易所
        return self._fetch_all_parallel(symbol)

    def _fetch_with_latency(self, adapter: ExchangeAdapter, symbol: str) -> dict[str, Any]:
        """单所查询并记录延迟。"""
        t0 = time.perf_counter()
        ticker = adapter.fetch_ticker(symbol)
        latency = (time.perf_counter() - t0) * 1000

        status = self._status_cache.get(adapter.exchange_id)
        if status:
            status.latency_ms = latency
            status.connected = bool(ticker)

        if ticker:
            ticker["exchange"] = adapter.exchange_id
            ticker["latency_ms"] = round(latency, 1)
        return ticker

    def _fetch_all_parallel(self, symbol: str) -> dict[str, Any]:
        """并行查询所有交易所，返回最优买/卖价。"""
        if not self.adapters:
            logger.warning("无已注册交易所")
            return {}

        all_tickers: list[dict] = []
        best_bid = 0.0
        best_ask = float("inf")
        best_bid_exchange = ""
        best_ask_exchange = ""

        with ThreadPoolExecutor(max_workers=min(len(self.adapters), 10)) as executor:
            futures = {
                executor.submit(self._fetch_with_latency, adapter, symbol): adapter.exchange_id
                for adapter in self.adapters.values()
            }

            for future in as_completed(futures):
                exchange_id = futures[future]
                try:
                    ticker = future.result()
                    if ticker:
                        all_tickers.append(ticker)
                        bid = ticker.get("bid", 0) or 0
                        ask = ticker.get("ask", 0) or float("inf")
                        if bid > best_bid:
                            best_bid = bid
                            best_bid_exchange = exchange_id
                        if ask < best_ask:
                            best_ask = ask
                            best_ask_exchange = exchange_id
                except Exception as e:
                    logger.error(f"并行查询 {exchange_id} 异常: {e}")

        if not all_tickers:
            return {}

        return {
            "symbol": symbol,
            "bid": best_bid,
            "ask": best_ask,
            "bid_exchange": best_bid_exchange,
            "ask_exchange": best_ask_exchange,
            "price": (best_bid + best_ask) / 2 if best_bid and best_ask != float("inf") else 0,
            "all_tickers": all_tickers,
        }

    # ── 跨所套利检测 ──

    def detect_arbitrage(
        self,
        symbol: str,
        min_spread_pct: float = 0.5,
    ) -> list[ArbitrageOpportunity]:
        """跨交易所价差套利检测。

        并行拉取所有交易所 ticker，计算任意两所之间的价差。
        价差公式：当 exchange_A 的 ask < exchange_B 的 bid 时，
        在 A 买入、在 B 卖出可套利。
        净利润 = 价差百分比 - 双边手续费。

        Args:
            symbol:         交易对（如 'BTC/USDT'）。
            min_spread_pct: 最小价差百分比阈值（默认 0.5%）。

        Returns:
            ArbitrageOpportunity 列表，按净利润降序排列。
        """
        if len(self.adapters) < 2:
            logger.warning("套利检测需要至少 2 个交易所")
            return []

        # 并行获取所有交易所 ticker
        tickers: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=min(len(self.adapters), 10)) as executor:
            futures = {
                executor.submit(self._fetch_with_latency, adapter, symbol): adapter.exchange_id
                for adapter in self.adapters.values()
            }
            for future in as_completed(futures):
                exchange_id = futures[future]
                try:
                    ticker = future.result()
                    if ticker and ticker.get("ask") and ticker.get("bid"):
                        tickers[exchange_id] = ticker
                except Exception as e:
                    logger.error(f"套利检测 - {exchange_id} 查询异常: {e}")

        if len(tickers) < 2:
            return []

        # 两两比较，找套利机会
        opportunities: list[ArbitrageOpportunity] = []
        exchanges = list(tickers.keys())

        for i in range(len(exchanges)):
            for j in range(i + 1, len(exchanges)):
                ex_a = exchanges[i]
                ex_b = exchanges[j]
                ticker_a = tickers[ex_a]
                ticker_b = tickers[ex_b]

                ask_a = float(ticker_a["ask"])
                bid_a = float(ticker_a["bid"])
                ask_b = float(ticker_b["ask"])
                bid_b = float(ticker_b["bid"])

                # 场景 1：在 A 买（ask_a），在 B 卖（bid_b）
                if bid_b > ask_a and ask_a > 0:
                    spread_pct = (bid_b - ask_a) / ask_a * 100
                    net_profit = spread_pct - self.fee_rate * 2 * 100
                    if net_profit >= min_spread_pct:
                        opportunities.append(ArbitrageOpportunity(
                            symbol=symbol,
                            buy_exchange=ex_a,
                            sell_exchange=ex_b,
                            buy_price=ask_a,
                            sell_price=bid_b,
                            spread_pct=round(spread_pct, 4),
                            net_profit_pct=round(net_profit, 4),
                            timestamp=int(time.time() * 1000),
                        ))

                # 场景 2：在 B 买（ask_b），在 A 卖（bid_a）
                if bid_a > ask_b and ask_b > 0:
                    spread_pct = (bid_a - ask_b) / ask_b * 100
                    net_profit = spread_pct - self.fee_rate * 2 * 100
                    if net_profit >= min_spread_pct:
                        opportunities.append(ArbitrageOpportunity(
                            symbol=symbol,
                            buy_exchange=ex_b,
                            sell_exchange=ex_a,
                            buy_price=ask_b,
                            sell_price=bid_a,
                            spread_pct=round(spread_pct, 4),
                            net_profit_pct=round(net_profit, 4),
                            timestamp=int(time.time() * 1000),
                        ))

        # 按净利润降序排列
        opportunities.sort(key=lambda o: o.net_profit_pct, reverse=True)
        return opportunities

    # ── 状态 ──

    def get_all_status(self) -> dict[str, Any]:
        """获取所有交易所的连接状态和延迟。

        并行 ping 每个交易所，更新延迟数据。

        Returns:
            {
                'total': int,
                'connected': int,
                'exchanges': {exchange_id: ExchangeStatus, ...}
            }
        """
        if not self.adapters:
            return {"total": 0, "connected": 0, "exchanges": {}}

        # 并行 ping
        with ThreadPoolExecutor(max_workers=min(len(self.adapters), 10)) as executor:
            futures = {
                executor.submit(self._ping_exchange, adapter): adapter.exchange_id
                for adapter in self.adapters.values()
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass

        exchanges_status = {
            ex_id: {
                "connected": s.connected,
                "latency_ms": round(s.latency_ms, 1),
                "error": s.error,
            }
            for ex_id, s in self._status_cache.items()
        }

        return {
            "total": len(self.adapters),
            "connected": self.connected_count,
            "exchanges": exchanges_status,
        }

    def _ping_exchange(self, adapter: ExchangeAdapter) -> None:
        """Ping 单个交易所，更新延迟和连接状态。"""
        status = self._status_cache.get(adapter.exchange_id)
        t0 = time.perf_counter()
        try:
            ticker = adapter.fetch_ticker("BTC/USDT")
            latency = (time.perf_counter() - t0) * 1000
            if status:
                status.latency_ms = latency
                status.connected = bool(ticker)
                status.error = "" if ticker else "ticker 返回为空"
        except Exception as e:
            if status:
                status.latency_ms = 0.0
                status.connected = False
                status.error = str(e)

    # ── 交易对发现 ──

    def get_common_symbols(self) -> list[str]:
        """获取所有交易所共同支持的交易对列表。

        Returns:
            交易对字符串列表，按字母排序。
        """
        if len(self.adapters) < 2:
            return self.adapters[list(self.adapters.keys())[0]].get_supported_markets() if self.adapters else []

        all_markets: list[set[str]] = []
        for adapter in self.adapters.values():
            markets = adapter.get_supported_markets()
            if markets:
                all_markets.append(set(markets))

        if not all_markets:
            return []

        common = all_markets[0]
        for m in all_markets[1:]:
            common = common & m

        return sorted(common)
