#!/usr/bin/env python3
"""
Canopy Desktop App Builder (macOS)

使用 PyInstaller 将 canopy.main 打包为 macOS .app 应用。
输出: dist/Canopy.app
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DIST_DIR = PROJECT_ROOT / "dist"
APP_NAME = "Canopy"
MAIN_SCRIPT = PROJECT_ROOT / "canopy" / "main.py"
ICON_PATH = PROJECT_ROOT / "assets" / "icon.icns"
SPEC_FILE = PROJECT_ROOT / "canopy.spec"


def ensure_pyinstaller() -> None:
    """确保 PyInstaller 已安装，如未安装则自动 pip install。"""
    try:
        import PyInstaller  # noqa: F401
        print(f"[OK] PyInstaller 已安装")
    except ImportError:
        print("[INSTALL] PyInstaller 未安装，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("[OK] PyInstaller 安装完成")


def clean_previous_build() -> None:
    """清理上一次构建产物。"""
    for path in [DIST_DIR, PROJECT_ROOT / "build", SPEC_FILE]:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
                print(f"[CLEAN] 已删除目录: {path}")
            else:
                path.unlink()
                print(f"[CLEAN] 已删除文件: {path}")


def build_app() -> Path:
    """使用 PyInstaller 打包 .app。"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        f"--distpath={DIST_DIR}",
        f"--workpath={PROJECT_ROOT / 'build'}",
        "--add-data", f"{PROJECT_ROOT / 'canopy' / 'web'}:canopy/web",
    ]

    # 如果有图标文件则添加
    if ICON_PATH.exists():
        cmd.extend(["--icon", str(ICON_PATH)])

    # 添加主脚本
    cmd.append(str(MAIN_SCRIPT))

    print(f"[BUILD] 执行命令: {' '.join(cmd)}")
    subprocess.check_call(cmd)

    app_path = DIST_DIR / f"{APP_NAME}.app"
    if not app_path.exists():
        # PyInstaller onedir 模式下 .app 在 Canopy/ 目录下
        alt_path = DIST_DIR / APP_NAME / f"{APP_NAME}.app"
        if alt_path.exists():
            app_path = alt_path

    return app_path


def main() -> None:
    print("=" * 60)
    print("  Canopy Desktop App Builder (macOS)")
    print("=" * 60)

    os.chdir(PROJECT_ROOT)

    ensure_pyinstaller()
    clean_previous_build()

    print(f"\n[BUILD] 开始打包 {APP_NAME}.app ...")
    app_path = build_app()

    if app_path.exists():
        print(f"\n[SUCCESS] .app 已生成: {app_path}")
        # 显示文件大小
        total_size = sum(f.stat().st_size for f in app_path.rglob("*") if f.is_file())
        print(f"[INFO] 应用大小: {total_size / (1024 * 1024):.1f} MB")
    else:
        print(f"\n[ERROR] 未能找到生成的 .app 文件")
        print(f"[DEBUG] dist 目录内容: {list(DIST_DIR.rglob('*'))[:20]}")
        sys.exit(1)

    print("\n[DONE] 构建完成！可使用以下命令安装:")
    print(f"  bash scripts/install.sh")


if __name__ == "__main__":
    main()
