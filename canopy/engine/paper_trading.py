"""
Canopy 纸交易（模拟盘）引擎

模拟盘账户：初始资金 / 持仓 / 订单 / 成交记录。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PaperAccount:
    """模拟盘账户。"""
    initial_balance: float = 100000.0
    balance: float = 100000.0
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    orders: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    pnl_history: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def total_equity(self, prices: dict[str, float] | None = None) -> float:
        """计算总权益（余额 + 持仓市值）。"""
        equity = self.balance
        for sym, pos in self.positions.items():
            qty = float(pos.get("quantity", 0))
            price = (prices or {}).get(sym, float(pos.get("avg_price", 0)))
            equity += qty * price
        return round(equity, 2)

    def total_pnl(self, prices: dict[str, float] | None = None) -> float:
        """计算总未实现盈亏。"""
        pnl = 0.0
        for sym, pos in self.positions.items():
            qty = float(pos.get("quantity", 0))
            entry = float(pos.get("avg_price", 0))
            current = (prices or {}).get(sym, entry)
            pnl += qty * (current - entry)
        return round(pnl, 2)


class PaperTradingEngine:
    """模拟盘交易引擎。"""

    def __init__(self, initial_balance: float = 100000.0):
        self.account = PaperAccount(initial_balance=initial_balance)

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float = 0.0,
        strategy: str = "manual",
    ) -> dict[str, Any]:
        """下单（立即模拟成交）。"""
        order_id = str(uuid.uuid4())[:8]

        order: dict[str, Any] = {
            "id": order_id,
            "symbol": symbol,
            "side": side.lower(),
            "type": order_type,
            "quantity": quantity,
            "price": price,
            "strategy": strategy,
            "status": "PENDING",
            "created_at": datetime.now().isoformat(),
            "filled_qty": 0,
            "filled_price": 0,
        }

        # 模拟市价成交
        fill_price = price if price > 0 else self._get_last_price(symbol)
        if fill_price <= 0:
            order["status"] = "REJECTED"
            order["reject_reason"] = "No price available"
            self.account.orders.append(order)
            return order

        cost = fill_price * quantity

        if side.lower() == "buy":
            if cost > self.account.balance:
                order["status"] = "REJECTED"
                order["reject_reason"] = f"Insufficient balance: need {cost:.2f}, have {self.account.balance:.2f}"
                self.account.orders.append(order)
                return order
            self.account.balance -= cost
            self._update_position(symbol, quantity, fill_price)
        else:
            pos = self.account.positions.get(symbol)
            if not pos or pos.get("quantity", 0) < quantity:
                order["status"] = "REJECTED"
                order["reject_reason"] = f"Insufficient quantity: need {quantity}, have {pos.get('quantity', 0) if pos else 0}"
                self.account.orders.append(order)
                return order
            self.account.balance += cost
            self._update_position(symbol, -quantity, fill_price)

        order["status"] = "FILLED"
        order["filled_qty"] = quantity
        order["filled_price"] = fill_price
        order["filled_at"] = datetime.now().isoformat()
        self.account.orders.append(order)

        # 成交记录
        self.account.fills.append({
            "order_id": order_id,
            "symbol": symbol,
            "side": side.lower(),
            "quantity": quantity,
            "price": fill_price,
            "cost": round(cost, 2),
            "timestamp": datetime.now().isoformat(),
        })

        # 更新 PnL 快照
        self._snapshot_pnl()

        return order

    def _update_position(self, symbol: str, delta: float, price: float):
        """更新持仓。"""
        if symbol not in self.account.positions:
            self.account.positions[symbol] = {"quantity": 0.0, "avg_price": 0.0}

        pos = self.account.positions[symbol]
        old_qty = float(pos["quantity"])

        if delta > 0:
            # 买入：加权平均成本
            new_qty = old_qty + delta
            total_cost = old_qty * float(pos["avg_price"]) + delta * price
            pos["avg_price"] = round(total_cost / new_qty, 8) if new_qty > 0 else 0
        else:
            new_qty = old_qty + delta  # delta 为负

        pos["quantity"] = round(new_qty, 8)

        # 清除零持仓
        if pos["quantity"] <= 0:
            self.account.positions.pop(symbol, None)

    def _snapshot_pnl(self):
        """记录 PnL 快照。"""
        self.account.pnl_history.append({
            "time": datetime.now().isoformat(),
            "balance": round(self.account.balance, 2),
            "equity": self.account.total_equity(),
            "unrealized_pnl": self.account.total_pnl(),
            "positions_count": len(self.account.positions),
        })
        if len(self.account.pnl_history) > 5000:
            self.account.pnl_history = self.account.pnl_history[-5000:]

    def _get_last_price(self, symbol: str) -> float:
        """从最近成交中取价格。"""
        for f in reversed(self.account.fills):
            if f["symbol"] == symbol:
                return float(f["price"])
        return 0.0

    def get_account(self) -> dict[str, Any]:
        """获取账户摘要。"""
        return {
            "initial_balance": self.account.initial_balance,
            "balance": round(self.account.balance, 2),
            "equity": self.account.total_equity(),
            "unrealized_pnl": self.account.total_pnl(),
            "positions": self.account.positions,
            "positions_count": len(self.account.positions),
        }

    def get_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.account.orders[-limit:]

    def get_pnl_history(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.account.pnl_history[-limit:]

    def reset(self):
        """重置模拟盘账户。"""
        self.account = PaperAccount(initial_balance=self.account.initial_balance)
