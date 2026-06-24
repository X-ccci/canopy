"""
Prometheus 指标导出模块 — 纯标准库实现，零第三方依赖。

提供 Counter 和 Gauge 两种指标类型，输出符合 Prometheus 文本格式规范。
"""

import threading


class _Counter:
    """单调递增计数器，支持标签维度。"""

    def __init__(self, name: str, help_text: str, label_names: tuple[str, ...] = ()):
        self.name = name
        self.help = help_text
        self.label_names = label_names
        self._data: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, value: float = 1.0, labels: dict[str, str] | None = None):
        label_values = self._canonical_labels(labels)
        with self._lock:
            self._data[label_values] = self._data.get(label_values, 0.0) + value

    def _canonical_labels(self, labels: dict[str, str] | None) -> tuple[str, ...]:
        if labels is None:
            labels = {}
        return tuple(labels.get(k, "") for k in self.label_names)

    def collect(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            for label_values, val in self._data.items():
                if label_values:
                    pairs = ",".join(
                        f'{k}="{v}"' for k, v in zip(self.label_names, label_values)
                    )
                    lines.append(f"{self.name}{{{pairs}}} {val}")
                else:
                    lines.append(f"{self.name} {val}")
        return lines


class _Gauge:
    """可增可减的瞬时值仪表盘。"""

    def __init__(self, name: str, help_text: str, label_names: tuple[str, ...] = ()):
        self.name = name
        self.help = help_text
        self.label_names = label_names
        self._data: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, labels: dict[str, str] | None = None):
        label_values = self._canonical_labels(labels)
        with self._lock:
            self._data[label_values] = value

    def inc(self, value: float = 1.0, labels: dict[str, str] | None = None):
        label_values = self._canonical_labels(labels)
        with self._lock:
            self._data[label_values] = self._data.get(label_values, 0.0) + value

    def dec(self, value: float = 1.0, labels: dict[str, str] | None = None):
        self.inc(-value, labels)

    def _canonical_labels(self, labels: dict[str, str] | None) -> tuple[str, ...]:
        if labels is None:
            labels = {}
        return tuple(labels.get(k, "") for k in self.label_names)

    def collect(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        with self._lock:
            for label_values, val in self._data.items():
                if label_values:
                    pairs = ",".join(
                        f'{k}="{v}"' for k, v in zip(self.label_names, label_values)
                    )
                    lines.append(f"{self.name}{{{pairs}}} {val}")
                else:
                    lines.append(f"{self.name} {val}")
        return lines


# ---------------------------------------------------------------------------
# 全局指标注册
# ---------------------------------------------------------------------------

_registry: list = []
_registry_lock = threading.Lock()


def _register(metric):
    with _registry_lock:
        _registry.append(metric)
    return metric


# ---- 业务指标定义 ----

strategy_signals_total = _register(_Counter(
    "canopy_strategy_signals_total",
    "策略产生的信号总数，按策略名和交易对标签",
    label_names=("strategy", "symbol"),
))

orders_total = _register(_Counter(
    "canopy_orders_total",
    "订单总数，按订单状态标签",
    label_names=("status",),
))

pnl = _register(_Gauge(
    "canopy_pnl",
    "当前未实现盈亏（PnL）",
))

latency_seconds = _register(_Gauge(
    "canopy_latency_seconds",
    "最近一次操作的延迟（秒）",
    label_names=("operation",),
))

circuit_breaker_total = _register(_Counter(
    "canopy_circuit_breaker_total",
    "熔断触发次数",
))


# ---- 采集入口 ----

def collect_all() -> str:
    """生成完整的 Prometheus 文本格式指标输出。"""
    parts = []
    with _registry_lock:
        for metric in _registry:
            parts.extend(metric.collect())
    parts.append("")
    return "\n".join(parts)
