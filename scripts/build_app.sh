#!/usr/bin/env bash
#
# build_app.sh — 免 PyInstaller 创建 macOS Canopy.app Bundle
#
# 用法:
#   bash scripts/build_app.sh              # 构建 + 安装
#   bash scripts/build_app.sh --build-only # 仅构建，不安装
#   bash scripts/build_app.sh --clean      # 清理构建产物
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

APP_NAME="Canopy"
BUNDLE_ID="com.xccci.canopy"
DIST_DIR="${PROJECT_ROOT}/dist"
APP_BUNDLE="${DIST_DIR}/${APP_NAME}.app"
CONTENTS="${APP_BUNDLE}/Contents"
MACOS_DIR="${CONTENTS}/MacOS"
RESOURCES_DIR="${CONTENTS}/Resources"
ICON_SRC="${PROJECT_ROOT}/assets/icon.png"
ICON_DST="${RESOURCES_DIR}/icon.icns"
LAUNCH_SCRIPT="${MACOS_DIR}/${APP_NAME}"
PLIST="${CONTENTS}/Info.plist"
APP_TARGET="/Applications/${APP_NAME}.app"
LAUNCHER="/usr/local/bin/canopy"

# ── 颜色 ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${CYAN}[STEP]${NC} $*"; }

# ── 参数解析 ──
BUILD_ONLY=false
CLEAN_MODE=false
if [[ "${1:-}" == "--build-only" ]]; then BUILD_ONLY=true; fi
if [[ "${1:-}" == "--clean" ]]; then CLEAN_MODE=true; fi

# ═══════════════════════════════════════════════════════════════════
# 清理模式
# ═══════════════════════════════════════════════════════════════════
if $CLEAN_MODE; then
    if [[ -d "$APP_BUNDLE" ]]; then
        rm -rf "$APP_BUNDLE"
        log_info "已清理: $APP_BUNDLE"
    else
        log_info "无构建产物，无需清理。"
    fi
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════
# Step 1: 创建目录结构
# ═══════════════════════════════════════════════════════════════════
log_step "1/6 创建 .app bundle 目录结构"
rm -rf "$APP_BUNDLE"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
log_info "目录创建完成: $APP_BUNDLE"

# ═══════════════════════════════════════════════════════════════════
# Step 2: 图标转换 (PNG → ICNS)
# ═══════════════════════════════════════════════════════════════════
log_step "2/6 生成图标 icon.icns"
if [[ -f "$ICON_SRC" ]]; then
    # 创建临时 iconset 目录
    ICONSET="${DIST_DIR}/Canopy.iconset"
    mkdir -p "$ICONSET"

    # 用 sips 生成各尺寸
    for size in 16 32 64 128 256 512; do
        sips -z $size $size "$ICON_SRC" --out "${ICONSET}/icon_${size}x${size}.png" &>/dev/null
    done
    # 生成 @2x 尺寸
    for size in 16 32 128 256 512; do
        sips -z $((size*2)) $((size*2)) "$ICON_SRC" --out "${ICONSET}/icon_${size}x${size}@2x.png" &>/dev/null
    done

    # 用 iconutil 打包成 .icns
    iconutil -c icns "$ICONSET" -o "$ICON_DST" &>/dev/null
    rm -rf "$ICONSET"
    log_info "图标已生成: $ICON_DST"
else
    log_warn "未找到 icon.png ($ICON_SRC)，跳过图标生成。"
fi

# ═══════════════════════════════════════════════════════════════════
# Step 3: 创建 Info.plist
# ═══════════════════════════════════════════════════════════════════
log_step "3/6 创建 Info.plist"
cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleDisplayName</key>
    <string>Canopy</string>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSRequiresNativeExecution</key>
    <true/>
</dict>
</plist>
PLISTEOF
log_info "Info.plist 已创建"

# ═══════════════════════════════════════════════════════════════════
# Step 4: 创建启动脚本
# ═══════════════════════════════════════════════════════════════════
log_step "4/6 创建启动脚本 MacOS/Canopy"
cat > "$LAUNCH_SCRIPT" << 'LAUNCHEREOF'
#!/usr/bin/env bash
set -euo pipefail

