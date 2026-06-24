#!/usr/bin/env bash
#
# Canopy 一键部署脚本
# 用法: bash deploy/deploy.sh
#
# 步骤:
#   1. pip install 依赖
#   2. 初始化 data/ 目录
#   3. 复制 systemd unit → daemon-reload → enable + start
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================="
echo "  Canopy 部署脚本"
echo "========================================="
echo "  项目目录: $PROJECT_DIR"
echo ""

# ── 1. 安装 Python 依赖 ──
echo "[1/4] 安装 Python 依赖..."
cd "$PROJECT_DIR"

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
elif [ -f "pyproject.toml" ]; then
    pip install -e .
else
    # 核心依赖手动安装
    pip install ccxt pandas numpy pywebview python-cryptography
fi

echo "  依赖安装完成"
echo ""

# ── 2. 初始化 data/ 目录 ──
echo "[2/4] 初始化 data/ 目录..."
mkdir -p "$PROJECT_DIR/data/cache"
mkdir -p "$PROJECT_DIR/output"
mkdir -p "$PROJECT_DIR/logs"

if [ ! -f "$PROJECT_DIR/data/.init" ]; then
    touch "$PROJECT_DIR/data/.init"
    echo "  data/ 目录已初始化"
else
    echo "  data/ 目录已存在，跳过"
fi
echo ""

# ── 3. systemd 服务部署 ──
echo "[3/4] 部署 systemd 用户服务..."

SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

# 复制 service 文件
cp "$SCRIPT_DIR/canopy.service" "$SYSTEMD_USER_DIR/canopy.service"

echo "  systemd unit 已复制到: $SYSTEMD_USER_DIR/canopy.service"

# 重载 systemd
if command -v systemctl &>/dev/null; then
    systemctl --user daemon-reload
    echo "  systemd --user daemon-reload 完成"
else
    echo "  [WARN] systemctl 不可用（非 Linux 环境），跳过 daemon-reload"
fi
echo ""

# ── 4. 启用并启动服务 ──
echo "[4/4] 启用并启动服务..."

if command -v systemctl &>/dev/null; then
    systemctl --user enable canopy.service
    systemctl --user start canopy.service

    sleep 2
    STATUS=$(systemctl --user is-active canopy.service || echo "unknown")
    echo "  服务状态: $STATUS"
    echo ""
    echo "  管理命令:"
    echo "    systemctl --user status canopy"
    echo "    systemctl --user stop canopy"
    echo "    systemctl --user restart canopy"
    echo "    journalctl --user -u canopy -f"
else
    echo "  [SKIP] systemctl 不可用（非 Linux / 非 systemd 环境）"
    echo "  请手动启动: python canopy/main.py"
fi

echo ""
echo "========================================="
echo "  部署完成"
echo "========================================="
