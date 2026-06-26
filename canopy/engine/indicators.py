"""
Canopy 技术指标库 — MACD / RSI / 布林带 / EMA 交叉

所有指标函数输入 pandas DataFrame（OHLCV），返回指标值 Series/DataFrame。
策略可直接 from canopy.engine.indicators import macd, rsi, bollinger, ema_cross
"""

from __future__ import annotations

import pandas as pd
import numpy as np


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    MACD 指标：DIF / DEA / 柱（MACD 柱）。

    返回: DataFrame 包含 dif, dea, macd_hist 三列。
    """
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = 2 * (dif - dea)
    return pd.DataFrame({"dif": dif, "dea": dea, "macd_hist": macd_hist}, index=df.index)


def rsi(df: pd.DataFrame, period: int = 14):
    """
    RSI 相对强弱指标。

    返回: Series，值域 [0, 100]。
    """
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - 100 / (1 + rs)


def bollinger(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0):
    """
    布林带指标。

    返回: DataFrame 包含 upper, middle, lower 三列。
    """
    middle = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower}, index=df.index)


def ema_cross(df: pd.DataFrame, fast: int = 12, slow: int = 26):
    """
    EMA 双均线交叉信号。

    返回: DataFrame 包含 ema_fast, ema_slow, signal。
    signal = 1（金叉，快线上穿慢线）/ -1（死叉）/ 0（无信号）。
    """
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
    cross_down = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[cross_up] = 1
    signal[cross_down] = -1
    return pd.DataFrame({"ema_fast": ema_fast, "ema_slow": ema_slow, "signal": signal}, index=df.index)
