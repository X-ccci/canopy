"""
Canopy 邮件日报 — SMTP 发送 HTML 日报

内容包括：持仓 / 盈亏 / 策略状态 / 风控摘要。
配置: SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / TO_EMAIL
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any


# ── 配置 ──

SMTP_HOST = os.environ.get("CANOPY_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("CANOPY_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("CANOPY_SMTP_USER", "")
SMTP_PASS = os.environ.get("CANOPY_SMTP_PASS", "")
TO_EMAIL = os.environ.get("CANOPY_TO_EMAIL", "")


def _build_html(
    date_str: str,
    kpi: dict[str, Any],
    strategies: list[dict[str, Any]],
    risk: dict[str, Any],
) -> str:
    """构建 HTML 邮件正文。"""

    # 策略表格行
    strategy_rows = ""
    for s in strategies:
        pnl_cls = "#22c55e" if s.get("pnl_pct", 0) >= 0 else "#ef4444"
        strategy_rows += f"""
        <tr>
            <td style="padding:6px 10px;">{s.get('name', '—')}</td>
            <td style="padding:6px 10px;">{s.get('pair', s.get('symbol', '—'))}</td>
            <td style="padding:6px 10px;color:{pnl_cls}">{s.get('pnl_pct', 0):+.2f}%</td>
            <td style="padding:6px 10px;">{s.get('status', '—')}</td>
        </tr>"""

    cb = risk.get("circuit_breaker", {})
    cb_status = "⚠️ 已触发" if cb.get("tripped") else "✅ 正常"

    return f"""
    <html>
    <head><style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
        h2 {{ color: #38bdf8; margin-top: 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #334155; color: #94a3b8; font-size: 12px; }}
        td {{ border-bottom: 1px solid #1e293b; }}
        .kpi {{ display: inline-block; min-width: 100px; text-align: center; padding: 12px 16px; }}
        .kpi-value {{ font-size: 24px; font-weight: 700; }}
        .kpi-label {{ font-size: 11px; color: #94a3b8; }}
        .green {{ color: #22c55e; }}
        .red {{ color: #ef4444; }}
    </style></head>
    <body>
        <h2>Canopy Daily Report — {date_str}</h2>

        <div class="card">
            <h3>Portfolio Summary</h3>
            <div class="kpi"><div class="kpi-label">Total Value</div><div class="kpi-value green">${kpi.get('total_value', 0):,.2f}</div></div>
            <div class="kpi"><div class="kpi-label">24h PnL</div><div class="kpi-value {'green' if kpi.get('pnl_24h', 0) >= 0 else 'red'}">${kpi.get('pnl_24h', 0):+,.2f}</div></div>
            <div class="kpi"><div class="kpi-label">Active Strategies</div><div class="kpi-value">{kpi.get('active_strategies', 0)}</div></div>
            <div class="kpi"><div class="kpi-label">30d Win Rate</div><div class="kpi-value">{kpi.get('win_rate', 0)}%</div></div>
        </div>

        <div class="card">
            <h3>Active Strategies</h3>
            <table>
                <thead><tr><th>Strategy</th><th>Pair</th><th>PnL</th><th>Status</th></tr></thead>
                <tbody>{strategy_rows}</tbody>
            </table>
        </div>

        <div class="card">
            <h3>Risk Summary</h3>
            <table>
                <tr><td style="padding:6px 10px">Circuit Breaker</td><td style="padding:6px 10px">{cb_status}</td></tr>
                <tr><td style="padding:6px 10px">Drawdown</td><td style="padding:6px 10px">{risk.get('drawdown_pct', 0):.2f}%</td></tr>
                <tr><td style="padding:6px 10px">Daily PnL</td><td style="padding:6px 10px">${risk.get('daily_pnl', 0):,.2f}</td></tr>
                <tr><td style="padding:6px 10px">Open Positions</td><td style="padding:6px 10px">{risk.get('open_positions', 0)}</td></tr>
                <tr><td style="padding:6px 10px">Total Exposure</td><td style="padding:6px 10px">{risk.get('total_exposure', 0)}%</td></tr>
            </table>
        </div>

        <p style="color:#64748b;font-size:11px;margin-top:24px;">Canopy Nature-Tech Terminal · Auto-generated at {datetime.now().isoformat()}</p>
    </body>
    </html>
    """


def send_daily_report(
    kpi: dict[str, Any] | None = None,
    strategies: list[dict[str, Any]] | None = None,
    risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    发送 HTML 日报邮件。

    参数:
        kpi: KPI 指标字典。
        strategies: 策略状态列表。
        risk: 风控状态字典。

    返回: {success, error}
    """
    if not SMTP_USER or not SMTP_PASS or not TO_EMAIL:
        return {"success": False, "error": "SMTP 配置不完整，请设置环境变量"}

    date_str = datetime.now().strftime("%Y-%m-%d %A")
    html = _build_html(
        date_str,
        kpi or {},
        strategies or [],
        risk or {},
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Canopy Daily Report — {date_str}"
    msg["From"] = SMTP_USER
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [TO_EMAIL], msg.as_string())
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
