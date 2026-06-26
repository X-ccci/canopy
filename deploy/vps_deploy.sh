#!/usr/bin/env bash
# ============================================================
# Canopy VPS Deployment Script
# 支持 Ubuntu 20.04 / 22.04
# ============================================================
set -euo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
NC="\033[0m"

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*"; }

OS_ID=$(grep '^ID=' /etc/os-release | cut -d= -f2 | tr -d '"' || echo "unknown")
OS_VSN=$(grep '^VERSION_ID=' /etc/os-release | cut -d= -f2 | tr -d '"' || echo "")

log "Canopy VPS Deploy — OS: ${OS_ID} ${OS_VSN}"

if [[ "$OS_ID" != "ubuntu" ]]; then
    warn "本脚本针对 Ubuntu 20.04/22.04 优化，当前系统: ${OS_ID} ${OS_VSN}"
fi

# ── 1. 系统依赖 ──
log "安装系统依赖..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv \
    git curl wget tmux \
    build-essential libssl-dev libffi-dev \
    libsqlite3-dev

# ── 2. 创建项目目录 ──
APP_DIR="/opt/canopy"
log "部署目录: ${APP_DIR}"
sudo mkdir -p "$APP_DIR"
sudo chown "$(whoami):$(whoami)" "$APP_DIR"

# ── 3. git clone ──
if [[ -d "${APP_DIR}/.git" ]]; then
    log "项目已存在，执行 git pull..."
    cd "$APP_DIR"
    git pull --ff-only
else
    log "克隆项目..."
    # 如有私有仓库，改为你的仓库地址
    REPO_URL="${CANOPY_REPO_URL:-https://github.com/your-org/canopy.git}"
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 4. Python 虚拟环境 ──
log "创建虚拟环境..."
python3 -m venv "${APP_DIR}/.venv"
source "${APP_DIR}/.venv/bin/activate"

# ── 5. pip install ──
log "安装 Python 依赖..."
pip install --upgrade pip setuptools wheel
pip install -r "${APP_DIR}/requirements.txt" 2>/dev/null || pip install \
    ccxt pandas numpy scipy fastapi uvicorn websockets \
    python-dotenv sqlalchemy aiosqlite jinja2 httpx

# ── 6. 配置文件 ──
if [[ ! -f "${APP_DIR}/.env" ]]; then
    log "创建 .env 模板..."
    cat > "${APP_DIR}/.env" <<'EOF'
# 交易所 API
BINANCE_API_KEY=
BINANCE_API_SECRET=
OKX_API_KEY=
OKX_API_SECRET=
BYBIT_API_KEY=
BYBIT_API_SECRET=

# 告警渠道
FEISHU_WEBHOOK_URL=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
WECHAT_SCKEY=

# 运行模式
CANOPY_MODE=production
CANOPY_SANDBOX=true
EOF
    warn ".env 已生成，请填入真实的 API Key 后重新启动"
fi

# ── 7. systemd 服务 ──
SERVICE_FILE="/etc/systemd/system/canopy.service"
log "创建 systemd 服务..."

sudo tee "$SERVICE_FILE" > /dev/null <<SYSTEMD
[Unit]
Description=Canopy Crypto Trading Engine
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${APP_DIR}/.venv/bin/python -m canopy.web.server
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=canopy

# 安全加固
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${APP_DIR}/data
ReadWritePaths=/tmp

[Install]
WantedBy=multi-user.target
SYSTEMD

sudo systemctl daemon-reload
sudo systemctl enable canopy

# ── 8. 启动 ──
log "启动 Canopy 服务..."
sudo systemctl restart canopy
sleep 3
sudo systemctl status canopy --no-pager || true

# ── 9. tmux 便捷脚本 ──
cat > "${APP_DIR}/tmux_canopy.sh" <<'TMUX'
#!/usr/bin/env bash
# Canopy tmux 多窗口启动脚本
SESSION="canopy"
tmux new-session -d -s "$SESSION" -n "server"
tmux send-keys -t "$SESSION:0" "cd /opt/canopy && source .venv/bin/activate && python -m canopy.web.server" Enter
tmux new-window -t "$SESSION" -n "runner"
tmux send-keys -t "$SESSION:1" "cd /opt/canopy && source .venv/bin/activate && python -m canopy.engine.runner --mode multi --exchanges binance okx bybit" Enter
tmux new-window -t "$SESSION" -n "monitor"
tmux send-keys -t "$SESSION:2" "cd /opt/canopy && watch -n 5 'systemctl status canopy --no-pager'" Enter
tmux select-window -t "$SESSION:0"
tmux attach -t "$SESSION"
TMUX
chmod +x "${APP_DIR}/tmux_canopy.sh"

log "=========================================="
log "部署完成!"
log "  Web UI:      http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):8080"
log "  systemd 日志: journalctl -u canopy -f"
log "  tmux 多窗口:  ${APP_DIR}/tmux_canopy.sh"
log "  .env 配置:     ${APP_DIR}/.env"
log "=========================================="
