#!/usr/bin/env python3
"""
复盘报告生成器 — 从 SQLite 数据库读取历史交易数据，生成 PDF 复盘报告。

输出内容：
  - 净值曲线 SVG 图
  - 每日 PnL 日历热力图 (HTML)
  - 策略对比表
  - Sharpe / 最大回撤等核心指标

依赖：pip install matplotlib fpdf2
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Any

# ---- 图表（matplotlib） ----
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ---- PDF 输出 ----
try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False


# ---- Jinja2（HTML 模板渲染，可选） ----
try:
    from jinja2 import Template
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False


# ============================================================================
# 数据读取
# ============================================================================

def fetch_trades(db_path: str, start: str | None = None,
                 end: str | None = None) -> list[dict]:
    """从 SQLite 读取 trades 表历史数据。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if start and end:
        rows = conn.execute(
            "SELECT * FROM trades WHERE executed_at >= ? AND executed_at <= ? ORDER BY executed_at ASC",
            (start, end)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY executed_at ASC"
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def fetch_orders(db_path: str, start: str | None = None,
                 end: str | None = None) -> list[dict]:
    """从 SQLite 读取 orders 表历史数据。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if start and end:
        rows = conn.execute(
            "SELECT * FROM orders WHERE created_at >= ? AND created_at <= ? ORDER BY created_at ASC",
            (start, end)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY created_at ASC"
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ============================================================================
# 指标计算
# ============================================================================

def _parse_ts(ts: str) -> datetime:
    """兼容多种 ISO 格式时间戳。"""
    ts = ts.replace("T", " ").split(".")[0].split("+")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(ts)


def compute_metrics(trades: list[dict]) -> dict:
    """根据成交记录计算核心量化指标。"""
    if not trades:
        return {
            "total_trades": 0, "total_pnl": 0.0, "total_return_pct": 0.0,
            "sharpe_ratio": 0.0, "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0, "profit_factor": 0.0, "equity_curve": [],
            "daily_pnl": [], "strategy_stats": []
        }

    # 按时间排序
    sorted_trades = sorted(trades, key=lambda t: t.get("executed_at", ""))

    # 净值曲线 & 每日 PnL
    cum_pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    daily_map: dict[str, float] = {}
    equity_curve: list[dict] = []

    for t in sorted_trades:
        pnl = float(t.get("pnl", 0.0) or 0.0)
        cum_pnl += pnl
        if cum_pnl > peak:
            peak = cum_pnl
        dd = (peak - cum_pnl) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

        date_str = t.get("executed_at", "")[:10]
        daily_map[date_str] = daily_map.get(date_str, 0.0) + pnl

        equity_curve.append({
            "date": date_str,
            "cumulative_pnl": round(cum_pnl, 4),
            "drawdown_pct": round(dd, 2)
        })

    # 日度汇总
    daily_pnl = []
    cum = 0.0
    peak_daily = 0.0
    for date in sorted(daily_map):
        pnl = daily_map[date]
        cum += pnl
        if cum > peak_daily:
            peak_daily = cum
        dd_daily = (peak_daily - cum) / peak_daily * 100 if peak_daily > 0 else 0.0
        daily_pnl.append({"date": date, "pnl": round(pnl, 4),
                          "cumulative_pnl": round(cum, 4),
                          "drawdown": round(dd_daily, 2)})

    # 胜率 & 盈亏比
    wins = [t for t in sorted_trades if float(t.get("pnl", 0.0) or 0.0) > 0]
    losses = [t for t in sorted_trades if float(t.get("pnl", 0.0) or 0.0) < 0]
    win_rate = len(wins) / len(sorted_trades) * 100 if sorted_trades else 0.0

    gross_profit = sum(float(t.get("pnl", 0.0) or 0.0) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl", 0.0) or 0.0) for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    # Sharpe（简化：日收益率的 Sharpe）
    daily_returns = list(daily_map.values())
    if len(daily_returns) >= 2:
        import math
        mean_ret = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_ret = math.sqrt(variance)
        sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0.0
    else:
        sharpe = 0.0

    total_pnl = cum_pnl
    total_return_pct = total_pnl / abs(float(sorted_trades[0].get("price", 1.0) or 1.0)) * 100

    return {
        "total_trades": len(sorted_trades),
        "total_pnl": round(total_pnl, 4),
        "total_return_pct": round(total_return_pct, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "equity_curve": equity_curve,
        "daily_pnl": daily_pnl[-20:],  # 最近 20 个交易日
    }


def compute_strategy_stats(trades: list[dict], orders: list[dict]) -> list[dict]:
    """按策略维度汇总。"""
    # 按 (strategy, symbol) 分组
    groups: dict[tuple[Any, Any], dict] = {}
    for t in trades:
        key = (t.get("strategy", "default"), t.get("symbol", ""))
        if key not in groups:
            groups[key] = {"trades": [], "pnls": []}
        groups[key]["trades"].append(t)
        groups[key]["pnls"].append(float(t.get("pnl", 0.0) or 0.0))

    # 统计信号数
    signal_counts: dict[tuple[Any, Any], int] = {}
    for o in orders:
        key = (o.get("strategy", "default"), o.get("symbol", ""))  # type: ignore[index]
        signal_counts[key] = signal_counts.get(key, 0) + 1

    results = []
    for (strategy, symbol), data in groups.items():  # type: ignore[str-unpack]
        pnls = data["pnls"]
        wins = [p for p in pnls if p > 0]
        results.append({
            "strategy": strategy,
            "symbol": symbol,
            "signals": signal_counts.get((strategy, symbol), 0),  # type: ignore[index]
            "trades": len(pnls),
            "total_pnl": round(sum(pnls), 4),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
            "sharpe": 0.0,   # 单策略 Sharpe 需要更多数据，暂简化
            "max_dd": 0.0,
        })

    return sorted(results, key=lambda x: x["total_pnl"], reverse=True)


# ============================================================================
# 图表生成
# ============================================================================

def draw_equity_curve(equity_curve: list[dict], output_path: str) -> str:
    """生成净值曲线 SVG 并返回文件路径。"""
    if not HAS_MPL or not equity_curve:
        return ""

    fig, ax = plt.subplots(figsize=(10, 4))
    dates = [d["date"] for d in equity_curve]
    values = [d["cumulative_pnl"] for d in equity_curve]

    ax.plot(dates, values, color="#2563eb", linewidth=1.2)
    ax.fill_between(range(len(dates)), values, 0,
                    where=[v >= 0 for v in values],
                    color="#86efac", alpha=0.3)
    ax.fill_between(range(len(dates)), values, 0,
                    where=[v < 0 for v in values],
                    color="#fca5a5", alpha=0.3)
    ax.axhline(y=0, color="#94a3b8", linewidth=0.5, linestyle="--")
    ax.set_title("Equity Curve (Cumulative PnL)", fontsize=13, fontweight="bold")
    ax.set_ylabel("PnL")
    ax.grid(axis="y", alpha=0.3)

    # x 轴间隔
    step = max(1, len(dates) // 10)
    ax.set_xticks(range(0, len(dates), step))
    ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)],
                       rotation=30, ha="right", fontsize=8)

    fig.tight_layout()
    fig.savefig(output_path, format="svg", dpi=100, bbox_inches="tight")
    plt.close(fig)
    return output_path


# ============================================================================
# 日历热力图数据
# ============================================================================

def build_calendar_data(daily_map: dict[str, float],
                        start: datetime, end: datetime) -> list[dict]:
    """构造按月的日历热力图数据。"""
    months = []
    current = start.replace(day=1)
    while current <= end:
        month_end = (current.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        days = []
        cursor = current
        while cursor <= min(month_end, end):
            date_str = cursor.strftime("%Y-%m-%d")
            days.append({
                "date_str": date_str,
                "day_num": cursor.day,
                "pnl": daily_map.get(date_str, None),
            })
            cursor += timedelta(days=1)
        months.append({
            "label": current.strftime("%Y年%m月"),
            "days": days,
        })
        current = (month_end + timedelta(days=1)).replace(day=1)
    return months


# ============================================================================
# PDF 生成
# ============================================================================

def generate_pdf_fpdf(report_data: dict, output_path: str):
    """使用 fpdf2 生成 PDF（纯 Python，无系统依赖）。"""
    if not HAS_FPDF:
        raise ImportError("fpdf2 not installed. Run: pip install fpdf2")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # 标题
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "Canopy Trading Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Period: {report_data['start_date']} ~ {report_data['end_date']}  |  "
                    f"Generated: {report_data['report_date']}",
             new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    # KPI
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Key Metrics", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)

    kpis = [
        ("Total Trades", str(report_data["total_trades"])),
        ("Total PnL", f"{report_data['total_pnl']:.4f}"),
        ("Total Return", f"{report_data['total_return_pct']:.2f}%"),
        ("Sharpe Ratio", f"{report_data['sharpe_ratio']:.2f}"),
        ("Max Drawdown", f"{report_data['max_drawdown_pct']:.2f}%"),
        ("Win Rate", f"{report_data['win_rate_pct']:.1f}%"),
        ("Profit Factor", f"{report_data['profit_factor']:.2f}"),
    ]
    for label, value in kpis:
        pdf.cell(45, 6, f"{label}:", border=0)
        pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # 嵌入图表
    if report_data.get("equity_svg_path") and os.path.exists(report_data["equity_svg_path"]):
        # 将 SVG 转 PNG 嵌入（fpdf2 SVG 支持有限，用 matplotlib 另存 PNG）
        png_path = report_data["equity_svg_path"].replace(".svg", ".png")
        if not os.path.exists(png_path):
            try:
                # 重新保存为 PNG
                pass  # 已在 draw_equity_curve 时处理
            except Exception:
                pass
        else:
            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(0, 8, "Equity Curve", new_x="LMARGIN", new_y="NEXT")
            pdf.image(png_path, x=10, w=190)
            pdf.ln(4)

    # 策略对比表
    if report_data.get("strategy_stats"):
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, "Strategy Comparison", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)

        headers = ["Strategy", "Symbol", "Signals", "Trades", "Win Rate", "Total PnL"]
        col_widths = [35, 25, 20, 20, 25, 30]
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 6, h, border=1, align="C")
        pdf.ln()

        for s in report_data["strategy_stats"]:
            row = [s["strategy"][:14], s["symbol"],
                   str(s["signals"]), str(s["trades"]),
                   f"{s['win_rate']:.1f}%", f"{s['total_pnl']:.4f}"]
            for i, val in enumerate(row):
                pdf.cell(col_widths[i], 6, val, border=1, align="C")
            pdf.ln()

    pdf.ln(4)

    # 日度明细
    if report_data.get("daily_pnl"):
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, "Daily PnL (Last 20 Days)", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)

        d_headers = ["Date", "Trades", "PnL", "Cum PnL", "Drawdown"]
        d_widths = [30, 25, 35, 35, 30]
        for i, h in enumerate(d_headers):
            pdf.cell(d_widths[i], 6, h, border=1, align="C")
        pdf.ln()

        for d in report_data["daily_pnl"]:
            row = [d["date"], str(d.get("trades", "-")),
                   f"{d['pnl']:.4f}", f"{d['cumulative_pnl']:.4f}",
                   f"{d['drawdown']:.2f}%"]
            for i, val in enumerate(row):
                pdf.cell(d_widths[i], 6, val, border=1, align="C")
            pdf.ln()

    pdf.output(output_path)


def generate_report_html(report_data: dict, output_path: str) -> str:
    """使用 Jinja2 模板渲染 HTML 报告。"""
    if not HAS_JINJA2:
        raise ImportError("jinja2 not installed. Run: pip install jinja2")

    # 嵌入 SVG 作为内联图片
    equity_svg = ""
    svg_path = report_data.get("equity_svg_path", "")
    if svg_path and os.path.exists(svg_path):
        with open(svg_path) as f:
            equity_svg = f.read()

    # 构建日历数据
    start = datetime.strptime(report_data["start_date"], "%Y-%m-%d")
    end = datetime.strptime(report_data["end_date"], "%Y-%m-%d")
    daily_map = {d["date"]: d["pnl"] for d in report_data.get("daily_pnl", [])}
    # 也加入 equity_curve 中所有日期的数据
    for pt in report_data.get("equity_curve", []):
        if pt["date"] not in daily_map:
            daily_map[pt["date"]] = 0.0
    calendar_months = build_calendar_data(daily_map, start, end)

    template_path = os.path.join(os.path.dirname(__file__), "report_template.html")
    with open(template_path, encoding="utf-8") as f:
        template = Template(f.read())

    html = template.render(
        report_date=report_data["report_date"],
        start_date=report_data["start_date"],
        end_date=report_data["end_date"],
        total_return_pct=report_data["total_return_pct"],
        sharpe_ratio=report_data["sharpe_ratio"],
        max_drawdown_pct=report_data["max_drawdown_pct"],
        total_trades=report_data["total_trades"],
        win_rate_pct=report_data["win_rate_pct"],
        profit_factor=report_data["profit_factor"],
        equity_curve_svg=equity_svg,
        calendar_months=calendar_months,
        strategy_stats=report_data.get("strategy_stats", []),
        daily_pnl=report_data.get("daily_pnl", []),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


# ============================================================================
# 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Canopy 复盘报告生成器")
    parser.add_argument("--db", default="", help="SQLite 数据库路径（默认读取 config.db_path）")
    parser.add_argument("--start", default="", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--output", default="", help="输出 PDF 路径")
    parser.add_argument("--html", default="", help="同时输出 HTML 路径")
    parser.add_argument("--temp-dir", default="", help="临时文件目录")
    args = parser.parse_args()

    # 数据库路径
    db_path = args.db
    if not db_path:
        # 尝试从 config 读取
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            import config
            db_path = config.db_path
        except Exception:
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                   "data", "canopy.db")

    # 日期范围
    now = datetime.now()
    start = args.start or (now - timedelta(days=30)).strftime("%Y-%m-%d")
    end = args.end or now.strftime("%Y-%m-%d")

    # 输出路径
    output_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = args.temp_dir or os.path.join(output_dir, "..", "logs")
    os.makedirs(temp_dir, exist_ok=True)

    pdf_path = args.output or os.path.join(output_dir, f"report_{now:%Y%m%d_%H%M%S}.pdf")

    print(f"[report] Reading data from {db_path}  ({start} ~ {end})")

    # 读取数据
    trades = fetch_trades(db_path, start, end + "T23:59:59")
    orders = fetch_orders(db_path, start, end + "T23:59:59")

    if not trades:
        print("[report] No trades found in the specified period. Generating empty report.")

    # 计算指标
    metrics = compute_metrics(trades)
    strategy_stats = compute_strategy_stats(trades, orders)

    # 生成图表
    equity_svg_path = ""
    if HAS_MPL and metrics["equity_curve"]:
        equity_svg_path = os.path.join(temp_dir, "equity_curve.svg")
        draw_equity_curve(metrics["equity_curve"], equity_svg_path)
        # 同时生成 PNG 给 fpdf2 嵌入
        png_path = equity_svg_path.replace(".svg", ".png")
        if not os.path.exists(png_path):
            try:
                fig, ax = plt.subplots(figsize=(10, 4))
                dates = [d["date"] for d in metrics["equity_curve"]]
                values = [d["cumulative_pnl"] for d in metrics["equity_curve"]]
                ax.plot(range(len(dates)), values, color="#2563eb", linewidth=1.2)
                ax.set_title("Equity Curve", fontsize=13)
                ax.grid(alpha=0.3)
                fig.tight_layout()
                fig.savefig(png_path, dpi=100, bbox_inches="tight")
                plt.close(fig)
            except Exception:
                pass

    # 组装报告数据
    report_data = {
        "report_date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "start_date": start,
        "end_date": end,
        **metrics,
        "strategy_stats": strategy_stats,
        "equity_svg_path": equity_svg_path,
    }

    # 输出 HTML（可选）
    if args.html and HAS_JINJA2:
        html_path = args.html
        generate_report_html(report_data, html_path)
        print(f"[report] HTML report saved to {html_path}")

    # 输出 PDF
    if HAS_FPDF:
        generate_pdf_fpdf(report_data, pdf_path)
        print(f"[report] PDF report saved to {pdf_path}")
    else:
        print("[report] fpdf2 not installed. Install with: pip install fpdf2")
        # 降级：输出 HTML
        if HAS_JINJA2:
            html_path = pdf_path.replace(".pdf", ".html")
            generate_report_html(report_data, html_path)
            print(f"[report] HTML report saved to {html_path} (PDF not available)")

    # 输出摘要
    print(f"\n{'='*50}")
    print(f"  Total Trades:  {metrics['total_trades']}")
    print(f"  Total PnL:     {metrics['total_pnl']:.4f}")
    print(f"  Return:        {metrics['total_return_pct']:.2f}%")
    print(f"  Sharpe:        {metrics['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown:  {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Win Rate:      {metrics['win_rate_pct']:.1f}%")
    print(f"{'='*50}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
