#!/usr/bin/env python
"""回测报告 PDF 导出 — 读取回测结果，使用 WeasyPrint 生成 PDF。

功能：
- 读取 JSON 回测结果或回测输出文件
- 渲染净值曲线 SVG 图
- 交易明细表格
- KPI 指标卡片
- 自动安装 weasyprint 依赖

用法：
    python scripts/export_report.py --input backtest_result.json --output report.pdf
    python scripts/export_report.py --input data/optimize_trend.json --title "趋势策略优化报告"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_PROJ_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))


def ensure_weasyprint() -> bool:
    """确保 weasyprint 已安装，未安装则自动 pip install。"""
    try:
        import weasyprint  # noqa: F401
        return True
    except ImportError:
        print("[export_report] weasyprint 未安装，正在自动安装...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "weasyprint"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[export_report] weasyprint 安装成功")
            return True
        except Exception as e:
            print(f"[export_report] weasyprint 安装失败: {e}")
            return False


def _generate_equity_svg(equity_curve: list[dict] | list[float],
                          width: int = 720, height: int = 320,
                          title: str = "净值曲线") -> str:
    """生成净值曲线 SVG 字符串。"""
    if not equity_curve:
        return "<svg></svg>"

    # 标准化数据
    if isinstance(equity_curve[0], dict):
        values = [float(e.get("value", e.get("equity", 0))) for e in equity_curve]
    else:
        values = [float(v) for v in equity_curve]

    if not values:
        return "<svg></svg>"

    pad = {"top": 40, "right": 20, "bottom": 50, "left": 80}
    pw = width - pad["left"] - pad["right"]
    ph = height - pad["top"] - pad["bottom"]

    vmin, vmax = min(values), max(values)
    vrange = vmax - vmin or 1

    def x_scale(i: int) -> float:
        return pad["left"] + (i / max(1, len(values) - 1)) * pw

    def y_scale(v: float) -> float:
        return pad["top"] + ph - ((v - vmin) / vrange) * ph

    # 生成路径
    points = " ".join(f"{x_scale(i)},{y_scale(v)}" for i, v in enumerate(values))
    area_path = f"M{x_scale(0)},{pad['top'] + ph} L{points} L{x_scale(len(values)-1)},{pad['top'] + ph} Z"

    # Y 轴刻度
    y_ticks = ""
    for i in range(5):
        v = vmin + vrange * i / 4
        y = y_scale(v)
        y_ticks += (
            f'<text x="{pad["left"] - 8}" y="{y + 4}" text-anchor="end" '
            f'font-size="10" fill="#8892b0">${v:,.0f}</text>'
            f'<line x1="{pad["left"]}" y1="{y}" x2="{width - pad["right"]}" y2="{y}" '
            f'stroke="#1e293b" stroke-width="0.5"/>'
        )

    # 初始资金参考线
    init_y = y_scale(values[0])

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
  <defs>
    <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#50c878" stop-opacity="0.25"/>
      <stop offset="1" stop-color="#50c878" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="#0f172a" rx="8"/>
  <text x="{width/2}" y="24" text-anchor="middle" font-size="14" font-weight="600" fill="#e2e8f0">{title}</text>
  {y_ticks}
  <line x1="{pad["left"]}" y1="{init_y}" x2="{width - pad["right"]}" y2="{init_y}"
        stroke="rgba(255,255,255,0.15)" stroke-dasharray="5,5" stroke-width="1"/>
  <path d="{area_path}" fill="url(#areaGrad)"/>
  <polyline points="{points}" fill="none" stroke="#50c878" stroke-width="2" stroke-linejoin="round"/>
</svg>"""
    return svg


def _render_kpi_cards(metrics: dict) -> str:
    """渲染 KPI 指标卡片 HTML。"""
    labels = {
        "total_return": "总收益",
        "annual_return": "年化收益",
        "sharpe_ratio": "夏普比率",
        "sortino_ratio": "索提诺比率",
        "max_drawdown": "最大回撤",
        "calmar_ratio": "卡玛比率",
        "win_rate": "胜率",
        "profit_factor": "盈利因子",
        "total_trades": "总交易数",
    }

    cards = ""
    for key, label in labels.items():
        val = metrics.get(key, "N/A")
        if isinstance(val, float):
            if "return" in key or "drawdown" in key or "rate" in key:
                formatted = f"{val * 100:.2f}%" if abs(val) < 10 else f"{val:.2f}"
            else:
                formatted = f"{val:.4f}"
        else:
            formatted = str(val)
        cards += f"""
    <div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value">{formatted}</div>
    </div>"""

    return cards


def _render_trades_table(trades: list[dict]) -> str:
    """渲染交易明细表格 HTML。"""
    if not trades:
        return '<p style="color:#64748b;">无交易记录</p>'

    rows = ""
    for t in trades[:50]:  # 最多 50 条
        pnl = t.get("pnl", 0) or 0
        pnl_cls = "positive" if pnl >= 0 else "negative"
        pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        rows += f"""
      <tr>
        <td>{str(t.get("time", t.get("timestamp", "")))[:19]}</td>
        <td>{t.get("action", t.get("side", ""))}</td>
        <td>${t.get("price", 0):,.2f}</td>
        <td>{t.get("size", t.get("amount", 0))}</td>
        <td class="{pnl_cls}">{pnl_str}</td>
        <td>{t.get("reason", "")}</td>
      </tr>"""

    return f"""<table class="trades-table">
    <thead><tr><th>时间</th><th>操作</th><th>价格</th><th>数量</th><th>盈亏</th><th>原因</th></tr></thead>
    <tbody>{rows}
    </tbody></table>"""


