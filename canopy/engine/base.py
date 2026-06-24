"""策略基类 — 定义交易策略的生命周期接口与参数 schema。"""

from abc import ABC, abstractmethod


class Strategy(ABC):
    """交易策略抽象基类。

    所有策略必须继承此类并实现生命周期方法。
    策略参数通过 params 字典传入，子类应定义 default_params 并提供类型校验。
    """

    default_params: dict = {}

    def __init__(self, name: str = "", params: dict | None = None, exchange_adapter=None):
        self.name = name or self.__class__.__name__
        self.exchange = exchange_adapter
        self.params = {**self.default_params, **(params or {})}
        self._is_running: bool = False
        self.symbol: str = ""
        self.timeframe: str = "1h"

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self):
        """启动策略。"""
        self._is_running = True
        self.on_start()

    def stop(self):
        """停止策略。"""
        self._is_running: bool = False
        self.symbol: str = ""
        self.timeframe: str = "1h"
        self.on_stop()

    # ── 子类可覆写的生命周期回调 ──

    def on_start(self):
        """策略启动时的初始化逻辑（子类覆写）。"""
        pass

    def on_stop(self):
        """策略停止时的清理逻辑（子类覆写）。"""
        pass

    # ── 子类必须实现的抽象方法 ──

    @abstractmethod
    def on_tick(self, ticker: dict):
        """逐笔成交回调。

        Args:
            ticker: 交易所返回的 ticker 数据，包含 bid/ask/last 等字段。
        """
        ...

    @abstractmethod
    def on_bar(self, candle: dict):
        """K线闭合回调。

        Args:
            candle: 包含 open/high/low/close/volume/time 的 OHLCV 数据。
        """
        ...

    @abstractmethod
    def on_order(self, order: dict):
        """订单状态变更回调。

        Args:
            order: 包含 id/symbol/type/side/status/filled 等字段的订单信息。
        """
        ...

    def validate_params(self) -> bool:
        """校验策略参数是否合法（子类可覆写）。

        Returns:
            bool: 参数是否有效。
        """
        return True
