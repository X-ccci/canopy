"""
Canopy 交易日志 — SQLite 持久化

表 trade_journal: 入场理由 / 截图路径 / 盈亏 / 复盘笔记 / 标签。
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "trade_journal.db"


def _get_db() -> sqlite3.Connection:
    """获取数据库连接，初始化表结构。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL,
            exit_price REAL,
            quantity REAL,
            pnl REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            entry_reason TEXT,
            exit_reason TEXT,
            screenshot_path TEXT,
            review_notes TEXT,
            tags TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    """)
    conn.commit()
    return conn


def create_entry(
    symbol: str,
    side: str,
    entry_price: float,
    quantity: float,
    entry_reason: str = "",
    screenshot_path: str = "",
    tags: list[str] | None = None,
) -> int:
    """创建交易日志条目。返回行 ID。"""
    conn = _get_db()
    cur = conn.execute(
        """INSERT INTO trade_journal
           (symbol, side, entry_price, quantity, entry_reason, screenshot_path, tags, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            symbol, side.upper(), entry_price, quantity,
            entry_reason, screenshot_path,
            json.dumps(tags or []),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def update_exit(
    entry_id: int,
    exit_price: float,
    exit_reason: str = "",
) -> dict | None:
    """更新平仓信息并计算盈亏。"""
    conn = _get_db()
    row = conn.execute("SELECT * FROM trade_journal WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        conn.close()
        return None

    entry_price = row["entry_price"]
    quantity = row["quantity"]
    side = row["side"]

    if side == "BUY":
        pnl = (exit_price - entry_price) * quantity
    else:
        pnl = (entry_price - exit_price) * quantity

    pnl_pct = (pnl / (entry_price * quantity)) * 100 if entry_price and quantity else 0

    conn.execute(
        """UPDATE trade_journal SET
           exit_price = ?, exit_reason = ?, pnl = ?, pnl_pct = ?, updated_at = ?
           WHERE id = ?""",
        (exit_price, exit_reason, round(pnl, 4), round(pnl_pct, 4), datetime.now().isoformat(), entry_id),
    )
    conn.commit()
    conn.close()

    return {
        "id": entry_id,
        "symbol": row["symbol"],
        "side": row["side"],
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl_pct, 2),
    }


def update_review(entry_id: int, review_notes: str) -> bool:
    """添加/更新复盘笔记。"""
    conn = _get_db()
    conn.execute(
        "UPDATE trade_journal SET review_notes = ?, updated_at = ? WHERE id = ?",
        (review_notes, datetime.now().isoformat(), entry_id),
    )
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def add_tags(entry_id: int, tags: list[str]) -> bool:
    """追加标签到已有条目。"""
    conn = _get_db()
    row = conn.execute("SELECT tags FROM trade_journal WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        conn.close()
        return False

    existing = json.loads(row["tags"] or "[]")
    merged = list(set(existing + tags))
    conn.execute(
        "UPDATE trade_journal SET tags = ?, updated_at = ? WHERE id = ?",
        (json.dumps(merged), datetime.now().isoformat(), entry_id),
    )
    conn.commit()
    conn.close()
    return True


def get_entries(
    limit: int = 50,
    symbol: str = "",
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """查询交易日志。"""
    conn = _get_db()
    query = "SELECT * FROM trade_journal WHERE 1=1"
    params: list[Any] = []

    if symbol:
        query += " AND symbol = ?"
        params.append(symbol)
    if tags:
        for tag in tags:
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [
        {
            "id": r["id"],
            "symbol": r["symbol"],
            "side": r["side"],
            "entry_price": r["entry_price"],
            "exit_price": r["exit_price"],
            "quantity": r["quantity"],
            "pnl": r["pnl"],
            "pnl_pct": r["pnl_pct"],
            "entry_reason": r["entry_reason"],
            "exit_reason": r["exit_reason"],
            "screenshot_path": r["screenshot_path"],
            "review_notes": r["review_notes"],
            "tags": json.loads(r["tags"] or "[]"),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def delete_entry(entry_id: int) -> bool:
    """删除交易日志条目。"""
    conn = _get_db()
    conn.execute("DELETE FROM trade_journal WHERE id = ?", (entry_id,))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def get_stats(symbol: str = "") -> dict[str, Any]:
    """获取交易统计。"""
    conn = _get_db()
    where = "WHERE exit_price IS NOT NULL"
    params: list[Any] = []
    if symbol:
        where += " AND symbol = ?"
        params.append(symbol)

    rows = conn.execute(
        f"SELECT pnl, pnl_pct, side FROM trade_journal {where}", params
    ).fetchall()
    conn.close()

    if not rows:
        return {"total_trades": 0, "win_rate": 0, "total_pnl": 0, "avg_pnl": 0}

    wins = sum(1 for r in rows if r["pnl"] > 0)
    total_pnl = sum(r["pnl"] for r in rows)
    return {
        "total_trades": len(rows),
        "winning_trades": wins,
        "losing_trades": len(rows) - wins,
        "win_rate": round(wins / len(rows) * 100, 1) if rows else 0,
        "total_pnl": round(total_pnl, 4),
        "avg_pnl": round(total_pnl / len(rows), 4) if rows else 0,
    }
