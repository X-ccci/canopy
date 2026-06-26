"""
多渠道告警通知 — 飞书 Webhook + Telegram Bot + 微信 Server酱。

触发条件：熔断器跳闸、日亏损超限、策略异常退出。

配置（从 .env 读取）：
- FEISHU_WEBHOOK_URL      飞书机器人 Webhook 地址
- TELEGRAM_BOT_TOKEN      Telegram Bot Token
- TELEGRAM_CHAT_ID        Telegram 目标 Chat ID
- WECHAT_SCKEY            微信 Server酱 Sckey
"""
from __future__ import annotations

import json
import os
import urllib.request
import concurrent.futures
from datetime import datetime
from typing import Optional

# ── 环境变量 ──
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
WECHAT_SCKEY = os.environ.get("WECHAT_SCKEY", "")


# ══════════════════════════════════════════════════════════════════════
# 飞书 Webhook
# ══════════════════════════════════════════════════════════════════════

def _send_feishu_card(title: str, fields: list[tuple[str, str]], color: str = "red") -> bool:
    """发送飞书卡片消息。"""
    if not FEISHU_WEBHOOK_URL:
        return False

    field_items = [{"title": k, "content": v, "short": True} for k, v in fields]

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color,
            },
            "elements": [
                {"tag": "div", "fields": field_items},
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"Canopy Alert · {datetime.now().isoformat()}"}
                    ],
                },
            ],
        },
    }

    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            FEISHU_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200  # type: ignore[no-any-return]
    except Exception as e:
        print(f"[告警] 飞书发送失败: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
# Telegram Bot
# ══════════════════════════════════════════════════════════════════════

def _send_telegram(text: str) -> bool:
    """通过 Telegram Bot API 发送消息。"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return body.get("ok", False)
    except Exception as e:
        print(f"[告警] Telegram 发送失败: {e}")
        return False


def _format_telegram_message(title: str, fields: list[tuple[str, str]]) -> str:
    """格式化 Telegram Markdown 消息。"""
    lines = [f"*{title}*", ""]
    for k, v in fields:
        lines.append(f"• *{k}*: {v}")
    lines.extend(["", f"`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"])
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 微信 Server酱
# ══════════════════════════════════════════════════════════════════════

def _send_wechat(title: str, content: str) -> bool:
    """通过 Server酱 推送微信消息。"""
    if not WECHAT_SCKEY:
        return False

    url = f"https://sctapi.ftqq.com/{WECHAT_SCKEY}.send"
    payload = {
        "title": title,
        "desp": content,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return body.get("code") == 0
    except Exception as e:
        print(f"[告警] 微信推送失败: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
# 统一广播（三渠道并行推送）
# ══════════════════════════════════════════════════════════════════════

def _broadcast(
    title: str,
    fields: list[tuple[str, str]],
    color: str = "red",
) -> dict[str, bool]:
    """并行向飞书/Telegram/微信三渠道推送告警。

    Returns:
        {'feishu': bool, 'telegram': bool, 'wechat': bool}
    """
    results: dict[str, bool] = {"feishu": False, "telegram": False, "wechat": False}
    content_text = "\n".join(f"{k}: {v}" for k, v in fields)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}

        if FEISHU_WEBHOOK_URL:
            futures["feishu"] = executor.submit(_send_feishu_card, title, fields, color)

        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            tg_text = _format_telegram_message(title, fields)
            futures["telegram"] = executor.submit(_send_telegram, tg_text)

        if WECHAT_SCKEY:
            futures["wechat"] = executor.submit(_send_wechat, title, content_text)

        for key, future in futures.items():
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"[告警] 渠道 {key} 异常: {e}")

    return results


# ══════════════════════════════════════════════════════════════════════
# 公开 API（保持向后兼容）
# ══════════════════════════════════════════════════════════════════════

def circuit_breaker_tripped(reason: str, tripped_at: str | None = None) -> dict[str, bool]:
    """熔断器跳闸告警。"""
    return _broadcast(
        title="[熔断告警] Circuit Breaker Tripped",
        fields=[
            ("触发原因", reason),
            ("触发时间", tripped_at or datetime.now().isoformat()),
            ("状态", "所有交易已锁定"),
        ],
        color="red",
    )


def daily_loss_exceeded(loss_amount: float, limit_pct: float, current_balance: float) -> dict[str, bool]:
    """日亏损超限告警。"""
    return _broadcast(
        title="[风控告警] Daily Loss Exceeded",
        fields=[
            ("当日亏损", f"${loss_amount:,.2f}"),
            ("亏损比例", f"{limit_pct * 100:.1f}%"),
            ("当前余额", f"${current_balance:,.2f}"),
            ("触发时间", datetime.now().isoformat()),
        ],
        color="orange",
    )


def strategy_error(strategy_name: str, error_msg: str, extra: dict | None = None) -> dict[str, bool]:
    """策略异常退出告警。"""
    fields = [
        ("策略名称", strategy_name),
        ("错误信息", error_msg[:200]),
        ("异常时间", datetime.now().isoformat()),
    ]
    if extra:
        for k, v in extra.items():
            fields.append((k, str(v)[:200]))
    return _broadcast(
        title="[策略告警] Strategy Error",
        fields=fields,
        color="orange",
    )


def is_available() -> bool:
    """检查是否有任意告警渠道已配置。"""
    return bool(FEISHU_WEBHOOK_URL or TELEGRAM_BOT_TOKEN or WECHAT_SCKEY)


def get_available_channels() -> dict[str, bool]:
    """获取各渠道可用状态。"""
    return {
        "feishu": bool(FEISHU_WEBHOOK_URL),
        "telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "wechat": bool(WECHAT_SCKEY),
    }
