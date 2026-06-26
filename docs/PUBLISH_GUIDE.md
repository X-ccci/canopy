---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: dfa59edf71882ac3e29663828f688f4a_3f6ad3d5712411f1986d525400d9a7a1
    ReservedCode1: a+s8J0XzH4adVGF6qpOAOtM3tg0Krg3wFDZKfcD3L1rhA4omRDkg9oBggc9AEv+8ZbhQipdzOdNBh4690Frk/nlZLoK39RxpwcZBaMqKzVquqPeRnJ551yAwhiUSj3YNF36WqmCpdfIGW+Z00fguzuE8aghUOxKTrrxdBGaaupYuaqQmWlLEPauZt9Q=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: dfa59edf71882ac3e29663828f688f4a_3f6ad3d5712411f1986d525400d9a7a1
    ReservedCode2: a+s8J0XzH4adVGF6qpOAOtM3tg0Krg3wFDZKfcD3L1rhA4omRDkg9oBggc9AEv+8ZbhQipdzOdNBh4690Frk/nlZLoK39RxpwcZBaMqKzVquqPeRnJ551yAwhiUSj3YNF36WqmCpdfIGW+Z00fguzuE8aghUOxKTrrxdBGaaupYuaqQmWlLEPauZt9Q=
---

# Canopy 社区发布指南

## 一、发布前检查清单

- [ ] `README.md` 更新到最新版本号
- [ ] `assets/screenshots/` 目录包含 6 张以上截图
- [ ] `docs/CHANGELOG.md` 记录本版本变更
- [ ] 所有 API Key 从源码中移除（使用 `.env`）
- [ ] 测试 `deploy/vps_deploy.sh` 在干净 Ubuntu 22.04 上跑通
- [ ] Docker 镜像构建成功：`docker compose -f deploy/docker-compose.prod.yml build`

---

## 二、Product Hunt 文案模板

### English

**Title:** Canopy — Nature-Themed Crypto Trading Terminal with Genetic Optimizer

**Tagline:** Multi-exchange, multi-strategy, open-source trading engine with a gorgeous nature-tech UI

**Description:**

Canopy is an open-source crypto trading terminal that feels alive. It combines a bioluminescent forest-themed UI with serious trading firepower: real-time WebSocket feeds across Binance/OKX/Bybit, a built-in genetic algorithm strategy optimizer, and 30-day backtest simulations.

Key highlights:
- 5 battle-tested strategies: Grid, Trend, Arbitrage, Momentum, Mean Reversion
- Multi-exchange parallel execution (Binance + OKX + Bybit simultaneously)
- Genetic algorithm optimizer with progress visualization
- Multi-channel alerts: Telegram, WeChat, Feishu
- 30-day simulation with Sharpe/MDD/PnL tracking
- VPS one-click deploy script (Ubuntu 20.04/22.04)
- Beautiful responsive Web UI with 4 nature themes

**Link:** https://github.com/your-org/canopy

**Maker's comment:** Built this because I wanted a trading terminal that didn't look like a spreadsheet from 1995. The forest theme actually helps with decision fatigue during long trading sessions. Would love feedback from the PH community!

---

### 中文

**标题：** Canopy — 自然生态风加密交易终端，内置遗传算法策略优化器

**一句话：** 多交易所并行、多策略驱动、开源加密交易引擎，搭配惊艳的自然科技风 UI

**描述：**

Canopy 是一个开源加密交易终端，以仿生森林主题为视觉基调，内核搭载硬核交易能力：跨 Binance/OKX/Bybit 实时 WebSocket 行情、内置遗传算法策略优化器、以及 30 天回测模拟系统。

核心亮点：
- 5 大零交易策略：网格、趋势、套利、动量、均值回归
- 多交易所并行执行（Binance + OKX + Bybit 同时运行）
- 遗传算法参数优化器，含可视化进度条
- 多渠道告警：Telegram、微信、飞书三端并行推送
- 30 天模拟跑分系统（PnL/Sharpe/MDD 日频记录）
- VPS 一键部署脚本（Ubuntu 20.04/22.04）
- 4 套自然主题 + 暗/亮双模式响应式 Web UI

