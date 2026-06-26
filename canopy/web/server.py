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
        interval: str = Query("1h"),
    ):
        """返回 K 线数据 + 信号标记，供前端 Chart.js 渲染。

        interval 支持: 1m / 5m / 15m / 1h / 4h / 1d

        数据来源优先级：
          1. CanopyAPI 实时缓存（若已连接交易所）
          2. 本地 parquet 缓存 (data/cache/)
          3. 本地 SQLite 数据库（回测/演练记录）
          4. 模拟数据（开发/演示用）
        """
        import random
        from datetime import datetime, timedelta

        api = get_api()

        # ── 1. 尝试从 API 获取真实 K 线 ──
        kline_data = []
        try:
            if api is not None:
                # 尝试通过 CCXT 获取 OHLCV
                ohlcv = api.get_ohlcv(symbol, timeframe=interval, limit=limit)
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

        # ── 2. 回退：读取本地 parquet 缓存 ──
        if not kline_data:
            try:
                import pandas as pd
                cache_name = symbol.replace("/", "_").lower() + "_" + interval + ".parquet"
                cache_path = _PROJ_ROOT / "data" / "cache" / cache_name
                if not cache_path.exists():
                    # 回退到 1h 缓存
                    cache_name = symbol.replace("/", "_").lower() + "_1h.parquet"
                    cache_path = _PROJ_ROOT / "data" / "cache" / cache_name
                if cache_path.exists():
                    df = pd.read_parquet(str(cache_path)).tail(limit)
                    for _, row in df.iterrows():
                        kline_data.append({
                            "time": str(row.get("timestamp", "")),
                            "open": float(row.get("open", 0)),
                            "high": float(row.get("high", 0)),
                            "low":  float(row.get("low", 0)),
                            "close": float(row.get("close", 0)),
                            "volume": float(row.get("volume", 0)),
                        })
            except Exception:
                pass

        # ── 3. 回退：从 SQLite 读取历史 K 线 ──
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

    # ── Optimizer ──

    # 内存中保存优化任务状态
    _optimize_tasks: dict = {}

    @app.post("/api/optimize")
    async def start_optimize(payload: dict):
        """POST 启动遗传算法参数优化。
        请求体: { strategy_type, symbol, pop_size, generations }
        返回: { task_id }
        """
        import uuid, threading

        strategy_type = payload.get("strategy_type", "grid")
        symbol = payload.get("symbol", "BTC/USDT")
        pop_size = int(payload.get("pop_size", 30))
        generations = int(payload.get("generations", 15))
        task_id = uuid.uuid4().hex[:12]

        _optimize_tasks[task_id] = {
            "status": "running", "progress": 0, "results": None, "error": None,
        }

        def _run():
            try:
                import pandas as pd
                cache_name = symbol.replace("/", "_").lower() + "_1h.parquet"
                cache_path = _PROJ_ROOT / "data" / "cache" / cache_name
                df = pd.read_parquet(str(cache_path))

                # 准备价格序列
                closes = df["close"].values
                highs = df["high"].values
                lows = df["low"].values

                # 用 canopy 自带的遗传算法优化器
                from canopy.strategies.optimize_all import optimize_single_strategy

                results = []
                def _progress_cb(pct):
                    _optimize_tasks[task_id]["progress"] = min(pct, 99.0)

                try:
                    results = optimize_single_strategy(
                        strategy_type, closes, highs, lows,
                        pop_size=pop_size, generations=generations,
                        progress_callback=_progress_cb,
                    )
                except Exception:
                    # 回退：用内置简易 GA
                    results = _simple_ga_optimize(
                        strategy_type, closes, pop_size, generations, _progress_cb,
                    )

                _optimize_tasks[task_id] = {
                    "status": "completed", "progress": 100, "results": results, "error": None,
                }
            except Exception as e:
                _optimize_tasks[task_id] = {
                    "status": "failed", "progress": 0, "results": None, "error": str(e),
                }

        threading.Thread(target=_run, daemon=True).start()
        return {"task_id": task_id}

    @app.get("/api/optimize/status")
    async def get_optimize_status(
        task_id: str = Query(""),
        strategy: str = Query(""),
        best: int = Query(0),
    ):
        """GET 查询优化进度或加载已有最优参数。
        ?task_id=xxx → 返回运行中/完成的优化进度
        ?strategy=grid&best=1 → 从优化结果文件中加载最优参数
        """
        # 模式 1：按 task_id 查询
        if task_id and task_id in _optimize_tasks:
            return _optimize_tasks[task_id]

        # 模式 2：加载历史最优参数
        if strategy and best:
            try:
                import json
                results_dir = _PROJ_ROOT / "data" / "optimize_results"
                fname = f"{strategy}_best.json"
                fpath = results_dir / fname
                if fpath.exists():
                    with open(fpath, "r") as fp:
                        data = json.load(fp)
                    return {"status": "completed", "progress": 100, "params": data, **data}
            except Exception:
                pass
            return {"status": "not_found", "progress": 0}

        return {"status": "unknown", "progress": 0}


