#!/usr/bin/env python3
"""nms_save.py - 无人深空（No Man's Sky）iOS 存档解析 / 编辑 / 重打包

存档格式（.hg）：
    [0~N 字节头部] + zlib( JSON )
    部分版本是 gzip 或裸 JSON，工具会自动识别。

用法:
    python nms_save.py info   <save.hg>
    python nms_save.py dump   <save.hg> [--out save.json]
    python nms_save.py pack   <save.json> <原save.hg> <输出.hg>
    python nms_save.py set    <save.hg> --stat UNITS=4294967295
    python nms_save.py set    <save.hg> --stat NANITES=99999999 --stat UNITS=2000000000
    python nms_save.py get    <save.hg> --stat UNITS
    python nms_save.py set    <save.hg> --path "PlayerStateData/PlayerName" --value "海鸥"
    python nms_save.py list-stats <save.hg>

注意:
  * 修改前会自动生成 .bak 备份
  * 数值上限受游戏自身 int32/uint32 限制，超过会溢出成负数
  * 存档被游戏写回前，务必退出游戏（后台也算），否则改动会被覆盖
"""
import argparse
import gzip
import io
import json
import os
import shutil
import sys
import zlib


# ---------- 容器层 ----------

def split_container(data: bytes):
    """返回 (prefix_bytes, payload_bytes, kind)"""
    # 裸 JSON
    for i in range(0, min(64, len(data))):
        if data[i:i + 1] == b"{":
            try:
                json.loads(data[i:].decode("utf-8"))
                return data[:i], data[i:], "raw-json"
            except Exception:
                pass
    # gzip
    for i in range(0, min(64, len(data))):
        if data[i:i + 2] == b"\x1f\x8b":
            try:
                return data[:i], gzip.decompress(data[i:]), "gzip"
            except Exception:
                pass
    # zlib
    for i in range(0, min(64, len(data))):
        if data[i] == 0x78 and data[i + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                return data[:i], zlib.decompress(data[i:]), "zlib"
            except Exception:
                pass
    raise ValueError("无法识别的存档格式（前 64 字节里找不到 zlib/gzip/JSON 流）")


def load(path):
    with open(path, "rb") as f:
        raw = f.read()
    prefix, payload, kind = split_container(raw)
    doc = json.loads(payload.decode("utf-8"))
    return doc, prefix, kind, raw


def save(doc, prefix, kind, out_path, raw=None):
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if kind == "gzip":
        body = gzip.compress(payload, 9)
    elif kind == "raw-json":
        body = payload
    else:
        body = zlib.compress(payload, 9)
    with open(out_path, "wb") as f:
        f.write(prefix + body)
    # 自校验
    doc2, _, _, _ = load(out_path)
    if doc2 != doc:
        raise RuntimeError("写回校验失败，JSON 往返不一致")
    return len(prefix) + len(body)


# ---------- 统计项层 ----------

def iter_stat_entries(node, path=""):
    """递归找出所有形如 {"Id": "UNITS", "Value": {"IntValue": n}} 的条目"""
    if isinstance(node, dict):
        if isinstance(node.get("Id"), str) and "Value" in node:
            yield node, path
        for k, v in node.items():
            yield from iter_stat_entries(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from iter_stat_entries(v, f"{path}[{i}]")


def stat_value(entry):
    v = entry.get("Value")
    if isinstance(v, dict):
        for key in ("IntValue", "FloatValue", "StringValue", "BoolValue"):
            if key in v:
                return v[key]
    return v


def set_stat_value(entry, value):
    v = entry.get("Value")
    if isinstance(v, dict):
        if "IntValue" in v:
            v["IntValue"] = int(value)
        elif "FloatValue" in v:
            v["FloatValue"] = float(value)
        else:
            v["IntValue"] = int(value)
    else:
        entry["Value"] = {"IntValue": int(value)}


def find_stats(doc, name):
    out = []
    for entry, path in iter_stat_entries(doc):
        if entry["Id"] == name:
            out.append((entry, path))
    return out


def json_path_set(doc, path, value):
    cur = doc
    parts = [p for p in path.split("/") if p]
    for p in parts[:-1]:
        if isinstance(cur, list):
            cur = cur[int(p)]
        else:
            cur = cur[p]
    last = parts[-1]
    old = cur[int(last)] if isinstance(cur, list) else cur.get(last)
    # 保持类型
    if isinstance(old, bool):
        value = str(value).lower() in ("1", "true", "yes")
    elif isinstance(old, int):
        value = int(value)
    elif isinstance(old, float):
        value = float(value)
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value
    return old, value


# ---------- 命令 ----------

def cmd_info(a):
    doc, prefix, kind, raw = load(a.file)
    payload_len = len(json.dumps(doc))
    print(f"文件      : {a.file}")
    print(f"大小      : {len(raw):,} B")
    print(f"容器      : {kind}  头部 {len(prefix)} 字节  prefix={prefix.hex()}")
    print(f"解压 JSON : {payload_len:,} 字节")
    psd = doc.get("PlayerStateData") if isinstance(doc, dict) else None
    if isinstance(psd, dict):
        print(f"存档版本  : {doc.get('Version', '?')}  (FID: {doc.get('FID', '?')})")
        print(f"玩家名    : {psd.get('PlayerName', '?')}")
        ua = psd.get("UniverseAddress") or {}
        if isinstance(ua, dict) and ua.get("RealityIndex") is not None:
            print(f"宇宙索引  : {ua.get('RealityIndex')}")
        for key in ("Units", "Nanites", "Specials"):
            if key in psd:
                print(f"{key:<10}: {psd[key]}")
    stats = [e for e, _ in iter_stat_entries(doc)]
    print(f"统计项数量: {len(stats)}")
    for name in ("UNITS", "NANITES", "NANITES_EVER", "DIST_WALKED"):
        for e, p in find_stats(doc, name):
            print(f"  {name:<12} = {stat_value(e)}   @{p}")
            break


def cmd_dump(a):
    doc, _, _, _ = load(a.file)
    out = a.out or (os.path.splitext(a.file)[0] + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"已导出 {out}  ({os.path.getsize(out):,} B)")


def cmd_pack(a):
    with open(a.json, "r", encoding="utf-8") as f:
        doc = json.load(f)
    doc0, prefix, kind, _ = load(a.base)
    n = save(doc, prefix, kind, a.out)
    print(f"已打包 {a.out}  ({n:,} B, 容器={kind})")


def cmd_get(a):
    doc, _, _, _ = load(a.file)
    for spec in a.stat:
        hits = find_stats(doc, spec)
        if not hits:
            print(f"{spec}: 未找到")
            continue
        for e, p in hits[:5]:
            print(f"{spec} = {stat_value(e)}   @{p}")


def cmd_list_stats(a):
    doc, _, _, _ = load(a.file)
    seen = {}
    for e, p in iter_stat_entries(doc):
        seen.setdefault(e["Id"], stat_value(e))
    for k in sorted(seen):
        print(f"{k:<28} {seen[k]}")


def cmd_set(a):
    doc, prefix, kind, _ = load(a.file)
    shutil.copy2(a.file, a.file + ".bak")
    changed = 0
    for spec in a.stat or []:
        if "=" not in spec:
            print(f"跳过非法参数 {spec}（应为 NAME=VALUE）")
            continue
        name, val = spec.split("=", 1)
        hits = find_stats(doc, name)
        if not hits:
            print(f"{name}: 未找到，跳过")
            continue
        for e, p in hits:
            old = stat_value(e)
            set_stat_value(e, val)
            print(f"{name}: {old} -> {stat_value(e)}   @{p}")
            changed += 1
    for path, value in zip(a.path or [], a.value or []):
        old, new = json_path_set(doc, path, value)
        print(f"{path}: {old!r} -> {new!r}")
        changed += 1
    if not changed:
        print("没有改动。")
        return
    n = save(doc, prefix, kind, a.file)
    print(f"\n已写回 {a.file}  ({n:,} B)，备份在 {a.file}.bak")


def main():
    ap = argparse.ArgumentParser(description="No Man's Sky 存档编辑器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info"); p.add_argument("file"); p.set_defaults(func=cmd_info)
    p = sub.add_parser("dump"); p.add_argument("file"); p.add_argument("--out"); p.set_defaults(func=cmd_dump)
    p = sub.add_parser("pack"); p.add_argument("json"); p.add_argument("base"); p.add_argument("out"); p.set_defaults(func=cmd_pack)
    p = sub.add_parser("get"); p.add_argument("file"); p.add_argument("--stat", action="append"); p.set_defaults(func=cmd_get)
    p = sub.add_parser("list-stats"); p.add_argument("file"); p.set_defaults(func=cmd_list_stats)
    p = sub.add_parser("set"); p.add_argument("file")
    p.add_argument("--stat", action="append", help="NAME=VALUE，可重复")
    p.add_argument("--path", action="append", help="JSON 路径，如 PlayerStateData/PlayerName")
    p.add_argument("--value", action="append", help="配合 --path 使用，可重复")
    p.set_defaults(func=cmd_set)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