**工具链接：** https://github.com/your-org/canopy

**作者的话：** 厌倦了长得像 1995 年 Excel 的交易终端，所以做了这个。森林主题意外地缓解了长时间盯盘的决策疲劳。期待社区的反馈！

---

## 三、Twitter 推文模板

### Thread (4 tweets)

**Tweet 1:**
Introducing Canopy — an open-source crypto trading terminal where algorithms meet a bioluminescent forest. 

Multi-exchange + genetic optimizer + 30-day sim. All open source.

[attach dashboard screenshot]

**Tweet 2:**
The genetic algorithm optimizer is my favorite part. Drop in BTC/USDT data, set population=30, generations=15, and watch it breed the best strategy params in real-time. Progress bar included.

[attach optimizer screenshot]

**Tweet 3:**
Alert fatigue is real. Canopy pushes to Telegram, WeChat (Server酱), and Feishu — all in parallel. Never miss a signal.

[attach alert screenshot]

**Tweet 4:**
Deploy in 5 minutes:
```bash
git clone https://github.com/your-org/canopy
cd canopy && bash deploy/vps_deploy.sh
```

Stars welcome if this saves you from building yet another trading terminal. 

---

## 四、币圈论坛帖子模板

### 适用于：币安广场 / 知乎 / 金色财经 / Reddit r/algotrading

**标题：** [开源] Canopy：一个颜值能打的加密量化交易终端，多策略 + 遗传算法优化

**正文：**

我做了一个开源的加密交易终端 Canopy，核心功能：

1. **多交易所并行**：Binance / OKX / Bybit 三所同时连，跨所价差实时检测
2. **5 大内置策略**：网格、趋势跟踪、套利、动量突破、均值回归，均通过真实数据 GA 优化
3. **遗传算法优化器**：Web UI 直接调参，种群 + 代数可视化进度条
4. **30 天模拟跑分**：真实 BTC/ETH/BNB 数据上每日记录 PnL / Sharpe / MDD
5. **三渠道告警**：Telegram + 微信 + 飞书，并行推送不遗漏
6. **VPS 一键部署**：bash deploy/vps_deploy.sh 五分钟上线

技术栈：Python + FastAPI + Chart.js + SQLite + Docker + systemd

GitHub: https://github.com/your-org/canopy

用爱发电，求 Star，也欢迎 PR 贡献策略。

---

## 五、截图清单

位于 `assets/screenshots/`，建议录制以下场景：

| 文件名 | 内容 | 说明 |
|---|---|---|
| `dashboard.png` | 主仪表盘 | 暗色 Emerald 主题，含 KPI/图表/持仓 |
| `optimizer.png` | 优化器标签页 | 遗传算法运行中，进度条+结果表格 |
| `backtest.png` | 回测面板 | KPI 卡片 + 净值曲线 + 交易记录 |
| `multi_exchange.png` | 多交易所状态 | 三所连接状态 + 跨所价差表格 |
| `alerts.png` | 告警配置 | 三渠道并行推送示意 |
| `mobile.png` | 移动端视图 | 汉堡菜单 + 单列布局自适应 |
| `themes.png` | 四套主题 | Emerald/Amber/Amethyst/Coral 并列 |
| `vps_deploy.png` | 部署终端 | deploy.sh 执行过程截图 |

---

## 六、发布节奏建议

| Day | 动作 |
|---|---|
| D-3 | 提交 Product Hunt 预览页，邀请早期关注者 |
| D-1 | 推特预热：发 2 条 teaser + 截图 |
| D | PH Launch Day：凌晨 EST 发帖，同步推特 thread + Reddit 发帖 |
| D+1 | 币安广场 / 知乎发帖，附中文版文案 |
| D+3 | 复盘数据：PV / 安装量 / Star 增量，发复盘推文 |
*（内容由AI生成，仅供参考）*
