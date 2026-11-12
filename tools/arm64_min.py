#!/usr/bin/env python3
"""arm64_min.py - 够用就行的 ARM64 反汇编器，专治「跳到地址 0」这类崩溃

只解码排查崩溃需要的指令族：
  adrp / add / ldr(字面量|无符号偏移) / ldrb / str / mov / movz / movk
  bl / blr / br / ret / b.cond / cbz / cbnz / ldp / stp / nop / sub / cmp
其余一律输出 .word，绝不假装懂。

用法:
  python tools/arm64_min.py <二进制> <文件偏移> [前后指令数]
  python tools/arm64_min.py <二进制> <偏移> --find-zero   # 找把寄存器写成立即数 0 的指令
"""
import argparse
import struct
import sys


def sx(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def decode(w, pc):
    """返回 (文本, 副作用) 副作用用 (目标寄存器, 表达式) 表示"""
    if w == 0xD503201F:
        return "nop", None
    if w == 0xD65F03C0:
        return "ret", None
    if w == 0xD65F0BFF:
        return "ret  (x30)", None
    if (w & 0xFFFFFC1F) == 0xD65F0000:
        return f"ret  x{(w >> 5) & 0x1F}", None
    if (w & 0xFFFFFC1F) == 0xD63F0000:
        return f"blr  x{(w >> 5) & 0x1F}", None
    if (w & 0xFFFFFC1F) == 0xD61F0000:
        return f"br   x{(w >> 5) & 0x1F}", None

    # bl imm26
    if (w >> 26) == 0b100101:
        imm = sx(w & 0x03FFFFFF, 26) * 4
        return f"bl   0x{pc + imm:x}", None
    # b imm26
    if (w >> 26) == 0b000101:
        imm = sx(w & 0x03FFFFFF, 26) * 4
        return f"b    0x{pc + imm:x}", None

    # b.cond
    if (w & 0xFF000010) == 0x54000000:
        cond = w & 0xF
        imm = sx((w >> 5) & 0x7FFFF, 19) * 4
        names = ["eq","ne","cs","cc","mi","pl","vs","vc","hi","ls","ge","lt","gt","le","al","nv"]
        return f"b.{names[cond]:3} 0x{pc + imm:x}", None

    # cbz / cbnz
    if (w & 0x7E000000) == 0x34000000:
        sf = (w >> 31) & 1
        op = (w >> 24) & 1
        rt = w & 0x1F
        imm = sx((w >> 5) & 0x7FFFF, 19) * 4
        return f"{'cbnz' if op else 'cbz '} {'x' if sf else 'w'}{rt}, 0x{pc + imm:x}", None

    # adrp
    if (w & 0x9F000000) == 0x90000000:
        rd = w & 0x1F
        immlo = (w >> 29) & 3
        immhi = (w >> 5) & 0x7FFFF
        imm = sx((immhi << 2) | immlo, 21) << 12
        page = (pc & ~0xFFF) + imm
        return f"adrp x{rd}, 0x{page:x}", (rd, f"page(0x{page:x})")

    # add/sub (immediate, 64/32)
    if (w & 0x1F000000) == 0x11000000:
        sf = (w >> 31) & 1
        op = (w >> 30) & 1
        s = (w >> 29) & 1
        sh = (w >> 22) & 1
        imm12 = (w >> 10) & 0xFFF
        rn = (w >> 5) & 0x1F
        rd = w & 0x1F
        val = imm12 << (12 if sh else 0)
        m = "sub" if op else "add"
        if s:
            return f"cmp  {'x' if sf else 'w'}{rn}, #0x{val:x}", None
        return f"{m}  {'x' if sf else 'w'}{rd}, {'x' if sf else 'w'}{rn}, #0x{val:x}", (rd, f"x{rn}+0x{val:x}")

    # movz / movn / movk
    if (w & 0x1F800000) == 0x12800000 or (w & 0x1F800000) == 0x52800000:
        sf = (w >> 31) & 1
        opc = (w >> 29) & 3
        hw = (w >> 21) & 3
        imm16 = (w >> 5) & 0xFFFF
        rd = w & 0x1F
        sh = hw * 16
        if opc == 2:      # movz
            return f"movz {'x' if sf else 'w'}{rd}, #0x{imm16:x}, lsl #{sh}", (rd, f"0x{imm16 << sh:x}")
        if opc == 0:      # movn
            return f"movn {'x' if sf else 'w'}{rd}, #0x{imm16:x}, lsl #{sh}", (rd, "~imm")
        return f"movk {'x' if sf else 'w'}{rd}, #0x{imm16:x}, lsl #{sh}", (rd, None)

    # ORR (immediate) -> mov alias when rn==xzr
    if (w & 0x1F800000) == 0x32000000:
        sf = (w >> 31) & 1
        n = (w >> 22) & 1
        immr = (w >> 16) & 0x3F
        imms = (w >> 10) & 0x3F
        rn = (w >> 5) & 0x1F
        rd = w & 0x1F
        if rn == 31 and not n and imms == 0:
            val = (1 << (immr + 1)) - 1 if immr else 0
            return f"mov  {'x' if sf else 'w'}{rd}, #0x{val:x}", (rd, f"0x{val:x}")
        return f"orr  {'x' if sf else 'w'}{rd}, {'x' if sf else 'w'}{rn}, #{immr}:{imms}", None

    # LDR/STR unsigned offset (64-bit / 32-bit)
    if (w & 0x3B000000) == 0x39000000:
        size = (w >> 30) & 3
        opc = (w >> 22) & 3
        is_load = (opc & 1) == 1
        rn = (w >> 5) & 0x1F
        rt = w & 0x1F
        imm = ((w >> 10) & 0xFFF) * (1 << size)
        regw = {0: "w", 1: "w", 2: "w", 3: "x"}[size]
        mn = "ldr" if is_load else "str"
        return f"{mn}  {regw}{rt}, [x{rn}, #0x{imm:x}]", ((rt, f"[x{rn}+0x{imm:x}]") if is_load else None)

    # LDR (literal) 64/32-bit
    if (w & 0x3B000000) == 0x18000000:
        opc = (w >> 30) & 3
        rt = w & 0x1F
        imm = sx((w >> 5) & 0x7FFFF, 19) * 4
        regw = "x" if opc == 1 else "w"
        return f"ldr  {regw}{rt}, 0x{pc + imm:x}", (rt, f"*(0x{pc + imm:x})")

    # LDP/STP (pre/post/offset) 64-bit
    if (w & 0x3A000000) == 0x28000000:
        opc = (w >> 30) & 3
        rn = (w >> 5) & 0x1F
        rt = w & 0x1F
        rt2 = (w >> 10) & 0x1F
        imm = sx((w >> 15) & 0x7F, 7) * 8
        mn = {0: "stp", 1: "ldp", 2: "stp", 3: "ldp"}[opc]
        return f"{mn}  x{rt}, x{rt2}, [x{rn}, #0x{imm & 0xFFFFFFFF:x}]", None

    return f".word 0x{w:08x}", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("offset", help="文件偏移，可写 0xBC59C")
    ap.add_argument("count", nargs="?", type=int, default=40)
    ap.add_argument("--find-zero", action="store_true")
    ap.add_argument("--base", default="0x100000000")
    a = ap.parse_args()

    off = int(a.offset, 0)
    base = int(a.base, 0)
    n = a.count
    start = max(0, off - n * 4)
    data = open(a.binary, "rb").read()
    print(f"文件 {a.binary}  __TEXT 基址 {base:#x}")
    print(f"反汇编区间 0x{start:x} .. 0x{off + 40:x}\n")

    p = start
    while p < off + 40:
        if p + 4 > len(data):
            break
        w = struct.unpack_from("<I", data, p)[0]
        text, _ = decode(w, base + p)
        mark = "  <<<<<< 崩溃点" if p == off else ""
        print(f"  {p:#09x}  {w:08x}  {text}{mark}")
        p += 4


if __name__ == "__main__":
    sys.exit(main())
