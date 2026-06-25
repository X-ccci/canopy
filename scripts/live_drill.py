#!/usr/bin/env python3
"""
Canopy 实盘演练脚本 — 全链路 WS 模式，dry_run=True 仅模拟不下单。

用法:
    python scripts/live_drill.py
    python scripts/live_drill.py --duration 1800
    python scripts/live_drill.py --symbols BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT

流程:
    1. 从 Vault（或环境变量）加载 Binance testnet 密钥
    2. 连接 testnet → 启动 5 策略 Runner（WS 模式）
    3. RiskManager + DryRunExecutor 全链路（仅记录，不实际提交交易所）
    4. 所有信号/风控决策/模拟订单写入 SQLite
    5. 每 5 分钟输出汇总：信号数 / 通过率 / 持仓 / 熔断状态
    6. --duration 超时或 Ctrl+C → 打印最终绩效报告
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from canopy.config import Config  # noqa: E402
from canopy.data.fetcher import DataFetcher  # noqa: E402
from canopy.engine.executor import Order, OrderExecutor  # noqa: E402
from canopy.engine.risk import RiskManager  # noqa: E402
from canopy.engine.runner import StrategyRunner  # noqa: E402
from canopy.exchange.ccxt_adapter import ExchangeAdapter  # noqa: E402
from canopy.utils.database import Database  # noqa: E402

# from canopy.utils.logger import setup_logger  # removed (not available)

# Vault 加载
VAULT_PATH = Path(PROJECT_ROOT) / "utils" / "vault.py"
if str(VAULT_PATH.parent) not in sys.path:
    sys.path.insert(0, str(VAULT_PATH.parent))
try:
    from vault import load_credentials as vault_load_credentials  # noqa: E402
except ImportError:
    vault_load_credentials = None

logger = None  # 将在 main 中初始化


# ── Dry-Run 订单执行器 ──

class DryRunExecutor(OrderExecutor):
    """干跑执行器：仅记录订单到 SQLite，不实际发送到交易所。"""

    def __init__(self, db: Database):
        self.risk_manager = None
        self.db = db
        self._order_queue: list[Order] = []
        self._order_history: list[Order] = []
        self._running = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._on_fill_callbacks = []
        self._order_counter: int = 0

    def submit(self, order_dict: dict) -> Order:
        self._order_counter += 1
        order = Order(order_dict)
        order.id = f"dryrun_{self._order_counter}"
        with self._lock:
            self._order_queue.append(order)
        if self.db:
            self._sync_order_to_db(order)
        return order

    def _execute_order(self, order: Order):
        """干跑执行：直接标记 FILLED，不调交易所 API。"""
        try:
            order.status = "FILLED"
            order.filled_qty = order.quantity
            order.avg_fill_price = order.price
            order.filled_at = datetime.now().isoformat()

            if self.db:
                self._sync_order_to_db(order)

            for cb in self._on_fill_callbacks:
                try:
                    cb(order)
                except Exception:
                    pass
        except Exception as e:
            order.status = "REJECTED"
            order.error = str(e)
        finally:
            with self._lock:
                self._order_history.append(order)
                if len(self._order_history) > 1000:
                    self._order_history = self._order_history[-1000:]


# ── 信号统计器 ──

@dataclass
class DrillStats:
    """演练统计数据。"""
    total_signals: int = 0
    approved: int = 0
    rejected: int = 0
    holds: int = 0
    circuit_trips: int = 0
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    signals_per_strategy: dict = field(default_factory=dict)
    reject_reasons: dict = field(default_factory=dict)

    def record_signal(self, strategy_name: str, approved: bool, reason: str = ""):
        self.total_signals += 1
        self.signals_per_strategy[strategy_name] = (
            self.signals_per_strategy.get(strategy_name, 0) + 1
        )
        if approved:
            self.approved += 1
        else:
            self.rejected += 1
            if reason:
                self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1

    def summary(self, risk_mgr: RiskManager | None) -> str:
        elapsed = (datetime.now() - datetime.fromisoformat(self.start_time)).total_seconds()
        elapsed_str = f"{int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m {int(elapsed % 60)}s"
        pass_rate = f"{self.approved / max(self.total_signals, 1) * 100:.1f}%"

        lines = [
            "",
            "=" * 60,
            f"  [汇总] 运行时长: {elapsed_str}",
            f"  信号总数: {self.total_signals}  |  通过: {self.approved}  |  拒绝: {self.rejected}",
            f"  通过率: {pass_rate}",
        ]

        if self.signals_per_strategy:
            lines.append("  各策略信号:")
            for name, cnt in sorted(self.signals_per_strategy.items()):
                lines.append(f"    {name}: {cnt}")

        if risk_mgr:
            status = risk_mgr.get_status()
            lines.extend([
                f"  当前余额: ${status['current_balance']:,.2f}",
                f"  回撤: {status['drawdown_pct']}%",
                f"  总敞口: {status['total_exposure']}%",
                f"  持仓数: {status['open_positions']}",
                f"  熔断: {'已触发' if status['circuit_breaker']['tripped'] else 'OK'}",
            ])

        lines.append("=" * 60)
        return "\n".join(lines)


# ── 密钥加载 ──

def load_credentials() -> tuple[str, str]:
    """加载 Binance testnet 密钥，优先级: Vault > 环境变量。

    Returns:
        (api_key, api_secret)
    """
    # 1. Vault
    if vault_load_credentials:
        try:
            creds = vault_load_credentials("binance")
            if creds:
                print("[Vault] 已从 Vault 加载 binance 凭证")
                return creds  # type: ignore[no-any-return]
        except Exception as e:
            print(f"[Vault] 加载失败: {e}")

    # 2. 环境变量
    api_key = os.environ.get("BINANCE_API_KEY", "")
    api_secret = os.environ.get("BINANCE_API_SECRET", "")
    if api_key and api_secret:
        print("[环境变量] 已从环境变量加载 Binance 凭证")
        return api_key, api_secret

    # 3. 占位符（仅用于 testnet 公开行情）
    print("[警告] 未找到 API 密钥，使用空凭证（仅测试网公开行情可用）")
    return "", ""


# ── 主运行逻辑 ──

def run_drill(
    duration: int,
    symbols: list[str],
    db_path: str,
    report_interval: int = 300,
):
    """执行实盘演练。

    Args:
        duration:        运行时长（秒）。
        symbols:         交易对列表。
        db_path:         SQLite 数据库路径。
        report_interval: 汇总报告间隔（秒），默认 300（5 分钟）。
    """
    global logger
    import logging  # noqa: E402
    logger = logging.getLogger("live_drill")

    # ── 1. 加载密钥 ──
    api_key, api_secret = load_credentials()

    # ── 2. 初始化 DB ──
    db = Database(db_path)
    logger.info(f"SQLite 数据库就绪: {db_path}")

    # ── 3. 配置 ──
    config = Config()
    config.exchange = "binance"
    config.api_key = api_key
    config.api_secret = api_secret
    config.testnet = True
    config.ws_enabled = True
    config.ws_channels = [
        {"type": "ticker", "symbol": s} for s in symbols
    ] + [
        {"type": "kline", "symbol": s, "interval": "1h"} for s in symbols
    ]

    # ── 4. 连接交易所 ──
    adapter = ExchangeAdapter("binance", config)
    ok = adapter.connect()
    if not ok:
        if not api_key:
            # testnet 公开行情可能不需要 API Key
            logger.warning("API Key 为空，尝试以公开模式连接 testnet...")
            adapter.exchange = getattr(
                __import__("ccxt", fromlist=["binance"]), "binance"
            )({
                "enableRateLimit": True,
            })
            if hasattr(adapter.exchange, "urls") and "test" in adapter.exchange.urls:
                adapter.exchange.set_sandbox_mode(True)
            try:
                adapter.exchange.fetch_ticker("BTC/USDT")
                adapter._connected = True
                logger.info("Binance testnet 公开模式连接成功")
            except Exception as e:
                logger.error(f"连接失败: {e}")
                print(f"[错误] 无法连接 Binance testnet: {e}")
                sys.exit(1)
        else:
            logger.error("连接失败")
            sys.exit(1)

    fetcher = DataFetcher(adapter)
    logger.info("交易所连接就绪")

    # ── 5. 创建 Runner + 干跑执行器 ──
    runner = StrategyRunner(adapter, fetcher, config=config)

    # 替换执行器为干跑版本
    dry_executor = DryRunExecutor(db)
    dry_executor.start()
    runner.executor = dry_executor

    # ── 6. 添加策略 ──
    strategy_defs = [
        ("Mean Reversion v3", "mean_reversion", symbols[0] if symbols else "BTC/USDT", "1h"),
        ("Grid Infinity", "grid", symbols[1] if len(symbols) > 1 else "ETH/USDT", "1h",
         {"upper_price": 4000, "lower_price": 3200, "grid_count": 10}),
        ("Trend Surf", "trend", symbols[2] if len(symbols) > 2 else "SOL/USDT", "1h"),
        ("Arbitrage Nexus", "arbitrage", symbols[3] if len(symbols) > 3 else "BNB/USDT", "1h"),
        ("Volatility Harvester", "momentum", symbols[4] if len(symbols) > 4 else "AVAX/USDT", "1h"),
    ]

    for name, s_type, sym, tf, *params in strategy_defs:
        kwargs = params[0] if params else {}
        runner.add_strategy(name, s_type, sym, tf, **kwargs)  # type: ignore[arg-type]
        logger.info(f"策略已注册: {name} ({s_type}) on {sym} {tf}")

    # ── 7. 统计数据 ──
    stats = DrillStats()
    stats_lock = threading.Lock()

    # ── 8. 信号拦截回调 ──
    original_submit = runner.executor.submit

    def dry_run_submit(order_dict):
        strategy_name = order_dict.get("strategy", "")
        order_dict.get("reason", "")
        with stats_lock:
            stats.record_signal(strategy_name, approved=True)
        # 写入 DB（含策略名）
        order_dict["strategy"] = strategy_name
        return original_submit(order_dict)

    runner.executor.submit = dry_run_submit  # type: ignore[method-assign]

    # 拦截 reject
    original_log_signal = runner._log_signal

    def intercept_log_signal(strategy_name, signal, candle):
        action = signal.get("action", "")
        reason = signal.get("reason", "")
        if action == "REJECTED":
            with stats_lock:
                stats.record_signal(strategy_name, approved=False, reason=reason)
            # 记录拒绝信号到 DB
            db.upsert_order(
                order_id=f"rej_{int(time.time()*1000)}_{strategy_name}",
                strategy=strategy_name,
                symbol=signal.get("symbol", ""),
                side=signal.get("side", "buy"),
                price=signal.get("price", candle.get("close", 0)),
                amount=signal.get("quantity", 0),
                status="REJECTED",
            )
        elif action == "HOLD":
            with stats_lock:
                stats.holds += 1
        original_log_signal(strategy_name, signal, candle)

    runner._log_signal = intercept_log_signal  # type: ignore[method-assign]

    # ── 9. 熔断监控 ──
    def monitor_circuit_breaker():
        while runner._running:
            if runner.risk_mgr.circuit_breaker.is_tripped:
                with stats_lock:
                    stats.circuit_trips += 1
            threading.Event().wait(5)

    cb_thread = threading.Thread(target=monitor_circuit_breaker, daemon=True)
    cb_thread.start()

    # ── 10. 启动 ──
    print("\n" + "=" * 60)
    print("  Canopy 实盘演练 — 干跑 模式")
    print("=" * 60)
    print("  交易所: Binance 测试网")
    print(f"  策略数: {len(runner.strategies)}")
    print(f"  交易对: {', '.join(symbols)}")
    print(f"  运行时长: {duration}s ({duration // 60} 分钟)")
    print("  模式: 干跑（仅记录，不实际下单）")
    print("=" * 60 + "\n")

    runner.start_all()
    logger.info("全策略已启动（WS 模式）")
    print("[启动] 5 策略 Runner 已启动，等待 WS 连接...\n")

    # 等待 WS 连接稳定
    time.sleep(3)

    # ── 11. 定时汇总线程 ──
    def periodic_report():
        while runner._running:
            time.sleep(report_interval)
            if not runner._running:
                break
            with stats_lock:
                print(stats.summary(runner.risk_mgr))

    reporter = threading.Thread(target=periodic_report, daemon=True)
    reporter.start()

    # ── 12. 优雅退出 ──
    stop_event = threading.Event()
    shutdown_reason = ""

    def graceful_shutdown(sig=None, frame=None):
        nonlocal shutdown_reason
        shutdown_reason = f"收到信号 {sig}" if sig else "超时停止"
        stop_event.set()

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    # 主等待
    start_ts = time.time()
    while not stop_event.is_set():
        elapsed = time.time() - start_ts
        if elapsed >= duration:
            shutdown_reason = "运行时长到期"
            break
        stop_event.wait(min(1, duration - elapsed))

    # ── 13. 停止 ──
    print(f"\n[停止] {shutdown_reason}，正在关闭...")
    runner.stop_all()
    dry_executor.stop()
    time.sleep(1)

    # ── 14. 最终报告 ──
    print("\n")
    print("=" * 60)
    print("  实盘演练最终绩效报告")
    print("=" * 60)

    with stats_lock:
        elapsed = (datetime.now() - datetime.fromisoformat(stats.start_time)).total_seconds()
        elapsed_str = f"{int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m {int(elapsed % 60)}s"

        print(f"  运行时长:     {elapsed_str}")
        print(f"  信号总数:     {stats.total_signals}")
        print(f"  通过:         {stats.approved}")
        print(f"  拒绝:         {stats.rejected}")
        print(f"  HOLD:         {stats.holds}")
        print(f"  通过率:       {stats.approved / max(stats.total_signals, 1) * 100:.1f}%")
        print(f"  熔断触发:     {stats.circuit_trips} 次")

        # 风控状态
        risk_status = runner.risk_mgr.get_status()
        print(f"  当前余额:     ${risk_status['current_balance']:,.2f}")
        print(f"  峰值余额:     ${risk_status['peak_balance']:,.2f}")
        print(f"  最大回撤:     {risk_status['drawdown_pct']}%")
        print(f"  总敞口:       {risk_status['total_exposure']}%")
        print(f"  持仓数:       {risk_status['open_positions']}")
        print(f"  熔断状态:     {'已触发' if risk_status['circuit_breaker']['tripped'] else '正常'}")

        # 各策略明细
        print("\n  策略信号明细:")
        for name in runner.strategies:
            cnt = stats.signals_per_strategy.get(name, 0)
            print(f"    {name}: {cnt} 信号")

        # 拒绝原因 Top 5
        if stats.reject_reasons:
            print("\n  拒绝原因 Top 5:")
            top_reasons = sorted(stats.reject_reasons.items(), key=lambda x: -x[1])[:5]
            for reason, cnt in top_reasons:
                print(f"    {reason}: {cnt} 次")

    # DB 统计
    try:
        orders = db.get_orders(limit=1000)
        filled = sum(1 for o in orders if o.get("status") == "FILLED")
        rejected = sum(1 for o in orders if o.get("status") == "REJECTED")
        print("\n  SQLite 订单记录:")
        print(f"    总订单: {len(orders)}")
        print(f"    已成交: {filled}")
        print(f"    已拒绝: {rejected}")
    except Exception:
        pass

    print("=" * 60)

    db.close()
    print("\n[完成] 演练完成，数据库已关闭。")


def main():
    parser = argparse.ArgumentParser(
        description="Canopy 实盘演练 — Binance testnet WS 全链路干跑",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python scripts/live_drill.py\n"
               "  python scripts/live_drill.py --duration 1800\n"
               "  python scripts/live_drill.py --symbols BTC/USDT,ETH/USDT,SOL/USDT",
    )
    parser.add_argument("--duration", type=int, default=3600,
                        help="运行时长（秒），默认 3600（1 小时）")
    parser.add_argument("--symbols", type=str, default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT",
                        help="交易对列表，逗号分隔")
    parser.add_argument("--db", type=str, default="",
                        help="SQLite 数据库路径（默认 data/canopy_live_drill.db）")
    parser.add_argument("--report-interval", type=int, default=300,
                        help="汇总报告间隔（秒），默认 300")
    parser.add_argument("--verbose", action="store_true",
                        help="启用 DEBUG 日志级别")

    args = parser.parse_args()

    # 日志
    import logging  # noqa: E402
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 数据库路径
    db_path = args.db or os.path.join(PROJECT_ROOT, "data", "canopy_live_drill.db")

    # 符号解析
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()][:5]

    run_drill(
        duration=args.duration,
        symbols=symbols,
        db_path=db_path,
        report_interval=args.report_interval,
    )


if __name__ == "__main__":
    main()
