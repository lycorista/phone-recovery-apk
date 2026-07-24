#!/usr/bin/env python3
"""
手机数据恢复 APK 构建工具

支持两种构建方式:

  方式 1 — 本机构建 (需要 Linux):
    python3 build_apk.py

  方式 2 — Google Colab 云端免费构建:
    将整个 phone_recovery_apk 文件夹上传到 Google Colab
    然后运行此脚本

前置条件 (本机构建):
  • Linux 或 WSL2 (Windows Subsystem for Linux)
  • Python 3.8+
  • 至少 4GB 可用磁盘空间
  • 稳定的网络连接 (首次构建需下载 SDK/NDK, 约 1-2GB)

输出:
  • bin/phonerecovery-1.0.0-*.apk (可直接安装的 APK 文件)
"""

import os
import sys
import shutil
import subprocess
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def print_header():
    print("""
╔══════════════════════════════════════════════════╗
║   📱 手机数据恢复 APK 构建工具                  ║
║   Phone Recovery APK Builder                    ║
╚══════════════════════════════════════════════════╝
""")


def install_buildozer():
    """安装 Buildozer"""
    print("[1/4] 安装 Buildozer...")
    try:
        import buildozer
        print("    ✓ Buildozer 已安装")
    except ImportError:
        print("    正在安装 buildozer...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "buildozer", "cython"],
            check=True
        )
        print("    ✓ Buildozer 安装完成")


def install_system_deps():
    """安装系统依赖 (仅 Linux)"""
    if sys.platform != "linux":
        return

    print("[2/4] 检查系统依赖...")
    deps = [
        "autoconf", "automake", "libtool", "pkg-config",
        "libffi-dev", "libssl-dev", "zlib1g-dev",
        "openjdk-17-jdk", "git", "wget", "unzip",
        "python3-dev", "libltdl-dev", "cmake",
    ]

    try:
        subprocess.run(
            ["sudo", "apt-get", "update", "-qq"],
            check=True, capture_output=True
        )
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "-qq"] + deps,
            check=True, capture_output=True
        )
        print("    ✓ 系统依赖就绪")
    except Exception as e:
        print(f"    ⚠ 部分依赖可能未安装: {e}")
        print("    如构建失败, 请手动安装上述依赖")


def build_apk():
    """使用 Buildozer 构建 APK"""
    os.chdir(SCRIPT_DIR)

    print("[3/4] 开始构建 APK (首次约需 15-30 分钟)...")
    print("    正在下载 Android SDK/NDK...")
    print("    请在下载期间保持网络连接\n")

    result = subprocess.run(
        ["buildozer", "-v", "android", "debug"],
        cwd=SCRIPT_DIR
    )

    if result.returncode != 0:
        print("\n❌ 构建失败! 常见问题:")
        print("   1. 网络问题 → 重试")
        print("   2. 磁盘空间不足 → 需要至少 4GB 空闲空间")
        print("   3. Java 版本 → 需要 JDK 17")
        print("   4. 内存不足 → 关闭其他程序")
        return False

    return True


def find_apk():
    """查找生成的 APK 文件"""
    bin_dir = SCRIPT_DIR / "bin"
    if bin_dir.exists():
        apks = list(bin_dir.glob("*.apk"))
        if apks:
            return apks[0]
    return None


def print_result(apk_path):
    """打印构建结果"""
    if apk_path and apk_path.exists():
        size_mb = apk_path.stat().st_size / (1024 * 1024)
        print(f"""
╔══════════════════════════════════════════════════╗
║   ✅ APK 构建成功!                              ║
╚══════════════════════════════════════════════════╝

  📦 APK 文件: {apk_path.name}
  📏 文件大小: {size_mb:.1f} MB

  📱 安装到手机:

    方法 1 — USB:
      • USB 连接手机 → 文件传输模式
      • 将 APK 复制到手机任意位置
      • 手机上点击 APK 文件安装

    方法 2 — 二维码:
      • 将 APK 上传到临时文件分享服务
      • 生成二维码手机扫码下载

    方法 3 — adb:
      adb install {apk_path}

  ⚠ 安装时可能需要:
    • 允许「安装未知来源应用」
    • 授予「存储」权限
""")


def google_colab_mode():
    """Google Colab 一键构建脚本"""
    colab_script = '''
# ──────────────────────────────────────────
#  Google Colab — 手机数据恢复 APK 构建
#  复制此代码到 Colab 单元格中运行
# ──────────────────────────────────────────

# 第 1 步: 安装依赖
!sudo apt-get update -qq
!sudo apt-get install -y -qq autoconf automake libtool pkg-config libffi-dev libssl-dev zlib1g-dev openjdk-17-jdk git wget unzip python3-dev libltdl-dev cmake
!pip install buildozer cython

# 第 2 步: 克隆项目 (替换为你的项目地址)
!git clone YOUR_REPO_URL phone_recovery_apk
# 或者上传文件后解压:
# !unzip phone_recovery_apk.zip

# 第 3 步: 构建 APK
%cd phone_recovery_apk
!buildozer -v android debug

# 第 4 步: 下载 APK
from google.colab import files
import glob
for apk in glob.glob("bin/*.apk"):
    files.download(apk)
    print(f"下载中: {apk}")
'''
    print(colab_script)


def main():
    print_header()

    # 检测环境
    if "COLAB_GPU" in os.environ or "--colab" in sys.argv:
        google_colab_mode()
        return

    if sys.platform != "linux":
        print("⚠ 当前不是 Linux 环境。")
        print("")
        print("构建 Android APK 需要 Linux 环境。你可以:")
        print("")
        print("  1️⃣ 使用 WSL2 (Windows 最简方案):")
        print("     • 安装 WSL2: wsl --install")
        print("     • 进入 WSL: wsl")
        print(f"     • 运行: cd {SCRIPT_DIR} && python3 build_apk.py")
        print("")
        print("  2️⃣ 使用 Google Colab (免费云端构建):")
        print("     • 打开 https://colab.research.google.com/")
        print("     • 将本文件夹上传到 Colab")
        print("     • 运行: python3 build_apk.py --colab")
        print("")
        print("  3️⃣ 使用 Docker (一键构建):")
        print("     docker run -v $(pwd):/app -it ubuntu:22.04 bash")
        print("     cd /app && python3 build_apk.py")
        return

    # Linux 环境: 开始构建
    os.chdir(SCRIPT_DIR)

    install_system_deps()
    install_buildozer()
    success = build_apk()

    if success:
        apk_path = find_apk()
        print_result(apk_path)
    else:
        print("\n构建失败, 请检查上述错误信息。")


if __name__ == "__main__":
    main()
