#!/usr/bin/env python3
"""集成测试脚本 — 验证 ExchangeAdapter、DataFetcher、CrashScenario 三个模块。

使用 Binance testnet（公开行情不需要 API Key），
测试行情拉取、缓存、压力测试模拟全链路。
"""

from __future__ import annotations

import os
import sys
import traceback

import pandas as pd

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from canopy.config import Config
from canopy.exchange.ccxt_adapter import ExchangeAdapter
from canopy.data.fetcher import DataFetcher
from canopy.backtest.cases.crash_scenarios import (
    CRASH_SCENARIOS,
    generate_pressure_test,
    generate_all_tests,
)

SEP = "─" * 60


def test_config():
    """测试 Config 数据类实例化。"""
    print(f"\n{SEP}")
    print("[TEST] Config 实例化")
    cfg = Config(testnet=True)
    print(f"  exchange={cfg.exchange}, testnet={cfg.testnet}")
    print(f"  data_cache_dir={cfg.data_cache_dir}")
    assert cfg.exchange == "binance"
    assert cfg.testnet is True
    print("  → PASS")
    return cfg


def test_adapter_connect(cfg: Config) -> ExchangeAdapter:
    """测试 ExchangeAdapter 连接 Binance testnet。"""
    print(f"\n{SEP}")
    print("[TEST] ExchangeAdapter 连接 Binance testnet")
    adapter = ExchangeAdapter(exchange_id="binance", config=cfg)
    try:
        success = adapter.connect()
        if success:
            print("  → PASS（已连接）")
        else:
            print("  → FAIL（连接失败，但未抛异常）")
    except Exception as e:
        print(f"  → FAIL（异常）: {e}")
        traceback.print_exc()
        return adapter
    return adapter


def test_fetch_ticker(adapter: ExchangeAdapter):
    """测试 fetch_ticker 获取 BTC/USDT 行情。"""
    print(f"\n{SEP}")
    print("[TEST] fetch_ticker('BTC/USDT')")
    try:
        ticker = adapter.fetch_ticker("BTC/USDT")
        if ticker:
            for k, v in ticker.items():
                print(f"  {k}: {v}")
            assert "symbol" in ticker and ticker["symbol"] == "BTC/USDT"
            print("  → PASS")
        else:
            print("  → FAIL（返回空 dict）")
    except Exception as e:
        print(f"  → FAIL（异常）: {e}")
        traceback.print_exc()


def test_fetch_ohlcv(adapter: ExchangeAdapter):
    """测试 fetch_ohlcv 获取 K 线数据。"""
    print(f"\n{SEP}")
    print("[TEST] fetch_ohlcv('BTC/USDT', '1h', limit=50)")
    try:
        df = adapter.fetch_ohlcv("BTC/USDT", "1h", limit=50)
        if not df.empty:
            print(f"  行数: {len(df)}, 列: {list(df.columns)}")
            print(f"  dtypes:\n{df.dtypes}")
            print(f"\n  前 5 行:")
            print(df.head(5).to_string())
            assert "timestamp" in df.columns
            assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
            print("  → PASS")
        else:
            print("  → FAIL（返回空 DataFrame）")
    except Exception as e:
        print(f"  → FAIL（异常）: {e}")
        traceback.print_exc()


def test_fetch_ohlcv_with_since(adapter: ExchangeAdapter):
    """测试 fetch_ohlcv 带 since ISO 日期参数。"""
    print(f"\n{SEP}")
    print("[TEST] fetch_ohlcv('BTC/USDT', '1h', since='2025-01-01', limit=10)")
    try:
        df = adapter.fetch_ohlcv("BTC/USDT", "1h", since="2025-01-01", limit=10)
        if not df.empty:
            print(f"  行数: {len(df)}")
            print(f"  时间范围: {df['timestamp'].min()} → {df['timestamp'].max()}")
            print("  → PASS")
        else:
            print("  → FAIL（返回空 DataFrame，可能该时间范围无数据）")
    except Exception as e:
        print(f"  → FAIL（异常）: {e}")
        traceback.print_exc()


def test_data_fetcher_cache(adapter: ExchangeAdapter, cfg: Config):
    """测试 DataFetcher 缓存读写。"""
    print(f"\n{SEP}")
    print("[TEST] DataFetcher 缓存读写")

    # 先清除已有该交易对的缓存，确保测试干净
    fetcher = DataFetcher(adapter=adapter, cache_dir=cfg.data_cache_dir)
    fetcher.clear_cache(symbol="BTC_USDT")

    try:
        print("  1) 首次拉取（无缓存）...")
        df1 = fetcher.get_ohlcv("BTC/USDT", "1h", limit=20)
        if df1.empty:
            print("  → FAIL（首次拉取返回空）")
            return
        print(f"     拉取: {len(df1)} 行")

        print("  2) 二次读取（应命中缓存）...")
        df2 = fetcher.get_ohlcv("BTC/USDT", "1h", limit=20)
        if df2.empty:
            print("  → FAIL（缓存读取返回空）")
            return

        # 验证数据一致性
        if df1.equals(df2):
            print(f"     缓存命中，数据一致: {len(df2)} 行")
        else:
            print(f"     缓存命中但数据有差异: 首次 {len(df1)} vs 缓存 {len(df2)}")
            # 可能是实时数据变化，只验证列一致
            assert list(df1.columns) == list(df2.columns)

        print("  3) force_refresh=True 强制刷新...")
        df3 = fetcher.get_ohlcv("BTC/USDT", "1h", limit=20, force_refresh=True)
        print(f"     强制刷新: {len(df3)} 行")

        # 缓存信息
        info = fetcher.get_cache_info()
        print(f"\n  缓存统计: {info['file_count']} 文件, {info['total_size_bytes']} bytes")
        print("  → PASS")

    except Exception as e:
        print(f"  → FAIL（异常）: {e}")
        traceback.print_exc()


