"""
技术指标模块 — MACD / RSI / 布林带 / EMA 交叉
输入: OHLCV DataFrame (columns: open, high, low, close, volume)
输出: pd.Series 或 (Series, Series, Series)
"""

import pandas as pd
import numpy as np


def macd(close: pd.Series, fast=12, slow=26, signal=9) -> dict:
    """MACD 指标。

    Returns:
        { 'dif': pd.Series, 'dea': pd.Series, 'hist': pd.Series }
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2  # 柱状图（国内常用 *2）
    return {"dif": dif, "dea": dea, "hist": hist}


def rsi(close: pd.Series, period=14) -> pd.Series:
    """RSI 相对强弱指标。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))


def bollinger(close: pd.Series, period=20, std_dev=2) -> dict:
    """布林带。

    Returns:
        { 'mid': pd.Series, 'upper': pd.Series, 'lower': pd.Series }
    """
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return {"mid": mid, "upper": upper, "lower": lower}


def ema_cross(close: pd.Series, fast=12, slow=26) -> pd.Series:
    """EMA 快慢线交叉信号。

    返回: 1 (金叉, fast 上穿 slow), -1 (死叉), 0 (无变化)
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    cross = pd.Series(0, index=close.index)
    # 金叉: 前一根 fast <= slow，当前 fast > slow
    golden = (ema_fast.shift(1) <= ema_slow.shift(1)) & (ema_fast > ema_slow)
    death = (ema_fast.shift(1) >= ema_slow.shift(1)) & (ema_fast < ema_slow)
    cross[golden] = 1
    cross[death] = -1
    return cross


__all__ = ["macd", "rsi", "bollinger", "ema_cross"]
