#!/usr/bin/env python3
"""macho_lc.py - 纯 Python Mach-O 加载命令解析器（Windows/Linux 可用，不需要 macOS 工具链）

用法:
    python macho_lc.py <macho_file> [--all]

输出: 架构、LC_ID_DYLIB、LC_LOAD_DYLIB、LC_LOAD_WEAK_DYLIB、LC_RPATH、LC_REEXPORT_DYLIB、
      LC_LOAD_UPWARD_DYLIB、加密状态(LC_ENCRYPTION_INFO)、code signature 大小。
"""
import struct
import sys

MH_MAGIC = 0xFEEDFACE
MH_CIGAM = 0xCEFAEDFE
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE
FAT_MAGIC = 0xCAFEBABE
FAT_CIGAM = 0xBEBAFECA
FAT_MAGIC_64 = 0xCAFEBABF

LC_REQ_DYLD = 0x80000000

LC_NAMES = {
    0x1: "LC_SEGMENT",
    0x2: "LC_SYMTAB",
    0x3: "LC_SYMSEG",
    0x4: "LC_THREAD",
    0x5: "LC_UNIXTHREAD",
    0x6: "LC_LOADFVMLIB",
    0x7: "LC_IDFVMLIB",
    0x8: "LC_IDENT",
    0x9: "LC_FVMFILE",
    0xA: "LC_PREPAGE",
    0xB: "LC_DYSYMTAB",
    0xC: "LC_LOAD_DYLIB",
    0xD: "LC_ID_DYLIB",
    0xE: "LC_LOAD_DYLINKER",
    0xF: "LC_ID_DYLINKER",
    0x10: "LC_PREBOUND_DYLIB",
    0x11: "LC_ROUTINES",
    0x12: "LC_SUB_FRAMEWORK",
    0x13: "LC_SUB_UMBRELLA",
    0x14: "LC_SUB_CLIENT",
    0x15: "LC_SUB_LIBRARY",
    0x16: "LC_TWOLEVEL_HINTS",
    0x17: "LC_PREBIND_CKSUM",
    0x18 | LC_REQ_DYLD: "LC_LOAD_WEAK_DYLIB",
    0x19: "LC_SEGMENT_64",
    0x1A: "LC_ROUTINES_64",
    0x1B: "LC_UUID",
    0x1C | LC_REQ_DYLD: "LC_RPATH",
    0x1D: "LC_CODE_SIGNATURE",
    0x1E: "LC_SEGMENT_SPLIT_INFO",
    0x1F | LC_REQ_DYLD: "LC_REEXPORT_DYLIB",
    0x20: "LC_LAZY_LOAD_DYLIB",
    0x21: "LC_ENCRYPTION_INFO",
    0x22: "LC_DYLD_INFO",
    0x23 | LC_REQ_DYLD: "LC_LOAD_UPWARD_DYLIB",
    0x24: "LC_VERSION_MIN_MACOSX",
    0x25: "LC_VERSION_MIN_IPHONEOS",
    0x26: "LC_FUNCTION_STARTS",
    0x27: "LC_DYLD_ENVIRONMENT",
    0x28 | LC_REQ_DYLD: "LC_MAIN",
    0x29: "LC_DATA_IN_CODE",
    0x2A: "LC_SOURCE_VERSION",
    0x2B: "LC_DYLIB_CODE_SIGN_DRS",
    0x2C: "LC_ENCRYPTION_INFO_64",
    0x2D: "LC_LINKER_OPTION",
    0x2E: "LC_LINKER_OPTIMIZATION_HINT",
    0x2F: "LC_VERSION_MIN_TVOS",
    0x30: "LC_VERSION_MIN_WATCHOS",
    0x31: "LC_NOTE",
    0x32: "LC_BUILD_VERSION",
}

DYLIB_CMDS = {0xC, 0xD, 0x18 | LC_REQ_DYLD, 0x1F | LC_REQ_DYLD, 0x20, 0x23 | LC_REQ_DYLD}
PLATFORM = {1: "macOS", 2: "iOS", 3: "tvOS", 4: "watchOS", 6: "MacCatalyst", 7: "iOS-sim", 8: "tvOS-sim"}


def cstr(buf, off):
    end = buf.find(b"\x00", off)
    return buf[off:end if end != -1 else len(buf)].decode("utf-8", "replace")