cd /Users/cccc/Desktop/canopy
exec python3 -m canopy.main --web --no-desktop "$@"
LAUNCHEREOF

chmod +x "$LAUNCH_SCRIPT"
log_info "启动脚本已创建并设置可执行权限"

# ═══════════════════════════════════════════════════════════════════
# Step 5: 验证 .app 结构
# ═══════════════════════════════════════════════════════════════════
log_step "5/6 验证 .app 结构完整性"

verify_app() {
    local errors=0

    # 检查必需文件
    check_exists() {
        if [[ ! -e "$1" ]]; then
            log_error "缺失: $1"
            errors=$((errors + 1))
        fi
    }
    check_exec() {
        if [[ ! -x "$1" ]]; then
            log_error "不可执行: $1"
            errors=$((errors + 1))
        fi
    }

    check_exists "$CONTENTS"
    check_exists "$MACOS_DIR"
    check_exists "$RESOURCES_DIR"
    check_exists "$LAUNCH_SCRIPT"
    check_exec "$LAUNCH_SCRIPT"
    check_exists "$PLIST"

    if [[ $errors -eq 0 ]]; then
        log_info "验证通过：.app 结构完整"
        return 0
    else
        log_error "验证失败：发现 $errors 处问题"
        return 1
    fi
}

verify_app

# 显示 bundle 结构
echo ""
log_info "Bundle 结构:"
find "$APP_BUNDLE" -not -path '*/\.*' | sort | sed "s|${APP_BUNDLE}|Canopy.app|" | while read -r line; do
    if [[ -d "$APP_BUNDLE/${line#Canopy.app/}" ]]; then
        echo "  ${line}/"
    else
        echo "  ${line}"
    fi
done

# ═══════════════════════════════════════════════════════════════════
# Step 6: 安装到 /Applications 并创建启动器
# ═══════════════════════════════════════════════════════════════════
if $BUILD_ONLY; then
    log_info "--build-only 模式，跳过安装。"
    exit 0
fi

log_step "6/6 安装到系统"

# ── 关闭已有实例 ──
pkill -f "${APP_NAME}.app" 2>/dev/null || true

# ── 复制到 /Applications ──
if [[ -d "$APP_TARGET" ]]; then
    rm -rf "$APP_TARGET"
    log_info "已移除旧版: $APP_TARGET"
fi
cp -a "$APP_BUNDLE" "$APP_TARGET"
log_info "已安装到: $APP_TARGET"

# ── 创建 /usr/local/bin/canopy 启动器 ──
if [[ -w "/usr/local/bin" ]] || [[ ! -d "/usr/local/bin" ]]; then
    # 可写或不存在 → 尝试创建目录
    mkdir -p /usr/local/bin 2>/dev/null || true
fi

cat > "$LAUNCHER" << LAUNCHEREOF
#!/usr/bin/env bash
# Canopy CLI 启动器
exec open -a "${APP_TARGET}" "\$@"
LAUNCHEREOF

chmod +x "$LAUNCHER" 2>/dev/null || {
    log_warn "无权限写入 $LAUNCHER，尝试 sudo..."
    sudo cp "${DIST_DIR}/canopy_launcher" "$LAUNCHER" 2>/dev/null || \
        log_warn "无法创建 /usr/local/bin/canopy，请手动执行:"
    log_warn "  sudo cp ${DIST_DIR}/canopy_launcher $LAUNCHER"
    log_warn "  sudo chmod +x $LAUNCHER"
}

# 备用：在 dist 中保留一份启动器
cat > "${DIST_DIR}/canopy_launcher" << LAUNCHEREOF
#!/usr/bin/env bash
exec open -a "${APP_TARGET}" "\$@"
LAUNCHEREOF
chmod +x "${DIST_DIR}/canopy_launcher"

log_info "CLI 启动器已创建: $LAUNCHER"

# ── 完成 ──
echo ""
log_info "=============================================="
log_info "  Canopy.app 构建并安装完成！"
log_info "=============================================="
log_info "  .app 路径: $APP_TARGET"
log_info "  CLI 命令:  canopy"
log_info "  也可双击:  $APP_TARGET (Finder 中)"
log_info "=============================================="
