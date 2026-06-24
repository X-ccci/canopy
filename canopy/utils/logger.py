"""
结构化 JSON 日志模块。按日自动轮转，输出到 logs/ 目录。
"""
import json
import logging
import os
import threading
from datetime import date, datetime

# 日志目录绝对路径 — 指向项目根目录下的 logs/
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
_LOGGERS: dict[str, "StructuredLogger"] = {}
_LOCK = threading.Lock()


class DailyRotatingHandler(logging.Handler):
    """按日轮转的文件 handler，每天生成一个新日志文件"""

    def __init__(self, log_dir: str, name: str = "canopy"):
        super().__init__()
        self._log_dir = log_dir
        self._name = name
        self._current_date: str = ""
        self._file = None
        os.makedirs(self._log_dir, exist_ok=True)
        self._rotate()

    def _rotate(self):
        new_date = date.today().isoformat()
        if new_date == self._current_date and self._file:
            return
        if self._file:
            self._file.close()
        self._current_date = new_date
        filepath = os.path.join(self._log_dir, f"{self._name}-{new_date}.log")
        self._file = open(filepath, "a", encoding="utf-8")

    def emit(self, record: logging.LogRecord):
        try:
            # 跨天后自动切换文件
            if date.today().isoformat() != self._current_date:
                self._rotate()
            self._file.write(record.getMessage() + "\n")  # type: ignore[attr-defined]
            self._file.flush()  # type: ignore[attr-defined]
        except Exception:
            self.handleError(record)

    def close(self):
        if self._file:
            self._file.close()
        super().close()


class StructuredLogger:
    """输出 JSON 格式结构化日志的 logger 包装器"""

    def __init__(self, name: str = "canopy"):
        self._logger = logging.getLogger(f"canopy.{name}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        if not self._logger.handlers:
            handler = DailyRotatingHandler(_LOG_DIR, name)
            self._logger.addHandler(handler)

    # ---- 策略信号 ----
    def signal(self, strategy: str, symbol: str, side: str, price: float, extra: dict | None = None):
        self._log("SIGNAL", {
            "strategy": strategy,
            "symbol": symbol,
            "side": side,
            "price": price,
            **(extra or {})
        })

    # ---- 风控决策 ----
    def risk(self, action: str, approved: bool, reason: str = "", extra: dict | None = None):
        self._log("RISK", {
            "approved": approved,
            "reason": reason,
            **(extra or {})
        })

    # ---- 订单状态 ----
    def order(self, status: str, order_id: str = "", symbol: str = "", side: str = "",
              price: float = 0.0, amount: float = 0.0, error: str = "", extra: dict | None = None):
        self._log("ORDER", {
            "status": status,
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "price": price,
            "amount": amount,
            "error": error,
            **(extra or {})
        })

    # ---- 通用信息 ----
    def info(self, category: str, message: str, extra: dict | None = None):
        self._log("INFO", {"category": category, "message": message, **(extra or {})})

    def warning(self, category: str, message: str, extra: dict | None = None):
        self._log("WARNING", {"category": category, "message": message, **(extra or {})})

    def error(self, category: str, message: str, extra: dict | None = None):
        self._log("ERROR", {"category": category, "message": message, **(extra or {})})

    def debug(self, category: str, message: str, extra: dict | None = None):
        self._log("DEBUG", {"category": category, "message": message, **(extra or {})})

    # ---- 内部 ----
    def _log(self, event_type: str, payload: dict):
        record = {
            "ts": datetime.now().isoformat(),
            "type": event_type,
            **payload
        }
        self._logger.info(json.dumps(record, ensure_ascii=False, default=str))


def get_logger(name: str = "canopy") -> StructuredLogger:
    """工厂函数：获取或创建命名 logger 实例"""
    with _LOCK:
        if name not in _LOGGERS:
            _LOGGERS[name] = StructuredLogger(name)
        return _LOGGERS[name]
