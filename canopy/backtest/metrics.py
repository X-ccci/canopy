"""绩效指标 — 回测结果分析：夏普比率、最大回撤、胜率、盈亏比、月度热力图、卡玛比率、索提诺比率。"""


import numpy as np
import pandas as pd


def sharpe_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.02,
    periods_per_year: int = 365,
) -> float:
    """计算年化夏普比率。

    公式:
        Sharpe = (mean(R) - Rf / periods) / std(R) * sqrt(periods)

    Args:
        returns:          收益率序列（小数形式，如 0.01 = 1%）。
        risk_free_rate:   无风险利率（年化，默认 0.02 = 2%）。
        periods_per_year: 年化周期数（日频 365，小时频 365*24）。

    Returns:
        年化夏普比率。
    """
    if len(returns) == 0:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    std = np.std(excess, ddof=1)
    if std == 0 or np.isclose(std, 0.0):
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(periods_per_year))


def max_drawdown(equity: np.ndarray) -> float:
    """计算最大回撤。

    公式:
        MDD = max((peak_t - equity_t) / peak_t)

    Args:
        equity: 净值序列（逐日或逐笔）。

    Returns:
        最大回撤比例（小数，如 0.25 = 25%）。
    """
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    if peak[0] == 0:
        return 0.0
    drawdown = (peak - equity) / peak
    return float(np.max(drawdown))


def win_rate(trades: list[dict]) -> float:
    """计算胜率。

    公式:
        WinRate = 盈利笔数 / 总笔数

    Args:
        trades: 交易记录列表，每条记录须包含 'pnl' 字段。

    Returns:
        胜率（0~1）。
    """
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return wins / len(trades)


def profit_factor(trades: list[dict]) -> float:
    """计算盈亏比（盈利因子）。

    公式:
        ProfitFactor = 总盈利 / |总亏损|

    Args:
        trades: 交易记录列表，每条记录须包含 'pnl' 字段。

    Returns:
        盈亏因子（>1 表示盈利，<1 表示亏损）。
    """
    gross_profit = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 1.0  # type: ignore[no-any-return]
    return gross_profit / gross_loss  # type: ignore[no-any-return]


def monthly_heatmap(equity: np.ndarray, dates: pd.DatetimeIndex) -> dict[str, float]:
    """生成月度收益率热力图数据。

    公式:
        月收益率 = (月末净值 - 月初净值) / 月初净值

    Args:
        equity: 净值序列，与 dates 一一对应。
        dates:  DatetimeIndex，每条净值对应的日期。

    Returns:
        字典，key 为 'YYYY-MM'，value 为月收益率（小数）。
    """
    if len(equity) < 2 or len(dates) < 2:
        return {}

    df = pd.DataFrame({"equity": equity}, index=dates)
    monthly = df["equity"].resample("ME").last()
    monthly_pct = monthly.pct_change().dropna()

    result: dict[str, float] = {}
    for dt, val in monthly_pct.items():
        key = dt.strftime("%Y-%m")
        result[key] = round(float(val), 6)
    return result


def calmar_ratio(returns: np.ndarray, equity: np.ndarray, periods_per_year: int = 365) -> float:
    """计算年化卡玛比率。

    公式:
        Calmar = 年化收益率 / 最大回撤

    Args:
        returns:          收益率序列。
        equity:           净值序列。
        periods_per_year: 年化周期数。

    Returns:
        卡玛比率。最大回撤为 0 时返回 inf。
    """
    if len(returns) == 0 or len(equity) == 0:
        return 0.0
    annual_return = np.mean(returns) * periods_per_year
    mdd = max_drawdown(equity)
    if mdd == 0 or np.isclose(mdd, 0.0):
        return float("inf") if annual_return > 0 else 0.0
    return float(annual_return / mdd)


def sortino_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.02,
    periods_per_year: int = 365,
) -> float:
    """计算年化索提诺比率（使用下行标准差）。

    公式:
        Sortino = (mean(R) - Rf / periods) / downside_std(R) * sqrt(periods)

    Args:
        returns:          收益率序列。
        risk_free_rate:   无风险利率（年化）。
        periods_per_year: 年化周期数。

    Returns:
        年化索提诺比率。
    """
    if len(returns) == 0:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    downside = np.minimum(excess, 0.0)
    downside_std = np.std(downside, ddof=1)
    if downside_std == 0 or np.isclose(downside_std, 0.0):
        return 0.0
    return float(np.mean(excess) / downside_std * np.sqrt(periods_per_year))