def parse_thin(buf, base_off, label, want_all):
    magic = struct.unpack_from("<I", buf, base_off)[0]
    if magic in (MH_MAGIC_64, MH_CIGAM_64):
        is64 = True
        hdr = struct.unpack_from("<IiiIIIII", buf, base_off)
        cputype, cpusub, _ft, ncmds, sizeofcmds, flags, _res = hdr[1:]
    elif magic in (MH_MAGIC, MH_CIGAM):
        is64 = False
        hdr = struct.unpack_from("<IiiIIII", buf, base_off)
        cputype, cpusub, _ft, ncmds, sizeofcmds, flags = hdr[1:]
    else:
        print(f"  [{label}] 不是 Mach-O (magic={magic:#x})")
        return

    arch = {0x0100000C: "arm64", 0x01000007: "x86_64", 12: "arm", 7: "i386"}.get(cputype & 0xFFFFFFFF, hex(cputype))
    if cputype & 0xFFFFFFFF == 0x0100000C and cpusub == 2:
        arch += "e"
    print(f"\n  [{label}] arch={arch} ncmds={ncmds} sizeofcmds={sizeofcmds} flags={flags:#x} 64bit={is64}")

    off = base_off + (32 if is64 else 28)
    end = off + sizeofcmds
    found = []
    others = []
    while off < end and ncmds > 0:
        cmd, cmdsize = struct.unpack_from("<II", buf, off)
        if cmdsize < 8:
            break
        name = LC_NAMES.get(cmd, f"cmd_{cmd:#x}")
        if cmd in DYLIB_CMDS:
            name_off = struct.unpack_from("<I", buf, off + 8)[0]
            found.append((name, cstr(buf, off + name_off)))
        elif cmd == 0x1C | LC_REQ_DYLD:
            name_off = struct.unpack_from("<I", buf, off + 8)[0]
            found.append((name, cstr(buf, off + name_off)))
        elif cmd == 0x21:  # LC_ENCRYPTION_INFO
            cryptoff, cryptsize, cryptid = struct.unpack_from("<III", buf, off + 8)
            others.append(("LC_ENCRYPTION_INFO", f"cryptid={cryptid} size={cryptsize} (0=未加密,1=AppStore加密)"))
        elif cmd == 0x2C:  # LC_ENCRYPTION_INFO_64
            cryptoff, cryptsize, cryptid, pad = struct.unpack_from("<IIII", buf, off + 8)
            others.append(("LC_ENCRYPTION_INFO_64", f"cryptid={cryptid} size={cryptsize} (0=未加密,1=AppStore加密)"))
        elif cmd == 0x1D:  # LC_CODE_SIGNATURE
            dataoff, datasize = struct.unpack_from("<II", buf, off + 8)
            others.append(("LC_CODE_SIGNATURE", f"off={dataoff} size={datasize}"))
        elif cmd == 0x32:  # LC_BUILD_VERSION
            platform, minos, sdk, ntools = struct.unpack_from("<IIII", buf, off + 8)
            others.append(("LC_BUILD_VERSION", f"{PLATFORM.get(platform, platform)} minos={minos>>16}.{(minos>>8)&0xff}.{minos&0xff} sdk={sdk>>16}.{(sdk>>8)&0xff}.{sdk&0xff}"))
        elif want_all:
            others.append((name, f"size={cmdsize}"))
        off += cmdsize
        ncmds -= 1

    print("  --- 注入 / 链接的 dylib ---")
    if not found:
        print("    (无)")
    for name, path in found:
        print(f"    {name:<26} {path}")
    if others:
        print("  --- 其他关键命令 ---")
        for name, info in others:
            print(f"    {name:<26} {info}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    want_all = "--all" in sys.argv[2:]
    with open(path, "rb") as f:
        buf = f.read()

    magic = struct.unpack_from(">I", buf, 0)[0]
    print(f"文件: {path}  大小: {len(buf):,} bytes")
    if magic in (FAT_MAGIC, FAT_MAGIC_64):
        nfat = struct.unpack_from(">I", buf, 4)[0]
        is64fat = magic == FAT_MAGIC_64
        print(f"FAT 二进制，包含 {nfat} 个架构")
        off = 8
        for i in range(nfat):
            if is64fat:
                _ct, _cs, offset, size, align, _r = struct.unpack_from(">iiQQII", buf, off)
                off += 32
            else:
                _ct, _cs, offset, size, align = struct.unpack_from(">iiIII", buf, off)
                off += 20
            parse_thin(buf, offset, f"slice{i}", want_all)
    else:
        parse_thin(buf, 0, "thin", want_all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