def build_html(
    equity_svg: str,
    metrics: dict,
    trades: list[dict],
    strategy_name: str,
    report_title: str,
) -> str:
    """构建完整 HTML 文档。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{report_title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f172a; color: #e2e8f0; padding: 40px;
  }}
  h1 {{ font-size: 28px; margin-bottom: 4px; color: #50c878; }}
  .subtitle {{ font-size: 13px; color: #64748b; margin-bottom: 32px; }}
  .section {{ margin-bottom: 36px; }}
  .section-title {{ font-size: 18px; font-weight: 600; margin-bottom: 12px; border-left: 3px solid #50c878; padding-left: 10px; }}
  .kpi-grid {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }}
  .kpi-card {{
    flex: 1; min-width: 130px; padding: 16px;
    background: #1e293b; border-radius: 10px;
    border: 1px solid #334155;
  }}
  .kpi-label {{ font-size: 11px; color: #64748b; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .kpi-value {{ font-size: 22px; font-weight: 700; color: #e2e8f0; }}
  .chart-container {{ background: #1e293b; border-radius: 10px; padding: 8px; border: 1px solid #334155; }}
  .trades-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  .trades-table th {{ background: #1e293b; color: #64748b; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #334155; }}
  .trades-table td {{ padding: 8px 12px; border-bottom: 1px solid #1e293b; }}
  .trades-table tr:nth-child(even) {{ background: #1a2332; }}
  .positive {{ color: #50c878; font-weight: 600; }}
  .negative {{ color: #f47272; font-weight: 600; }}
  .footer {{ font-size: 11px; color: #475569; text-align: center; margin-top: 40px; padding-top: 16px; border-top: 1px solid #334155; }}
</style>
</head>
<body>
<h1>{report_title}</h1>
<div class="subtitle">策略: {strategy_name} · 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>

<div class="section">
  <div class="section-title">KPI 指标</div>
  <div class="kpi-grid">{_render_kpi_cards(metrics)}
  </div>
</div>

<div class="section">
  <div class="section-title">净值曲线</div>
  <div class="chart-container">{equity_svg}</div>
</div>

<div class="section">
  <div class="section-title">交易明细</div>
  {_render_trades_table(trades)}
</div>

<div class="footer">Canopy Nature-Tech Terminal · 回测报告自动生成</div>
</body>
</html>"""


def load_input(input_path: str) -> tuple[dict | None, str]:
    """加载输入数据，自动识别 JSON 结构中的回测数据。"""
    with open(input_path) as f:
        data = json.load(f)

    metrics = {}
    trades = []
    equity = []
    strategy_name = ""

    # 尝试多种数据结构
    if "optimal_metrics" in data:
        metrics = data["optimal_metrics"]
        strategy_name = data.get("strategy", "")
    elif "metrics" in data:
        metrics = data["metrics"]
        strategy_name = data.get("strategy", "")
    elif "best_metrics" in data:
        metrics = data["best_metrics"]
        strategy_name = data.get("strategy", "")

    if "optimal_params" in data:
        strategy_name = strategy_name or data.get("strategy", "Unknown")

    if "trades" in data:
        trades = data["trades"]
    if "equity_curve" in data:
        equity = data["equity_curve"]
    elif "equity" in data:
        equity = data["equity"]

    if not metrics and "final_population" in data:
        pop = data["final_population"]
        if pop:
            best = max(pop, key=lambda x: x.get("fitness", float("-inf")))
            metrics = best.get("metrics", {})
            strategy_name = strategy_name or data.get("strategy", "Unknown")

    return {
        "metrics": metrics,
        "trades": trades,
        "equity": equity,
        "strategy": strategy_name,
    }, strategy_name


def main():
    parser = argparse.ArgumentParser(description="Canopy 回测报告 PDF 导出")
    parser.add_argument("--input", "-i", required=True, help="输入 JSON 文件路径")
    parser.add_argument("--output", "-o", default="", help="输出 PDF 路径（默认与输入同目录同名）")
    parser.add_argument("--title", "-t", default="", help="报告标题")
    args = parser.parse_args()

    # 安装 weasyprint
    if not ensure_weasyprint():
        print("[export_report] 无法安装 weasyprint，请手动 pip install weasyprint")
        sys.exit(1)

    import weasyprint

    # 加载数据
    parsed, strategy_name = load_input(args.input)
    title = args.title or f"Canopy 回测报告 — {strategy_name or 'Unknown'}"

    # 生成 SVG
    equity_svg = _generate_equity_svg(parsed["equity"], title="净值曲线 (Equity Curve)")

    # 构建 HTML
    html_content = build_html(
        equity_svg=equity_svg,
        metrics=parsed["metrics"],
        trades=parsed["trades"],
        strategy_name=strategy_name,
        report_title=title,
    )

    # 输出路径
    output_path = args.output
    if not output_path:
        input_stem = Path(args.input).stem
        output_path = os.path.join(os.path.dirname(args.input) or ".", f"{input_stem}_report.pdf")

    # 生成 PDF
    print(f"[export_report] 生成 PDF: {output_path}")
    doc = weasyprint.HTML(string=html_content)
    doc.write_pdf(output_path)
    print(f"[export_report] PDF 已生成: {output_path} ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
