from canopy.utils.logger import get_logger

__all__ = ["get_logger"]

# ── 可选: optimizer 子模块引用 ──

try:
    from canopy.optimizer import (  # noqa: F401
        GeneticOptimizer,
        GridSearchOptimizer,
        OptimizationAnalyzer,
    )
except ImportError:
    pass
