"""
Canopy CCXT 交易所适配层。

connect() 时优先从 Vault 读取 API 密钥，
Vault 无记录则回退到环境变量。
"""

import os

import ccxt

from canopy.config import vault_enabled  # type: ignore[attr-defined]


def connect(exchange: str) -> ccxt.Exchange:
    """
    连接到指定交易所。

    密钥获取优先级：
      1. Vault（data/vault.json）— 需 vault_enabled=True
      2. 环境变量 {EXCHANGE}_API_KEY / {EXCHANGE}_API_SECRET
    """
    exchange_cls = getattr(ccxt, exchange, None)
    if exchange_cls is None:
        raise ValueError(f"不支持的交易所: {exchange}")

    api_key: str | None = None
    api_secret: str | None = None

    # 1. 尝试从 Vault 读取
    if vault_enabled:
        try:
            from canopy.utils.vault import load_credentials

            creds = load_credentials(exchange)
            if creds:
                api_key, api_secret = creds
        except Exception:
            pass  # Vault 不可用时静默回退

    # 2. 回退到环境变量
    if not api_key or not api_secret:
        key_env = f"{exchange.upper()}_API_KEY"
        secret_env = f"{exchange.upper()}_API_SECRET"
        api_key = os.environ.get(key_env, "")
        api_secret = os.environ.get(secret_env, "")

    if not api_key or not api_secret:
        raise ValueError(
            f"未找到 {exchange} 的 API 凭证。"
            f"请设置环境变量 {exchange.upper()}_API_KEY / {exchange.upper()}_API_SECRET，"
            f"或使用 canopy.utils.vault.save_credentials() 保存到 Vault。"
        )

    return exchange_cls({"apiKey": api_key, "secret": api_secret})
