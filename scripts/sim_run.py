#!/usr/bin/env python3
"""模拟运行入口 — 脱网模式下基于历史 Parquet 数据运行完整交易链路。

用法:
    python scripts/sim_run.py \\
        --strategy mean_reversion \\
        --symbol BTC/USDT \\
        --timeframe 1h \\
        --capital 10000 \\
        --data data/cache/BTC_USDT_1h.parquet

    # 启用净值曲线绘图
    python scripts/sim_run.py ... --plot

    # 自定义滑点和手续费
    python scripts/sim_run.py ... --slippage 0.001 --commission 0.002
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from canopy.engine.backtest.metrics import PerformanceMetrics  # noqa: E402
from canopy.engine.factory import StrategyFactory  # noqa: E402
from canopy.engine.risk import RiskConfig, RiskManager  # noqa: E402
from canopy.sim.account import SimAccount  # noqa: E402
from canopy.sim.broker import SimBroker  # noqa: E402
from canopy.sim.engine import SimEngine  # noqa: E402

logger = logging.getLogger("sim_run")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def build_data_path(symbol: str, timeframe: str, data_dir: str) -> str:
    """根据 symbol/timeframe 构建 Parquet 缓存路径。

    Args:
        symbol:    交易对，如 'BTC/USDT'。
        timeframe: 周期，如 '1h'。
        data_dir:  数据目录路径。

    Returns:
        完整 Parquet 文件路径。
    """
    key = symbol.replace("/", "_")
    return os.path.join(data_dir, f"{key}_{timeframe}.parquet")


def generate_fallback_data(symbol: str, timeframe: str, data_dir: str,
                           length: int = 200) -> str:
    """生成回退测试数据并写入 Parquet。

    Args:
        symbol:    交易对。
        timeframe: 周期。
        data_dir:  输出目录。
        length:    K 线数量。

    Returns:
        写入的 Parquet 文件路径。
    """
    from canopy.engine.fallback import generate_fallback_test_data  # noqa: E402

    os.makedirs(data_dir, exist_ok=True)
    df = generate_fallback_test_data(symbol, timeframe, length)
    path = build_data_path(symbol, timeframe, data_dir)
    df.to_parquet(path, index=False)
    logger.info(f"已生成 {length} 条模拟数据 → {path}")
    return path


def run_simulation(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    initial_capital: float,
    data_path: str,
    slippage: float,
    commission: float,
    plot: bool,
    risk_config: RiskConfig | None = None,
    strategy_params: dict | None = None,
) -> dict:
    """运行模拟交易。

    流程:
        1. 加载 Parquet 数据 → 初始化 SimEngine
        2. 创建 SimAccount + SimBroker
        3. 逐根 K 线推进：
           a. 当前 K 线喂给策略 on_bar() → 获取信号
           b. 信号通过 RiskManager 审批
           c. 审批通过后 SimBroker.submit_order() 撮合成交
        4. 最终输出绩效报告（含净值曲线 PNG 可选）

    Returns:
        绩效报告字典。
    """
    # ── 1. 初始化引擎 ──
    engine = SimEngine(data_path, slippage=slippage, commission=commission)
    if not engine.load():
        logger.error(f"无法加载数据: {data_path}")
        sys.exit(1)

    logger.info(f"数据加载完成: {engine.total_bars} 根 K 线, symbol={engine.symbol}")

    # ── 2. 初始化账户与券商 ──
    account = SimAccount(initial_capital=initial_capital)
    broker = SimBroker(engine=engine, account=account)

    # ── 3. 初始化策略 ──
    factory = StrategyFactory()
    factory._register_builtins()
    strategy = factory.create(strategy_name, **(strategy_params or {}))
    strategy.start()

    # ── 4. 初始化风控 ──
    risk = RiskManager(
        config=risk_config or RiskConfig(),
        initial_balance=initial_capital,
    )

    # ── 5. 事件日志 ──
    broker.on_submit(lambda e: logger.debug(f"ORDER_SUBMITTED: {e['order'].id}"))
    broker.on_match(lambda e: logger.info(
        f"ORDER_MATCHED: {e['order'].side} {e['order'].amount} "
        f"{e['order'].symbol} @ {e['order'].filled_price}"
    ))

    # ── 6. 逐根推进 ──
    equity_curve: list[float] = [initial_capital]
    trades_log: list[dict] = []
    bar_index: list[str] = []

    # 记录初始状态
    initial_timestamp = str(engine.current_timestamp)
    bar_index.append(initial_timestamp)

    while True:
        candle = engine.current_candle
        ts = str(engine.current_timestamp)

        # 6a. 策略 on_bar
        signal = strategy.on_bar(candle)

        # 6b. 风控审批
        current_price = candle["close"]
        approved, reason, order_dict = risk.approve(
            signal, current_price=current_price,
            account_balance=broker.account.balance,
        )

        # 6c. 下单
        if approved and order_dict:
            action = order_dict.get("action", "HOLD")
            qty = order_dict.get("quantity", 0)
            side = order_dict.get("side", "buy")
            price = order_dict.get("price", current_price)

            result = broker.submit_order(
                symbol=symbol,
                side=side,
                order_type="market",
                amount=qty,
                price=price,
            )

            trade_entry = {
                "time": ts,
                "action": action,
                "side": side,
                "price": result.get("price", current_price),
                "amount": round(qty, 4),
                "status": result.get("status"),
                "cost": round(result.get("cost", 0), 2),
                "fee": round(result.get("fee", 0), 4),
                "reason": signal.get("reason", ""),
                "message": result.get("message", ""),
            }
            trades_log.append(trade_entry)

            # 打印交易日志
            status_icon = "+" if result.get("status") == "FILLED" else "?"
            print(
                f"[{ts}] {status_icon} {action} {side.upper()} "
                f"{qty:.4f} @ {result.get('price', current_price):.2f} "
                f"| {result.get('message', '')} "
                f"| 余额: {broker.account.balance:.2f}"
            )
        else:
            if reason and reason != "Signal is HOLD":
                logger.debug(f"[{ts}] 风控拒绝: {reason}")

        # 6d. 记录净值
        portfolio = broker.get_portfolio()
        equity_curve.append(portfolio["equity"])
        bar_index.append(ts)

        # 6e. 推进
        step_result = broker.step()
        if not step_result["advanced"]:
            break

    # ── 7. 最终平仓 ──
    positions = broker.get_positions()
    final_candle = engine.current_candle
    final_candle["close"] if final_candle else 0

    for sym, pos in positions.items():
        if pos["quantity"] > 0:
            side = "sell" if pos["side"] == "LONG" else "buy"
            result = broker.submit_order(
                symbol=sym,
                side=side,
                order_type="market",
                amount=pos["quantity"],
            )
            logger.info(f"最终平仓: {side} {pos['quantity']} {sym} → {result.get('status')}")

    strategy.stop()

    # ── 8. 绩效报告 ──
    metrics = PerformanceMetrics(equity_curve, trades_log)
    perf = metrics.calculate_all()

    report = {
        "strategy": strategy_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "initial_capital": initial_capital,
        "final_equity": perf["final_equity"],
        "total_return_pct": round(perf["total_return"] * 100, 2),
        "max_drawdown_pct": round(perf["max_drawdown"] * 100, 2),
        "sharpe_ratio": perf["sharpe_ratio"],
        "sortino_ratio": perf["sortino_ratio"],
        "calmar_ratio": perf["calmar_ratio"],
        "win_rate": round(perf["win_rate"] * 100, 2),
        "profit_factor": perf["profit_factor"],
        "total_trades": perf["total_trades"],
        "total_bars": engine.total_bars,
        "slippage": slippage * 100,
        "commission": commission * 100,
        "ran_at": datetime.now().isoformat(),
    }

    # ── 9. 打印报告 ──
    print("\n" + "=" * 60)
    print("  模拟交易绩效报告")
    print("=" * 60)
    print(f"  策略:         {report['strategy']}")
    print(f"  交易对:       {report['symbol']}  {report['timeframe']}")
    print(f"  K 线总数:     {report['total_bars']}")
    print(f"  初始资金:     ${report['initial_capital']:,.2f}")
    print(f"  最终权益:     ${report['final_equity']:,.2f}")
    print(f"  总收益率:     {report['total_return_pct']:+.2f}%")
    print(f"  最大回撤:     {report['max_drawdown_pct']:.2f}%")
    print(f"  夏普比率:     {report['sharpe_ratio']:.2f}")
    print(f"  索提诺比率:   {report['sortino_ratio']:.2f}")
    print(f"  卡玛比率:     {report['calmar_ratio']:.2f}")
    print(f"  胜率:         {report['win_rate']:.1f}%")
    print(f"  盈亏比:       {report['profit_factor']:.2f}")
    print(f"  交易次数:     {report['total_trades']}")
    print(f"  滑点:         {report['slippage']:.2f}%")
    print(f"  手续费:       {report['commission']:.2f}%")
    print("=" * 60)

    # ── 10. 净值曲线 ──
    if plot:
        try:
            import matplotlib  # noqa: E402
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: E402

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

            # 净值曲线
            ax1.plot(equity_curve, color="#2563eb", linewidth=1.5, label="Equity")
            ax1.axhline(y=initial_capital, color="gray", linestyle="--",
                        linewidth=0.8, label="Initial Capital")
            ax1.set_ylabel("Equity (USDT)")
            ax1.set_title(f"Canopy Sim: {strategy_name} on {symbol} ({timeframe})")
            ax1.legend(loc="upper left")
            ax1.grid(True, alpha=0.3)

            # 回撤
            peak = equity_curve[0]
            drawdowns = []
            for v in equity_curve:
                if v > peak:
                    peak = v
                dd = (peak - v) / peak * 100 if peak > 0 else 0
                drawdowns.append(dd)
            ax2.fill_between(range(len(drawdowns)), drawdowns, 0,
                             color="#ef4444", alpha=0.3, label="Drawdown %")
            ax2.set_ylabel("Drawdown (%)")
            ax2.set_xlabel("Bar Index")
            ax2.legend(loc="lower left")
            ax2.grid(True, alpha=0.3)

            output_path = os.path.join(PROJECT_ROOT, "output", "sim_equity_curve.png")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            plt.tight_layout()
            plt.savefig(output_path, dpi=150, bbox_inches="tight")
            plt.close()
            logger.info(f"净值曲线已保存 → {output_path}")
            report["equity_plot"] = output_path
        except ImportError:
            logger.warning("matplotlib 未安装，跳过绘")
            report["equity_plot"] = None

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Canopy 脱网模拟交易运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/sim_run.py --strategy mean_reversion --symbol BTC/USDT --timeframe 1h --capital 10000
  python scripts/sim_run.py --strategy grid --symbol ETH/USDT --timeframe 4h --capital 5000 --plot
        """,
    )
    parser.add_argument("--strategy", required=True,
                        choices=["trend", "grid", "arbitrage", "momentum", "mean_reversion"],
                        help="策略类型")
    parser.add_argument("--symbol", default="BTC/USDT", help="交易对（默认: BTC/USDT）")
    parser.add_argument("--timeframe", default="1h", help="K 线周期（默认: 1h）")
    parser.add_argument("--capital", type=float, default=10000, help="初始资金（默认: 10000）")
    parser.add_argument("--data", default="", help="Parquet 数据文件路径（留空则自动生成模拟数据）")
    parser.add_argument("--data-dir", default="data/cache",
                        help="数据缓存目录（默认: data/cache）")
    parser.add_argument("--slippage", type=float, default=0.0005,
                        help="滑点比例（默认: 0.0005 = 0.05%%）")
    parser.add_argument("--commission", type=float, default=0.001,
                        help="手续费率（默认: 0.001 = 0.1%%）")
    parser.add_argument("--plot", action="store_true", help="绘制净值曲线并保存 PNG")
    parser.add_argument("--bars", type=int, default=200,
                        help="自动生成模拟数据的 K 线数量（默认: 200）")

    args = parser.parse_args()

    # 确定数据路径
    if args.data:
        data_path = args.data
    else:
        data_path = build_data_path(args.symbol, args.timeframe, args.data_dir)
        if not os.path.exists(data_path):
            logger.info(f"数据文件不存在，自动生成 {args.bars} 根模拟 K 线...")
            data_path = generate_fallback_data(
                args.symbol, args.timeframe, args.data_dir, args.bars
            )

    if not os.path.exists(data_path):
        logger.error(f"数据文件不存在: {data_path}")
        sys.exit(1)

    run_simulation(
        strategy_name=args.strategy,
        symbol=args.symbol,
        timeframe=args.timeframe,
        initial_capital=args.capital,
        data_path=data_path,
        slippage=args.slippage,
        commission=args.commission,
        plot=args.plot,
    )


if __name__ == "__main__":
    main()
