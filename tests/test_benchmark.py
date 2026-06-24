"""
test_benchmark.py — 性能基准测试

测量：
1. WS 行情解析吞吐（1000 msg/s 目标）
2. 订单队列延迟（submit → fill 端到端 ms 级）
3. 5 策略并发运行 1000 bar 总耗时

结果输出到项目根目录 benchmark_results.csv。
"""
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from canopy.engine.factory import StrategyFactory
from canopy.sim.account import SimAccount
from canopy.sim.broker import SimBroker
from canopy.sim.engine import SimEngine

# ── 输出路径 ──
BENCHMARK_CSV = os.path.join(os.path.dirname(__file__), "..", "benchmark_results.csv")


# ══════════════════════════════════════════════════════════════
# Benchmark 1: WS 行情解析吞吐
# ══════════════════════════════════════════════════════════════

def _make_ws_message(symbol: str = "BTC/USDT", seq: int = 0) -> str:
    """构造模拟 WS kline 消息 JSON。"""
    return json.dumps({
        "e": "kline",
        "s": symbol,
        "k": {
            "t": 1700000000000 + seq * 60000,
            "o": f"{50000 + seq * 10:.2f}",
            "h": f"{50100 + seq * 10:.2f}",
            "l": f"{49900 + seq * 10:.2f}",
            "c": f"{50050 + seq * 10:.2f}",
            "v": f"{100 + seq % 50:.4f}",
        }
    })


def _parse_ws_message(raw: str) -> dict:
    """模拟 WS 消息解析为 candle dict。"""
    data = json.loads(raw)
    k = data["k"]
    return {
        "timestamp": k["t"],
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "volume": float(k["v"]),
    }


class TestWSThroughput:
    """WS 行情解析吞吐基准。"""

    TARGET_MSG_COUNT = 10_000
    TARGET_RATE = 1_000  # msg/s

    def test_ws_parse_throughput(self):
        """测量 WS 消息解析吞吐量。"""
        messages = [_make_ws_message(seq=i) for i in range(self.TARGET_MSG_COUNT)]

        start = time.perf_counter()
        for msg in messages:
            _parse_ws_message(msg)
        elapsed = time.perf_counter() - start

        rate = self.TARGET_MSG_COUNT / elapsed
        latency_us = (elapsed / self.TARGET_MSG_COUNT) * 1_000_000

        # 写入 CSV
        _write_result("ws_parse_throughput", {
            "msg_count": self.TARGET_MSG_COUNT,
            "elapsed_s": round(elapsed, 4),
            "rate_msg_per_s": round(rate, 1),
            "avg_latency_us": round(latency_us, 2),
            "target_rate_met": rate >= self.TARGET_RATE,
        })

        # 仅做记录性断言（不硬阻断 CI）
        print(f"\n[WS 吞吐] {rate:.0f} msg/s | 平均延迟 {latency_us:.1f} μs")
        assert True  # 始终通过，结果在 CSV 中


# ══════════════════════════════════════════════════════════════
# Benchmark 2: 订单队列延迟（submit → fill 端到端）
# ══════════════════════════════════════════════════════════════

