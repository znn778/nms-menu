#!/usr/bin/env python3
"""macho_inject.py - 往 Mach-O 里加一条 LC_LOAD_DYLIB（纯 Python，Windows 可用）

原理: 利用 __TEXT 里 load command 区域到第一个 section 之间的空白填充，
      把新命令写进去，再更新 ncmds / sizeofcmds。不移动任何已有数据。

用法:
    python macho_inject.py <macho> --add @executable_path/Frameworks/NMSMenu.dylib
    python macho_inject.py <macho> --check        # 只看剩余空间

注意: 注入后代码签名失效，必须重签。
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_macho as pm  # noqa: E402

LC_SEGMENT_64 = 0x19
LC_SEGMENT = 0x1
LC_LOAD_DYLIB = 0xC


def load_cmd_region(buf, base):
    magic = struct.unpack_from("<I", buf, base)[0]
    is64 = magic == pm.MH_MAGIC_64
    ncmds, sizeofcmds = struct.unpack_from("<II", buf, base + 16)
    start = base + (32 if is64 else 28)
    return is64, ncmds, sizeofcmds, start


def first_section_offset(buf, base):
    is64, ncmds, sizeofcmds, off = load_cmd_region(buf, base)
    end = off + sizeofcmds
    best = None
    while off < end:
        cmd, size = struct.unpack_from("<II", buf, off)
        if size < 8:
            break
        if cmd == LC_SEGMENT_64:
            nsects = struct.unpack_from("<I", buf, off + 64)[0]
            so = off + 72
            for _ in range(nsects):
                sec_off = struct.unpack_from("<I", buf, so + 48)[0]
                if sec_off > 0 and (best is None or sec_off < best):
                    best = sec_off
                so += 80
        elif cmd == LC_SEGMENT:
            nsects = struct.unpack_from("<I", buf, off + 48)[0]
            so = off + 56
            for _ in range(nsects):
                sec_off = struct.unpack_from("<I", buf, so + 40)[0]
                if sec_off > 0 and (best is None or sec_off < best):
                    best = sec_off
                so += 68
        off += size
    return best


def add_dylib(buf, base, path, dry_run=False):
    is64, ncmds, sizeofcmds, start = load_cmd_region(buf, base)
    end = start + sizeofcmds
    limit = first_section_offset(buf, base)
    if limit is None:
        return False, "找不到 section 边界，拒绝写入"

    name = path.encode("utf-8") + b"\x00"
    size = 24 + len(name)
    size = (size + 7) & ~7  # 8 字节对齐

    free = limit - end
    if free < size:
        return False, f"load command 区只剩 {free} 字节，需要 {size} 字节"

    if dry_run:
        return True, f"可写入（空闲 {free} 字节，需要 {size} 字节）"

    struct.pack_into("<IIIIII", buf, end, LC_LOAD_DYLIB, size, 24, 2, 0x10000, 0x10000)
    buf[end + 24:end + 24 + len(name)] = name
    struct.pack_into("<II", buf, base + 16, ncmds + 1, sizeofcmds + size)
    return True, f"已注入 {path}（{size} 字节，剩余空闲 {free - size} 字节）"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    target = None
    check = False
    i = 1
    while i < len(args):
        if args[i] == "--add":
            target = args[i + 1]
            i += 2
        elif args[i] == "--check":
            check = True
            i += 1
        else:
            i += 1

    with open(path, "rb") as f:
        buf = bytearray(f.read())

    slices, is_fat = pm.slices(bytes(buf))
    ok_any = False
    for base, _size, label in slices:
        ok, msg = add_dylib(buf, base, target or "@executable_path/Frameworks/NMSMenu.dylib", dry_run=check)
        print(f"[{label}] {msg}")
        ok_any = ok_any or ok

    if check or not ok_any:
        return 0 if ok_any else 1

    with open(path, "wb") as f:
        f.write(buf)
    print("\n完成。代码签名已失效，必须重签。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
