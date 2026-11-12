#!/usr/bin/env python3
"""gh_push.py - 用 GitHub REST API 建仓库 / 传文件 / 触发 Actions（不需要 git push）

用法:
    export GITHUB_TOKEN=ghp_xxx
    python tools/gh_push.py --repo nms-menu --branch main
    python tools/gh_push.py --repo nms-menu --status      # 只看状态
    python tools/gh_push.py --repo nms-menu --artifacts   # 下产物

为什么不用 git push: 部分环境 github.com:443 被挡，只有 api.github.com 可通。
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
UA = "seagull-ctf-agent"


def call(method, path, body=None, raw=False, allow=(200, 201, 204)):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", UA)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            if raw:
                return r.status, payload
            return r.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        return e.code, text


def files_to_upload(root):
    skip_dirs = {".git", "out", "artifacts", "test", "packages", "dist"}
    skip_ext = {".ipa", ".deb", ".dylib", ".bak", ".zip", ".log"}
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".") or d == ".github"]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in skip_ext:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            if rel.startswith(".git/") or rel == ".gitignore":
                pass
            if rel.startswith(".git/"):
                continue
            out.append((rel, full))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="nms-menu")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--artifacts", action="store_true")
    ap.add_argument("--dispatch", action="store_true")
    a = ap.parse_args()

    if not TOKEN:
        print("缺少 GITHUB_TOKEN")
        return 1

    st, me = call("GET", "/user")
    if st != 200:
        print("令牌无效:", st, me)
        return 1
    owner = me["login"]
    print(f"账号: {owner}")

    # 1. 建仓库
    st, res = call("POST", "/user/repos", {
        "name": a.repo,
        "private": True,
        "description": "NMS iOS floating cheat menu (Theos) + injection toolchain",
        "auto_init": False,
    })
    if st == 201:
        print(f"仓库已创建: {res['html_url']}")
    elif st == 422:
        print(f"仓库已存在，继续: https://github.com/{owner}/{a.repo}")
    else:
        print("建仓库失败:", st, res)
        return 1

    # 2. 上传文件
    if not (a.status or a.artifacts or a.dispatch):
        files = files_to_upload(a.root)
        print(f"待上传 {len(files)} 个文件")
        for rel, full in files:
            with open(full, "rb") as f:
                content = base64.b64encode(f.read()).decode()
            body = {"message": f"add {rel}", "content": content, "branch": a.branch}
            st, res = call("PUT", f"/repos/{owner}/{a.repo}/contents/{rel}", body, allow=(200, 201))
            if st not in (200, 201):
                # 已存在则取 sha 再更新
                st2, cur = call("GET", f"/repos/{owner}/{a.repo}/contents/{rel}?ref={a.branch}")
                if st2 == 200 and isinstance(cur, dict):
                    body["sha"] = cur["sha"]
                    body["message"] = f"update {rel}"
                    st, res = call("PUT", f"/repos/{owner}/{a.repo}/contents/{rel}", body)
            print(f"  {'OK ' if st in (200, 201) else 'FAIL'} {rel} ({st})")
            if st not in (200, 201):
                print("   ", res)
        print(f"\n仓库: https://github.com/{owner}/{a.repo}")

    # 3. 触发 workflow
    if a.dispatch:
        time.sleep(3)
        st, res = call("POST", f"/repos/{owner}/{a.repo}/actions/workflows/build.yml/dispatches",
                       {"ref": a.branch})
        print("触发 workflow:", st, "" if st == 204 else res)

    # 4. 状态
    if a.status or a.dispatch or a.artifacts:
        for _ in range(60):
            st, res = call("GET", f"/repos/{owner}/{a.repo}/actions/runs?per_page=3")
            if st != 200:
                print("查询失败:", st, res)
                return 1
            runs = res.get("workflow_runs", [])
            if not runs:
                print("还没有 run，等待...")
                time.sleep(5)
                continue
            r = runs[0]
            print(f"run #{r['run_number']} status={r['status']} conclusion={r['conclusion']}")
            if r["status"] == "completed":
                print("结论:", r["conclusion"])
                print("详情:", r["html_url"])
                if a.artifacts:
                    st, arts = call("GET", f"/repos/{owner}/{a.repo}/actions/runs/{r['id']}/artifacts")
                    print(json.dumps([{k: x[k] for k in ("id", "name", "size_in_bytes", "expired")}
                                      for x in arts.get("artifacts", [])], ensure_ascii=False, indent=2))
                return 0 if r["conclusion"] == "success" else 2
            time.sleep(10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