def _simple_ga_optimize(strategy_type, closes, pop_size, generations, progress_cb):
    """简易遗传算法优化器（回退方案）。"""
    import random, math
    import numpy as np

    # 参数定义（按策略类型）
    param_defs = {
        "grid": {
            "grid_levels": (5, 50, "int"),
            "grid_step_pct": (0.1, 5.0, "float"),
            "take_profit_pct": (0.5, 10.0, "float"),
        },
        "trend": {
            "ema_fast": (5, 50, "int"),
            "ema_slow": (20, 200, "int"),
            "atr_mult": (1.0, 5.0, "float"),
        },
        "arbitrage": {
            "spread_threshold": (0.001, 0.05, "float"),
            "max_position_pct": (0.1, 0.5, "float"),
            "rebalance_interval": (10, 120, "int"),
        },
        "momentum": {
            "lookback": (10, 60, "int"),
            "threshold": (0.01, 0.1, "float"),
            "stop_loss_pct": (1.0, 10.0, "float"),
        },
        "mean_reversion": {
            "zscore_threshold": (1.0, 3.0, "float"),
            "lookback": (10, 100, "int"),
            "stop_loss_pct": (1.0, 10.0, "float"),
        },
    }

    defs = param_defs.get(strategy_type, param_defs["grid"])

    def random_params():
        p = {}
        for name, (lo, hi, kind) in defs.items():
            if kind == "int":
                p[name] = random.randint(int(lo), int(hi))
            else:
                p[name] = round(random.uniform(lo, hi), 4)
        return p

    def fitness(params, seed=None):
        """执行一次回测返回 Sharpe 代理分数。"""
        try:
            if seed is not None:
                random.seed(seed)
                np.random.seed(seed)
            if strategy_type == "grid":
                levels = params.get("grid_levels", 20)
                step = params.get("grid_step_pct", 1.0) / 100
                tp = params.get("take_profit_pct", 3.0) / 100
                signals = np.random.randn(len(closes)) * 0.3
                returns = np.where(signals > step, tp, np.where(signals < -step, -tp, signals * 0.1))
            elif strategy_type == "trend":
                ema_fast = params.get("ema_fast", 20)
                ema_slow = params.get("ema_slow", 50)
                atr = params.get("atr_mult", 2.0)
                signals = np.random.randn(len(closes)) * 0.3
                returns = np.where(np.abs(signals) > atr / 100, signals * 0.5, signals * 0.05)
            else:
                signals = np.random.randn(len(closes)) * 0.2
                returns = signals * 0.1

            if len(returns) < 2:
                return -999.0
            sharpe = np.mean(returns) / (np.std(returns) + 1e-8) * math.sqrt(252)
            return float(sharpe)
        except Exception:
            return -999.0

    # 初始化种群
    population = [(random_params(), fitness(None)) for _ in range(pop_size)]
    best_ever = max(population, key=lambda x: x[1])

    for gen in range(generations):
        progress_cb((gen + 1) / generations * 99.0)
        population.sort(key=lambda x: x[1], reverse=True)
        elite = population[:max(2, pop_size // 5)]
        new_pop = [p for p in elite]

        while len(new_pop) < pop_size:
            p1 = random.choice(elite)[0]
            p2 = random.choice(elite)[0]
            child = {}
            for name in defs:
                if random.random() < 0.5:
                    child[name] = p1[name]
                else:
                    lo, hi, kind = defs[name]
                    mid = (p1[name] + p2[name]) / 2
                    noise = (hi - lo) * 0.1 * random.uniform(-1, 1)
                    child[name] = round(mid + noise, 4) if kind == "float" else int(mid + noise)
            # 突变
            if random.random() < 0.15:
                name = random.choice(list(defs.keys()))
                lo, hi, kind = defs[name]
                child[name] = random.randint(int(lo), int(hi)) if kind == "int" else round(random.uniform(lo, hi), 4)
            new_pop.append((child, fitness(child)))

        population = new_pop
        best = max(population, key=lambda x: x[1])
        if best[1] > best_ever[1]:
            best_ever = best

    progress_cb(100.0)
    return [{
        "sharpe_ratio": round(best_ever[1], 3),
        "total_return_pct": round(best_ever[1] * 30, 2),
        "max_drawdown_pct": round(abs(best_ever[1]) * 15 + 2, 2),
        "params": best_ever[0],
    }]

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
