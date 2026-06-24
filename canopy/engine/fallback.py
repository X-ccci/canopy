"""
回退测试数据生成器：为回测生成模拟 OHLCV 数据。
"""
import random
import math
from datetime import datetime, timedelta

import pandas as pd


def generate_fallback_test_data(symbol: str = 'BTC/USDT', timeframe: str = '1h',
                                 length: int = 200) -> pd.DataFrame:
    """生成模拟 OHLCV 数据用于回测。

    Args:
        symbol:    交易对（影响初始价格和波动率）。
        timeframe: 时间周期（影响时间戳间隔）。
        length:    K 线数量。

    Returns:
        DataFrame，含 timestamp/open/high/low/close/volume 列。
    """
    # 初始价格映射
    base_prices = {
        'BTC/USDT': 65000, 'ETH/USDT': 3400, 'SOL/USDT': 170,
        'BNB/USDT': 600, 'AVAX/USDT': 38
    }
    base_price = base_prices.get(symbol, 100)

    # 时间间隔映射
    tf_deltas = {'1h': timedelta(hours=1), '4h': timedelta(hours=4),
                 '1d': timedelta(days=1)}
    delta = tf_deltas.get(timeframe, timedelta(hours=1))

    # 随机种子保证可复现但不同调用有变化
    random.seed(hash(symbol + timeframe) % (2 ** 31))
    math_seed = random.random()

    rows = []
    current_time = datetime(2025, 1, 1)
    price = base_price
    trend = 0.0002  # 微弱的上涨趋势

    for i in range(length):
        daily_vol = base_price * 0.02  # 日波动率约 2%
        tick_vol = daily_vol / math.sqrt(24) if timeframe != '1d' else daily_vol

        # 几何布朗运动 + 均值回归
        drift = trend * price
        shock = random.gauss(0, tick_vol)
        mean_rev = 0.0001 * (base_price - price)
        price_change = drift + shock + mean_rev

        open_price = price
        close_price = price + price_change * 0.6
        high_price = max(open_price, close_price) + abs(random.gauss(0, tick_vol * 0.5))
        low_price = min(open_price, close_price) - abs(random.gauss(0, tick_vol * 0.5))
        volume = abs(random.gauss(base_price * 0.5, base_price * 0.2))

        rows.append({
            'timestamp': current_time.isoformat(),
            'open': round(open_price, 2),
            'high': round(high_price, 2),
            'low': round(low_price, 2),
            'close': round(close_price, 2),
            'volume': round(volume, 2)
        })

        price = close_price
        current_time += delta

    return pd.DataFrame(rows)
