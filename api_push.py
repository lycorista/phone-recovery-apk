#!/usr/bin/env python3
"""
通过 GitHub API 直接推送代码 + 触发构建 + 下载 APK
绕过 git push 的网络限制
"""

import os
import sys
import json
import base64
import time
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_NAME = "phone-recovery-apk"
TOKEN = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_TOKEN", "")
USERNAME = "lycorista"
BRANCH = "master"

API_BASE = "https://api.github.com"
HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "PhoneRecovery",
}


def api(method, path, data=None):
    """调用 GitHub API"""
    url = f"{API_BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()) if resp.status != 204 else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  API Error [{e.code}]: {err[:300]}")
        return None


def get_all_files():
    """获取项目中所有需要上传的文件"""
    files = {}
    ignore = {".git", "__pycache__", "bin", ".buildozer", ".gradle"}

    for f in SCRIPT_DIR.rglob("*"):
        if f.is_file() and not any(p in ignore for p in f.parts):
            rel = str(f.relative_to(SCRIPT_DIR)).replace("\\", "/")
            with open(f, "rb") as fh:
                files[rel] = fh.read()
    return files


def push_via_api():
    """通过 GitHub API 推送整个项目"""
    print("  [1/6] 准备文件...")
    files = get_all_files()
    print(f"        {len(files)} 个文件待上传")

    # 1. 获取当前 HEAD ref
    print("  [2/6] 获取仓库状态...")
    ref = api("GET", f"/repos/{USERNAME}/{REPO_NAME}/git/ref/heads/{BRANCH}")
    if not ref:
        # 仓库是空的，需要先初始化
        print("        ⚠ 仓库为空，先创建初始提交...")
        api("PUT", f"/repos/{USERNAME}/{REPO_NAME}/contents/README.md", {
            "message": "初始化仓库",
            "content": base64.b64encode(b"# Phone Recovery APK").decode(),
            "branch": BRANCH,
        })
        time.sleep(2)
        ref = api("GET", f"/repos/{USERNAME}/{REPO_NAME}/git/ref/heads/{BRANCH}")

    if not ref:
        print("        ❌ 无法获取仓库引用")
        return False

    # 获取 commit 对象以取得 tree SHA
    commit_sha = ref["object"]["sha"]
    commit_obj = api("GET", f"/repos/{USERNAME}/{REPO_NAME}/git/commits/{commit_sha}")
    if not commit_obj:
        print("        ❌ 无法获取 commit 对象")
        return False

    parent_tree_sha = commit_obj["tree"]["sha"]
    print(f"        HEAD commit: {commit_sha[:8]}  tree: {parent_tree_sha[:8]}")

    # 2. 为每个文件创建 blob
    print("  [3/6] 创建文件 blobs...")
    blobs = []
    for path, content in sorted(files.items()):
        blob = api("POST", f"/repos/{USERNAME}/{REPO_NAME}/git/blobs", {
            "content": base64.b64encode(content).decode(),
            "encoding": "base64",
        })
        if blob:
            blobs.append({
                "path": path,
                "mode": "100644",
                "type": "blob",
                "sha": blob["sha"],
            })
            print(f"        ✓ {path} ({blob['sha'][:8]})")

    if not blobs:
        print("        ❌ 没有文件被上传")
        return False

    # 3. 创建 tree (不用 base_tree，直接包含所有文件)
    print("  [4/6] 创建 tree...")
    tree = api("POST", f"/repos/{USERNAME}/{REPO_NAME}/git/trees", {
        "tree": blobs,
    })
    if not tree:
        return False
    print(f"        Tree: {tree['sha'][:8]}")

    # 4. 创建 commit
    print("  [5/6] 创建 commit...")
    commit = api("POST", f"/repos/{USERNAME}/{REPO_NAME}/git/commits", {
        "message": "手机数据恢复 APK v1.0 - 全部文件",
        "tree": tree["sha"],
        "parents": [commit_sha],
    })
    if not commit:
        return False
    print(f"        Commit: {commit['sha'][:8]}")

    # 5. 更新 ref
    print("  [6/6] 更新分支 ref...")
    result = api("PATCH", f"/repos/{USERNAME}/{REPO_NAME}/git/refs/heads/{BRANCH}", {
        "sha": commit["sha"],
        "force": True,
    })
    if result:
        print("        ✅ 代码推送成功！")
        return True
    return False


