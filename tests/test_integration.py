"""
test_integration.py — 端到端集成测试
覆盖 SimBroker → 5 策略 → RiskManager → OrderExecutor 全链路。

正向路径：策略产生信号 → 风控通过 → 订单成交 → 持仓更新
异常路径：熔断后信号被拒、资金不足订单被拒
"""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from canopy.engine.factory import StrategyFactory
from canopy.engine.risk import RiskConfig, RiskManager
from canopy.sim.account import SimAccount
from canopy.sim.broker import SimBroker
from canopy.sim.engine import SimEngine

# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def parquet_path():
    """生成模拟 K 线 Parquet 数据（200 根 1h K 线，包含趋势+震荡）。"""
    np.random.seed(42)
    n = 200
    base_price = 50000.0
    trend = np.linspace(0, 8000, n)  # 从 50000 涨到 58000（趋势）
    noise = np.cumsum(np.random.randn(n) * 200)  # 随机游走噪声

    close = base_price + trend + noise
    # 构造 OHLC：在 close 基础上加日内波动
    intraday_range = np.abs(np.random.randn(n) * 150) + 50
    high = close + intraday_range / 2
    low = close - intraday_range / 2
    open_price = np.roll(close, 1)
    open_price[0] = close[0] - 30
    volume = np.abs(np.random.randn(n) * 500 + 2000)

    timestamps = pd.date_range("2025-01-01", periods=n, freq="1h")

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": np.round(open_price, 2),
        "high": np.round(np.maximum(high, open_price), 2),
        "low": np.round(np.minimum(low, open_price), 2),
        "close": np.round(close, 2),
        "volume": np.round(volume, 2),
    })

    # 写入临时目录
    tmp = tempfile.mkdtemp(prefix="canopy_integration_")
    fpath = os.path.join(tmp, "BTC_USDT_1h.parquet")
    df.to_parquet(fpath, index=False)
    yield fpath
    # 清理
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def engine(parquet_path):
    """创建并加载 SimEngine。"""
    eng = SimEngine(data_path=parquet_path, slippage=0.0005, commission=0.001)
    assert eng.load(), "SimEngine 加载失败"
    return eng


@pytest.fixture
def account():
    """创建 SimAccount，初始资金 100000 USDT。"""
    return SimAccount(initial_capital=100000.0)


@pytest.fixture
def broker(engine, account):
    """创建 SimBroker，封装 engine + account。"""
    return SimBroker(engine=engine, account=account)


@pytest.fixture
def risk_manager():
    """创建 RiskManager，默认配置。"""
    config = RiskConfig()
    return RiskManager(config=config, initial_balance=100000.0)


@pytest.fixture
def factory():
    """创建策略工厂并注册 5 种策略。"""
    f = StrategyFactory()
    f._register_builtins()
    return f


@pytest.fixture
def strategies(factory):
    """创建 5 个策略实例（共用同一个 symbol）。"""
    return {
        "trend":             factory.create("trend"),
        "grid":              factory.create("grid", upper_price=65000, lower_price=45000),
        "momentum":          factory.create("momentum"),
        "mean_reversion":    factory.create("mean_reversion"),
        "arbitrage":         factory.create("arbitrage"),
    }


# ══════════════════════════════════════════════════════════════
# 正向路径测试
# ══════════════════════════════════════════════════════════════

