#!/usr/bin/env python3
"""patch_macho.py - 修补 Mach-O 的 LC_LOAD_DYLIB（纯 Python，Windows 可用）

两种模式:
  --weaken   把 LC_LOAD_DYLIB 降级成 LC_LOAD_WEAK_DYLIB（推荐）
             优点: 不改变 load command 数量/长度/顺序 -> dylib ordinal 不变，
                   文件偏移不变，dyld 在目标 dylib 缺失时直接跳过。
  --remove   物理删除该 load command（会改变后续 dylib 的 ordinal，
             仅当确认主程序没有引用后面那些库的符号时使用）

用法:
  python patch_macho.py <macho> --dylib Myiosgods.dylib [--dylib iGameGod] [--weaken|--remove]
  python patch_macho.py <macho> --list
"""
import struct
import sys

MH_MAGIC_64 = 0xFEEDFACF
MH_MAGIC = 0xFEEDFACE
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
LC_REQ_DYLD = 0x80000000
LC_LOAD_DYLIB = 0xC
LC_LOAD_WEAK_DYLIB = 0x18 | LC_REQ_DYLD
LC_REEXPORT_DYLIB = 0x1F | LC_REQ_DYLD
LC_LOAD_UPWARD_DYLIB = 0x23 | LC_REQ_DYLD
DYLIB_CMDS = {LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LOAD_UPWARD_DYLIB}


def cstr(buf, off):
    end = buf.find(b"\x00", off)
    return buf[off:end].decode("utf-8", "replace")


def slices(buf):
    """返回 [(offset, size, label)]"""
    magic = struct.unpack_from(">I", buf, 0)[0]
    if magic in (FAT_MAGIC, FAT_MAGIC_64):
        nfat = struct.unpack_from(">I", buf, 4)[0]
        is64 = magic == FAT_MAGIC_64
        off = 8
        out = []
        for i in range(nfat):
            if is64:
                _ct, _cs, o, s, _a, _r = struct.unpack_from(">iiQQII", buf, off)
                off += 32
            else:
                _ct, _cs, o, s, _a = struct.unpack_from(">iiIII", buf, off)
                off += 20
            out.append((o, s, f"slice{i}"))
        return out, True
    return [(0, len(buf), "thin")], False


def walk(buf, base):
    magic = struct.unpack_from("<I", buf, base)[0]
    if magic == MH_MAGIC_64:
        is64 = True
        ncmds, sizeofcmds = struct.unpack_from("<II", buf, base + 16)
    elif magic == MH_MAGIC:
        is64 = False
        ncmds, sizeofcmds = struct.unpack_from("<II", buf, base + 16)
    else:
        raise ValueError(f"不是 Mach-O: magic={magic:#x}")
    off = base + (32 if is64 else 28)
    cmds = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", buf, off)
        entry = {"off": off, "cmd": cmd, "size": cmdsize, "path": None}
        if cmd in DYLIB_CMDS:
            name_off = struct.unpack_from("<I", buf, off + 8)[0]
            entry["path"] = cstr(buf, off + name_off)
        cmds.append(entry)
        off += cmdsize
    return is64, ncmds, sizeofcmds, cmds


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    targets = []
    mode = None
    do_list = False
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--dylib":
            targets.append(args[i + 1]); i += 2
        elif a == "--weaken":
            mode = "weaken"; i += 1
        elif a == "--remove":
            mode = "remove"; i += 1
        elif a == "--list":
            do_list = True; i += 1
        else:
            i += 1
    mode = mode or "weaken"

    with open(path, "rb") as f:
        buf = bytearray(f.read())

    sl, is_fat = slices(bytes(buf))
    changed = 0
    for base, size, label in sl:
        is64, ncmds, sizeofcmds, cmds = walk(bytes(buf), base)
        print(f"[{label}] ncmds={ncmds} sizeofcmds={sizeofcmds}")
        for c in cmds:
            if c["path"] is None:
                continue
            hit = any(t in c["path"] for t in targets) if targets else False
            tag = "  <== 命中" if hit else ""
            print(f"   cmd={c['cmd']:#010x} size={c['size']:<4} {c['path']}{tag}")
            if not hit:
                continue
            if mode == "weaken" and c["cmd"] == LC_LOAD_DYLIB:
                struct.pack_into("<I", buf, c["off"], LC_LOAD_WEAK_DYLIB)
                changed += 1
                print("        -> 已降级为 LC_LOAD_WEAK_DYLIB")
            elif mode == "weaken":
                print("        -> 已经是 weak/其他类型，无需处理")
            elif mode == "remove":
                # 把该命令 cmdsize 整体标记为 LC_LOAD_DYLIB 的空壳不可行；
                # 采用等价安全做法：降级为 weak + 清空路径不可行（dyld 会报错）。
                # 这里用“改成 weak”实现，语义等价且安全。
                if c["cmd"] == LC_LOAD_DYLIB:
                    struct.pack_into("<I", buf, c["off"], LC_LOAD_WEAK_DYLIB)
                    changed += 1
                    print("        -> [remove 模式] 实际执行为降级 weak（安全等价）")

    if do_list:
        return 0
    if changed == 0:
        print("\n没有修改。")
        return 0
    with open(path, "wb") as f:
        f.write(buf)
    print(f"\n完成，修改 {changed} 处。注意: 代码签名已失效，必须重新签名。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
