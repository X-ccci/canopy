#!/usr/bin/env python3
"""
Canopy 实盘驱动脚本 — Binance Testnet 真实下单模式。

用法:
    python scripts/go_live.py
    python scripts/go_live.py --duration 1800
    python scripts/go_live.py --symbols BTC/USDT,ETH/USDT,SOL/USDT
    python scripts/go_live.py --capital 0.01

流程:
    1. 检查 Vault 是否有 binance testnet 密钥
    2. 若无密钥 → 交互式引导用户输入 → 保存到 Vault
    3. 连接 Binance testnet（sandbox 模式）
    4. WebSocket 实时行情 → 启动 5 策略 Runner
    5. RiskManager + OrderExecutor 全链路（dry_run=False）
    6. 每 5 分钟输出汇总
    7. Ctrl+C 退出 → 关闭所有持仓 → 打印最终绩效报告
"""

from __future__ import annotations

import argparse
import getpass
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from canopy.config import Config  # noqa: E402
from canopy.data.fetcher import DataFetcher  # noqa: E402
from canopy.engine.executor import Order, OrderExecutor  # noqa: E402
from canopy.engine.risk import RiskManager  # noqa: E402
from canopy.engine.runner import StrategyRunner  # noqa: E402
from canopy.exchange.ccxt_adapter import ExchangeAdapter  # noqa: E402
from canopy.utils.database import Database  # noqa: E402

# Vault 加载
VAULT_PATH = Path(PROJECT_ROOT) / "utils" / "vault.py"
if str(VAULT_PATH.parent) not in sys.path:
    sys.path.insert(0, str(VAULT_PATH.parent))
try:
    from vault import load_credentials as vault_load_credentials  # noqa: E402
    from vault import save_credentials as vault_save_credentials  # noqa: E402
except ImportError:
    vault_load_credentials = None
    vault_save_credentials = None


# ═══════════════════════════════════════════════════════════════════
#  密钥加载（交互式引导）
# ═══════════════════════════════════════════════════════════════════

def interactive_prompt_keys() -> tuple[str, str] | None:
    """交互式引导用户输入 Binance Testnet API Key/Secret。

    提供获取 testnet 密钥的指引，然后通过安全方式读取输入。
    """
    print("\n" + "=" * 60)
    print("  Binance Testnet API Key 未配置")
    print("=" * 60)
    print()
    print("  获取 Testnet 密钥步骤：")
    print("    1. 打开 https://testnet.binance.vision/")
    print("    2. 使用 GitHub 账号登录")
    print("    3. 进入 API Management → 创建 HMAC API Key")
    print("    4. 复制 API Key 和 Secret")
    print()
    print("  (直接按 Enter 跳过，稍后手动配置)")
    print("-" * 60)

    api_key = input("  API Key: ").strip()
    if not api_key:
        print("\n  [SKIP] 未输入 API Key，取消连接。")
        return None

    api_secret = getpass.getpass("  API Secret: ").strip()
    if not api_secret:
        print("\n  [SKIP] 未输入 API Secret，取消连接。")
        return None

    # 保存到 Vault
    if vault_save_credentials:
        try:
            vault_save_credentials("binance", api_key, api_secret)
            print("\n  [Vault] 密钥已加密保存到 Vault。")
        except Exception as e:
            print(f"\n  [WARN] Vault 保存失败: {e}")
            print("  密钥仅本次会话使用，不会落盘。")

    return api_key, api_secret


def load_credentials(require_keys: bool = True) -> tuple[str, str] | None:
    """加载 Binance testnet 密钥。

    优先级: Vault → 环境变量 → 交互式引导

    Args:
        require_keys: True 表示必须有真实密钥（实盘模式），
                      False 允许空密钥（仅公开行情）。

    Returns:
        (api_key, api_secret) 或 None。
    """
    # 1. Vault
    if vault_load_credentials:
        try:
            creds = vault_load_credentials("binance")
            if creds and creds[0] and creds[1]:
                print("[Vault] 已从 Vault 加载 binance 凭证")
                return creds
        except Exception as e:
            print(f"[Vault] 加载失败: {e}")

    # 2. 环境变量
    api_key = os.environ.get("BINANCE_API_KEY", "")
    api_secret = os.environ.get("BINANCE_API_SECRET", "")
    if api_key and api_secret:
        print("[Env] 已从环境变量加载 Binance 凭证")
        return api_key, api_secret

    # 3. 交互式引导
    if require_keys:
        return interactive_prompt_keys()

    # 4. 无密钥
    print("[WARN] 未找到 API 密钥，使用空凭证（仅测试网公开行情可用）")
    return "", ""