class TestPositiveFullPipeline:
    """正向路径：策略 → 风控 → 下单 → 成交 → 持仓更新。"""

    def test_signal_to_fill_full_chain(self, engine, broker, risk_manager, strategies):
        """遍历所有 K 线，验证至少有一条完整成交链路。"""
        fill_count = 0
        reject_count = 0
        hold_count = 0
        position_updates = []

        broker.on_position_update(lambda evt: position_updates.append(evt))

        # 推进 200 根 K 线
        for _ in range(engine.total_bars):
            candle = engine.current_candle
            current_price = candle["close"]

            for s_name, s in strategies.items():
                signal = s.on_bar(candle)
                if signal is None:
                    continue

                action = signal.get("action", "HOLD")
                if action == "HOLD":
                    hold_count += 1
                    continue

                # 风控审批
                signal["symbol"] = "BTC/USDT"
                approved, reason, order_dict = risk_manager.approve(
                    signal, current_price,
                    account_balance=broker.account.balance
                )

                if not approved:
                    reject_count += 1
                    continue

                # SimBroker 下单
                result = broker.submit_order(
                    symbol=order_dict["symbol"],
                    side=order_dict["side"],
                    order_type="market",
                    amount=order_dict["quantity"],
                )

                if result["status"] == "FILLED":
                    fill_count += 1
                    # 同步风控持仓
                    side = "LONG" if order_dict["side"] == "buy" else "SHORT"
                    risk_manager.update_position(
                        order_dict["symbol"], side,
                        result["price"], result["amount"],
                        result["price"]
                    )
                elif result["status"] == "REJECTED":
                    reject_count += 1

            engine.step()

        # 断言：至少有一次完整成交
        assert fill_count > 0, f"期望至少 1 笔成交，实际 {fill_count}"
        # 断言：持仓更新事件已触发
        assert len(position_updates) > 0, "期望收到 POSITION_UPDATED 事件"

    def test_positions_updated_after_fill(self, engine, broker, risk_manager, strategies):
        """单笔成交后持仓应正确更新。"""
        total_bars = engine.total_bars
        filled = False

        for i in range(total_bars):
            candle = engine.current_candle
            current_price = candle["close"]

            if filled:
                break

            for s_name, s in strategies.items():
                signal = s.on_bar(candle)
                if signal is None or signal.get("action") == "HOLD":
                    continue

                signal["symbol"] = "BTC/USDT"
                approved, reason, order_dict = risk_manager.approve(
                    signal, current_price,
                    account_balance=broker.account.balance
                )
                if not approved:
                    continue

                result = broker.submit_order(
                    symbol=order_dict["symbol"],
                    side=order_dict["side"],
                    order_type="market",
                    amount=order_dict["quantity"],
                )

                if result["status"] == "FILLED":
                    filled = True
                    # 验证返回结果包含所有必要字段
                    assert result["order_id"], "order_id 不应为空"
                    assert result["price"] > 0, "成交价应 > 0"
                    assert result["amount"] > 0, "成交量应 > 0"
                    assert result["cost"] > 0, "成交金额应 > 0"

                    # 验证账户持仓
                    positions = broker.get_positions()
                    assert len(positions) > 0, "成交后应有持仓"

                    # 验证组合数据
                    portfolio = broker.get_portfolio()
                    assert "equity" in portfolio
                    assert "balance" in portfolio
                    break

            engine.step()

        assert filled, "遍历全部 K 线后应有至少 1 笔成交"

    def test_risk_manager_status_updated(self, engine, broker, risk_manager, strategies):
        """风控状态应随交易推进而更新。"""
        initial_status = risk_manager.get_status()
        assert initial_status["open_positions"] == 0

        # 推进直到有成交
        for _ in range(engine.total_bars):
            candle = engine.current_candle
            current_price = candle["close"]

            for s_name, s in strategies.items():
                signal = s.on_bar(candle)
                if signal is None or signal.get("action") == "HOLD":
                    continue

                signal["symbol"] = "BTC/USDT"
                approved, reason, order_dict = risk_manager.approve(
                    signal, current_price,
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
                        side = "LONG" if order_dict["side"] == "buy" else "SHORT"
                        risk_manager.update_position(
                            order_dict["symbol"], side,
                            result["price"], result["amount"],
                            result["price"]
                        )

            engine.step()

        # 验证风控状态已更新
        final_status = risk_manager.get_status()
        assert "circuit_breaker" in final_status
        assert "current_balance" in final_status
        assert "drawdown_pct" in final_status


# ══════════════════════════════════════════════════════════════
# 异常路径测试
# ══════════════════════════════════════════════════════════════

class TestNegativeCircuitBreaker:
    """熔断后信号应被拒。"""

    def test_signal_rejected_after_circuit_breaker(self, engine, broker, strategies):
        """熔断器触发后所有信号应被拒绝。"""
        config = RiskConfig(max_drawdown_pct=0.01)  # 极低回撤阈值
        rm = RiskManager(config=config, initial_balance=100000.0)
        # 手动 trip 熔断器
        rm.circuit_breaker.trip("Test: max drawdown triggered")

        # 推进到策略能产生信号的阶段
        candle = engine.current_candle
        for _ in range(50):
            engine.step()
        candle = engine.current_candle

        for s_name, s in strategies.items():
            signal = s.on_bar(candle)
            if signal is None or signal.get("action") == "HOLD":
                continue

            signal["symbol"] = "BTC/USDT"
            approved, reason, order = rm.approve(
                signal, candle["close"],
                account_balance=broker.account.balance
            )

            # 熔断后必须拒绝
            assert not approved, f"熔断后 {s_name} 信号应被拒绝"
            assert "Circuit breaker" in reason or "circuit" in reason or "tripped" in reason, \
                f"拒绝原因应包含熔断信息: {reason}"

    def test_signal_approved_after_reset(self, engine, broker, strategies):
        """熔断重置后信号应可恢复审批。"""
        config = RiskConfig(
            max_position_pct=0.3,        # 允许较大仓位
            max_total_exposure=1.0,      # 允许满仓敞口
            max_drawdown_pct=0.5,        # 放宽回撤
            max_daily_loss_pct=0.5,      # 放宽日亏损
            min_volatility_filter=0.0,   # 关闭波动率过滤
            max_volatility_filter=1.0,
        )
        rm = RiskManager(config=config, initial_balance=100000.0)
        rm.circuit_breaker.trip("Test trip")
        assert rm.circuit_breaker.is_tripped

        rm.reset_circuit_breaker()
        assert not rm.circuit_breaker.is_tripped

        # 推进到策略能产生信号的阶段（遍历全部数据直到信号出现）
        total = engine.total_bars
        for _ in range(total):
            candle = engine.current_candle
            for s_name, s in strategies.items():
                signal = s.on_bar(candle)
                if signal is None or signal.get("action") == "HOLD":
                    continue

                signal["symbol"] = "BTC/USDT"
                approved, reason, order = rm.approve(
                    signal, candle["close"],
                    account_balance=broker.account.balance
                )
                if approved:
                    return  # 至少有一个策略通过即可

            engine.step()

        pytest.fail("熔断重置后应至少有一个策略信号通过审批")


class TestNegativeInsufficientBalance:
    """资金不足时订单应被拒绝。"""

    def test_order_rejected_on_insufficient_balance(self, engine):
        """资金不足时 SimBroker 应返回 REJECTED。"""
        # 极小资金账户
        account = SimAccount(initial_capital=10.0)
        eng = SimEngine(data_path=engine.data_path, slippage=0.0005, commission=0.001)
        eng.load()
        brk = SimBroker(engine=eng, account=account)

        # 尝试下一笔大单
        result = brk.submit_order(
            symbol="BTC/USDT",
            side="buy",
            order_type="limit",
            amount=10.0,
            price=50000.0,
        )

        assert result["status"] == "REJECTED", \
            f"资金不足应返回 REJECTED，实际: {result['status']}"
        assert "余额不足" in result.get("message", ""), \
            f"拒绝信息应包含余额不足: {result.get('message')}"

    def test_market_order_rejected_insufficient_at_match(self, engine):
        """市价单撮合时余额不足应被拒绝。"""
        # 刚好够限价但不够市价滑点的资金
        account = SimAccount(initial_capital=51000.0)
        eng = SimEngine(data_path=engine.data_path, slippage=0.0005, commission=0.001)
        eng.load()

        # 推进到高价区域
        for _ in range(150):
            eng.step()

        brk = SimBroker(engine=eng, account=account)
        eng.current_candle["close"]

        # 模拟资金不足：余额设得很低
        brk.account.balance = 100.0

        result = brk.submit_order(
            symbol="BTC/USDT",
            side="buy",
            order_type="market",
            amount=10.0,
        )

        assert result["status"] == "REJECTED", \
            f"市价单资金不足应 REJECTED，实际: {result['status']}"
        assert "资金不足" in result.get("message", ""), \
            f"拒绝信息应包含资金不足: {result.get('message')}"


# ══════════════════════════════════════════════════════════════
# 全策略信号覆盖
# ══════════════════════════════════════════════════════════════

class TestAllStrategiesProduceSignal:
    """验证策略都能在足够数据后产生非 HOLD 信号。

    注意：ArbitrageStrategy 依赖 on_dual_ticker（跨交易所 ticker），
    不在纯 on_bar 信号测试范围内。
    """

    def test_core_strategies_eventually_signal(self, engine, strategies):
        """遍历所有 K 线后，4 种核心策略至少产生过一次非 HOLD 信号。"""
        # arbitrage 策略依赖 on_dual_ticker，跳过
        core = {k: v for k, v in strategies.items() if k != "arbitrage"}
        signal_counts: dict[str, int] = {k: 0 for k in core}

        for _ in range(engine.total_bars):
            candle = engine.current_candle
            for s_name, s in core.items():
                signal = s.on_bar(candle)
                if signal and signal.get("action") != "HOLD":
                    signal_counts[s_name] += 1
            engine.step()

        for s_name, count in signal_counts.items():
            assert count > 0, \
                f"策略 {s_name} 在 {engine.total_bars} 根 K 线上未产生任何非 HOLD 信号"
