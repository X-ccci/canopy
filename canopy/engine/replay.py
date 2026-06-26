"""
Canopy 交易回放引擎

历史 K 线逐根推进，策略信号实时标注。
支持逐根和批量两种回放模式。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class ReplayState:
    """回放状态。"""
    df: pd.DataFrame | None = None
    current_index: int = 0
    total_bars: int = 0
    signals: list[dict[str, Any]] = field(default_factory=list)
    start_time: str = ""
    symbol: str = ""
    paused: bool = False
    finished: bool = False
    speed: float = 1.0  # 倍速，1.0 = 实时


class ReplayEngine:
    """交易回放引擎。"""

    def __init__(self):
        self._sessions: dict[str, ReplayState] = {}

    def init_session(
        self,
        session_id: str,
        df: pd.DataFrame,
        symbol: str = "BTC/USDT",
    ) -> dict[str, Any]:
        """初始化回放会话。"""
        if df.empty:
            return {"error": "DataFrame is empty"}

        state = ReplayState(
            df=df.copy(),
            total_bars=len(df),
            current_index=0,
            symbol=symbol,
            start_time=str(df.index[0]) if hasattr(df.index[0], 'isoformat') else str(df.index[0]),
        )
        self._sessions[session_id] = state

        return {
            "session_id": session_id,
            "symbol": symbol,
            "total_bars": state.total_bars,
            "start_time": state.start_time,
            "current_index": 0,
        }

    def step(self, session_id: str, strategy_signal_fn=None) -> dict[str, Any]:
        """
        逐根推进一根 K 线。

        参数:
            session_id: 会话 ID。
            strategy_signal_fn: 可选，策略信号函数 (df_slice) -> signal_dict。

        返回: 当前状态和信号。
        """
        state = self._sessions.get(session_id)
        if state is None or state.df is None:
            return {"error": "Session not found", "finished": True}

        if state.finished:
            return {"finished": True, "message": "Replay already finished"}

        if state.paused:
            return {"paused": True, "current_index": state.current_index}

        idx = state.current_index
        if idx >= state.total_bars:
            state.finished = True
            return {"finished": True, "current_index": idx, "total_bars": state.total_bars}

        row = state.df.iloc[idx]
        bar = {
            "index": idx,
            "time": str(state.df.index[idx]) if hasattr(state.df.index[idx], 'isoformat') else str(state.df.index[idx]),
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "volume": float(row.get("volume", 0)),
        }

        signal = None
        if strategy_signal_fn and idx >= 50:  # 需要足够预热
            try:
                df_slice = state.df.iloc[:idx + 1]
                signal = strategy_signal_fn(df_slice)
                if signal:
                    signal["bar_index"] = idx
                    signal["bar_time"] = bar["time"]
                    state.signals.append(signal)
            except Exception:
                pass

        state.current_index = idx + 1
        if state.current_index >= state.total_bars:
            state.finished = True

        return {
            "finished": state.finished,
            "paused": state.paused,
            "bar": bar,
            "signal": signal,
            "current_index": state.current_index,
            "total_bars": state.total_bars,
            "progress_pct": round(state.current_index / state.total_bars * 100, 1),
        }

    def batch(self, session_id: str, count: int = 50, strategy_signal_fn=None) -> dict[str, Any]:
        """
        批量推进 N 根 K 线。

        返回: 最后状态 + 所有信号列表。
        """
        results = []
        new_signals = []
        for _ in range(count):
            result = self.step(session_id, strategy_signal_fn)
            if result.get("error"):
                break
            results.append(result)
            if result.get("signal"):
                new_signals.append(result["signal"])
            if result.get("finished"):
                break

        last = results[-1] if results else {"finished": True}
        return {
            **last,
            "bars_processed": len(results),
            "new_signals": new_signals,
        }

    def pause(self, session_id: str) -> dict[str, Any]:
        """暂停回放。"""
        state = self._sessions.get(session_id)
        if state is None:
            return {"error": "Session not found"}
        state.paused = True
        return {"paused": True, "current_index": state.current_index}

    def resume(self, session_id: str) -> dict[str, Any]:
        """继续回放。"""
        state = self._sessions.get(session_id)
        if state is None:
            return {"error": "Session not found"}
        state.paused = False
        return {"paused": False, "current_index": state.current_index}

    def set_speed(self, session_id: str, speed: float) -> dict[str, Any]:
        """设置回放速度（倍速）。"""
        state = self._sessions.get(session_id)
        if state is None:
            return {"error": "Session not found"}
        state.speed = max(0.1, min(10.0, speed))
        return {"speed": state.speed}

    def get_signals(self, session_id: str) -> list[dict[str, Any]]:
        """获取当前会话所有信号。"""
        state = self._sessions.get(session_id)
        if state is None:
            return []
        return state.signals

    def get_state(self, session_id: str) -> dict[str, Any]:
        """获取当前状态。"""
        state = self._sessions.get(session_id)
        if state is None:
            return {"error": "Session not found"}
        return {
            "current_index": state.current_index,
            "total_bars": state.total_bars,
            "paused": state.paused,
            "finished": state.finished,
            "speed": state.speed,
            "progress_pct": round(state.current_index / state.total_bars * 100, 1) if state.total_bars else 0,
            "signals_count": len(state.signals),
        }

    def destroy_session(self, session_id: str):
        """销毁回放会话。"""
        self._sessions.pop(session_id, None)
