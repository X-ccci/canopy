"""全局配置 — 交易所 API 密钥、数据库路径、日志级别等集中管理。"""

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    """Canopy 全局配置数据类。"""

    # ── 交易所配置 ──
    exchange: str = "binance"
    api_key: str = ""          # 占位，运行前需填入
    api_secret: str = ""       # 占位，运行前需填入
    testnet: bool = True       # 默认使用测试网

    # ── 数据库 ──
    db_path: str = field(default_factory=lambda: os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "canopy.db"
    ))

    # ── 日志 ──
    log_level: str = "INFO"
    log_file: str = field(default_factory=lambda: os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "canopy.log"
    ))

    # ── WebSocket ──
    ws_enabled: bool = False             # 是否启用 WebSocket 实时行情（替代 REST 轮询）
    ws_reconnect_interval: float = 5.0   # 重连间隔（秒）
    ws_ping_interval: float = 30.0       # 心跳间隔（秒）
    ws_channels: list[dict] = field(default_factory=list)
    # ws_channels 示例: [{"type": "ticker", "symbol": "BTC/USDT"},
    #                    {"type": "kline", "symbol": "ETH/USDT", "interval": "1h"}]

    # ── 回测 ──
    backtest_initial_capital: float = 10000.0
    backtest_commission: float = 0.001   # 手续费率

    # ── 数据 ──
    data_cache_dir: str = field(default_factory=lambda: os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "cache"
    ))

    def ensure_dirs(self):
        """确保必要的目录存在。"""
        for path in [os.path.dirname(self.db_path),
                     os.path.dirname(self.log_file),
                     self.data_cache_dir]:
            os.makedirs(path, exist_ok=True)