# ═══════════════════════════════════════════════════════════════════
#  信号统计
# ═══════════════════════════════════════════════════════════════════

@dataclass
class LiveStats:
    """实盘统计数据。"""
    total_signals: int = 0
    approved: int = 0
    rejected: int = 0
    holds: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
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

    def record_order(self, status: str):
        if status == "FILLED":
            self.orders_filled += 1
        elif status == "REJECTED":
            self.orders_rejected += 1

    def summary(self, risk_mgr: RiskManager | None) -> str:
        elapsed = (datetime.now() - datetime.fromisoformat(self.start_time)).total_seconds()
        h, rem = divmod(int(elapsed), 3600)
        m, s = divmod(rem, 60)
        elapsed_str = f"{h}h {m}m {s}s"
        pass_rate = f"{self.approved / max(self.total_signals, 1) * 100:.1f}%"

        lines = [
            "",
            "=" * 60,
            f"  [LIVE 汇总] 运行时长: {elapsed_str}",
            f"  信号: {self.approved}/{self.total_signals} 通过 ({pass_rate})  |  拒绝: {self.rejected}",
            f"  订单: 提交 {self.orders_submitted}  |  成交 {self.orders_filled}  |  拒绝 {self.orders_rejected}",
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
                f"  熔断: {'TRIPPED' if status['circuit_breaker']['tripped'] else 'OK'}",
            ])

        lines.append("=" * 60)
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
#  主运行逻辑
# ═══════════════════════════════════════════════════════════════════