def wait_for_build():
    """等待 GitHub Actions 构建完成并下载 APK"""
    print("\n  ⏳ 等待 GitHub Actions 自动构建...")
    print(f"  在线查看: https://github.com/{USERNAME}/{REPO_NAME}/actions\n")

    # 等待工作流启动
    time.sleep(10)

    for attempt in range(60):  # 最多等 30 分钟
        time.sleep(30)
        try:
            runs = api("GET", f"/repos/{USERNAME}/{REPO_NAME}/actions/runs?per_page=3")
            if not runs:
                continue

            for run in runs.get("workflow_runs", []):
                status = run["status"]
                conclusion = run.get("conclusion", "")
                run_id = run["id"]

                mins = (attempt + 1) * 0.5
                print(f"\r  [{mins:.0f}min] 状态: {status} {conclusion}  run_id={run_id}", end="", flush=True)

                if status == "completed":
                    print()
                    if conclusion == "success":
                        return run_id
                    else:
                        print(f"\n  ❌ 构建失败!")
                        print(f"  查看日志: {run['html_url']}")
                        return None
                break  # 只看最新的

        except Exception as e:
            print(f"\n  ⚠ 查询失败: {e}")

    print("\n  ⚠ 等待超时 (30分钟)")
    return None


def download_apk(run_id):
    """下载构建好的 APK"""
    if not run_id:
        return

    artifacts = api("GET", f"/repos/{USERNAME}/{REPO_NAME}/actions/runs/{run_id}/artifacts")
    if not artifacts:
        return

    for artifact in artifacts.get("artifacts", []):
        name = artifact["name"]
        if "apk" in name.lower():
            url = artifact["archive_download_url"]
            size_mb = artifact["size_in_bytes"] / 1024 / 1024

            print(f"\n  📥 下载 APK: {name} ({size_mb:.1f} MB)")

            dl_headers = dict(HEADERS)
            dl_req = urllib.request.Request(url, headers=dl_headers)
            try:
                with urllib.request.urlopen(dl_req, timeout=60) as resp:
                    zip_path = SCRIPT_DIR / f"{name}.zip"
                    zip_path.write_bytes(resp.read())
                print(f"  ✅ 已保存: {zip_path}")
                print(f"\n  📱 解压后获得 APK，传到手机安装即可！")
            except Exception as e:
                print(f"  ⚠ 下载失败: {e}")
                print(f"  手动下载: https://github.com/{USERNAME}/{REPO_NAME}/actions/runs/{run_id}")
            return

    print(f"\n  ⚠ 未找到 APK artifact")
    print(f"  手动查看: https://github.com/{USERNAME}/{REPO_NAME}/actions/runs/{run_id}")


def main():
    if not TOKEN:
        print("用法: python api_push.py <github_token>")
        return

    print("""
╔══════════════════════════════════════════════════════╗
║   📱 手机数据恢复 — API 直推 + 自动构建          ║
╚══════════════════════════════════════════════════════╝
""")
    print(f"  账号: {USERNAME}")
    print(f"  仓库: {USERNAME}/{REPO_NAME}")
    print()

    # 推送代码
    if not push_via_api():
        print("\n  ❌ 推送失败")
        return

    # 等待构建
    run_id = wait_for_build()

    # 下载 APK
    if run_id:
        download_apk(run_id)

    print(f"\n  ✅ 完成！仓库: https://github.com/{USERNAME}/{REPO_NAME}")


if __name__ == "__main__":
    main()
