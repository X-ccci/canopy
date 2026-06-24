"""
SQLite 持久化模块。管理 orders / trades / positions 三张表。
"""
import os
import sqlite3
import threading
from datetime import datetime


class Database:
    """SQLite 数据库封装，线程安全。"""

    def __init__(self, db_path: str = ""):
        if db_path:
            self._db_path = db_path
        else:
            import config
            self._db_path = config.db_path

        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_tables()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn  # type: ignore[no-any-return]

    def _init_tables(self):
        with self._lock:
            conn = self._conn
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL DEFAULT '',
                    symbol TEXT NOT NULL DEFAULT '',
                    side TEXT NOT NULL DEFAULT '',
                    price REAL NOT NULL DEFAULT 0.0,
                    amount REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL DEFAULT '',
                    price REAL NOT NULL DEFAULT 0.0,
                    amount REAL NOT NULL DEFAULT 0.0,
                    pnl REAL DEFAULT 0.0,
                    exchange_order_id TEXT DEFAULT '',
                    executed_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    side TEXT NOT NULL DEFAULT 'LONG',
                    amount REAL NOT NULL DEFAULT 0.0,
                    avg_entry_price REAL NOT NULL DEFAULT 0.0,
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
                CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
                CREATE INDEX IF NOT EXISTS idx_trades_order ON trades(order_id);
            """)
            conn.commit()

    # ---- Orders ----

    def upsert_order(self, order_id: str, strategy: str = "", symbol: str = "",
                     side: str = "", price: float = 0.0, amount: float = 0.0,
                     status: str = "PENDING") -> None:
        now = datetime.now().isoformat()
        with self._lock:
            self._conn.execute("""
                INSERT INTO orders (id, strategy, symbol, side, price, amount, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at
            """, (order_id, strategy, symbol, side, price, amount, status, now, now))
            self._conn.commit()

    def update_order_status(self, order_id: str, status: str) -> None:
        now = datetime.now().isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE orders SET status=?, updated_at=? WHERE id=?",
                (status, now, order_id)
            )
            self._conn.commit()

    def get_orders(self, limit: int = 50, status: str = "") -> list[dict]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM orders WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    # ---- Trades ----

    def insert_trade(self, order_id: str, symbol: str, price: float, amount: float,
                     pnl: float = 0.0, exchange_order_id: str = "") -> int:
        now = datetime.now().isoformat()
        with self._lock:
            cur = self._conn.execute("""
                INSERT INTO trades (order_id, symbol, price, amount, pnl, exchange_order_id, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (order_id, symbol, price, amount, pnl, exchange_order_id, now))
            self._conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def get_trades(self, limit: int = 50, symbol: str = "") -> list[dict]:
        with self._lock:
            if symbol:
                rows = self._conn.execute(
                    "SELECT * FROM trades WHERE symbol=? ORDER BY executed_at DESC LIMIT ?",
                    (symbol, limit)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM trades ORDER BY executed_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    # ---- Positions ----

    def upsert_position(self, symbol: str, side: str = "LONG", amount: float = 0.0,
                        avg_entry_price: float = 0.0) -> None:
        now = datetime.now().isoformat()
        with self._lock:
            self._conn.execute("""
                INSERT INTO positions (symbol, side, amount, avg_entry_price, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    side=excluded.side,
                    amount=excluded.amount,
                    avg_entry_price=excluded.avg_entry_price,
                    updated_at=excluded.updated_at
            """, (symbol, side, amount, avg_entry_price, now))
            self._conn.commit()

    def delete_position(self, symbol: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            self._conn.commit()

    def get_positions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
        return [dict(r) for r in rows]

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
