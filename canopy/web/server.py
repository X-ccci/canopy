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
        title="Canopy Web Dashboard",
        description="Nature-Tech Trading Terminal — HTTP + WebSocket API",
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
        index_path = static_dir / "index.html"
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
            return {"connected": False, "status": "disconnected", "status_label": "OFFLINE"}
        try:
            return api.get_ws_status()
        except Exception:
            return {"connected": False, "status": "disconnected", "status_label": "ERROR"}

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
            return {"connected": False, "exchange": "Disconnected", "runner": {}, "mode": "Idle"}
        try:
            return api.get_status()
        except Exception:
            return {"connected": False, "exchange": "Error", "runner": {}, "mode": "Unknown"}

    @app.get("/api/sentiment")
    async def get_sentiment():
        api = get_api()
        if api is None:
            return {}
        try:
            return api.get_sentiment()
        except Exception:
            return {}

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
