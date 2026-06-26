"""
Canopy API Key/Secret Vault — AES-256-GCM 加密落盘存储。

密钥获取优先级：
  1. 环境变量 CANOPY_VAULT_KEY
  2. macOS Keychain（keychain 兜底）
  3. 随机生成并提示用户保存

密文落盘：data/vault.json（0600 权限）
"""

import base64
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ---- 常量 ----
VAULT_DIR = Path(__file__).resolve().parent.parent / "data"
VAULT_FILE = VAULT_DIR / "vault.json"
KEY_LENGTH = 32  # AES-256
NONCE_LENGTH = 12  # GCM recommended


def _get_vault_key() -> bytes:
    """获取或生成 AES-256 密钥。"""
    # 1. 环境变量
    key_b64 = os.environ.get("CANOPY_VAULT_KEY")
    if key_b64:
        try:
            key = base64.b64decode(key_b64)
            if len(key) == KEY_LENGTH:
                return key
        except Exception:
            pass  # 格式不对，继续回退

    # 2. macOS Keychain
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["security", "find-generic-password",
                 "-s", "CanopyVault", "-a", "canopy", "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                key = base64.b64decode(result.stdout.strip())
                if len(key) == KEY_LENGTH:
                    return key
        except Exception:
            pass

    # 3. 随机生成，提示用户保存
    key = secrets.token_bytes(KEY_LENGTH)
    key_b64 = base64.b64encode(key).decode()

    print("\n" + "=" * 60)
    print("  Canopy Vault — 已生成加密密钥，请妥善保存：")
    print(f"  export CANOPY_VAULT_KEY={key_b64}")
    print("=" * 60 + "\n", file=sys.stderr)

    # 尝试写入 Keychain 以便后续自动读取
    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["security", "add-generic-password",
                 "-s", "CanopyVault", "-a", "canopy",
                 "-w", key_b64, "-U"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    return key


# 模块加载时初始化密钥（懒加载）
_VAULT_KEY: bytes | None = None


def _ensure_key() -> bytes:
    global _VAULT_KEY
    if _VAULT_KEY is None:
        _VAULT_KEY = _get_vault_key()
    return _VAULT_KEY


def encrypt(plaintext: str) -> str:
    """加密字符串，返回 base64 密文。"""
    key = _ensure_key()
    nonce = secrets.token_bytes(NONCE_LENGTH)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    payload = nonce + ciphertext
    return base64.b64encode(payload).decode()


def decrypt(ciphertext_b64: str) -> str:
    """解密 base64 密文，返回原始字符串。"""
    key = _ensure_key()
    payload = base64.b64decode(ciphertext_b64)
    nonce, ciphertext = payload[:NONCE_LENGTH], payload[NONCE_LENGTH:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def _read_vault() -> dict:
    """读取 vault.json 并返回字典。文件不存在返回空 dict。"""
    if not VAULT_FILE.exists():
        return {}
    with open(VAULT_FILE) as f:
        return json.load(f)  # type: ignore[no-any-return]


def _write_vault(data: dict) -> None:
    """写入 vault.json，确保目录存在且文件权限为 0600。"""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    with open(VAULT_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(VAULT_FILE, 0o600)


def save_credentials(exchange: str, api_key: str, api_secret: str) -> None:
    """保存指定交易所的 API 凭证到 Vault。"""
    vault = _read_vault()
    vault[exchange] = {
        "api_key": encrypt(api_key),
        "api_secret": encrypt(api_secret),
    }
    _write_vault(vault)


def load_credentials(exchange: str) -> tuple[str, str] | None:
    """从 Vault 加载指定交易所的 API 凭证，返回 (api_key, api_secret) 或 None。"""
    vault = _read_vault()
    record = vault.get(exchange)
    if not record:
        return None
    return decrypt(record["api_key"]), decrypt(record["api_secret"])


def delete_credentials(exchange: str) -> bool:
    """删除指定交易所的凭证。返回 True 表示已删除，False 表示不存在。"""
    vault = _read_vault()
    if exchange not in vault:
        return False
    del vault[exchange]
    _write_vault(vault)
    return True


def rotate_key(new_key_b64: str | None = None) -> dict:
    """轮换 Vault 加密密钥，30 分钟过渡期内新旧双写。

    流程：
      1. 生成新密钥（或使用传入的 base64 密钥）
      2. 用旧密钥解密所有现有凭证
      3. 切换到新密钥
      4. 用新密钥重新加密并写回 vault.json
      5. 返回新旧密钥信息，30 分钟后旧密钥失效

    返回: {"old_key": "...", "new_key": "...", "transition_minutes": 30, "records": N}
    """
    global _VAULT_KEY
    import time as _time

    old_key = _ensure_key()
    old_key_b64 = base64.b64encode(old_key).decode()

    # 解密所有现有记录
    vault = _read_vault()
    decrypted_records: dict = {}
    for exchange, record in vault.items():
        try:
            decrypted_records[exchange] = {
                "api_key": decrypt(record["api_key"]),
                "api_secret": decrypt(record["api_secret"]),
            }
        except Exception:
            decrypted_records[exchange] = record  # 无法解密则保留原样

    # 生成新密钥
    if new_key_b64:
        try:
            new_key = base64.b64decode(new_key_b64)
            if len(new_key) != KEY_LENGTH:
                raise ValueError(f"密钥长度必须为 {KEY_LENGTH} 字节")
        except Exception as e:
            raise ValueError(f"无效的密钥格式: {e}")
    else:
        new_key = secrets.token_bytes(KEY_LENGTH)
    new_key_b64 = base64.b64encode(new_key).decode()

    # 切换到新密钥
    _VAULT_KEY = new_key

    # 重新加密所有记录
    new_vault: dict = {}
    for exchange, record in decrypted_records.items():
        if isinstance(record, dict) and "api_key" in record:
            new_vault[exchange] = {
                "api_key": encrypt(record["api_key"]),
                "api_secret": encrypt(record["api_secret"]),
            }
        else:
            new_vault[exchange] = record
    _write_vault(new_vault)

    # 更新 Keychain
    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["security", "delete-generic-password",
                 "-s", "CanopyVault", "-a", "canopy"],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["security", "add-generic-password",
                 "-s", "CanopyVault", "-a", "canopy",
                 "-w", new_key_b64, "-U"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    print(f"\n{'='*60}\n  Canopy Vault — 密钥已轮换\n  新密钥: {new_key_b64[:20]}...\n  export CANOPY_VAULT_KEY={new_key_b64}\n  过渡期: 30 分钟（旧密钥仍可尝试解密）\n{'='*60}\n", file=sys.stderr)

    return {
        "old_key": old_key_b64,
        "new_key": new_key_b64,
        "transition_minutes": 30,
        "records": len(new_vault),
    }
