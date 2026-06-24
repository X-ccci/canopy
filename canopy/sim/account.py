"""模拟账户 — 跟踪资金、持仓、已实现 PnL，冻结保证金并拒绝资金不足的订单。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SimPosition:
    """持仓记录。"""
    symbol: str
    side: str                     # LONG / SHORT
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SimOrder:
    """模拟订单。"""
    id: str
    symbol: str
    side: str                     # buy / sell
    order_type: str               # market / limit
    price: float
    amount: float
    status: str = "SUBMITTED"     # SUBMITTED / MATCHED / CANCELLED / REJECTED
    filled: float = 0.0
    filled_price: float = 0.0
    cost: float = 0.0
    fee: float = 0.0
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    matched_at: str = ""


@dataclass
class TradeEvent:
    """成交事件。"""
    order_id: str
    order_type: str               # ENTRY（开仓）/ EXIT（平仓）
    symbol: str
    side: str
    price: float
    amount: float
    pnl: float                    # 此次成交的已实现盈亏
    timestamp: str


class SimAccount:
    """模拟账户。

    跟踪：
    - 余额（可用 + 冻结）
    - 持仓（多/空）
    - 已实现 / 未实现盈亏
    - 保证金冻结与释放
    """

    def __init__(self, initial_capital: float = 10000.0):
        """
        Args:
            initial_capital: 初始资金（USDT）。
        """
        self.initial_capital = initial_capital
        self.balance: float = initial_capital       # 可用余额
        self.frozen: float = 0.0                    # 冻结保证金
        self.equity: float = initial_capital        # 总权益 = balance + frozen + unrealized_pnl
        self.realized_pnl: float = 0.0

        self.positions: dict[str, SimPosition] = {}
        self.orders: dict[str, SimOrder] = {}
        self.trade_history: list[TradeEvent] = []
        self._order_counter: int = 0

    # ── 账户查询接口 ──

    def get_balance(self) -> dict[str, float]:
        """返回余额快照。"""
        return {
            "total": round(self.balance + self.frozen, 2),
            "free": round(self.balance, 2),
            "frozen": round(self.frozen, 2),
            "pnl": round(self.realized_pnl, 2),
        }

    def get_positions(self) -> dict[str, dict]:
        """返回所有持仓。"""
        return {
            sym: {
                "symbol": pos.symbol,
                "side": pos.side,
                "quantity": pos.quantity,
                "avg_entry_price": pos.avg_entry_price,
                "current_price": pos.current_price,
                "unrealized_pnl": round(pos.unrealized_pnl, 2),
                "realized_pnl": round(pos.realized_pnl, 2),
                "opened_at": pos.opened_at,
            }
            for sym, pos in self.positions.items()
        }

    def get_portfolio(self) -> dict:
        """返回完整组合快照。"""
        unrealized_total = sum(
            p.unrealized_pnl for p in self.positions.values()
        )
        self.equity = self.balance + self.frozen + unrealized_total
        return {
            "balance": round(self.balance, 2),
            "frozen": round(self.frozen, 2),
            "equity": round(self.equity, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized_total, 2),
            "total_return_pct": round(
                (self.equity / self.initial_capital - 1) * 100, 2
            ),
            "positions": self.get_positions(),
        }

    # ── 下单 ──

    def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: float | None = None,
    ) -> SimOrder | None:
        """提交订单：校验余额并冻结保证金。

        Args:
            symbol:     交易对。
            side:       'buy' 或 'sell'。
            order_type: 'market' 或 'limit'。
            amount:     下单数量。
            price:      限价（市价单可为 None，将在撮合时填充）。

        Returns:
            SimOrder 对象；资金不足时返回 None。
        """
        # 生成订单 ID
        self._order_counter += 1
        order_id = f"sim_ord_{self._order_counter}"

        # 估算所需资金
        est_price = price or 0
        if order_type == "market":
            est_price = price or 0  # 市价单暂时估为 0，实际执行时再校验
        est_cost = est_price * amount

        # 对于买单，检查是否有足够余额
        if side == "buy" and order_type == "limit" and price:
            required = est_cost * 1.01  # 预留 1% 价格波动空间
            if required > self.balance:
                logger.warning(
                    f"资金不足：需要 {required:.2f}，可用 {self.balance:.2f}"
                )
                return None

        order = SimOrder(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price or 0,
            amount=amount,
        )
        self.orders[order_id] = order
        return order

    # ── 成交处理 ──

    def on_fill(self, order: SimOrder, fill_price: float, fill_result: dict) -> SimOrder:
        """处理订单成交：更新余额、持仓、盈亏。

        Args:
            order:       被成交的订单。
            fill_price:  实际成交价。
            fill_result: 撮合引擎返回的成交结果（含 cost/fee 等）。

        Returns:
            更新后的 SimOrder。
        """
        cost = fill_result.get("cost", fill_price * order.amount)
        fee = fill_result.get("fee", 0)

        order.status = "MATCHED"
        order.filled = order.amount
        order.filled_price = fill_price
        order.cost = cost
        order.fee = fee
        order.matched_at = datetime.now().isoformat()

        pnl = 0.0
        event_type = "ENTRY"

        if order.side == "buy":
            # 检查是否在平空仓
            short_pos = self.positions.get(order.symbol)
            if short_pos and short_pos.side == "SHORT" and short_pos.quantity > 0:
                # 平空仓
                close_qty = min(order.amount, short_pos.quantity)
                close_pnl = (short_pos.avg_entry_price - fill_price) * close_qty
                self.realized_pnl += close_pnl
                self.balance += close_pnl
                pnl = close_pnl

                short_pos.realized_pnl += close_pnl
                short_pos.quantity -= close_qty
                if short_pos.quantity <= 0:
                    del self.positions[order.symbol]
                    self.frozen -= close_qty * short_pos.avg_entry_price * 0.5

                event_type = "EXIT"
                remaining = order.amount - close_qty

                if remaining > 0:
                    # 还有剩余 → 开多仓
                    self._open_long(order.symbol, remaining, fill_price)
                    self.balance -= remaining * fill_price + fee
                else:
                    self.balance -= close_qty * fill_price + fee
            else:
                # 纯开多仓
                self._open_long(order.symbol, order.amount, fill_price)
                self.balance -= cost + fee

        elif order.side == "sell":
            long_pos = self.positions.get(order.symbol)
            if long_pos and long_pos.side == "LONG" and long_pos.quantity > 0:
                # 平多仓
                close_qty = min(order.amount, long_pos.quantity)
                close_pnl = (fill_price - long_pos.avg_entry_price) * close_qty
                self.realized_pnl += close_pnl
                self.balance += close_pnl
                pnl = close_pnl

                long_pos.realized_pnl += close_pnl
                long_pos.quantity -= close_qty
                if long_pos.quantity <= 0:
                    del self.positions[order.symbol]
                    self.frozen -= close_qty * long_pos.avg_entry_price * 0.5

                event_type = "EXIT"
                remaining = order.amount - close_qty

                if remaining > 0:
                    self._open_short(order.symbol, remaining, fill_price)
                self.balance += close_qty * fill_price - fee
            else:
                # 纯开空仓
                self._open_short(order.symbol, order.amount, fill_price)
                self.balance += cost - fee

        # 记录成交事件
        trade_event = TradeEvent(
            order_id=order.id,
            order_type=event_type,
            symbol=order.symbol,
            side=order.side,
            price=fill_price,
            amount=order.filled,
            pnl=round(pnl, 2),
            timestamp=datetime.now().isoformat(),
        )
        self.trade_history.append(trade_event)

        # 更新持仓市价
        self._mark_to_market(fill_price)

        logger.info(
            f"成交: {order.side} {order.amount} {order.symbol} @ {fill_price:.4f} "
            f"PnL={pnl:.2f} 余额={self.balance:.2f}"
        )
        return order

    def _open_long(self, symbol: str, quantity: float, price: float) -> None:
        """开多仓或加仓。"""
        pos = self.positions.get(symbol)
        if pos and pos.side == "LONG":
            total_qty = pos.quantity + quantity
            pos.avg_entry_price = (
                (pos.avg_entry_price * pos.quantity + price * quantity) / total_qty
            )
            pos.quantity = total_qty
        else:
            self.positions[symbol] = SimPosition(
                symbol=symbol,
                side="LONG",
                quantity=quantity,
                avg_entry_price=price,
                current_price=price,
            )
        self.frozen += quantity * price * 0.5  # 50% 保证金率

    def _open_short(self, symbol: str, quantity: float, price: float) -> None:
        """开空仓或加仓。"""
        pos = self.positions.get(symbol)
        if pos and pos.side == "SHORT":
            total_qty = pos.quantity + quantity
            pos.avg_entry_price = (
                (pos.avg_entry_price * pos.quantity + price * quantity) / total_qty
            )
            pos.quantity = total_qty
        else:
            self.positions[symbol] = SimPosition(
                symbol=symbol,
                side="SHORT",
                quantity=quantity,
                avg_entry_price=price,
                current_price=price,
            )
        self.frozen += quantity * price * 0.5

    def reject_order(self, order: SimOrder, reason: str) -> None:
        """拒绝订单。"""
        order.status = "REJECTED"
        order.reason = reason

    # ── 市值重估 ──

    def _mark_to_market(self, current_price: float) -> None:
        """按当前价格重估所有持仓。"""
        for pos in self.positions.values():
            pos.current_price = current_price
            if pos.side == "LONG":
                pos.unrealized_pnl = (current_price - pos.avg_entry_price) * pos.quantity
            else:
                pos.unrealized_pnl = (pos.avg_entry_price - current_price) * pos.quantity

    def mark_to_market_public(self, current_price: float) -> None:
        """公开接口：按当前价格重估持仓。"""
        self._mark_to_market(current_price)

    # ── 订单列表 ──

    def get_pending_orders(self) -> list[SimOrder]:
        """获取未成交的限价单。"""
        return [
            o for o in self.orders.values()
            if o.status == "SUBMITTED" and o.order_type == "limit"
        ]

    def get_recent_trades(self, limit: int = 50) -> list[dict]:
        """获取最近的成交记录。"""
        events = self.trade_history[-limit:]
        return [
            {
                "time": e.timestamp,
                "order_id": e.order_id,
                "type": e.order_type,
                "symbol": e.symbol,
                "side": e.side,
                "price": e.price,
                "amount": e.amount,
                "pnl": e.pnl,
            }
            for e in events
        ]
