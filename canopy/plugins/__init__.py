"""
Canopy 插件系统 — 自动发现和加载插件

三种插件类型：strategy / indicator / alerter
从 canopy/plugins/ 目录自动发现和加载。
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("canopy.plugins")

# ── 插件类型注册表 ──
PLUGIN_TYPES = ("strategy", "indicator", "alerter")


class PluginLoader:
    """自动发现和加载 canopy/plugins/ 目录下的插件。"""

    def __init__(self, plugin_dir: str | Path | None = None):
        if plugin_dir is None:
            plugin_dir = Path(__file__).resolve().parent
        self.plugin_dir = Path(plugin_dir)
        self._strategies: dict[str, type] = {}
        self._indicators: dict[str, Callable] = {}
        self._alerters: dict[str, type] = {}
        self._loaded = False

    def discover(self) -> dict[str, list[str]]:
        """
        扫描插件目录，返回发现摘要。

        返回: {"strategy": [...], "indicator": [...], "alerter": [...]}
        """
        discovered: dict[str, list[str]] = {t: [] for t in PLUGIN_TYPES}

        if not self.plugin_dir.exists():
            logger.warning(f"插件目录不存在: {self.plugin_dir}")
            return discovered

        for finder, name, ispkg in pkgutil.iter_modules([str(self.plugin_dir)]):
            if name.startswith("_"):
                continue
            try:
                module = importlib.import_module(f"canopy.plugins.{name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if not inspect.isclass(attr) and not callable(attr):
                        continue
                    if attr_name.startswith("_"):
                        continue

                    # 策略插件：继承自 canopy.engine.base.Strategy
                    try:
                        from canopy.engine.base import Strategy
                        if inspect.isclass(attr) and issubclass(attr, Strategy) and attr is not Strategy:
                            self._strategies[name] = attr
                            discovered["strategy"].append(f"{name}.{attr_name}")
                    except (ImportError, TypeError):
                        pass

                    # 指标插件：函数标注 indicator
                    if hasattr(attr, "__canopy_indicator__"):
                        self._indicators[name] = attr
                        discovered["indicator"].append(f"{name}.{attr_name}")

                    # 告警插件
                    if hasattr(attr, "__canopy_alerter__"):
                        self._alerters[name] = attr
                        discovered["alerter"].append(f"{name}.{attr_name}")

            except Exception as e:
                logger.debug(f"加载插件 {name} 失败: {e}")

        self._loaded = True
        return discovered

    def get_strategies(self) -> dict[str, type]:
        if not self._loaded:
            self.discover()
        return dict(self._strategies)

    def get_indicators(self) -> dict[str, Callable]:
        if not self._loaded:
            self.discover()
        return dict(self._indicators)

    def get_alerters(self) -> dict[str, type]:
        if not self._loaded:
            self.discover()
        return dict(self._alerters)

    def reload(self):
        """重新扫描插件目录。"""
        self._strategies.clear()
        self._indicators.clear()
        self._alerters.clear()
        self._loaded = False
        return self.discover()


def register_indicator(func: Callable) -> Callable:
    """装饰器：将函数标记为 Canopy 指标插件。"""
    func.__canopy_indicator__ = True  # type: ignore[attr-defined]
    return func


def register_alerter(cls: type) -> type:
    """装饰器：将类标记为 Canopy 告警插件。"""
    cls.__canopy_alerter__ = True  # type: ignore[attr-defined]
    return cls
