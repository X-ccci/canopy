#!/usr/bin/env bash
#
# Canopy Desktop App 安装脚本 (macOS)
#
# 功能:
#   1. 将 dist/Canopy.app 复制到 /Applications/
#   2. 设置正确的权限
#   3. 创建 /usr/local/bin/canopy 启动器
#
# 用法:
#   bash scripts/install.sh
#   bash scripts/install.sh --uninstall   # 卸载
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_NAME="Canopy"
APP_SOURCE="${PROJECT_ROOT}/dist/${APP_NAME}.app"
APP_TARGET="/Applications/${APP_NAME}.app"
LAUNCHER="/usr/local/bin/canopy"

# ── 颜色定义 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── 卸载模式 ──
if [[ "${1:-}" == "--uninstall" ]]; then
    log_info "开始卸载 Canopy..."

    if [[ -d "$APP_TARGET" ]]; then
        rm -rf "$APP_TARGET"
        log_info "已删除: $APP_TARGET"
    else
        log_warn "未找到: $APP_TARGET"
    fi

    if [[ -f "$LAUNCHER" ]]; then
        rm -f "$LAUNCHER"
        log_info "已删除: $LAUNCHER"
    else
        log_warn "未找到: $LAUNCHER"
    fi

    log_info "卸载完成。"
    exit 0
fi

# ── 安装前检查 ──
if [[ ! -d "$APP_SOURCE" ]]; then
    log_error "未找到 $APP_SOURCE"
    log_error "请先运行: python3 scripts/build_desktop.py"
    exit 1
fi

# ── 第 1 步: 复制 .app 到 /Applications ──
log_info "正在安装 Canopy.app 到 /Applications/ ..."
if [[ -d "$APP_TARGET" ]]; then
    log_warn "已存在旧版本，正在覆盖..."
    rm -rf "$APP_TARGET"
fi

cp -R "$APP_SOURCE" "$APP_TARGET"

# ── 第 2 步: 清除隔离属性 + 设置权限 ──
log_info "清除 Gatekeeper 隔离属性..."
xattr -cr "$APP_TARGET"
xattr -dr com.apple.quarantine "$APP_TARGET" 2>/dev/null || true
log_info "设置权限..."
chmod -R 755 "$APP_TARGET"

# ── 第 3 步: 创建 /usr/local/bin/canopy 启动器 ──
log_info "创建命令行启动器: $LAUNCHER"

# 确保 /usr/local/bin 存在
if [[ ! -d "/usr/local/bin" ]]; then
    sudo mkdir -p /usr/local/bin
fi

sudo tee "$LAUNCHER" > /dev/null << 'LAUNCHER_SCRIPT'
#!/usr/bin/env bash
# Canopy 命令行启动器
# 用法: canopy [参数...]

APP="/Applications/Canopy.app"

# 如果 .app 不存在，回退到 Python 直接运行
if [[ ! -d "$APP" ]]; then
    CANOPY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/Desktop/canopy"
    if [[ -d "$CANOPY_ROOT" ]]; then
        cd "$CANOPY_ROOT"
        exec python3 -m canopy.main "$@"
    else
        echo "[ERROR] Canopy 未安装，请先运行 install.sh" >&2
        exit 1
    fi
fi

# 使用 open 命令启动 .app
if [[ $# -eq 0 ]]; then
    open "$APP"
else
    # 传递参数：打开 app 并传递命令行参数
    open "$APP" --args "$@"
fi
LAUNCHER_SCRIPT

sudo chmod 755 "$LAUNCHER"

# ── 完成 ──
log_info "============================================"
log_info "  Canopy 安装完成！"
log_info "============================================"
log_info ""
log_info "  桌面应用: ${APP_TARGET}"
log_info "  命令行:   ${LAUNCHER}"
log_info ""
log_info "  启动方式:"
log_info "    - 在终端输入: canopy"
log_info "    - 在 Spotlight 搜索: Canopy"
log_info "    - 在 Applications 文件夹双击 Canopy.app"
log_info ""
log_info "  卸载方式:"
log_info "    bash scripts/install.sh --uninstall"
