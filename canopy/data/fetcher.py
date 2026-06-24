"""行情数据管理器 — 拉取、缓存、更新 OHLCV / Ticker / 深度数据。

使用 Parquet 格式缓存到本地目录，支持增量更新与缓存管理。
"""

from __future__ import annotations

import glob
import logging
import os
import re
from datetime import datetime
from typing import Any

import pandas as pd

from canopy.exchange.ccxt_adapter import ExchangeAdapter

logger = logging.getLogger(__name__)


class DataFetcher:
    """行情数据管理器。

    负责从交易所拉取 OHLCV / Ticker / 订单簿数据，
    并以 Parquet 格式缓存到本地，支持强制刷新与增量合并。
    """

    def __init__(self, adapter: ExchangeAdapter, cache_dir: str = "data/cache"):
        """
        Args:
            adapter:   ExchangeAdapter 实例，用于与交易所交互。
            cache_dir: 本地缓存目录路径。
        """
        self.adapter = adapter
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    # ── OHLCV ──

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: str | None = None,
        limit: int = 500,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """获取 OHLCV 数据，优先从缓存读取。

        缓存策略：
        - force_refresh=False：优先读缓存，缓存不存在时拉取。
        - force_refresh=True：跳过缓存，直接拉取。
        - 如果 since 晚于缓存最新时间，增量拉取后与缓存合并。

        Args:
            symbol:       交易对（如 'BTC/USDT'）。
            timeframe:    K 线周期。
            since:        ISO 日期字符串起始时间。
            limit:        拉取条数上限。
            force_refresh: 是否强制从交易所重新拉取。

        Returns:
            DataFrame，列: timestamp / open / high / low / close / volume。
        """
        if not force_refresh and since is None:
            cached = self.load_cached_ohlcv(symbol, timeframe)
            if cached is not None and not cached.empty:
                return cached

        if since is not None and not force_refresh:
            # 增量模式：检查缓存是否需要合并
            cached = self.load_cached_ohlcv(symbol, timeframe)
            if cached is not None and not cached.empty:
                cache_latest = cached["timestamp"].max()
                since_dt = pd.Timestamp(since)
                if since_dt <= cache_latest:
                    # 用户请求的起始时间已被缓存覆盖
                    return cached[cached["timestamp"] >= since_dt].reset_index(drop=True)
                # since 晚于缓存最新时间 → 拉取增量
                df_new = self.adapter.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
                if df_new.empty:
                    return cached[cached["timestamp"] >= since_dt].reset_index(drop=True)
                merged = pd.concat([cached, df_new], ignore_index=True)
                merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
                self.cache_ohlcv(symbol, timeframe, merged)
                return merged

        # 全量拉取
        df = self.adapter.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        if not df.empty:
            self.cache_ohlcv(symbol, timeframe, df)
        return df

    # ── Ticker 批量 ──

    def get_latest_tickers(self, symbols: list[str]) -> pd.DataFrame:
        """批量获取多个交易对的最新行情。

        Args:
            symbols: 交易对列表，如 ['BTC/USDT', 'ETH/USDT']。

        Returns:
            DataFrame，列: symbol / bid / ask / last / spread_pct / volume_24h。
        """
        rows: list[dict[str, Any]] = []
        for sym in symbols:
            ticker = self.adapter.fetch_ticker(sym)
            if not ticker:
                continue
            bid = ticker.get("bid") or 0
            ask = ticker.get("ask") or 0
            spread_pct = ((ask - bid) / ((bid + ask) / 2) * 100) if bid > 0 and ask > 0 else 0
            rows.append({
                "symbol": sym,
                "bid": bid,
                "ask": ask,
                "last": ticker.get("last"),
                "spread_pct": round(spread_pct, 4),
                "volume_24h": ticker.get("volume_24h"),
            })
        return pd.DataFrame(rows)

    # ── 订单簿 ──

    def get_order_book(self, symbol: str, depth: int = 10) -> dict[str, Any]:
        """获取深度（订单簿）数据。

        Args:
            symbol: 交易对。
            depth:  深度档位（默认 10）。

        Returns:
            {'bids': [[price, amount], ...],
             'asks': [[price, amount], ...],
             'timestamp': int}
            失败时返回空结构。
        """
        try:
            ob = self.adapter.exchange.fetch_order_book(symbol, limit=depth)  # type: ignore[union-attr]
            return {
                "bids": ob.get("bids", [])[:depth],
                "asks": ob.get("asks", [])[:depth],
                "timestamp": ob.get("timestamp"),
            }
        except Exception as e:
            logger.warning(f"get_order_book({symbol}, depth={depth}) 失败: {e}")
            return {"bids": [], "asks": [], "timestamp": None}

    # ── 缓存 I/O ──

    @staticmethod
    def _make_cache_key(symbol: str, timeframe: str) -> str:
        """将 symbol/timeframe 转换为安全的文件名片段。"""
        safe = re.sub(r"[^a-zA-Z0-9]", "_", f"{symbol}_{timeframe}")
        return safe

    def _cache_path(self, symbol: str, timeframe: str) -> str:
        """构建缓存文件完整路径。"""
        key = self._make_cache_key(symbol, timeframe)
        return os.path.join(self.cache_dir, f"{key}.parquet")

    def cache_ohlcv(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        """将 OHLCV DataFrame 写入 Parquet 缓存。

        Args:
            symbol:    交易对。
            timeframe: K 线周期。
            df:        待缓存的数据。
        """
        if df.empty:
            return
        path = self._cache_path(symbol, timeframe)
        df.to_parquet(path, index=False)
        logger.info(f"已缓存 {len(df)} 条 {symbol} {timeframe} → {path}")

    def load_cached_ohlcv(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        """从缓存加载 OHLCV 数据。

        Args:
            symbol:    交易对。
            timeframe: K 线周期。

        Returns:
            DataFrame；缓存不存在时返回 None。
        """
        path = self._cache_path(symbol, timeframe)
        if os.path.exists(path):
            return pd.read_parquet(path)
        return None

    # ── 缓存管理 ──

    def clear_cache(self, symbol: str | None = None) -> int:
        """清除缓存文件。

        Args:
            symbol: 指定交易对则只清除该交易对所有周期的缓存；
                    None 则清除全部。

        Returns:
            删除的文件数量。
        """
        if symbol is not None:
            safe = re.sub(r"[^a-zA-Z0-9]", "_", symbol)
            pattern = os.path.join(self.cache_dir, f"{safe}_*.parquet")
        else:
            pattern = os.path.join(self.cache_dir, "*.parquet")

        removed = 0
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                removed += 1
            except OSError as e:
                logger.warning(f"删除缓存失败 {f}: {e}")
        logger.info(f"已清除 {removed} 个缓存文件")
        return removed

    def get_cache_info(self) -> dict[str, Any]:
        """获取缓存目录统计信息。

        Returns:
            {'file_count': int, 'total_size_bytes': int, 'oldest_time': str|None,
             'newest_time': str|None, 'files': list[str]}
        """
        pattern = os.path.join(self.cache_dir, "*.parquet")
        files = glob.glob(pattern)

        total_size = 0
        oldest_ts: float | None = None
        newest_ts: float | None = None

        for f in files:
            total_size += os.path.getsize(f)
            mtime = os.path.getmtime(f)
            if oldest_ts is None or mtime < oldest_ts:
                oldest_ts = mtime
            if newest_ts is None or mtime > newest_ts:
                newest_ts = mtime

        return {
            "file_count": len(files),
            "total_size_bytes": total_size,
            "oldest_time": datetime.fromtimestamp(oldest_ts).isoformat() if oldest_ts else None,
            "newest_time": datetime.fromtimestamp(newest_ts).isoformat() if newest_ts else None,
            "files": [os.path.basename(f) for f in files],
        }
