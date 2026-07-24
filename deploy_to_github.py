#!/usr/bin/env python3
"""
GitHub 一键部署 — 创建仓库 → 推送代码 → 自动构建 APK → 下载

使用方法:
  python3 deploy_to_github.py

或者:
  python3 deploy_to_github.py --token ghp_xxxxxxxxxxxx
"""

import os
import sys
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_NAME = "phone-recovery-apk"
REPO_DESC = "手机数据恢复工具 — 独立 APK 无需 Termux"


def print_step(msg):
    print(f"\n  {'='*50}")
    print(f"  {msg}")
    print(f"  {'='*50}")


def get_token():
    """获取 GitHub Personal Access Token"""
    token = None

    # 1. 从命令行参数
    for i, arg in enumerate(sys.argv):
        if arg == "--token" and i + 1 < len(sys.argv):
            token = sys.argv[i + 1]

    # 2. 从环境变量
    if not token:
        token = os.environ.get("GITHUB_TOKEN")

    # 3. 从用户输入
    if not token:
        print("""
  ╔══════════════════════════════════════════════════════╗
  ║  需要 GitHub Personal Access Token (classic)        ║
  ║                                                     ║
  ║  获取方式:                                           ║
  ║  1. 打开 https://github.com/settings/tokens          ║
  ║  2. 点击 「Generate new token (classic)」            ║
  ║  3. 勾选 「repo」 权限                               ║
  ║  4. 生成后复制 token                                 ║
  ╚══════════════════════════════════════════════════════╝
  """)
        token = input("  请输入 GitHub Token: ").strip()

    return token


def get_username(token):
    """获取 GitHub 用户名"""
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PhoneRecovery",
        }
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            return data["login"]
    except Exception as e:
        print(f"  ❌ 验证 Token 失败: {e}")
        return None


def create_repo(token):
    """创建 GitHub 仓库"""
    data = json.dumps({
        "name": REPO_NAME,
        "description": REPO_DESC,
        "private": False,
        "auto_init": False,
        "has_issues": True,
    }).encode()

    req = urllib.request.Request(
        "https://api.github.com/user/repos",
        data=data,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PhoneRecovery",
            "Content-Type": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            return result.get("clone_url") or result.get("html_url")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if "already exists" in body or e.code == 422:
            print("  ⚠ 仓库已存在，将直接推送")
            username = get_username(token)
            return f"https://github.com/{username}/{REPO_NAME}.git"
        print(f"  ❌ 创建仓库失败: {e.code} - {body[:200]}")
        return None


def push_code(token, username):
    """推送代码到 GitHub"""
    os.chdir(SCRIPT_DIR)

    remote_url = f"https://{username}:{token}@github.com/{username}/{REPO_NAME}.git"

    # 检查是否有 remote
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True, cwd=SCRIPT_DIR
    )

    if result.returncode != 0:
        subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=SCRIPT_DIR)
    else:
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=SCRIPT_DIR)

    print("  正在推送代码到 GitHub...")
    result = subprocess.run(
        ["git", "push", "-u", "origin", "master", "--force"],
        capture_output=True, text=True, cwd=SCRIPT_DIR
    )

    if result.returncode == 0:
        print("  ✅ 代码推送成功！")
        return True
    else:
        print(f"  ❌ 推送失败: {result.stderr[:300]}")
        return False


def check_build_status(username, token):
    """检查 GitHub Actions 构建状态"""
    import time

    print("\n  ⏳ 等待 GitHub Actions 自动构建...")
    print(f"  查看进度: https://github.com/{username}/{REPO_NAME}/actions")
    print()

    for i in range(30):  # 最多等待 30 分钟
        time.sleep(30)
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{username}/{REPO_NAME}/actions/runs?per_page=1",
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "PhoneRecovery",
                }
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
                runs = data.get("workflow_runs", [])
                if runs:
                    status = runs[0]["status"]
                    conclusion = runs[0].get("conclusion", "")
                    print(f"\r  [{i+1}] 状态: {status} {conclusion}", end="", flush=True)

                    if status == "completed":
                        if conclusion == "success":
                            print("\n\n  ✅ APK 构建成功！")
                            return runs[0]["id"]
                        else:
                            print(f"\n\n  ❌ 构建失败: {conclusion}")
                            print(f"  查看日志: {runs[0]['html_url']}")
                            return None
        except Exception:
            pass

    print("\n  ⚠ 超时，请手动检查构建状态")
    return None


def download_apk(username, token, run_id):
    """下载构建好的 APK"""
    try:
        # 获取 artifacts
        req = urllib.request.Request(
            f"https://api.github.com/repos/{username}/{REPO_NAME}/actions/runs/{run_id}/artifacts",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "PhoneRecovery",
            }
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        for artifact in data.get("artifacts", []):
            if "apk" in artifact["name"].lower():
                download_url = artifact["archive_download_url"]
                print(f"\n  📥 正在下载 APK: {artifact['name']}")
                print(f"  大小: {artifact['size_in_bytes'] / 1024 / 1024:.1f} MB")

                # 下载 (需要认证)
                dl_req = urllib.request.Request(
                    download_url,
                    headers={
                        "Authorization": f"token {token}",
                        "User-Agent": "PhoneRecovery",
                    }
                )
                with urllib.request.urlopen(dl_req) as dl_resp:
                    zip_path = SCRIPT_DIR / f"{artifact['name']}.zip"
                    zip_path.write_bytes(dl_resp.read())

                print(f"  已保存: {zip_path}")
                print(f"\n  📱 解压后获得 APK 文件，传到手机安装即可！")
                return True
    except Exception as e:
        print(f"\n  ⚠ 下载失败: {e}")
        print(f"  请手动从 GitHub Actions 页面下载")
    return False


def main():
    print("""
╔══════════════════════════════════════════════════════╗
║   📱 手机数据恢复 — GitHub 自动构建部署            ║
╚══════════════════════════════════════════════════════╝
""")

    print_step("1. 获取 GitHub Token")
    token = get_token()
    if not token:
        return

    print_step("2. 验证 GitHub 账号")
    username = get_username(token)
    if not username:
        return
    print(f"  ✅ 账号: {username}")

    print_step("3. 创建 GitHub 仓库")
    repo_url = create_repo(token)
    if not repo_url:
        return
    print(f"  ✅ 仓库: {repo_url}")

    print_step("4. 推送代码")
    if not push_code(token, username):
        return

    print_step("5. 等待 GitHub Actions 构建")
    run_id = check_build_status(username, token)

    if run_id:
        print_step("6. 下载 APK")
        download_apk(username, token, run_id)

    print(f"""
╔══════════════════════════════════════════════════════╗
║  完成！                                              ║
║                                                     ║
║  仓库地址: https://github.com/{username}/{REPO_NAME}
║  Actions:  https://github.com/{username}/{REPO_NAME}/actions
║                                                     ║
║  以后修改代码后只需 git push 即可自动构建新 APK     ║
╚══════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