def run_live(
    duration: int,
    symbols: list[str],
    db_path: str,
    initial_capital: float = 0.01,
    report_interval: int = 300,
):
    """执行实盘驱动（真实提交订单到 Binance Testnet）。

    Args:
        duration:        运行时长（秒）。
        symbols:         交易对列表。
        db_path:         SQLite 数据库路径。
        initial_capital: 初始资金（BTC），默认 0.01。
        report_interval: 汇总报告间隔（秒），默认 300。
    """
    import logging
    logger = logging.getLogger("go_live")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── 1. 加载密钥 ──
    result = load_credentials(require_keys=True)
    if result is None:
        print("\n[EXIT] 无法获取 API 密钥，退出。")
        print("  提示: 设置环境变量 BINANCE_API_KEY / BINANCE_API_SECRET")
        print("        或手动编辑 vault.json 后重新运行。")
        sys.exit(0)
    api_key, api_secret = result

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
    print("\n[连接] 正在连接 Binance Testnet (sandbox)...")
    adapter = ExchangeAdapter("binance", config)
    ok = adapter.connect()
    if not ok:
        logger.error("连接 Binance testnet 失败，请检查网络和密钥。")
        print("[ERROR] 无法连接 Binance testnet。")
        print("  检查项：")
        print("    1. 网络是否可访问 testnet.binance.vision")
        print("    2. API Key 是否正确")
        print("    3. IP 是否在 API Key 白名单中")
        sys.exit(1)

    fetcher = DataFetcher(adapter)
    logger.info("交易所连接就绪")

    # ── 5. 创建 Runner + 真实执行器 ──
    risk_mgr = RiskManager(initial_balance=initial_capital * 50000)  # 以 USDT 估值
    runner = StrategyRunner(adapter, fetcher, config=config)

    # 替换执行器为真实下单版本
    real_executor = OrderExecutor(adapter, risk_mgr, db=db)
    real_executor.start()
    runner.executor = real_executor
    runner.risk_mgr = risk_mgr

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
    stats = LiveStats()
    stats_lock = threading.Lock()

    # ── 8. 信号与订单拦截回调 ──
    original_submit = runner.executor.submit

    def live_submit(order_dict):
        strategy_name = order_dict.get("strategy", "")
        with stats_lock:
            stats.record_signal(strategy_name, approved=True)
            stats.orders_submitted += 1
        order_dict["strategy"] = strategy_name
        return original_submit(order_dict)

    runner.executor.submit = live_submit  # type: ignore[method-assign]

    # 拦截 reject / hold 信号
    original_log_signal = runner._log_signal

    def intercept_log_signal(strategy_name, signal, candle):
        action = signal.get("action", "")
        reason = signal.get("reason", "")
        if action == "REJECTED":
            with stats_lock:
                stats.record_signal(strategy_name, approved=False, reason=reason)
                stats.orders_rejected += 1
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

    # ── 9. 订单成交回调（监听 FILLED 事件） ──
    def on_order_filled(order: Order):
        with stats_lock:
            stats.record_order("FILLED")
        logger.info(f"[FILLED] {order.symbol} {order.side} qty={order.filled_qty} "
                     f"@ ${order.avg_fill_price}")

    real_executor._on_fill_callbacks.append(on_order_filled)

    # ── 10. 熔断监控 ──
    def monitor_circuit_breaker():
        while runner._running:
            if runner.risk_mgr.circuit_breaker.is_tripped:
                with stats_lock:
                    stats.circuit_trips += 1
            threading.Event().wait(5)

    cb_thread = threading.Thread(target=monitor_circuit_breaker, daemon=True)
    cb_thread.start()

    # ── 11. 启动 ──
    btc_price = "N/A"
    try:
        ticker = adapter.fetch_ticker("BTC/USDT")
        btc_price = f"${ticker.get('last', 'N/A')}"
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  Canopy v0.2 — 实盘驱动 (Binance Testnet)")
    print("=" * 60)
    print(f"  交易所:     Binance Testnet (sandbox)")
    print(f"  策略数:     {len(runner.strategies)}")
    print(f"  交易对:     {', '.join(symbols)}")
    print(f"  初始资金:   {initial_capital} BTC")
    print(f"  BTC 现价:   {btc_price}")
    print(f"  运行时长:   {duration}s ({duration // 60} 分钟)")
    print(f"  模式:       LIVE (dry_run=False，真实提交订单到 testnet)")
    print("-" * 60)
    print(f"  汇总间隔:   {report_interval}s")
    print("  Ctrl+C 退出（自动平仓）")
    print("=" * 60 + "\n")

    runner.start_all()
    logger.info("全策略已启动（WS 模式）")
    print("[启动] 5 策略 Runner 已启动，等待 WS 连接...\n")

    time.sleep(3)

    # ── 12. 定时汇总线程 ──
    def periodic_report():
        while runner._running:
            time.sleep(report_interval)
            if not runner._running:
                break
            with stats_lock:
                print(stats.summary(runner.risk_mgr))

    reporter = threading.Thread(target=periodic_report, daemon=True)
    reporter.start()

    # ── 13. 优雅退出（平仓所有持仓） ──
    stop_event = threading.Event()
    shutdown_reason = ""

    def graceful_shutdown(sig=None, frame=None):
        nonlocal shutdown_reason
        shutdown_reason = f"收到信号 {sig}" if sig else "超时停止"
        stop_event.set()

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    start_ts = time.time()
    while not stop_event.is_set():
        elapsed = time.time() - start_ts
        if elapsed >= duration:
            shutdown_reason = "运行时长到期"
            break
        stop_event.wait(min(1, duration - elapsed))

    # ── 14. 平仓所有持仓 ──
    print(f"\n[停止] {shutdown_reason}，正在平仓所有持仓...")
    positions = getattr(runner.risk_mgr, 'positions', {})
    closed_count = 0
    failed_close = []

    for symbol, pos in list(positions.items()):
        qty = getattr(pos, 'quantity', 0)
        if qty <= 0:
            continue
        side = "sell"  # 平多仓
        logger.info(f"[平仓] {symbol} {side} qty={qty}")
        try:
            adapter.create_order(symbol, "market", side, qty)
            closed_count += 1
        except Exception as e:
            logger.error(f"[平仓失败] {symbol}: {e}")
            failed_close.append(symbol)

    runner.stop_all()
    real_executor.stop()
    time.sleep(1)

    # ── 15. 最终报告 ──
    print("\n")
    print("=" * 60)
    print("  Canopy v0.2 实盘绩效报告")
    print("=" * 60)

    with stats_lock:
        elapsed = (datetime.now() - datetime.fromisoformat(stats.start_time)).total_seconds()
        h, rem = divmod(int(elapsed), 3600)
        m, s = divmod(rem, 60)
        elapsed_str = f"{h}h {m}m {s}s"

        print(f"  运行时长:     {elapsed_str}")
        print(f"  信号总数:     {stats.total_signals}")
        print(f"  通过:         {stats.approved}")
        print(f"  拒绝:         {stats.rejected}")
        print(f"  HOLD:         {stats.holds}")
        print(f"  通过率:       {stats.approved / max(stats.total_signals, 1) * 100:.1f}%")
        print(f"  提交订单:     {stats.orders_submitted}")
        print(f"  成交订单:     {stats.orders_filled}")
        print(f"  拒绝订单:     {stats.orders_rejected}")
        print(f"  熔断触发:     {stats.circuit_trips} 次")
        print(f"  平仓数:       {closed_count}")
        if failed_close:
            print(f"  平仓失败:     {', '.join(failed_close)}")

        risk_status = runner.risk_mgr.get_status()
        print(f"  当前余额:     ${risk_status['current_balance']:,.2f}")
        print(f"  峰值余额:     ${risk_status['peak_balance']:,.2f}")
        print(f"  最大回撤:     {risk_status['drawdown_pct']}%")
        print(f"  熔断状态:     {'TRIPPED' if risk_status['circuit_breaker']['tripped'] else 'NORMAL'}")

        print("\n  策略信号明细:")
        for name in runner.strategies:
            cnt = stats.signals_per_strategy.get(name, 0)
            print(f"    {name}: {cnt} 信号")

        if stats.reject_reasons:
            print("\n  拒绝原因 Top 5:")
            top = sorted(stats.reject_reasons.items(), key=lambda x: -x[1])[:5]
            for reason, cnt in top:
                print(f"    {reason}: {cnt} 次")

    # DB 统计
    try:
        orders = db.get_orders(limit=1000)
        print(f"\n  SQLite 订单记录: {len(orders)} 条")
    except Exception:
        pass

    print("=" * 60)

    db.close()
    print("\n[DONE] 实盘运行结束。")


