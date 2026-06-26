"""
Canopy 链上存证 — 策略信号 SHA256 哈希 + 本地 proof_chain.json

可选：预留 Arweave / IPFS 上传接口。
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
PROOF_FILE = DATA_DIR / "proof_chain.json"


def _read_chain() -> list[dict[str, Any]]:
    """读取存证链。"""
    if not PROOF_FILE.exists():
        return []
    with open(PROOF_FILE) as f:
        return json.load(f)  # type: ignore[no-any-return]


def _write_chain(chain: list[dict[str, Any]]) -> None:
    """写入存证链。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROOF_FILE, "w") as f:
        json.dump(chain, f, indent=2)


def hash_signal(signal: dict[str, Any]) -> str:
    """
    对策略信号计算 SHA256 哈希。

    参数:
        signal: 信号字典，至少包含 symbol / action / price / timestamp。

    返回: 64 位 hex 哈希。
    """
    # 标准化字段顺序以保证确定性
    fields = sorted(signal.items())
    payload = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_proof(signal: dict[str, Any], strategy: str = "") -> dict[str, Any]:
    """
    记录一次策略信号存证。

    参数:
        signal: 信号字典。
        strategy: 策略名称。

    返回: 存证条目。
    """
    chain = _read_chain()
    sig_hash = hash_signal(signal)

    # 取上一块的哈希作为链式引用
    prev_hash = chain[-1]["hash"] if chain else "0" * 64

    entry: dict[str, Any] = {
        "index": len(chain),
        "timestamp": datetime.now().isoformat(),
        "unix_time": time.time(),
        "strategy": strategy,
        "signal_hash": sig_hash,
        "prev_hash": prev_hash,
        "signal_snapshot": {
            "symbol": signal.get("symbol", ""),
            "action": signal.get("action", ""),
            "price": signal.get("price", 0),
            "timestamp": signal.get("timestamp", ""),
        },
    }

    # 计算本块哈希
    block_payload = json.dumps(entry, sort_keys=True, default=str)
    entry["hash"] = hashlib.sha256(block_payload.encode("utf-8")).hexdigest()

    chain.append(entry)
    _write_chain(chain)

    return entry


def get_proof_history(limit: int = 50) -> list[dict[str, Any]]:
    """查看存证历史记录。"""
    chain = _read_chain()
    return chain[-limit:]


def verify_chain() -> dict[str, Any]:
    """
    验证存证链完整性。

    返回: {valid, total_blocks, broken_at (若断裂)}
    """
    chain = _read_chain()
    if not chain:
        return {"valid": True, "total_blocks": 0}

    for i, block in enumerate(chain):
        if i == 0:
            if block.get("prev_hash") != "0" * 64:
                return {"valid": False, "total_blocks": len(chain), "broken_at": 0, "reason": "Genesis prev_hash mismatch"}
            continue
        if block.get("prev_hash") != chain[i - 1].get("hash"):
            return {
                "valid": False,
                "total_blocks": len(chain),
                "broken_at": i,
                "reason": f"Block {i} prev_hash does not match block {i-1} hash",
            }

    return {"valid": True, "total_blocks": len(chain)}


# ── 预留：Arweave / IPFS 上传接口 ──

def upload_to_arweave(data: str) -> dict[str, Any]:
    """
    上传数据到 Arweave（预留接口，需配置 ARWEAVE_KEY）。
    """
    return {"success": False, "error": "Arweave upload not yet implemented", "tx_id": ""}


def upload_to_ipfs(data: str) -> dict[str, Any]:
    """
    上传数据到 IPFS（预留接口，需配置 IPFS_API）。
    """
    return {"success": False, "error": "IPFS upload not yet implemented", "cid": ""}
