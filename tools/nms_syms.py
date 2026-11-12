#!/usr/bin/env python3
"""nms_syms.py - 从 Mach-O 符号表提取并反混淆 C++ 符号（纯 Python）

用法:
    python nms_syms.py search "cGcPlayer" "Jetpack"      # 关键词 AND 匹配
    python nms_syms.py search "InventoryStore" "Remove"
    python nms_syms.py export cGcPlayer                  # 导出所有匹配符号到 TSV
    python nms_syms.py stats

输出列: 虚拟地址(vmaddr) 文件偏移 大小? 反混淆名
"""
import os
import struct
import sys

TEXT_VMADDR = 0x100000000  # __TEXT 的 vmaddr，fileoff=0


# ---------------- Itanium ABI 简易反混淆 ----------------

BUILTIN = {
    "v": "void", "b": "bool", "c": "char", "a": "signed char", "h": "unsigned char",
    "s": "short", "t": "unsigned short", "i": "int", "j": "unsigned int",
    "l": "long", "m": "unsigned long", "x": "long long", "y": "unsigned long long",
    "f": "float", "d": "double", "e": "long double", "w": "wchar_t",
}


class Demangler:
    def __init__(self, s):
        self.s = s
        self.i = 0

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def num(self):
        start = self.i
        while self.i < len(self.s) and self.s[self.i].isdigit():
            self.i += 1
        return int(self.s[start:self.i]) if self.i > start else 0

    def name(self):
        if self.peek() == "N":
            self.i += 1
            return self.nested()
        return self.source_name()

    def nested(self):
        parts = []
        while self.peek() and self.peek() != "E":
            c = self.peek()
            if c in "rVKRO":
                self.i += 1
                continue
            if c.isdigit():
                parts.append(self.source_name())
            else:
                parts.append(self.operator_or_special())
        if self.peek() == "E":
            self.i += 1
        return "::".join(p for p in parts if p)

    def operator_or_special(self):
        # 简化处理：跳过未知标记
        self.i += 1
        return ""

    def source_name(self):
        n = self.num()
        if n == 0:
            return self.operator_name()
        s = self.s[self.i:self.i + n]
        self.i += n
        return s

    def operator_name(self):
        two = self.s[self.i:self.i + 2]
        table = {"nw": "operator new", "dl": "operator delete", "eq": "operator==",
                 "ne": "operator!=", "lt": "operator<", "gt": "operator>",
                 "pl": "operator+", "mi": "operator-", "ml": "operator*",
                 "dv": "operator/", "cl": "operator()", "ix": "operator[]"}
        if two in table:
            self.i += 2
            return table[two]
        self.i += 1
        return "?"

    def type_(self):
        c = self.peek()
        if not c:
            return ""
        if c in BUILTIN:
            self.i += 1
            return BUILTIN[c]
        if c in "PKRrV":
            self.i += 1
            inner = self.type_()
            return {"P": inner + "*", "K": "const " + inner,
                    "R": inner + "&", "r": inner + "&", "V": inner}[c]
        if c.isdigit():
            self.i += 1  # 数字前缀
            return self.name()
        if c == "N":
            return self.name()
        if c == "S":
            # 替换/标准库，简化跳过
            while self.peek() and self.peek() != "E":
                self.i += 1
            if self.peek() == "E":
                self.i += 1
            return "std::?"
        self.i += 1
        return "?"

    def params(self):
        out = []
        while self.peek() and self.peek() != "E":
            if self.peek() == "v":
                self.i += 1
                return ["void"]
            out.append(self.type_())
            if len(out) > 12:
                break
        return out


def demangle(mangled):
    if not mangled.startswith("__Z") and not mangled.startswith("_Z"):
        return mangled
    s = mangled[3:] if mangled.startswith("__Z") else mangled[2:]
    try:
        d = Demangler(s)
        name = d.name()
        if d.peek() == "E":
            d.i += 1
        ps = d.params()
        if ps:
            return f"{name}({', '.join(ps)})"
        return name
    except Exception:
        return mangled


# ---------------- Mach-O ----------------

def load_symbols(path):
    buf = open(path, "rb").read()
    ncmds = struct.unpack_from("<I", buf, 16)[0]
    off = 32
    symtab = None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", buf, off)
        if cmd == 0x2:
            symtab = struct.unpack_from("<IIII", buf, off + 8)
        off += size
    if not symtab:
        raise SystemExit("没有符号表，二进制已剥离")

    symoff, nsyms, stroff, strsize = symtab
    strtab = buf[stroff:stroff + strsize]
    out = []
    for i in range(nsyms):
        n_strx, n_type, n_sect, n_desc, n_value = struct.unpack_from("<IBBHQ", buf, symoff + i * 16)
        if (n_type & 0x0e) != 0x0e or n_value == 0:
            continue
        if n_strx >= len(strtab):
            continue
        end = strtab.find(b"\0", n_strx)
        name = strtab[n_strx:end].decode("utf-8", "replace")
        if not name:
            continue
        out.append((name, n_value))
    return out


def cmd_search(path, kws):
    syms = load_symbols(path)
    hits = [(n, v) for n, v in syms if all(k in n for k in kws)]
    print(f"匹配 {len(hits)} 个符号（关键词: {' + '.join(kws)}）\n")
    seen = set()
    for n, v in hits:
        d = demangle(n)
        if d in seen:
            continue
        seen.add(d)
        print(f"  {v:#012x}  off={v - TEXT_VMADDR:#09x}  {d[:150]}")


def cmd_export(path, kws):
    syms = load_symbols(path)
    hits = [(n, v) for n, v in syms if all(k in n for k in kws)]
    out = "symbols_" + "_".join(kws) + ".tsv"
    with open(out, "w", encoding="utf-8") as f:
        f.write("vmaddr\tfileoff\tmangled\tdemangled\n")
        for n, v in sorted(hits, key=lambda x: x[1]):
            f.write(f"{v:#x}\t{v - TEXT_VMADDR:#x}\t{n}\t{demangle(n)}\n")
    print(f"已导出 {len(hits)} 条到 {out}")


def cmd_stats(path):
    syms = load_symbols(path)
    print(f"已定义符号: {len(syms):,}")
    from collections import Counter
    pre = Counter()
    for n, _ in syms:
        d = demangle(n)
        pre[d.split("(")[0].split("::")[0][:28]] += 1
    for k, v in pre.most_common(15):
        print(f"  {k:<30} {v:,}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    cmd, path = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    if cmd == "search":
        cmd_search(path, rest)
    elif cmd == "export":
        cmd_export(path, rest)
    elif cmd == "stats":
        cmd_stats(path)
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
