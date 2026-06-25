"""
Canopy Web Dashboard — FastAPI 服务器。

用法:
    python -m canopy.web.server                    # 独立启动
    python canopy/main.py --web                     # 通过 main.py 启动
    python canopy/main.py --web --port 8080          # 指定端口

路由:
    GET  /api/kpi          — KPI 指标
    GET  /api/strategies   — 策略状态
    GET  /api/portfolio    — 持仓分布
    GET  /api/orders       — 订单历史
    GET  /api/risk         — 风控状态
    GET  /api/ws-status    — WebSocket 连接状态
    WS   /ws               — 实时 ticker/kline 推送
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path
_PROJ_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("canopy.web.server")

# ── 全局 CanopyAPI 引用（由 main.py 或 server.py main 注入） ──
_canopy_api = None


def set_api(api):
    """注入 CanopyAPI 实例（由 main.py 调用）。"""
    global _canopy_api
    _canopy_api = api


def get_api():
    """获取 CanopyAPI 实例。"""
    global _canopy_api
    return _canopy_api


# ── FastAPI 应用工厂 ──

def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    static_dir = Path(__file__).parent / "static"

    app = FastAPI(
        title="Canopy Web 仪表盘",
        description="Nature-Tech 交易终端 — HTTP + WebSocket API",
        version="0.2.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 静态文件挂载 ──
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── REST API 路由 ──

    @app.get("/")
    async def root():
        """主页面"""
        index_path = Path(__file__).parent / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return HTMLResponse("<h1>Canopy Dashboard</h1><p>index.html not found</p>")

    @app.get("/api/kpi")
    async def get_kpi():
        api = get_api()
        if api is None:
            return _empty_kpi()
        try:
            return api.get_kpi()
        except Exception:
            return _empty_kpi()

    @app.get("/api/strategies")
    async def get_strategies():
        api = get_api()
        if api is None:
            return []
        try:
            return api.get_strategies()
        except Exception:
            return []

    @app.get("/api/portfolio")
    async def get_portfolio():
        api = get_api()
        if api is None:
            return []
        try:
            return api.get_portfolio()
        except Exception:
            return []

    @app.get("/api/orders")
    async def get_orders(limit: int = Query(50, le=200)):
        api = get_api()
        if api is None:
            return []
        try:
            return api.get_orders(limit)
        except Exception:
            return []

    @app.get("/api/risk")
    async def get_risk():
        api = get_api()
        if api is None:
            return {}
        try:
            return api.get_risk_status()
        except Exception:
            return {}

    @app.get("/api/ws-status")
    async def get_ws_status():
        api = get_api()
        if api is None:
            return {"connected": False, "status": "未连接", "status_label": "离线"}
        try:
            return api.get_ws_status()
        except Exception:
            return {"connected": False, "status": "未连接", "status_label": "错误"}

    @app.get("/api/ticker")
    async def get_ticker(symbol: str = Query("BTC/USDT")):
        api = get_api()
        if api is None:
            return {}
        try:
            return api.get_ticker(symbol)
        except Exception:
            return {}

    @app.get("/api/status")
    async def get_status():
        api = get_api()
        if api is None:
            return {"connected": False, "exchange": "已断开", "runner": {}, "mode": "空闲"}
        try:
            return api.get_status()
        except Exception:
            return {"connected": False, "exchange": "错误", "runner": {}, "mode": "未知"}

    @app.get("/api/sentiment")
    async def get_sentiment():
        api = get_api()
        if api is None:
            return {}
        try:
            return api.get_sentiment()
        except Exception:
            return {}

    @app.get("/api/chart-data")
    async def get_chart_data(
        symbol: str = Query("BTC/USDT"),
        limit: int = Query(100, le=500),
        signal_limit: int = Query(50, le=200),
    ):
        """返回 K 线数据 + 信号标记，供前端 Chart.js 渲染。

        数据来源优先级：
          1. CanopyAPI 实时缓存（若已连接交易所）
          2. 本地 SQLite 数据库（回测/演练记录）
          3. 模拟数据（开发/演示用）
        """
        import random
        from datetime import datetime, timedelta

        api = get_api()

        # ── 1. 尝试从 API 获取真实 K 线 ──
        kline_data = []
        try:
            if api is not None:
                # 尝试通过 CCXT 获取 OHLCV
                ohlcv = api.get_ohlcv(symbol, timeframe="1h", limit=limit)
                if ohlcv:
                    for row in ohlcv:
                        ts = row[0] / 1000  # ms → s
                        kline_data.append({
                            "time": datetime.utcfromtimestamp(ts).isoformat() + "Z",
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low":  float(row[3]),
                            "close": float(row[4]),
                            "volume": float(row[5]),
                        })
        except Exception:
            pass

        # ── 2. 回退：从 SQLite 读取历史 K 线 ──
        if not kline_data:
            try:
                from canopy.utils.database import Database
                import os
                db_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "canopy_live.db")
                if os.path.exists(db_path):
                    db = Database(db_path)
                    rows = db.get_klines(symbol.replace("/", ""), limit=limit)
                    if rows:
                        for r in rows:
                            kline_data.append({
                                "time": r.get("time", ""),
                                "open": float(r.get("open", 0)),
                                "high": float(r.get("high", 0)),
                                "low":  float(r.get("low", 0)),
                                "close": float(r.get("close", 0)),
                                "volume": float(r.get("volume", 0)),
                            })
            except Exception:
                pass

        # ── 3. 回退：生成模拟 K 线数据 ──
        if not kline_data:
            base_price = {
                "BTC/USDT": 67800, "ETH/USDT": 3520, "SOL/USDT": 168,
                "BNB/USDT": 620, "XRP/USDT": 2.5, "DOGE/USDT": 0.35,
                "ADA/USDT": 1.2, "DOT/USDT": 22, "MATIC/USDT": 1.8,
                "LINK/USDT": 25,
            }.get(symbol, 100)
            now = datetime.utcnow()
            for i in range(limit):
                t = now - timedelta(hours=limit - i)
                noise = random.gauss(0, base_price * 0.005)
                open_p = base_price + noise
                close_p = open_p + random.gauss(0, base_price * 0.003)
                high_p = max(open_p, close_p) + abs(random.gauss(0, base_price * 0.002))
                low_p = min(open_p, close_p) - abs(random.gauss(0, base_price * 0.002))
                vol = random.uniform(500, 5000)
                kline_data.append({
                    "time": t.isoformat() + "Z",
                    "open": round(open_p, 2),
                    "high": round(high_p, 2),
                    "low":  round(low_p, 2),
                    "close": round(close_p, 2),
                    "volume": round(vol, 2),
                })
                base_price = close_p  # 随机游走

        # ── 4. 信号标记 ──
        signals = []
        try:
            if api is not None:
                orders = api.get_orders(limit=signal_limit)
                for o in orders:
                    signals.append({
                        "time": o.get("created_at", ""),
                        "price": float(o.get("price", 0)),
                        "side": o.get("side", "buy"),
                        "strategy": o.get("strategy", ""),
                        "reason": o.get("reason", ""),
                    })
        except Exception:
            pass

        # 回退：从模拟 K 线中生成随机信号
        if not signals:
            import random as _r
            indices = sorted(_r.sample(range(10, max(11, len(kline_data) - 5)), min(signal_limit, max(0, len(kline_data) - 10))))
            for idx in indices:
                k = kline_data[idx]
                signals.append({
                    "time": k["time"],
                    "price": k["close"],
                    "side": _r.choice(["buy", "sell"]),
                    "strategy": _r.choice(["Mean Reversion v3", "Grid Infinity", "Trend Surf"]),
                    "reason": _r.choice(["RSI oversold", "Grid fill", "EMA crossover"]),
                })

        # ── 5. 净值曲线 ──
        equity = []
        try:
            if api is not None:
                equity = api.get_equity_curve(limit=200)
        except Exception:
            pass

        if not equity:
            # 从 K 线收盘价模拟净值
            initial = 10000.0
            equity = [{"time": kline_data[0]["time"], "value": initial}]
            for i, k in enumerate(kline_data[1:], 1):
                ret = (k["close"] - kline_data[i - 1]["close"]) / kline_data[i - 1]["close"]
                prev_equity = equity[-1]["value"]
                equity.append({
                    "time": k["time"],
                    "value": round(prev_equity * (1 + ret * 0.5), 2),
                })

        return {
            "symbol": symbol,
            "kline": kline_data,
            "signals": signals,
            "equity": equity,
        }

    # ── WebSocket ──

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        logger.info("WebSocket 客户端已连接")
        try:
            while True:
                api = get_api()
                payload = {
                    "ts": time.time(),
                    "ticker": {},
                    "ws_status": {},
                }
                if api is not None:
                    try:
                        payload["ticker"] = {
                            "BTC/USDT": api.get_ticker("BTC/USDT"),
                            "ETH/USDT": api.get_ticker("ETH/USDT"),
                            "SOL/USDT": api.get_ticker("SOL/USDT"),
                            "BNB/USDT": api.get_ticker("BNB/USDT"),
                            "XRP/USDT": api.get_ticker("XRP/USDT"),
                            "DOGE/USDT": api.get_ticker("DOGE/USDT"),
                            "ADA/USDT": api.get_ticker("ADA/USDT"),
                            "DOT/USDT": api.get_ticker("DOT/USDT"),
                            "MATIC/USDT": api.get_ticker("MATIC/USDT"),
                            "LINK/USDT": api.get_ticker("LINK/USDT"),
                        }
                        payload["ws_status"] = api.get_ws_status()
                    except Exception:
                        pass
                try:
                    await websocket.send_text(json.dumps(payload, default=str))
                except Exception:
                    break
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            logger.info("WebSocket 客户端断开")
        except Exception as e:
            logger.error(f"WebSocket 错误: {e}")

    return app


# ── 默认值 ──

def _empty_kpi() -> dict:
    return {
        "total_value": 0,
        "pnl_24h": 0,
        "pnl_pct": 0,
        "active_strategies": 0,
        "profitable": 0,
        "win_rate": 0,
    }


# ── 独立启动入口 ──

def run_server(host: str = "0.0.0.0", port: int = 8080):
    """启动 FastAPI 服务器（uvicorn）。"""
    import uvicorn
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
