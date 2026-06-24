"""策略工厂 — 根据名称和参数实例化策略，支持自定义规则组合。"""

from typing import Any

from canopy.engine.base import Strategy


class CustomStrategy(Strategy):
    """自定义规则组合策略。

    根据用户提供的规则列表逐条评估：
    - 所有规则满足 → 做多。
    - 所有规则的反向条件满足 → 做空。
    - 否则 → 持有。

    支持的 indicator:
        'close', 'ma', 'std', 'volume', 'rsi'
    支持的 condition:
        '>', '<', '>=', '<=', 'cross_above', 'cross_below'
    """

    default_params = {"rules": []}

    def __init__(self, rules: list[dict], **kwargs: Any) -> None:
        super().__init__(name="CustomStrategy", **kwargs)
        self.params["rules"] = rules
        self._closes: list[float] = []
        self._volumes: list[float] = []
        self._prev_close: float | None = None
        self._prev_ma: float | None = None
        self._position: int = 0

    def _eval_indicator(self, name: str, closes: list[float], volumes: list[float]) -> float | None:
        """根据指标名称计算当前值。

        Args:
            name:    指标名称。
            closes:  收盘价序列。
            volumes: 成交量序列。

        Returns:
            当前指标值，无法计算时返回 None。
        """
        if name == "close":
            return closes[-1] if closes else None
        if name == "volume":
            return volumes[-1] if volumes else None
        if name == "ma":
            n = 20
            if len(closes) >= n:
                return sum(closes[-n:]) / n  # type: ignore[no-any-return]
            return None
        if name == "std":
            n = 20
            if len(closes) >= n:
                avg = sum(closes[-n:]) / n
                var = sum((x - avg) ** 2 for x in closes[-n:]) / (n - 1)
                return var ** 0.5  # type: ignore[no-any-return]
            return None
        if name == "rsi":
            n = 14
            if len(closes) < n + 1:
                return None
            gains, losses = 0.0, 0.0
            for i in range(-n, 0):
                diff = closes[i] - closes[i - 1]
                if diff > 0:
                    gains += diff
                else:
                    losses -= diff
            avg_gain = gains / n
            avg_loss = losses / n
            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            return 100.0 - 100.0 / (1.0 + rs)
        return None

    def on_tick(self, ticker: dict) -> None:
        pass

    def on_bar(self, candle: dict) -> dict:
        """逐条评估规则，返回信号。

        Args:
            candle: OHLCV 字典。

        Returns:
            信号字典。
        """
        close = candle["close"]
        volume = candle.get("volume", 0)

        self._closes.append(close)
        self._volumes.append(volume)

        rules: list[dict] = self.params["rules"]
        if not rules:
            return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "无自定义规则"}

        all_long = True
        all_short = True

        for rule in rules:
            indicator = rule["indicator"]
            condition = rule["condition"]
            value = rule["value"]

            current = self._eval_indicator(indicator, self._closes, self._volumes)
            if current is None:
                return {"action": "HOLD", "price": close, "stop_loss": None,
                        "reason": f"指标 {indicator} 数据不足"}

            long_ok = False
            short_ok = False

            if condition == ">":
                long_ok = current > value
                short_ok = current < value
            elif condition == "<":
                long_ok = current < value
                short_ok = current > value
            elif condition == ">=":
                long_ok = current >= value
                short_ok = current <= value
            elif condition == "<=":
                long_ok = current <= value
                short_ok = current >= value
            elif condition == "cross_above":
                prev = self._eval_indicator(indicator, self._closes[:-1], self._volumes[:-1])
                long_ok = (prev is not None and prev <= value and current > value)
                short_ok = (prev is not None and prev >= value and current < value)
            elif condition == "cross_below":
                prev = self._eval_indicator(indicator, self._closes[:-1], self._volumes[:-1])
                long_ok = (prev is not None and prev >= value and current < value)
                short_ok = (prev is not None and prev <= value and current > value)

            all_long = all_long and long_ok
            all_short = all_short and short_ok

        if all_long and self._position <= 0:
            self._position = 1
            return {"action": "BUY", "price": close, "stop_loss": None, "reason": "所有规则满足，做多"}
        if all_short and self._position >= 0:
            self._position = -1
            return {"action": "SELL", "price": close, "stop_loss": None, "reason": "所有规则反向满足，做空"}

        return {"action": "HOLD", "price": close, "stop_loss": None, "reason": "规则未完全满足"}

    def on_order(self, order: dict) -> None:
        pass


class StrategyFactory:
    """策略工厂：注册并按名创建策略实例。"""

    def __init__(self) -> None:
        self._registry: dict[str, type[Strategy]] = {}

    def register(self, name: str, cls: type[Strategy]) -> None:
        """注册一个策略类。

        Args:
            name: 策略名称（用于 create 时查找）。
            cls:  策略类（须继承 Strategy）。
        """
        if not issubclass(cls, Strategy):
            raise TypeError(f"{cls.__name__} 必须继承 Strategy")
        self._registry[name] = cls

    def create(self, name: str, **params: Any) -> Strategy:
        """根据名称创建策略实例。

        Args:
            name:    已注册的策略名称。
            **params: 传递给策略构造函数的参数。

        Returns:
            策略实例。

        Raises:
            ValueError: 策略名称未注册。
        """
        if name not in self._registry:
            raise ValueError(f"未注册的策略: {name}。可用: {list(self._registry.keys())}")
        cls = self._registry[name]
        return cls(params=params) if params else cls()

    def list_strategies(self) -> list[str]:
        """返回所有已注册的策略名称。"""
        return list(self._registry.keys())

    def create_custom(self, rules: list[dict]) -> CustomStrategy:
        """根据用户自定义规则组合创建策略。

        Args:
            rules: 规则列表，每条规则为 dict:
                   {'indicator': str, 'condition': str, 'value': float}。

        Returns:
            CustomStrategy 实例，在 on_bar 中逐条评估规则：
            全部满足 → 做多，全部相反 → 做空。
        """
        return CustomStrategy(rules=rules)

    # ── 预注册内置策略 ──

    def _register_builtins(self) -> None:
        """注册 5 种内置策略。"""
        from canopy.engine.arbitrage import ArbitrageStrategy
        from canopy.engine.grid import GridStrategy
        from canopy.engine.mean_reversion import MeanReversionStrategy
        from canopy.engine.momentum import MomentumStrategy
        from canopy.engine.trend import TrendStrategy

        self.register("trend", TrendStrategy)
        self.register("grid", GridStrategy)
        self.register("arbitrage", ArbitrageStrategy)
        self.register("momentum", MomentumStrategy)
        self.register("mean_reversion", MeanReversionStrategy)


# 全局工厂实例
factory = StrategyFactory()
factory._register_builtins()


class CompositeStrategy(Strategy):
    """复合策略 — 组合多个子策略。

    TODO: 实现多策略信号融合、权重分配、冲突解决。
    """

    default_params = {
        "strategies": [],
        "weights": [],
        "mode": "vote",
    }

    def on_tick(self, ticker: dict) -> None:
        raise NotImplementedError

    def on_bar(self, candle: dict) -> dict:
        raise NotImplementedError

    def on_order(self, order: dict) -> None:
        raise NotImplementedError
