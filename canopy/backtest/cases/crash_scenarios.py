"""极端行情案例库 — 预设市场崩盘场景用于压力测试。

提供三大历史崩盘场景定义及模拟价格序列生成器。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class CrashScenario:
    """极端行情场景定义。

    Attributes:
        name:             场景名称。
        date:             发生日期。
        description:      详细描述。
        asset:            主要资产交易对。
        price_change_pct: 期间总价格变动百分比（如 -37.8）。
        max_drawdown_pct: 最大回撤百分比。
        duration_hours:   持续时间（小时）。
        key_events:       关键时间节点事件描述列表。
    """
    name: str
    date: str
    description: str
    asset: str
    price_change_pct: float
    max_drawdown_pct: float
    duration_hours: int
    key_events: list[str] = field(default_factory=list)


# ── 预设场景 ──

SCENARIO_312 = CrashScenario(
    name="2020-03-12 黑色星期四",
    date="2020-03-12",
    description=(
        "新冠疫情引发全球恐慌，BitMEX 连环爆仓踩踏，"
        "BTC 24h 跌超 50%，最低触及 $3,800"
    ),
    asset="BTC/USDT",
    price_change_pct=-37.8,
    max_drawdown_pct=-50.0,
    duration_hours=24,
    key_events=[
        "3/12 06:00 BTC $7,950 → 首次跌破 $7,000",
        "3/12 10:00 BitMEX 大规模清算开始",
        "3/12 18:00 最低 $3,800，DEX 滑点超过 30%",
        "3/13 反弹至 $5,000 上方",
    ],
)

SCENARIO_519 = CrashScenario(
    name="2021-05-19 五一九崩盘",
    date="2021-05-19",
    description=(
        "中国三协会联合声明禁止金融机构开展虚拟货币业务，"
        "叠加马斯克言论，BTC 日跌超 30%"
    ),
    asset="BTC/USDT",
    price_change_pct=-30.5,
    max_drawdown_pct=-35.0,
    duration_hours=14,
    key_events=[
        "5/18 三协会联合公告发布",
        "5/19 09:00 市场开始暴跌",
        "5/19 13:00 主要交易所宕机",
        "5/19 21:00 BTC $30,000 附近暂稳",
    ],
)

SCENARIO_FTX = CrashScenario(
    name="2022-11-08 FTX 崩盘",
    date="2022-11-08",
    description=(
        "FTX 流动性危机引爆，Alameda 资不抵债，"
        "币安放弃收购，BTC 跌破 $16,000"
    ),
    asset="BTC/USDT",
    price_change_pct=-22.3,
    max_drawdown_pct=-27.0,
    duration_hours=120,
    key_events=[
        "11/02 CoinDesk 曝光 Alameda 资产负债表",
        "11/06 币安宣布清仓 FTT",
        "11/08 FTX 暂停提现，币安签署收购意向",
        "11/09 币安放弃收购，FTX 申请破产",
    ],
)

CRASH_SCENARIOS: list[CrashScenario] = [SCENARIO_312, SCENARIO_519, SCENARIO_FTX]


# ── 模拟价格序列生成 ──

def generate_pressure_test(
    base_price: float,
    scenario: CrashScenario,
    n_steps: int = 500,
    seed: int = 42,
) -> pd.DataFrame:
    """根据场景生成模拟 OHLCV 价格序列，用于压力测试。

    模拟分为三个阶段：
    1. 前半段 — 正常波动：收益率服从均值为 0、标准差 2%/天的正态分布。
    2. 后半段 — 加速下跌：几何级叠加，波动率放大 3 倍。
    3. 末尾 — 反弹：价格回弹至跌幅的 30%-50%。

    Args:
        base_price: 起始基准价格。
        scenario:   预设极端行情场景。
        n_steps:    生成的 K 线步数。
        seed:       随机种子，保证可复现。

    Returns:
        DataFrame，列: timestamp / open / high / low / close / volume。
    """
    rng = np.random.default_rng(seed)

    # 阶段划分
    normal_len = n_steps // 2          # 前半段：正常波动
    crash_start = normal_len
    crash_len = n_steps - normal_len - n_steps // 8
    bounce_start = crash_start + crash_len

    # 日波动率（假设每步代表 1 小时，年化 70% → 小时波动率 ≈ 70%/sqrt(365*24)）
    daily_vol = 0.02
    crash_vol = daily_vol * 3.0

    # 计算目标价格范围
    scenario.price_change_pct / 100.0  # 如 -37.8 → -0.378
    max_dd_pct = scenario.max_drawdown_pct / 100.0  # 如 -50.0 → -0.50

    # 总跌幅在 crash 阶段实现几何级加速
    # 用指数衰减：price(t) = base * exp(rate * t)，使得 crash 结束时达到 max_drawdown
    crash_rate = np.log(1 + max_dd_pct) / crash_len  # 负值，表示对数衰减

    closes = np.zeros(n_steps)
    closes[0] = base_price

    # ── 阶段 1：正常波动 ──
    for i in range(1, normal_len):
        ret = rng.normal(0, daily_vol)
        closes[i] = closes[i - 1] * (1 + ret)

    # ── 阶段 2：加速下跌 ──
    for i in range(crash_start, bounce_start):
        j = i - crash_start  # crash 内的位置 0, 1, 2, ...
        # 几何级加速：越靠后跌幅越大
        geometric_factor = (j + 1) / crash_len
        ret = crash_rate * geometric_factor + rng.normal(0, crash_vol * geometric_factor)
        closes[i] = closes[i - 1] * (1 + ret)

    # ── 阶段 3：反弹 ──
    if bounce_start < n_steps:
        crash_bottom = closes[bounce_start - 1]
        # 反弹至跌幅的 30%-50%
        total_loss = base_price - crash_bottom
        bounce_target = crash_bottom + total_loss * rng.uniform(0.3, 0.5)
        bounce_len = n_steps - bounce_start

        for i in range(bounce_start, n_steps):
            j = i - bounce_start
            progress = (j + 1) / bounce_len
            # 反弹趋势 + 噪声
            trend_price = crash_bottom + (bounce_target - crash_bottom) * progress
            noise = trend_price * rng.normal(0, daily_vol * 1.5)
            closes[i] = max(trend_price + noise, crash_bottom * 0.8)

    # ── 构建 OHLCV ──
    opens = np.roll(closes, 1)
    opens[0] = base_price

    # high/low：在 close 附近加噪声
    intraday_range = np.abs(closes) * daily_vol * 0.5
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, intraday_range, n_steps))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, intraday_range, n_steps))
    lows = np.maximum(lows, 0.01)

    volume_base = 1000 + rng.exponential(500, n_steps)
    # 崩盘阶段成交量放大
    for i in range(crash_start, bounce_start):
        volume_base[i] *= 2.0 + rng.random()

    # 时间戳：从场景日期开始，每小时一根
    start_dt = pd.Timestamp(scenario.date)
    timestamps = pd.date_range(start=start_dt, periods=n_steps, freq="h")

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volume_base,
    })

    return df


def generate_all_tests(base_price: float = 50000) -> dict[str, pd.DataFrame]:
    """为所有预设场景生成压力测试数据。

    Args:
        base_price: 起始基准价格（默认 50000）。

    Returns:
        {scenario_name: DataFrame} 映射。
    """
    results: dict[str, pd.DataFrame] = {}
    for scenario in CRASH_SCENARIOS:
        df = generate_pressure_test(base_price, scenario)
        results[scenario.name] = df
    return results
