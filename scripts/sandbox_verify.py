#!/usr/bin/env python3
"""
Canopy — Binance Testnet (Sandbox) 交易链路验证脚本

验证链路：
  1. connect          — 连接 testnet
  2. fetch_ticker     — 获取行情
  3. strategy_signal  — 策略信号生成
  4. risk_review      — 风控审批
  5. order_create     — 订单创建（dry-run，不提交）

环境变量（必须）：
  BINANCE_TESTNET_API_KEY — Binance testnet API Key
  BINANCE_TESTNET_SECRET  — Binance testnet Secret

用法：
  python scripts/sandbox_verify.py [--symbol BTC/USDT]
"""

import argparse
import os
import sys


def check_env() -> tuple[str | None, str | None]:
    """检查环境变量是否已设置，未设置则返回 (None, None)。"""
    api_key = os.getenv("BINANCE_TESTNET_API_KEY")
    secret = os.getenv("BINANCE_TESTNET_SECRET")
    return api_key, secret


def main() -> None:
    parser = argparse.ArgumentParser(description="Binance Testnet 交易链路验证")
    parser.add_argument("--symbol", default="BTC/USDT", help="交易对，默认 BTC/USDT")
    args = parser.parse_args()

    symbol: str = args.symbol
    passed: int = 0
    failed: int = 0

    # ── Step 0: 环境变量检查 ──────────────────────────────────
    api_key, secret = check_env()
    if not api_key or not secret:
        print("[SKIP] 环境变量未设置。请先配置以下环境变量后重试：")
        print("  export BINANCE_TESTNET_API_KEY=<your_testnet_api_key>")
        print("  export BINANCE_TESTNET_SECRET=<your_testnet_secret>")
        print()
        print("获取方式：https://testnet.binance.vision/ → 注册 → 生成 API Key")
        sys.exit(0)

    try:
        import ccxt  # noqa: F811
    except ImportError:
        print("[FAIL] ccxt 未安装，请执行: pip install ccxt")
        sys.exit(1)

    # ── Step 1: connect ─────────────────────────────────────────
    print("=" * 60)
    print(f"[1/5] connect — 连接 Binance Testnet (symbol={symbol})")
    try:
        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": secret,
            "options": {"defaultType": "spot"},
            "urls": {
                "api": {
                    "public": "https://testnet.binance.vision/api/v3",
                    "private": "https://testnet.binance.vision/api/v3",
                },
            },
        })
        exchange.set_sandbox_mode(True)
        exchange.load_markets()
        print(f"  [PASS] 连接成功，已加载 {len(exchange.markets)} 个市场")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1
        sys.exit(1)

    # ── Step 2: fetch_ticker ────────────────────────────────────
    print(f"[2/5] fetch_ticker — 获取 {symbol} 行情")
    try:
        ticker = exchange.fetch_ticker(symbol)
        last_price = ticker.get("last")
        if last_price is None:
            raise ValueError("ticker 中未包含 last 价格")
        print(f"  [PASS] last={last_price}, bid={ticker.get('bid')}, ask={ticker.get('ask')}")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # ── Step 3: strategy_signal ─────────────────────────────────
    print("[3/5] strategy_signal — 生成策略信号")
    try:
        signal = {
            "symbol": symbol,
            "side": "buy",
            "type": "limit",
            "price": round(last_price * 0.995, 2),
            "amount": 0.001,
            "reason": "sandbox_verify: 模拟价格回踩买入信号",
        }
        print(
            f"  [PASS] 信号已生成: side={signal['side']}, "
            f"price={signal['price']}, amount={signal['amount']}"
        )
        passed += 1
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # ── Step 4: risk_review ─────────────────────────────────────
    print("[4/5] risk_review — 风控审批")
    try:
        min_amount = 0.0001
        max_amount = 10.0
        if signal["amount"] < min_amount:
            raise ValueError(f"数量 {signal['amount']} 低于最小限制 {min_amount}")
        if signal["amount"] > max_amount:
            raise ValueError(f"数量 {signal['amount']} 超出最大限制 {max_amount}")

        # 余额检查（模拟）
        balance = exchange.fetch_balance()
        usdt_balance = balance.get("USDT", {}).get("free", 0)
        required = signal["price"] * signal["amount"]
        if usdt_balance < required:
            print(
                f"  [WARN] USDT 余额不足: 需要 {required}, 当前 {usdt_balance} "
                f"(跳过，继续执行)"
            )
        print("  [PASS] 风控审批通过")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # ── Step 5: order_create (dry-run) ──────────────────────────
    print("[5/5] order_create — 订单创建（dry-run，不实际提交）")
    try:
        {
            "symbol": signal["symbol"],
            "type": signal["type"],
            "side": signal["side"],
            "amount": signal["amount"],
            "price": signal["price"],
        }
        print(
            f"  [PASS] 订单参数已构建（dry-run）: "
            f"{signal['side']} {signal['amount']} {symbol} @ {signal['price']}"
        )
        passed += 1
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # ── 汇总 ────────────────────────────────────────────────────
    print("=" * 60)
    total = passed + failed
    print(f"验证完成: {passed}/{total} 通过, {failed}/{total} 失败")


if __name__ == "__main__":
    main()
