"""套利策略 — 跨交易所价差套利，低买高卖同时执行。

支持两种模式：
1. 单所模式：通过 on_dual_ticker 接收两个不同交易所的 ticker 数据。
2. 多所模式：传入 MultiExchangeManager，自动并行轮询检测跨所套利机会。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from canopy.exchange.multi_adapter import MultiExchangeManager

from canopy.engine.base import Strategy


class ArbitrageStrategy(Strategy):
    """跨交易所套利策略。

    核心逻辑:
        1. 接收两个交易所的 ticker 数据（通过 on_dual_ticker）。
        2. 计算跨所价差百分比。
        3. 价差超过 min_spread_pct 时，在低价所买入、高价所卖出。
        4. 控制最大持仓量防止风险过度暴露。

    multi_adapter 模式:
        当传入 multi_adapter 时，on_bar 中将自动调用
        MultiExchangeManager.detect_arbitrage() 检测跨所套利机会，
        替代原有的 on_dual_ticker 双所比较逻辑。
        价差计算使用真正的 bid/ask：在买所的 ask 买入，在卖所的 bid 卖出，
        扣除双边手续费后得到净利润。

    默认参数:
        min_spread_pct (float): 最小价差百分比（默认 0.5，即 0.5%）。
        max_position (float):   单边最大持仓量（默认 1.0）。
        fee_rate (float):       双边手续费率（默认 0.002，即 0.2%）。
    """

    default_params = {
        "min_spread_pct": 0.5,
        "max_position": 1.0,
        "fee_rate": 0.002,  # 双边手续费 0.2%
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="ArbitrageStrategy", **kwargs)
        self._in_position: bool = False
        self.multi_adapter: MultiExchangeManager | None = kwargs.get("multi_adapter")

    # ── 多所模式: on_bar 自动检测 ──

    def on_bar(self, candle: dict) -> dict:
        """多所模式下自动检测套利；单所模式下回退到 on_dual_ticker。"""
        if self.multi_adapter is not None:
            return self._on_bar_multi(candle)
        return {
            "action": "HOLD", "price": candle["close"], "stop_loss": None,
            "reason": "请使用 on_dual_ticker 方法"
        }

    def _on_bar_multi(self, candle: dict) -> dict:
        """多所模式：调用 MultiExchangeManager.detect_arbitrage 检测套利。

        取满足 min_spread_pct 的最优机会（净利润最高），生成套利信号。
        """
        if self._in_position:
            return {
                "action": "HOLD", "buy_exchange": "", "sell_exchange": "",
                "buy_price": 0.0, "sell_price": 0.0, "spread_pct": 0.0,
                "net_profit_pct": 0.0, "amount": 0.0,
            }

        symbol = getattr(self, "symbol", "BTC/USDT")
        min_spread = self.params["min_spread_pct"]
        max_pos = self.params["max_position"]

        opportunities = self.multi_adapter.detect_arbitrage(  # type: ignore[union-attr]
            symbol=symbol,
            min_spread_pct=min_spread,
        )

        if not opportunities:
            return {
                "action": "HOLD", "buy_exchange": "", "sell_exchange": "",
                "buy_price": 0.0, "sell_price": 0.0, "spread_pct": 0.0,
                "net_profit_pct": 0.0, "amount": 0.0,
            }

        best = opportunities[0]
        self._in_position = True

        return {
            "action": "ARB_BUY_SELL",
            "buy_exchange": best.buy_exchange,
            "sell_exchange": best.sell_exchange,
            "buy_price": best.buy_price,
            "sell_price": best.sell_price,
            "spread_pct": best.spread_pct,
            "net_profit_pct": best.net_profit_pct,
            "amount": max_pos,
        }

    # ── 单所模式: on_dual_ticker ──

    def on_tick(self, ticker: dict) -> None:
        """套利策略使用 on_dual_ticker 而非 on_tick。"""
        pass

    def on_dual_ticker(self, ticker_a: dict, ticker_b: dict) -> dict:
        """处理两个交易所的行情，生成套利信号。

        使用 bid/ask 价差：低所 bid vs 高所 ask，扣除手续费后计算净利润。

        Args:
            ticker_a: 交易所 A 的 ticker，包含 'exchange'/'bid'/'ask'/'last'。
            ticker_b: 交易所 B 的 ticker，包含 'exchange'/'bid'/'ask'/'last'。

        Returns:
            信号字典: {'action': 'ARB_BUY_SELL'|'HOLD', 'buy_exchange': str,
                      'sell_exchange': str, 'buy_price': float,
                      'sell_price': float, 'spread_pct': float,
                      'net_profit_pct': float, 'amount': float}
        """
        min_spread = self.params["min_spread_pct"]
        max_pos = self.params["max_position"]
        fee_rate = self.params.get("fee_rate", 0.002)

        if self._in_position:
            return {
                "action": "HOLD", "buy_exchange": "", "sell_exchange": "",
                "buy_price": 0.0, "sell_price": 0.0, "spread_pct": 0.0,
                "net_profit_pct": 0.0, "amount": 0.0,
            }

        # 取 bid/ask，fallback 到 last
        bid_a = ticker_a.get("bid") or ticker_a.get("last", 0)
        ask_a = ticker_a.get("ask") or ticker_a.get("last", 0)
        bid_b = ticker_b.get("bid") or ticker_b.get("last", 0)
        ask_b = ticker_b.get("ask") or ticker_b.get("last", 0)

        if bid_a <= 0 or ask_a <= 0 or bid_b <= 0 or ask_b <= 0:
            return {
                "action": "HOLD", "buy_exchange": "", "sell_exchange": "",
                "buy_price": 0.0, "sell_price": 0.0, "spread_pct": 0.0,
                "net_profit_pct": 0.0, "amount": 0.0,
            }

        def _arb_signal(buy_ex: str, sell_ex: str, buy_p: float, sell_p: float) -> dict:
            if buy_p <= 0:
                return {}
            spread_pct = (sell_p - buy_p) / buy_p * 100
            net_profit = spread_pct - fee_rate * 100
            if net_profit >= min_spread:
                self._in_position = True
                return {
                    "action": "ARB_BUY_SELL",
                    "buy_exchange": buy_ex,
                    "sell_exchange": sell_ex,
                    "buy_price": buy_p,
                    "sell_price": sell_p,
                    "spread_pct": round(spread_pct, 4),
                    "net_profit_pct": round(net_profit, 4),
                    "amount": max_pos,
                }
            return {}

        # 场景 1：在 A 买（ask_a），在 B 卖（bid_b）
        if bid_b > ask_a:
            sig = _arb_signal(ticker_a.get("exchange", "A"), ticker_b.get("exchange", "B"), ask_a, bid_b)
            if sig:
                return sig

        # 场景 2：在 B 买（ask_b），在 A 卖（bid_a）
        if bid_a > ask_b:
            sig = _arb_signal(ticker_b.get("exchange", "B"), ticker_a.get("exchange", "A"), ask_b, bid_a)
            if sig:
                return sig

        return {
            "action": "HOLD", "buy_exchange": "", "sell_exchange": "",
            "buy_price": 0.0, "sell_price": 0.0, "spread_pct": 0.0,
            "net_profit_pct": 0.0, "amount": 0.0,
        }

    def on_order(self, order: dict) -> None:
        """订单成交后释放持仓标记。"""
        if order.get("status") == "filled":
            self._in_position = False
