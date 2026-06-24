"""模拟券商 — 组合 SimEngine + SimAccount，提供统一交易接口。

完整事件流:
    ORDER_SUBMITTED → ORDER_MATCHED → POSITION_UPDATED

submit_order() 自动完成：订单创建 → 余额校验 → 撮合 → 账户更新 → 返回成交结果。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from canopy.sim.account import SimAccount, SimOrder
from canopy.sim.engine import SimEngine

logger = logging.getLogger(__name__)


class SimBroker:
    """模拟券商。

    封装 SimEngine（行情 + 撮合）和 SimAccount（资金 + 持仓），
    提供 submit_order() 方法一站式完成订单全生命周期。

    策略/风控层只需调用 submit_order() → 检查返回结果即可。
    """

    def __init__(
        self,
        engine: SimEngine,
        account: SimAccount,
    ):
        """
        Args:
            engine:  SimEngine 实例（已加载数据）。
            account: SimAccount 实例（已设置初始资金）。
        """
        self.engine = engine
        self.account = account

        # 事件回调
        self._on_submit_callbacks: list[Callable] = []
        self._on_match_callbacks: list[Callable] = []
        self._on_position_update: list[Callable] = []

    # ── 核心：统一下单与撮合 ──

    def submit_order(
        self, symbol: str, side: str, order_type: str, amount: float, price: float = 0.0
    ) -> dict[str, Any]:
        """提交订单并自动撮合。

        流程:
            1. 账户创建订单（ORDER_SUBMITTED）
            2. 引擎撮合（ORDER_MATCHED）
            3. 账户更新余额/持仓（POSITION_UPDATED）

        Args:
            symbol:     交易对。
            side:       'buy' 或 'sell'。
            order_type: 'market' 或 'limit'。
            amount:     下单数量。
            price:      限价（市价单可忽略）。

        Returns:
            {
                'order_id': str,
                'status': 'FILLED' | 'PENDING' | 'REJECTED',
                'symbol': str,
                'side': str,
                'price': float,
                'amount': float,
                'cost': float,
                'fee': float,
                'message': str,
            }
        """
        # 1. 创建订单
        limit_price = price if order_type == "limit" else None
        order = self.account.submit_order(symbol, side, order_type, amount, limit_price)

        if order is None:
            return {
                "order_id": "",
                "status": "REJECTED",
                "symbol": symbol,
                "side": side,
                "price": price,
                "amount": amount,
                "cost": 0,
                "fee": 0,
                "message": "余额不足",
            }

        # ORDER_SUBMITTED 事件
        self._fire_submit(order)

        # 2. 撮合
        if order_type == "market":
            fill_result = self.engine.match_market_order(side, amount)
            if fill_result:
                fill_price = fill_result["price"]
                # 市价单买入需再次校验余额
                if side == "buy" and fill_price * amount > self.account.balance:
                    self.account.reject_order(order, "资金不足（撮合时校验）")
                    return {
                        "order_id": order.id,
                        "status": "REJECTED",
                        "symbol": symbol,
                        "side": side,
                        "price": fill_price,
                        "amount": amount,
                        "cost": 0,
                        "fee": 0,
                        "message": "资金不足（撮合时校验）",
                    }
                self.account.on_fill(order, fill_price, fill_result)
                self._fire_match(order, fill_result)
                self._fire_position_update()
                return self._fill_response(order, fill_result, "FILLED")
            else:
                self.account.reject_order(order, "撮合失败")
                return self._fill_response(order, {}, "REJECTED")

        elif order_type == "limit":
            fill_result = self.engine.match_limit_order(side, amount, price)  # type: ignore[assignment]
            if fill_result:
                self.account.on_fill(order, price, fill_result)
                self._fire_match(order, fill_result)
                self._fire_position_update()
                return self._fill_response(order, fill_result, "FILLED")
            else:
                # 限价单未触发，放入待成交队列
                return {
                    "order_id": order.id,
                    "status": "PENDING",
                    "symbol": symbol,
                    "side": side,
                    "price": price,
                    "amount": amount,
                    "cost": 0,
                    "fee": 0,
                    "message": f"限价单已提交，等待触发（限价={price}）",
                }

        return {
            "order_id": order.id if order else "",
            "status": "REJECTED",
            "symbol": symbol,
            "side": side,
            "price": price,
            "amount": amount,
            "cost": 0,
            "fee": 0,
            "message": "未知订单类型",
        }

    # ── 待成交限价单轮询 ──

    def check_pending(self) -> list[dict]:
        """检查所有待成交的限价单，对已触发的订单执行撮合。

        Returns:
            本轮新成交的订单结果列表。
        """
        filled = []
        for order in self.account.get_pending_orders():
            triggered = self.engine.check_limit_order(order.side, order.price)
            if triggered:
                fill_result = self.engine.match_limit_order(
                    order.side, order.amount, order.price
                )
                if fill_result:
                    self.account.on_fill(order, order.price, fill_result)
                    self._fire_match(order, fill_result)
                    self._fire_position_update()
                    filled.append(self._fill_response(order, fill_result, "FILLED"))
        return filled

    # ── 推进引擎 + 自动检查待成交订单 ──

    def step(self) -> dict[str, Any]:
        """推进到下一根 K 线，自动检查待成交限价单。

        Returns:
            {'advanced': bool, 'new_fills': list, 'candle': dict}
        """
        # 先检查当前 K 线的待成交订单
        new_fills = self.check_pending()

        # 推进引擎
        advanced = self.engine.step()

        # 推进后立即更新持仓市价
        if advanced:
            current_close = self.engine.current_candle.get("close", 0)
            if current_close:
                self.account.mark_to_market_public(current_close)

        # 推进后再检查一次新 K 线的待成交订单
        new_fills += self.check_pending()

        return {
            "advanced": advanced,
            "new_fills": new_fills,
            "candle": self.engine.current_candle if advanced else {},
            "cursor": self.engine.cursor,
            "total_bars": self.engine.total_bars,
        }

    # ── 快捷接口 ──

    def fetch_ticker(self, symbol: str) -> dict:
        return self.engine.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h",
                    since: str | None = None, limit: int = 500):
        return self.engine.fetch_ohlcv(symbol, timeframe, since, limit)

    def get_portfolio(self) -> dict:
        return self.account.get_portfolio()

    def get_balance(self) -> dict:
        return self.account.get_balance()

    def get_positions(self) -> dict:
        return self.account.get_positions()

    @property
    def symbol(self) -> str:
        return self.engine.symbol

    # ── 事件系统 ──

    def on_submit(self, callback: Callable) -> None:
        """注册 ORDER_SUBMITTED 回调。"""
        self._on_submit_callbacks.append(callback)

    def on_match(self, callback: Callable) -> None:
        """注册 ORDER_MATCHED 回调。"""
        self._on_match_callbacks.append(callback)

    def on_position_update(self, callback: Callable) -> None:
        """注册 POSITION_UPDATED 回调。"""
        self._on_position_update.append(callback)

    def _fire_submit(self, order: SimOrder) -> None:
        for cb in self._on_submit_callbacks:
            try:
                cb({"event": "ORDER_SUBMITTED", "order": order})
            except Exception:
                pass

    def _fire_match(self, order: SimOrder, fill_result: dict) -> None:
        for cb in self._on_match_callbacks:
            try:
                cb({"event": "ORDER_MATCHED", "order": order, "fill": fill_result})
            except Exception:
                pass

    def _fire_position_update(self) -> None:
        portfolio = self.account.get_portfolio()
        for cb in self._on_position_update:
            try:
                cb({"event": "POSITION_UPDATED", "portfolio": portfolio})
            except Exception:
                pass

    # ── 内部工具 ──

    @staticmethod
    def _fill_response(order: SimOrder, fill_result: dict, status: str) -> dict:
        return {
            "order_id": order.id,
            "status": status,
            "symbol": order.symbol,
            "side": order.side,
            "price": fill_result.get("price", order.price),
            "amount": order.amount,
            "cost": fill_result.get("cost", 0),
            "fee": fill_result.get("fee", 0),
            "message": "成交" if status == "FILLED" else order.reason,
        }
