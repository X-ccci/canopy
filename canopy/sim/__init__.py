"""脱网模拟交易模式 — 不连交易所也能跑完整交易链路。

提供 SimEngine（模拟撮合引擎）、SimAccount（模拟账户）、
SimBroker（模拟券商）三大组件，基于历史 Parquet 数据逐根 K 线推进，
支持市价/限价单撮合、滑点模拟、保证金冻结、事件流等完整功能。
"""

from canopy.sim.account import SimAccount
from canopy.sim.broker import SimBroker
from canopy.sim.engine import SimEngine

__all__ = ["SimEngine", "SimAccount", "SimBroker"]
