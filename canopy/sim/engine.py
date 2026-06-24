"""模拟撮合引擎 — 从 Parquet 历史数据逐根推进，模拟交易所行情与订单撮合。

与 ExchangeAdapter 提供同签名接口（fetch_ticker / fetch_ohlcv），
策略层无需修改即可从真实环境切换到模拟模式。
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class SimEngine:
    """模拟撮合引擎。

    从 Parquet 文件加载历史 K 线数据，按时间顺序逐根推进。
    每根 K 线即代表一个时间步，在该时间步内：
    - fetch_ticker 返回当前 K 线的 bid/ask/last
    - fetch_ohlcv 返回截止当前时间步的历史 K 线
    - 市价单按当前 K 线收盘价成交（含滑点）
    - 限价单在触及价位时成交
    """

    def __init__(
        self,
        data_path: str,
        slippage: float = 0.0005,
        commission: float = 0.001,
    ):
        """
        Args:
            data_path:  Parquet 文件路径，列必须包含 timestamp/open/high/low/close/volume。
            slippage:   滑点比例（默认 0.05%），成交价 = 理论价 * (1 ± slippage)。
            commission: 手续费率（默认 0.1%）。
        """
        self.data_path = data_path
        self.slippage = slippage
        self.commission = commission

        self._df: pd.DataFrame | None = None
        self._cursor: int = 0
        self._current_candle: dict[str, Any] = {}
        self._symbol: str = ""

    # ── 数据加载与推进 ──

    def load(self) -> bool:
        """加载 Parquet 数据并初始化引擎。

        Returns:
            True 表示加载成功，False 表示失败。
        """
        try:
            self._df = pd.read_parquet(self.data_path)
            if self._df.empty:
                logger.error(f"Parquet 文件为空: {self.data_path}")
                return False

            # 确保必要列存在
            required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
            missing = required_cols - set(str(c).lower() for c in self._df.columns)
            if missing:
                logger.error(f"Parquet 缺少必要列: {missing}")
                return False

            # 规范化列名
            self._df.columns = [c.lower() for c in self._df.columns]
            self._df["timestamp"] = pd.to_datetime(self._df["timestamp"])

            # 按时间排序
            self._df = self._df.sort_values("timestamp").reset_index(drop=True)
            self._cursor = 0
            self._current_candle = self._df_to_candle(self._df.iloc[0])

            # 从文件名推断 symbol
            import os
            basename = os.path.splitext(os.path.basename(self.data_path))[0]
            parts = basename.rsplit("_", 1)
            self._symbol = parts[0].replace("_", "/") if len(parts) > 1 else "UNKNOWN/USDT"

            logger.info(
                f"SimEngine 已加载 {len(self._df)} 条 K 线 → {self.data_path}"
            )
            return True
        except Exception as e:
            logger.error(f"加载 Parquet 失败: {e}")
            return False

    def step(self) -> bool:
        """推进到下一根 K 线。

        Returns:
            True 表示推进成功，False 表示已到末尾。
        """
        if self._df is None:
            return False
        self._cursor += 1
        if self._cursor >= len(self._df):
            return False
        self._current_candle = self._df_to_candle(self._df.iloc[self._cursor])
        return True

    def reset(self) -> None:
        """重置游标到起始位置。"""
        if self._df is not None and len(self._df) > 0:
            self._cursor = 0
            self._current_candle = self._df_to_candle(self._df.iloc[0])

    # ── 行情接口（与 ExchangeAdapter 同签名） ──

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """获取当前 K 线对应的模拟行情。

        基于当前 K 线的 OHLC 数据构造 bid/ask/last。

        Args:
            symbol: 交易对。

        Returns:
            {'symbol', 'bid', 'ask', 'last', 'volume_24h', 'timestamp'}
        """
        c = self._current_candle
        if not c:
            return {}
        half_spread = (c["high"] - c["low"]) * 0.1
        mid = c["close"]
        return {
            "symbol": symbol,
            "bid": round(mid - half_spread, 2),
            "ask": round(mid + half_spread, 2),
            "last": c["close"],
            "volume_24h": c["volume"],
            "timestamp": c["timestamp"],
        }

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: str | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        """返回截止当前游标位置的历史 K 线数据。

        Args:
            symbol:    交易对。
            timeframe: K 线周期（模拟中忽略，按实际数据）。
            since:     ISO 日期起始时间过滤。
            limit:     返回条数上限。

        Returns:
            DataFrame，列: timestamp/open/high/low/close/volume。
        """
        if self._df is None:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        subset = self._df.iloc[: self._cursor + 1].copy()

        if since is not None:
            try:
                since_dt = pd.Timestamp(since)
                subset = subset[subset["timestamp"] >= since_dt]
            except Exception:
                pass

        return subset.tail(limit).reset_index(drop=True)

    # ── 订单撮合 ──

    def match_market_order(self, side: str, amount: float) -> dict[str, Any]:
        """市价单撮合：按当前 K 线收盘价成交（含滑点）。

        Args:
            side:   'buy' 或 'sell'。
            amount: 下单数量。

        Returns:
            {'id', 'status', 'price', 'amount', 'cost', 'fee', 'side', 'symbol', 'filled'}
        """
        c = self._current_candle
        if not c:
            return {}

        base_price = c["close"]
        direction = 1 if side == "buy" else -1
        fill_price = base_price * (1 + direction * self.slippage)
        cost = fill_price * amount
        fee = cost * self.commission

        return {
            "id": f"sim_market_{self._cursor}_{side}",
            "status": "filled",
            "price": round(fill_price, 4),
            "amount": amount,
            "cost": round(cost, 4),
            "fee": round(fee, 4),
            "side": side,
            "symbol": self._symbol,
            "filled": amount,
        }

    def match_limit_order(self, side: str, amount: float, price: float) -> dict[str, Any] | None:
        """限价单撮合：检查当前 K 线是否触及限价。

        买单：low <= price 即成交；卖单：high >= price 即成交。
        成交价取限价（买方最优）。

        Args:
            side:   'buy' 或 'sell'。
            amount: 下单数量。
            price:  限价。

        Returns:
            成交结果字典；订单未触发时返回 None。
        """
        c = self._current_candle
        if not c:
            return None

        if side == "buy" and c["low"] <= price:
            triggered = True
        elif side == "sell" and c["high"] >= price:
            triggered = True
        else:
            triggered = False

        if not triggered:
            return None

        fill_price = price
        cost = fill_price * amount
        fee = cost * self.commission

        return {
            "id": f"sim_limit_{self._cursor}_{side}",
            "status": "filled",
            "price": round(fill_price, 4),
            "amount": amount,
            "cost": round(cost, 4),
            "fee": round(fee, 4),
            "side": side,
            "symbol": self._symbol,
            "filled": amount,
        }

    def check_limit_order(self, side: str, price: float) -> bool:
        """检查限价单在当前 K 线是否触发。

        Args:
            side:  'buy' 或 'sell'。
            price: 限价。

        Returns:
            True 表示已触发。
        """
        c = self._current_candle
        if not c:
            return False
        if side == "buy":
            return c["low"] <= price  # type: ignore[no-any-return]
        return c["high"] >= price  # type: ignore[no-any-return]

    # ── 状态查询 ──

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def total_bars(self) -> int:
        return len(self._df) if self._df is not None else 0

    @property
    def current_candle(self) -> dict[str, Any]:
        return self._current_candle

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def current_timestamp(self):
        """当前 K 线的时间戳。"""
        c = self._current_candle
        return c.get("timestamp") if c else None

    # ── 内部工具 ──

    @staticmethod
    def _df_to_candle(row: pd.Series) -> dict[str, Any]:
        return {
            "timestamp": str(row.get("timestamp", "")),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0)),
        }
