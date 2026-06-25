"""
飞书告警通知模块。通过 Webhook 机器人发送告警消息。
触发条件：熔断器跳闸、日亏损超限、策略异常退出。
"""
import json
import os
import urllib.request
from datetime import datetime

FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")


def _send_card(title: str, fields: list[tuple[str, str]], color: str = "red") -> bool:
    """发送飞书卡片消息"""
    if not FEISHU_WEBHOOK_URL:
        print(f"[告警] FEISHU_WEBHOOK_URL 未设置，跳过告警: {title}")
        return False

    field_items = [
        {"title": k, "content": v, "short": True}
        for k, v in fields
    ]

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": field_items
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"Canopy 告警 · {datetime.now().isoformat()}"}
                    ]
                }
            ]
        }
    }

    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            FEISHU_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200  # type: ignore[no-any-return]
    except Exception as e:
        print(f"[告警] 发送失败: {e}")
        return False


def circuit_breaker_tripped(reason: str, tripped_at: str | None = None) -> bool:
    """熔断器跳闸告警"""
    return _send_card(
        title="[熔断告警] 熔断器已跳闸",
        fields=[
            ("触发原因", reason),
            ("触发时间", tripped_at or datetime.now().isoformat()),
            ("状态", "所有交易已锁定")
        ],
        color="red"
    )


def daily_loss_exceeded(loss_amount: float, limit_pct: float, current_balance: float) -> bool:
    """日亏损超限告警"""
    return _send_card(
        title="[风控告警] 日亏损超限",
        fields=[
            ("当日亏损", f"${loss_amount:,.2f}"),
            ("亏损比例", f"{limit_pct * 100:.1f}%"),
            ("当前余额", f"${current_balance:,.2f}"),
            ("触发时间", datetime.now().isoformat())
        ],
        color="orange"
    )


def strategy_error(strategy_name: str, error_msg: str, extra: dict | None = None) -> bool:
    """策略异常退出告警"""
    fields = [
        ("策略名称", strategy_name),
        ("错误信息", error_msg[:200]),
        ("异常时间", datetime.now().isoformat())
    ]
    if extra:
        for k, v in extra.items():
            fields.append((k, str(v)[:200]))
    return _send_card(
        title="[策略告警] 策略异常",
        fields=fields,
        color="orange"
    )


def is_available() -> bool:
    """检查飞书 Webhook 是否已配置"""
    return bool(FEISHU_WEBHOOK_URL)