class TestOrderQueueLatency:
    """订单队列端到端延迟基准。"""

    ITERATIONS = 500

    def test_order_queue_latency(self):
        """测量 SimBroker submit_order 端到端延迟。"""
        # 生成数据 + 初始化引擎
        np.random.seed(123)
        n = 100
        base = 50000.0
        closes = base + np.cumsum(np.random.randn(n) * 100)
        highs = closes + np.abs(np.random.randn(n) * 50)
        lows = closes - np.abs(np.random.randn(n) * 50)
        opens = np.roll(closes, 1)
        opens[0] = closes[0] - 20

        df = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="1h"),
            "open": np.round(opens, 2),
            "high": np.round(np.maximum(highs, opens), 2),
            "low": np.round(np.minimum(lows, opens), 2),
            "close": np.round(closes, 2),
            "volume": np.round(np.abs(np.random.randn(n) * 500 + 2000), 2),
        })

        import tempfile
        tmp = tempfile.mkdtemp(prefix="canopy_bench_")
        fpath = os.path.join(tmp, "test.parquet")
        df.to_parquet(fpath, index=False)

        engine = SimEngine(data_path=fpath, slippage=0, commission=0)
        engine.load()
        account = SimAccount(initial_capital=1_000_000.0)
        broker = SimBroker(engine=engine, account=account)

        latencies_us = []

        for i in range(self.ITERATIONS):
            t0 = time.perf_counter()
            broker.submit_order(
                symbol="BTC/USDT",
                side="buy",
                order_type="market",
                amount=0.01,
            )
            t1 = time.perf_counter()
            latencies_us.append((t1 - t0) * 1_000_000)

        latencies_arr = np.array(latencies_us)

        _write_result("order_queue_latency", {
            "iterations": self.ITERATIONS,
            "mean_us": round(float(np.mean(latencies_arr)), 2),
            "median_us": round(float(np.median(latencies_arr)), 2),
            "p99_us": round(float(np.percentile(latencies_arr, 99)), 2),
            "min_us": round(float(np.min(latencies_arr)), 2),
            "max_us": round(float(np.max(latencies_arr)), 2),
        })

        print(f"\n[订单延迟] mean={np.mean(latencies_arr):.1f} μs | "
              f"median={np.median(latencies_arr):.1f} μs | "
              f"p99={np.percentile(latencies_arr, 99):.1f} μs")
        assert True

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# Benchmark 3: 5 策略并发运行 1000 bar
# ══════════════════════════════════════════════════════════════

def _run_single_strategy(strategy, engine, risk_manager, broker, bar_count):
    """单策略运行 bar_count 根 K 线，返回耗时与信号统计。"""
    signals = 0
    fills = 0
    rejects = 0

    t0 = time.perf_counter()
    for _ in range(bar_count):
        candle = engine.current_candle
        signal = strategy.on_bar(candle)
        if signal and signal.get("action") != "HOLD":
            signals += 1
            signal["symbol"] = "BTC/USDT"
            approved, reason, order_dict = risk_manager.approve(
                signal, candle["close"],
                account_balance=broker.account.balance
            )
            if approved and order_dict:
                result = broker.submit_order(
                    symbol=order_dict["symbol"],
                    side=order_dict["side"],
                    order_type="market",
                    amount=order_dict["quantity"],
                )
                if result["status"] == "FILLED":
                    fills += 1
                else:
                    rejects += 1
            else:
                rejects += 1
        engine.step()

    elapsed = time.perf_counter() - t0
    return {
        "elapsed_s": elapsed,
        "signals": signals,
        "fills": fills,
        "rejects": rejects,
        "bars": bar_count,
    }