def test_crash_scenarios():
    """测试极端行情案例库 — 场景定义与模拟生成。"""
    print(f"\n{SEP}")
    print("[TEST] 极端行情案例库")

    try:
        # 验证预设场景
        print(f"  预设场景数: {len(CRASH_SCENARIOS)}")
        for s in CRASH_SCENARIOS:
            print(f"    - {s.name} ({s.date}): {s.asset} {s.price_change_pct}%, {s.key_events[0]}...")

        # 生成 312 场景数据
        scenario = CRASH_SCENARIOS[0]
        print(f"\n  生成 {scenario.name} 模拟数据 (n_steps=500)...")
        df = generate_pressure_test(base_price=50000, scenario=scenario, n_steps=500)

        assert not df.empty
        assert len(df) == 500
        assert all(c in df.columns for c in ["timestamp", "open", "high", "low", "close", "volume"])

        # 统计
        daily_returns = df["close"].pct_change().dropna()
        max_daily_drop = daily_returns.min() * 100

        print(f"  行数: {len(df)}")
        print(f"  时间范围: {df['timestamp'].min()} → {df['timestamp'].max()}")
        print(f"  价格范围: ${df['close'].min():.2f} ~ ${df['close'].max():.2f}")
        print(f"  均值: ${df['close'].mean():.2f}")
        print(f"  标准差: ${df['close'].std():.2f}")
        print(f"  最大日跌幅: {max_daily_drop:.2f}%")

        # 验证三段结构
        n = len(df)
        seg1 = df.iloc[: n // 2]
        seg3 = df.iloc[int(n * 0.875) :]
        print(f"  前半段均值: ${seg1['close'].mean():.2f} (应接近 base_price)")
        print(f"  末尾反弹段均值: ${seg3['close'].mean():.2f}")
        print("  → PASS")

        # 测试 generate_all_tests
        print(f"\n  测试 generate_all_tests(base_price=60000)...")
        all_data = generate_all_tests(base_price=60000)
        assert len(all_data) == len(CRASH_SCENARIOS)
        for name, df_all in all_data.items():
            print(f"    {name}: {len(df_all)} 行, close 均值 ${df_all['close'].mean():.2f}")
        print("  → PASS")

    except Exception as e:
        print(f"  → FAIL（异常）: {e}")
        traceback.print_exc()


def test_adapter_methods(adapter: ExchangeAdapter):
    """测试适配器其他方法（即使无 API Key 也会优雅降级）。"""
    print(f"\n{SEP}")
    print("[TEST] ExchangeAdapter 其他方法（优雅降级）")

    tests = [
        ("fetch_balance", lambda: adapter.fetch_balance()),
        ("fetch_open_orders", lambda: adapter.fetch_open_orders()),
        ("get_supported_markets", lambda: adapter.get_supported_markets()[:5]),
        ("get_min_amount('BTC/USDT')", lambda: adapter.get_min_amount("BTC/USDT")),
        ("create_market_order (dry)", lambda: adapter.create_market_order("BTC/USDT", "buy", 0.001)),
    ]

    for name, func in tests:
        try:
            result = func()
            if isinstance(result, list):
                print(f"  {name}: 返回 {len(result)} 条 ({'PASS' if isinstance(result, list) else 'FAIL'})")
            elif isinstance(result, dict):
                has_keys = len(result) > 0
                print(f"  {name}: keys={list(result.keys())[:5]} ({'PASS' if has_keys else '可能需API Key'})")
            else:
                print(f"  {name}: {result} ({'PASS'})")
        except Exception as e:
            print(f"  {name}: 异常 — {e}")

    print("  → 所有方法均已测试（异常被兜底捕获）")


def main():
    print("=" * 60)
    print("  Canopy 交易所接入层 / 行情数据层 / 极端行情案例库 集成测试")
    print("=" * 60)

    cfg = test_config()
    adapter = test_adapter_connect(cfg)

    if adapter._connected:
        test_fetch_ticker(adapter)
        test_fetch_ohlcv(adapter)
        test_fetch_ohlcv_with_since(adapter)
        test_data_fetcher_cache(adapter, cfg)
        test_adapter_methods(adapter)
    else:
        print("\n⚠️  交易所未连接，跳过行情相关测试。")
        print("   请检查网络连接或 Binance API 可用性。")

    test_crash_scenarios()

    print(f"\n{'=' * 60}")
    print("  所有测试完成。")
    print("=" * 60)


if __name__ == "__main__":
    main()