# ═══════════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Canopy v0.2 实盘驱动 — Binance Testnet 真实下单",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/go_live.py\n"
            "  python scripts/go_live.py --duration 1800 --capital 0.01\n"
            "  python scripts/go_live.py --symbols BTC/USDT,ETH/USDT,SOL/USDT\n"
        ),
    )
    parser.add_argument("--duration", type=int, default=3600,
                        help="运行时长（秒），默认 3600（1 小时）")
    parser.add_argument("--symbols", type=str,
                        default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT",
                        help="交易对列表，逗号分隔")
    parser.add_argument("--capital", type=float, default=0.01,
                        help="初始资金（BTC），默认 0.01")
    parser.add_argument("--db", type=str, default="",
                        help="SQLite 数据库路径")
    parser.add_argument("--report-interval", type=int, default=300,
                        help="汇总报告间隔（秒），默认 300")
    parser.add_argument("--dry-run", action="store_true",
                        help="干跑模式（仅记录不下单，覆盖真实模式）")

    args = parser.parse_args()

    # 数据库路径
    db_path = args.db or os.path.join(PROJECT_ROOT, "data", "canopy_live.db")

    # 符号解析
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()][:5]

    if args.dry_run:
        print("[INFO] 干跑模式，使用 live_drill.py 逻辑...")
        # 回退到 live_drill 的干跑逻辑
        from scripts.live_drill import run_drill
        run_drill(
            duration=args.duration,
            symbols=symbols,
            db_path=db_path,
            report_interval=args.report_interval,
        )
    else:
        run_live(
            duration=args.duration,
            symbols=symbols,
            db_path=db_path,
            initial_capital=args.capital,
            report_interval=args.report_interval,
        )


if __name__ == "__main__":
    main()