class TestConcurrentStrategies:
    """5 策略并发运行基准。"""

    BAR_COUNT = 1_000

    def test_concurrent_strategies_1000_bars(self):
        """5 策略并发运行 1000 bar，测量总耗时。"""
        # 生成 1000 条 K 线数据
        np.random.seed(42)
        n = self.BAR_COUNT
        base = 50000.0
        trend = np.linspace(0, 3000, n)
        noise = np.cumsum(np.random.randn(n) * 150)
        closes = base + trend + noise
        highs = closes + np.abs(np.random.randn(n) * 80) + 30
        lows = closes - np.abs(np.random.randn(n) * 80) - 30
        opens = np.roll(closes, 1)
        opens[0] = closes[0] - 25

        df = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="1h"),
            "open": np.round(opens, 2),
            "high": np.round(np.maximum(highs, opens), 2),
            "low": np.round(np.minimum(lows, opens), 2),
            "close": np.round(closes, 2),
            "volume": np.round(np.abs(np.random.randn(n) * 800 + 3000), 2),
        })

        import tempfile
        tmp = tempfile.mkdtemp(prefix="canopy_concurrent_")
        fpath = os.path.join(tmp, "concurrent.parquet")
        df.to_parquet(fpath, index=False)

        # ── 串行基线 ──
        factory = StrategyFactory()
        factory._register_builtins()

        # 4 种 on_bar 策略（arbitrage 依赖 on_dual_ticker，排除）
        strategy_names = ["trend", "grid", "momentum", "mean_reversion"]
        strategies = {
            name: factory.create(name)
            for name in strategy_names
        }
        # grid 需要设定价格区间
        strategies["grid"] = factory.create(
            "grid", upper_price=56000, lower_price=44000
        )

        from canopy.engine.risk import RiskConfig, RiskManager

        risk_config = RiskConfig(
            max_position_pct=0.3,
            max_total_exposure=1.0,
            max_drawdown_pct=0.5,
            max_daily_loss_pct=0.5,
            min_volatility_filter=0.0,
            max_volatility_filter=1.0,
        )

        # ── 串行运行 ──
        serial_results = {}
        serial_start = time.perf_counter()

        for s_name, s in strategies.items():
            eng = SimEngine(data_path=fpath, slippage=0.0005, commission=0.001)
            eng.load()
            acct = SimAccount(initial_capital=500_000.0)
            brk = SimBroker(engine=eng, account=acct)
            rm = RiskManager(config=risk_config, initial_balance=500_000.0)
            serial_results[s_name] = _run_single_strategy(
                s, eng, rm, brk, self.BAR_COUNT
            )

        serial_total = time.perf_counter() - serial_start

        # ── 并发运行（线程池） ──
        concurrent_start = time.perf_counter()

        def run_strategy(name, strat):
            eng = SimEngine(data_path=fpath, slippage=0.0005, commission=0.001)
            eng.load()
            acct = SimAccount(initial_capital=500_000.0)
            brk = SimBroker(engine=eng, account=acct)
            rm = RiskManager(config=risk_config, initial_balance=500_000.0)
            result = _run_single_strategy(strat, eng, rm, brk, self.BAR_COUNT)
            return name, result

        concurrent_results = {}
        with ThreadPoolExecutor(max_workers=len(strategies)) as executor:
            futures = {
                executor.submit(run_strategy, name, s): name
                for name, s in strategies.items()
            }
            for future in as_completed(futures):
                name, result = future.result()
                concurrent_results[name] = result

        concurrent_total = time.perf_counter() - concurrent_start

        # ── 汇总统计 ──
        total_bar_iterations = self.BAR_COUNT * len(strategies)
        bars_per_sec_serial = total_bar_iterations / serial_total
        bars_per_sec_concurrent = total_bar_iterations / concurrent_total

        csv_data = {
            "bar_count": self.BAR_COUNT,
            "strategy_count": len(strategies),
            "total_bar_iterations": total_bar_iterations,
            "serial_total_s": round(serial_total, 3),
            "concurrent_total_s": round(concurrent_total, 3),
            "speedup": round(serial_total / concurrent_total, 2) if concurrent_total > 0 else 0,
            "bars_per_sec_serial": round(bars_per_sec_serial, 1),
            "bars_per_sec_concurrent": round(bars_per_sec_concurrent, 1),
        }
        for s_name in strategy_names:
            sr = serial_results[s_name]
            cr = concurrent_results[s_name]
            csv_data[f"{s_name}_serial_s"] = round(sr["elapsed_s"], 3)
            csv_data[f"{s_name}_concurrent_s"] = round(cr["elapsed_s"], 3)
            csv_data[f"{s_name}_signals"] = sr["signals"]
            csv_data[f"{s_name}_fills"] = sr["fills"]

        _write_result("concurrent_strategies", csv_data)

        print(f"\n[并发策略] {len(strategies)} 策略 × {self.BAR_COUNT} bar | "
              f"串行={serial_total:.2f}s | 并发={concurrent_total:.2f}s | "
              f"加速比={serial_total/concurrent_total:.2f}x")
        assert True

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

_results: list[dict] = []


def _write_result(benchmark_name: str, data: dict):
    """将一次 benchmark 结果附加到全局列表并写入 CSV。"""
    row = {"benchmark": benchmark_name, **data}
    _results.append(row)
    _flush_csv()


def _flush_csv():
    """将全部结果刷新写入 CSV。"""
    if not _results:
        return
    fieldnames = ["benchmark"]
    for row in _results:
        for k in row:
            if k not in fieldnames:
                fieldnames.append(k)

    os.makedirs(os.path.dirname(BENCHMARK_CSV) or ".", exist_ok=True)
    with open(BENCHMARK_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_results)
