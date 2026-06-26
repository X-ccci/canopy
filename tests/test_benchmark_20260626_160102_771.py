"""
Canopy 性能压测 — 1000 策略并发回测 + WS 万级消息吞吐

输出 CSV 性能报告到 benchmark_results.csv。
"""

from __future__ import annotations

import csv
import random
import time
from datetime import datetime
from pathlib import Path

import numpy as np


def generate_ohlcv(n_bars: int = 500) -> np.ndarray:
    """生成模拟 OHLCV 数据。"""
    np.random.seed(42)
    closes = 50000 + np.cumsum(np.random.randn(n_bars) * 200)
    highs = closes + np.abs(np.random.randn(n_bars) * 100)
    lows = closes - np.abs(np.random.randn(n_bars) * 100)
    opens = closes - np.random.randn(n_bars) * 50
    volumes = np.abs(np.random.randn(n_bars) * 1000) + 500
    return np.column_stack([opens, highs, lows, closes, volumes])


def simple_macd_strategy(closes: np.ndarray) -> list[int]:
    """简化 MACD 交叉策略。"""
    signals = np.zeros(len(closes), dtype=int)
    ema_fast = np.zeros(len(closes))
    ema_slow = np.zeros(len(closes))
    alpha_f = 2 / 13
    alpha_s = 2 / 27

    ema_fast[0] = closes[0]
    ema_slow[0] = closes[0]
    for i in range(1, len(closes)):
        ema_fast[i] = alpha_f * closes[i] + (1 - alpha_f) * ema_fast[i - 1]
        ema_slow[i] = alpha_s * closes[i] + (1 - alpha_s) * ema_slow[i - 1]
        if ema_fast[i] > ema_slow[i] and ema_fast[i - 1] <= ema_slow[i - 1]:
            signals[i] = 1
        elif ema_fast[i] < ema_slow[i] and ema_fast[i - 1] >= ema_slow[i - 1]:
            signals[i] = -1
    return signals.tolist()


def benchmark_backtest(n_strategies: int = 1000, n_bars: int = 500) -> dict:
    """1000 策略并发回测计时。"""
    print(f"\n--- Backtest Benchmark: {n_strategies} strategies x {n_bars} bars ---")

    ohlcv = generate_ohlcv(n_bars)
    closes = ohlcv[:, 3]

    start = time.perf_counter()
    for _ in range(n_strategies):
        simple_macd_strategy(closes)
    elapsed = time.perf_counter() - start

    throughput = n_strategies / elapsed
    total_bars_processed = n_strategies * n_bars

    print(f"  Elapsed: {elapsed:.3f}s")
    print(f"  Throughput: {throughput:.1f} strategies/s")
    print(f"  Total bars: {total_bars_processed:,}")

    return {
        "benchmark": "backtest_concurrency",
        "n_strategies": n_strategies,
        "n_bars": n_bars,
        "elapsed_s": round(elapsed, 4),
        "throughput_strat_per_s": round(throughput, 1),
        "total_bars": total_bars_processed,
        "bars_per_s": round(total_bars_processed / elapsed, 1),
    }


def benchmark_ws_messages(n_messages: int = 10000, payload_size: int = 256) -> dict:
    """WS 消息吞吐测试（模拟 JSON 序列化/反序列化）。"""
    print(f"\n--- WS Throughput Benchmark: {n_messages} messages ---")

    import json
    payload = {
        "ts": time.time(),
        "ticker": {
            f"SYM_{i}": {
                "bid": round(random.uniform(100, 50000), 2),
                "ask": round(random.uniform(100, 50000), 2),
                "last": round(random.uniform(100, 50000), 2),
                "volume": round(random.uniform(1000, 1000000), 2),
            }
            for i in range(5)
        },
    }
    # 填充到目标大小
    while len(json.dumps(payload)) < payload_size:
        payload[f"pad_{len(payload)}"] = "x" * 20

    serialized = json.dumps(payload)

    start = time.perf_counter()
    for _ in range(n_messages):
        msg = json.dumps(payload)
        _ = json.loads(msg)
    elapsed = time.perf_counter() - start

    throughput = n_messages / elapsed
    data_rate = (len(serialized) * 2 * n_messages) / elapsed / 1024 / 1024  # MB/s

    print(f"  Elapsed: {elapsed:.3f}s")
    print(f"  Throughput: {throughput:.0f} msg/s")
    print(f"  Data rate: {data_rate:.2f} MB/s")

    return {
        "benchmark": "ws_throughput",
        "n_messages": n_messages,
        "payload_bytes": len(serialized),
        "elapsed_s": round(elapsed, 4),
        "throughput_msg_per_s": round(throughput, 0),
        "data_rate_mb_per_s": round(data_rate, 2),
    }


def benchmark_latency(n_iterations: int = 10000) -> dict:
    """延迟基准测试：订单创建 + 风控审批。"""
    print(f"\n--- Latency Benchmark: {n_iterations} iterations ---")

    latencies = []
    for _ in range(n_iterations):
        t0 = time.perf_counter()
        # 模拟：信号生成 + 风险检查 + 订单构建
        rsi = 50 + np.random.randn() * 10
        price = 50000 + np.random.randn() * 500
        approved = rsi < 30 or rsi > 70
        if approved:
            _ = {"symbol": "BTC/USDT", "action": "BUY", "price": price, "qty": 0.01}
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)  # ms

    avg = np.mean(latencies)
    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)

    print(f"  Avg: {avg:.3f}ms | P50: {p50:.3f}ms | P95: {p95:.3f}ms | P99: {p99:.3f}ms")

    return {
        "benchmark": "latency",
        "n_iterations": n_iterations,
        "avg_ms": round(avg, 3),
        "p50_ms": round(p50, 3),
        "p95_ms": round(p95, 3),
        "p99_ms": round(p99, 3),
    }


def run_all_benchmarks(output_path: str = "benchmark_results.csv") -> list[dict]:
    """运行所有压测并输出 CSV 报告。"""
    results = []
    results.append(benchmark_backtest(1000, 500))
    results.append(benchmark_ws_messages(10000))
    results.append(benchmark_latency(10000))

    # 写入 CSV
    if results:
        keys = list(results[0].keys())
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp"] + keys)
            for r in results:
                writer.writerow([datetime.now().isoformat()] + [r.get(k, "") for k in keys])
        print(f"\nReport saved to {output_path}")

    return results


if __name__ == "__main__":
    run_all_benchmarks()
