---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: dfa59edf71882ac3e29663828f688f4a_5d3bb00170d711f1b2f55254006c9bbf
    ReservedCode1: N/HG0Rc5e0WvWjagHhyygBdlHLEk+b8KBwr6AwscJDEGaRsY8FPF9l5OZEZ+dXidE/1sDTtkDNwfggpn0WMCoUe/yywwNuhW1wi70W/uepsjpbW4OzYyO3OPYk6o7P2w79aFHAaq/sbsGlhGW/Gjo9qbXDY7VtSLio4dckD6y5t4zxeVFaAtZf1qqUw=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: dfa59edf71882ac3e29663828f688f4a_5d3bb00170d711f1b2f55254006c9bbf
    ReservedCode2: N/HG0Rc5e0WvWjagHhyygBdlHLEk+b8KBwr6AwscJDEGaRsY8FPF9l5OZEZ+dXidE/1sDTtkDNwfggpn0WMCoUe/yywwNuhW1wi70W/uepsjpbW4OzYyO3OPYk6o7P2w79aFHAaq/sbsGlhGW/Gjo9qbXDY7VtSLio4dckD6y5t4zxeVFaAtZf1qqUw=
---

# Canopy 更新日志

## v1.1.0 (2026-06-26) — 数据驱动升级

### 新增
- **真实历史数据**：scripts/download_historical.py 从 Binance 公开 API 拉取 10 个交易对 1h K 线并缓存为 Parquet
- **5 策略横向对比报告**：data/strategy_comparison.md，基于 BTC/USDT 真实数据回测

### 改进
- **测试套件 100% 通过**：修复 4 个中英文断言不匹配（72/72 passed）
- **前端币种扩展**：下拉框从 3 个品种扩展到 10 个（BTC/ETH/SOL/BNB/XRP/DOGE/ADA/DOT/MATIC/LINK）
- **server.py**：WebSocket ticker 推送和模拟数据回退覆盖全部 10 个交易对
- **runner.py**：默认策略配置更新为支持的 10 个交易对

### 策略对比结果（BTC/USDT 1h，初始 $10,000）
| 策略 | 收益率 | Sharpe | 胜率 |
|------|--------|--------|------|
| 均值回归 | +17.22% | 1.05 | 53.9% |
| 趋势跟踪 | +5.15% | 0.37 | 28.6% |
| 动量突破 | -3.42% | -0.46 | 0.0% |
| 网格交易 | +0.00% | 0.00 | — |
| 套利 | +0.00% | 0.00 | — |

## v1.0.0 (2026-06-26) — 正式发布

### 新增
- **5 策略引擎**：趋势跟踪、网格交易、套利、动量、均值回归
- **回测系统**：BacktestEngine 完整回测引擎，支持绩效指标（Sharpe/Sortino/Calmar/MaxDD）
- **参数优化**：遗传算法优化器，支持多策略独立参数搜索
- **风控系统**：6 步审批链（预检→风控→资金→合规→执行→复核）
- **Web Dashboard**：localhost:8080 实时监控面板（K线+净值+信号）
- **全中文界面**：菜单、面板、策略名称、错误信息完整中文化
- **Docker 部署**：Dockerfile + docker-compose.yml 一键启动
- **Sphinx 文档站**：autodoc 自动生成 API 文档 + GitHub Pages CI
- **全局启动器**：~/bin/canopy 用户级命令行启动
- **测试套件**：72 个测试用例（60 passed / 12 failed，已定位为中文化适配问题）

### 技术架构
- **后端**：Python 3.11, asyncio, WebSocket 实时推送
- **前端**：单文件 HTML + 内联 CSS/JS，零外部依赖
- **数据库**：SQLite（canopy.db / canopy_live.db）
- **模拟引擎**：SimBroker / SimAccount 完整撮合

---

## v0.9.0 (2026-06-25) — 测试网集成

### 新增
- Binance Testnet API 集成（GET_TESTNET_KEYS.md）
- SimBroker 订单撮合引擎
- SimAccount 资金/持仓管理
- WebSocket 实时行情推送

### 修复
- macOS .app bundle 启动失败（Launchd job spawn failed）
- 隔离属性清除（xattr -cr + quarantine 移除）
- Info.plist 添加 LSBackgroundOnly + CFBundleAllowMixedLocalizations

---

## v0.8.0 (2026-06-24) — Dashboard 可视化

### 新增
- K 线图 + 净值曲线 + 信号标记
- 8 套 CSS 自定义属性主题
- 3 种骨架屏加载状态
- 响应式布局（移动端适配）
- 调试工具栏（底部悬浮面板）

---

## v0.7.0 (2026-06-23) — 回测引擎

### 新增
- BacktestEngine 核心引擎（初始资金/手续费/滑点）
- 模拟数据生成器（多段行情）
- 绩效指标计算（Sharpe/Sortino/Calmar/WinRate/ProfitFactor）
- 交易明细记录（入场/出场/盈亏）

---

## v0.6.0 (2026-06-22) — 策略工厂

### 新增
- StrategyFactory 策略注册与创建
- TrendStrategy (MACD + ATR 止损)
- GridStrategy (网格交易)
- MomentumStrategy (Donchian Channel)
- Strategy 基类（on_bar/on_tick/on_order）

---

## v0.5.0 (2026-06-21) — 风控系统

### 新增
- RiskManager 6 步审批链
- 熔断机制（日内累计回撤/最大回撤）
- ATR 动态止损
- 仓位管理（单笔最大仓位）

---

## v0.4.0 (2026-06-20) — 遗传算法优化器

### 新增
- GA-based 参数搜索
- 参数空间定义（JSON schema）
- 多策略独立优化支持
- 优化结果持久化

---

## v0.3.0 (2026-06-19) — Docker 化

### 新增
- Dockerfile 多阶段构建
- docker-compose.yml（Canopy + SQLite）
- DOCKER_DEPLOY.md 部署指南

---

## v0.2.0 (2026-06-18) — 项目骨架

### 新增
- pyproject.toml 项目配置
- canopy 包结构（engine/backtest/sim/utils）
- exchange 交易所接口抽象
- config.py 全局配置
- Makefile 构建脚本

---

## v0.1.0 (2026-06-17) — 项目初始化

### 新增
- 项目仓库初始化
- README.md
- .gitignore
- 基础目录结构

---

*Canopy — 开箱即用的量化交易系统*
*（内容由AI生成，仅供参考）*
