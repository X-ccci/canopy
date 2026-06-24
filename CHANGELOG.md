---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: dfa59edf71882ac3e29663828f688f4a_51ba73a86fd811f1986d525400d9a7a1
    ReservedCode1: Os1TG7b/AVEyk0rN4T+3R8h8354jlZv1UIV7Qu5yGku3yVriGG/QNNemJGsT28bfZRdEB0DQnynEuKpFt7WJCn1hDrhYaXgQLi0wvSsb6uARpKtt4tpC+7KhpIsqwk+QSzEmQrlazLLdci5l+5n136mtdwhW4ucwHQcNKx52mRxay8AnKm6/Mod/Kh0=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: dfa59edf71882ac3e29663828f688f4a_51ba73a86fd811f1986d525400d9a7a1
    ReservedCode2: Os1TG7b/AVEyk0rN4T+3R8h8354jlZv1UIV7Qu5yGku3yVriGG/QNNemJGsT28bfZRdEB0DQnynEuKpFt7WJCn1hDrhYaXgQLi0wvSsb6uARpKtt4tpC+7KhpIsqwk+QSzEmQrlazLLdci5l+5n136mtdwhW4ucwHQcNKx52mRxay8AnKm6/Mod/Kh0=
---

# Changelog

## v0.1.0 (2026-06-24)

### Core Engine

- **Strategy Framework**: Abstract base class `Strategy` with lifecycle hooks (`on_start`, `on_stop`, `on_tick`, `on_bar`, `on_order`) and parameter validation.
- **Strategy Factory**: `StrategyFactory` with registry pattern; supports 5 built-in strategies and custom rule-based `CustomStrategy`.
- **Strategy Runner**: `StrategyRunner` manages multiple strategies in parallel threads with shared data layer; supports both REST polling and WebSocket push modes.
- **Composite Strategy**: `CompositeStrategy` stub for multi-strategy signal fusion (vote/weight modes).

### Built-in Strategies

- **Trend (`TrendStrategy`)**: Dual EMA crossover + MACD signal line + ATR trailing stop.
- **Grid (`GridStrategy`)**: Arithmetic/geometric grid lines within price range; auto-trigger on cross.
- **Momentum (`MomentumStrategy`)**: Donchian channel breakout + volume confirmation + ATR trailing stop.
- **Mean Reversion (`MeanReversionStrategy`)**: Z-Score deviation detection + Bollinger Bands confirmation.
- **Arbitrage (`ArbitrageStrategy`)**: Cross-exchange spread arbitrage via `MultiExchangeManager` or `on_dual_ticker`.

### Risk Management

- **RiskConfig**: Configurable parameters for position sizing, exposure limits, drawdown, daily loss, and volatility filters.
- **CircuitBreaker**: Global trade lock on max drawdown or daily loss hits; manual reset support.
- **RiskManager**: Signal approval chain (circuit breaker → daily loss → drawdown → signal validity → position sizing → exposure check). Generates approved order dicts.

### Order Execution

- **Order**: Order object with full lifecycle states (PENDING → OPEN → FILLED / CANCELLED / REJECTED).
- **OrderExecutor**: Threaded order executor; dequeues orders and sends to exchange via `ExchangeAdapter`; supports fill callbacks and position sync to `RiskManager`.
- **Database sync**: Orders and trades are automatically written to SQLite.

### Simulation Mode

- **SimEngine**: Replay engine driven by Parquet OHLCV data; step-by-step bar advancement; market/limit order matching with slippage and commission.
- **SimAccount**: Virtual account with balance, frozen margin, positions (LONG/SHORT), realized/unrealized PnL tracking.
- **SimBroker**: Unified broker wrapping `SimEngine` + `SimAccount`; one-shot `submit_order()` covering order creation → balance check → matching → account update. Full event system (`ORDER_SUBMITTED` / `ORDER_MATCHED` / `POSITION_UPDATED`).

### Exchange Integration

- **CCXT Adapter**: Wrapper around CCXT library for unified multi-exchange API.
- **WebSocket Client**: Real-time market data via WebSocket; supports kline, ticker, and trade channels; wildcard callbacks.
- **Multi-Exchange Manager**: Parallel multi-exchange data access for arbitrage detection.

### Data Layer

- **Data Fetcher**: OHLCV fetching with local caching (Parquet).
- **Database (SQLite)**: Persistent storage for positions, orders, and trades.

### Backtest System

- **Backtest Engine**: Full backtest loop with performance metrics calculation.
- **Backtest Runner**: Standalone runner with configuration-driven backtest execution.
- **Fallback Engine**: Graceful degradation when primary backtest engine is unavailable.

### Optimizer

- **Grid Search**: Parameter optimization via grid search over strategy hyperparameters.

### Web UI

- **pywebview GUI**: Desktop application with strategy management, backtest configuration, and performance visualization.
- **Strategy Dashboard**: Live status, signal log, risk metrics, and pending order count.

### Infrastructure

- **Configuration**: Environment-variable-driven global config (`CANOPY_DB_PATH`, `CANOPY_VAULT_ENABLED`).
- **Docker**: Multi-stage `Dockerfile` with Python 3.11-slim; `docker-compose.yml` for full-stack deployment.
- **CI Pipeline**: GitHub Actions with Ruff linting, Mypy type checking, and pytest across Python 3.10/3.11/3.12.
- **Project metadata**: `pyproject.toml` (PEP 621), `setup.cfg` (Ruff/Mypy), `Makefile`.
*（内容由AI生成，仅供参考）*
