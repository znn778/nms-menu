#!/usr/bin/env python3
"""nms_starter.py - 把一份真实的生存档改成"满资源开局"

前提：必须拿游戏自己生成的存档当模板（结构、版本号、宇宙地址都是游戏写的，
      凭空构造必崩）。用法分两步：

  1) 先看结构（不改文件）
     python nms_starter.py inspect save.hg

  2) 改成满配
     python nms_starter.py apply save.hg --out save_starter.hg

apply 做的事（都是结构驱动，不硬编码路径）：
  * Stats 里 UNITS / NANITES 拉满
  * 所有带 Amount + MaxAmount 的槽位：Amount = MaxAmount（资源/弹药/燃料全满）
  * 所有带 "IsUnlocked"/"Unlocked" 的槽位：置 True
  * 打印改了哪些容器、多少槽位，便于核对

不做的事（做不到，别指望）：
  * 凭空加科技（KnownTech 需要完整科技 ID 表，在 GAMEDATA 的 MBIN 里）
  * 凭空加物品槽（锁定槽不在 JSON 里，是引擎按库存等级算出来的）
"""
import argparse
import json
import os
import shutil
import sys
import zlib

MAX_UNITS = 2_000_000_000
MAX_NANITES = 100_000_000


# ---------- 容器 ----------

def split_container(data: bytes):
    for i in range(min(64, len(data))):
        if data[i] == 0x78 and data[i + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                return data[:i], zlib.decompress(data[i:]), "zlib"
            except Exception:
                pass
    raise ValueError("找不到 zlib 流，不是有效 .hg")


def load(path):
    raw = open(path, "rb").read()
    prefix, payload, kind = split_container(raw)
    return json.loads(payload.decode("utf-8")), prefix, kind


def save(doc, prefix, out):
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
    open(out, "wb").write(prefix + zlib.compress(payload, 9))


# ---------- 遍历 ----------

def walk(node, path=""):
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


def stat_entries(doc):
    out = []
    for p, n in walk(doc):
        if isinstance(n, dict) and isinstance(n.get("Id"), str) and "Value" in n:
            out.append((n, p))
    return out


def stat_value(e):
    v = e.get("Value")
    if isinstance(v, dict):
        for k in ("IntValue", "FloatValue"):
            if k in v:
                return v[k]
    return v


# ---------- 命令 ----------

def cmd_inspect(a):
    doc, prefix, kind = load(a.file)
    print(f"文件   : {a.file}")
    print(f"容器   : {kind}  头部 {len(prefix)}B  {prefix.hex()}")
    print(f"顶层键 : {list(doc.keys()) if isinstance(doc, dict) else type(doc)}")

    psd = doc.get("PlayerStateData") if isinstance(doc, dict) else None
    if isinstance(psd, dict):
        print(f"\nPlayerStateData 键数: {len(psd)}")
        inv_keys = [k for k in psd if "nventory" in k]
        print(f"库存容器: {inv_keys}")
        for k in inv_keys:
            v = psd[k]
            slots = v.get("Slots") if isinstance(v, dict) else None
            if isinstance(slots, list):
                print(f"  {k:<24} 槽位 {len(slots)}")
        for k in ("KnownTech", "KnownProducts", "KnownSpecials", "KnownWords"):
            if k in psd:
                print(f"  {k:<24} {len(psd[k]) if isinstance(psd[k], list) else '?'} 条")
        print(f"  玩家名: {psd.get('PlayerName')}")
        print(f"  Difficulty: {psd.get('Difficulty') or psd.get('PlayerStateData_Difficulty') or '?'}")

    print("\n统计项（前 20）:")
    for e, p in stat_entries(doc)[:20]:
        print(f"  {e['Id']:<22} = {stat_value(e)}")

    # 槽位样本
    samples = [(p, n) for p, n in walk(doc)
               if isinstance(n, dict) and "Amount" in n and "MaxAmount" in n]
    print(f"\n可填满的槽位: {len(samples)}")
    for p, n in samples[:3]:
        print(f"  {p}")
        print(f"    {json.dumps(n, ensure_ascii=False)[:200]}")


def cmd_apply(a):
    doc, prefix, kind = load(a.file)
    shutil.copy2(a.file, a.file + ".bak")

    changed_stats = []
    for e, p in stat_entries(doc):
        sid = e["Id"]
        if sid == "UNITS":
            e["Value"] = {"IntValue": MAX_UNITS}
            changed_stats.append(("UNITS", stat_value(e)))
        elif sid == "NANITES":
            e["Value"] = {"IntValue": MAX_NANITES}
            changed_stats.append(("NANITES", stat_value(e)))

    filled, unlocked, containers = 0, 0, {}
    for p, n in walk(doc):
        if not isinstance(n, dict):
            continue
        if "Amount" in n and "MaxAmount" in n:
            try:
                mx = int(n["MaxAmount"])
                if mx > 0 and n["Amount"] != mx:
                    n["Amount"] = mx
                    filled += 1
                    key = p.split("/")[2] if p.count("/") > 2 else p
                    containers[key] = containers.get(key, 0) + 1
            except (TypeError, ValueError):
                pass
        for flag in ("IsUnlocked", "Unlocked"):
            if flag in n and n[flag] is False:
                n[flag] = True
                unlocked += 1

    save(doc, prefix, a.out)
    print(f"已写入 {a.out}")
    for k, v in changed_stats:
        print(f"  {k} = {v}")
    print(f"  填满槽位: {filled}")
    for k, v in sorted(containers.items()):
        print(f"    {k}: {v}")
    print(f"  解锁标记: {unlocked}")
    print(f"  备份: {a.file}.bak")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect")
    p.add_argument("file")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("apply")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_apply)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
