#!/usr/bin/env python3
"""patch_binary.py - 把 ARM64 代码补丁直接烧进主二进制（不注入任何 dylib）

这条路完全不碰 dyld 依赖链，装机后不可能因为「库找不到」闪退。
代价：补丁是常开的，不能在游戏里开关。

用法:
  python tools/patch_binary.py check  <主二进制>          # 只看 4 个补丁点是否匹配
  python tools/patch_binary.py apply  <主二进制> [--only jetpack,godmode]
  python tools/patch_binary.py revert <主二进制>

地址全部来自 7.13 未剥离符号表反混淆，并用 8 字节原始机器码做校验，
版本不一致时直接拒绝，不会把程序改坏。
"""
import argparse
import shutil
import struct
import sys

# ARM64 指令编码
INSN_RET       = 0xD65F03C0
INSN_MOV_W0_0  = 0x52800000
INSN_MOV_W0_1  = 0x52800020
INSN_FMOV_S0_0 = 0x1E2703E0

# key, 标题, 文件偏移, 补丁 8 字节, 期望 8 字节
PATCHES = [
    ("jetpack",  "无限喷气背包",
     0x0DF5C5C, ((INSN_RET << 32) | INSN_FMOV_S0_0), 0x910003FDA9BF7BFD),
    ("shipfuel", "无限飞船燃料",
     0x10A0B10, ((INSN_RET << 32) | INSN_RET),       0x6D0623E9D10283FF),
    ("noitem",   "物品不消耗",
     0x02A18F8, ((INSN_RET << 32) | INSN_MOV_W0_1),  0xA90157F6D10103FF),
    ("godmode",  "无敌（玩家伤害）",
     0x0E13870, ((INSN_RET << 32) | INSN_MOV_W0_0),  0xA9014FF4D100C3FF),
]

MAGIC64 = 0xFEEDFACF


def load(path):
    with open(path, "rb") as f:
        return bytearray(f.read())


def sanity(buf):
    m = struct.unpack_from("<I", buf, 0)[0]
    if m != MAGIC64:
        raise SystemExit(f"不是 thin arm64 Mach-O (magic=0x{m:08x})")
    ncmds = struct.unpack_from("<I", buf, 16)[0]
    print(f"ncmds={ncmds}  size={len(buf):,}")


def read8(buf, off):
    return struct.unpack_from("<Q", buf, off)[0]


def cmd_check(buf, only):
    ok = 0
    for key, title, off, patch, expect in PATCHES:
        if only and key not in only:
            continue
        cur = read8(buf, off)
        if cur == expect:
            print(f"  [原版] {key:9} off=0x{off:08x}  {cur:016x}  {title}")
            ok += 1
        elif cur == patch:
            print(f"  [已打] {key:9} off=0x{off:08x}  {cur:016x}  {title}")
            ok += 1
        else:
            print(f"  [不符] {key:9} off=0x{off:08x}  实际 {cur:016x} 期望 {expect:016x}  {title}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "apply", "revert"])
    ap.add_argument("binary")
    ap.add_argument("--only", default="", help="逗号分隔，只处理这些 key")
    ap.add_argument("--out", default="", help="输出路径，默认原地改（会先备份 .bak）")
    a = ap.parse_args()

    only = {s.strip() for s in a.only.split(",") if s.strip()}
    buf = load(a.binary)
    sanity(buf)

    print("\n--- 补丁点校验 ---")
    cmd_check(buf, only)

    if a.action == "check":
        return 0

    out = a.out or a.binary
    if a.action == "apply":
        if not a.out:
            shutil.copy2(a.binary, a.binary + ".bak")
            print(f"\n已备份: {a.binary}.bak")
        n = 0
        print("\n--- 写入 ---")
        for key, title, off, patch, expect in PATCHES:
            if only and key not in only:
                continue
            cur = read8(buf, off)
            if cur == patch:
                print(f"  = {key} 已是补丁状态，跳过")
                continue
            if cur != expect:
                print(f"  X {key} 原始字节不匹配，拒绝打补丁")
                continue
            struct.pack_into("<Q", buf, off, patch)
            n += 1
            print(f"  + {key}  {expect:016x} -> {patch:016x}")
        print(f"\n共写入 {n} 处")
    else:
        if not a.out:
            shutil.copy2(a.binary, a.binary + ".bak")
        n = 0
        print("\n--- 还原 ---")
        for key, title, off, patch, expect in PATCHES:
            if only and key not in only:
                continue
            cur = read8(buf, off)
            if cur == patch:
                struct.pack_into("<Q", buf, off, expect)
                n += 1
                print(f"  - {key}  还原为 {expect:016x}")
            else:
                print(f"  = {key} 不是补丁状态，跳过")
        print(f"\n共还原 {n} 处")

    with open(out, "wb") as f:
        f.write(buf)
    print(f"写出: {out}  ({len(buf):,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
