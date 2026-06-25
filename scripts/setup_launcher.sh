#!/usr/bin/env bash
# Canopy 全局启动器安装脚本
# 将 canopy 命令安装到 /usr/local/bin，实现终端任意位置启动

set -euo pipefail

CANOPY_APP="/Applications/Canopy.app"

# ── 前置检查 ──
if [[ ! -d "$CANOPY_APP" ]]; then
    echo "错误: 未找到 Canopy.app ($CANOPY_APP)"
    echo "请确认应用已安装到 /Applications"
    exit 1
fi

echo "============================================"
echo "  Canopy 全局启动器安装"
echo "============================================"
echo ""
echo "即将创建 /usr/local/bin/canopy 启动脚本。"
echo "此操作需要管理员权限，请在弹出的对话框中输入密码。"
echo ""

# ── 创建启动脚本 ──
LAUNCHER_CONTENT='#!/usr/bin/env bash
# Canopy 全局启动器
# 用法: canopy [args...]

CANOPY_APP="/Applications/Canopy.app"

if [[ ! -d "$CANOPY_APP" ]]; then
    echo "错误: 未找到 Canopy.app，请确认已安装到 /Applications"
    exit 1
fi

open -a "$CANOPY_APP" "$@"
'

echo "$LAUNCHER_CONTENT" | sudo tee /usr/local/bin/canopy > /dev/null
sudo chmod +x /usr/local/bin/canopy

echo ""
echo "安装完成！"
echo "现在可以在终端任意位置输入 'canopy' 启动应用。"
echo ""
echo "验证: $(which canopy)"
echo "路径: /usr/local/bin/canopy"
