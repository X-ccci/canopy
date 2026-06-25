"""
download_historical.py — 从 Binance 公开 API 拉取历史 K 线数据并缓存为 Parquet。

用法：
    python scripts/download_historical.py

可修改下方 SYMBOLS / TIMEFRAME / LIMIT 变量调整拉取范围。
"""

import os
import time
from pathlib import Path

import pandas as pd
import requests

# ── 配置 ──
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "DOT/USDT", "MATIC/USDT", "LINK/USDT",
]
TIMEFRAME = "1h"
LIMIT = 1000  # 每交易对最多拉取根数
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"
BINANCE_REST = "https://api.binance.com/api/v3/klines"


def fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """从 Binance 公开 API 获取 K 线数据。"""
    # Binance symbol 格式为 BTCUSDT（无 /）
    binance_sym = symbol.replace("/", "")
    params = {
        "symbol": binance_sym,
        "interval": interval,
        "limit": limit,
    }
    resp = requests.get(BINANCE_REST, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for k in data:
        rows.append({
            "timestamp": pd.Timestamp(k[0], unit="ms"),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return pd.DataFrame(rows)


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    for sym in SYMBOLS:
        print(f"拉取 {sym} ...", end=" ", flush=True)
        try:
            df = fetch_klines(sym, TIMEFRAME, LIMIT)
        except Exception as e:
            print(f"失败: {e}")
            continue

        safe_name = sym.replace("/", "_")
        path = CACHE_DIR / f"{safe_name}_1h.parquet"
        df.to_parquet(path, index=False)
        print(f"OK ({len(df)} 条 → {path})")
        total += len(df)

        # 遵守速率限制
        time.sleep(0.5)

    print(f"\n总计缓存 {total} 条 K 线到 {CACHE_DIR}")


if __name__ == "__main__":
    main()
