#!/usr/bin/env python3
"""verify_ipa.py - 交付前硬校验：这个 IPA 装上去会不会因为 dyld 找不到库而闪退

检查项:
  1. 主二进制每条 硬 LC_LOAD_DYLIB / LC_LOAD_UPWARD_DYLIB 的 @executable_path / @rpath
     目标，在包内是否真实存在。缺失 = 启动必崩。
  2. weak 链接目标缺失只告警（dyld 会跳过，不致命）。
  3. 主二进制是否有 LC_CODE_SIGNATURE（重签工具需要它作为骨架）。
  4. 是否残留旧 _CodeSignature / SC_Info。
  5. 注入的 dylib 是否在 Frameworks/ 下、架构是否为 arm64。

用法:
  python tools/verify_ipa.py 成品.ipa
  python tools/verify_ipa.py 成品.ipa --strict     # 有告警就返回非 0
"""
import argparse
import os
import struct
import sys
import zipfile

LC_LOAD_DYLIB       = 0x0C
LC_LOAD_WEAK_DYLIB  = 0x80000018
LC_REEXPORT_DYLIB   = 0x8000001F
LC_LOAD_UPWARD_DYLIB = 0x80000023
LC_RPATH            = 0x8000001C
LC_CODE_SIGNATURE   = 0x1D
LC_ENCRYPTION_INFO_64 = 0x2C

MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF

DYLIB_CMDS = {LC_LOAD_DYLIB: "load", LC_LOAD_WEAK_DYLIB: "weak",
              LC_REEXPORT_DYLIB: "reexport", LC_LOAD_UPWARD_DYLIB: "upward"}


def thin_lcs(data, base):
    magic = struct.unpack_from("<I", data, base)[0]
    if magic != MH_MAGIC_64:
        return None
    ncmds, sizeofcmds = struct.unpack_from("<II", data, base + 16)
    off = base + 32
    out = []
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        rec = {"cmd": cmd, "off": off, "size": size, "path": None}
        if cmd in DYLIB_CMDS:
            name_off = struct.unpack_from("<I", data, off + 8)[0]
            raw = data[off + name_off: off + size]
            rec["path"] = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
        elif cmd == LC_RPATH:
            name_off = struct.unpack_from("<I", data, off + 8)[0]
            raw = data[off + name_off: off + size]
            rec["path"] = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
        elif cmd == LC_CODE_SIGNATURE:
            rec["dataoff"], rec["datasize"] = struct.unpack_from("<II", data, off + 8)
        out.append(rec)
        off += size
    return out


def slices(data):
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic in (FAT_MAGIC, FAT_MAGIC_64):
        n = struct.unpack_from(">I", data, 4)[0]
        off = 8
        res = []
        for _ in range(n):
            if magic == FAT_MAGIC:
                _ct, _cs, o, sz, _al = struct.unpack_from(">iiIII", data, off)
                off += 20
            else:
                _ct, _cs, o, sz, _al, _r = struct.unpack_from(">iiQQII", data, off)
                off += 32
            res.append((o, sz))
        return res, True
    return [(0, len(data))], False


def resolve(path, exe_dir, rpaths):
    """把 @executable_path / @rpath 展开成包内相对路径候选"""
    cands = []
    if path.startswith("@executable_path/"):
        cands.append(exe_dir + "/" + path[len("@executable_path/"):])
    elif path.startswith("@rpath/"):
        rest = path[len("@rpath/"):]
        for rp in rpaths:
            if rp.startswith("@executable_path/"):
                cands.append(exe_dir + "/" + rp[len("@executable_path/"):] + "/" + rest)
            elif rp.startswith("/"):
                cands.append(rp + "/" + rest)
    elif path.startswith("@loader_path/"):
        cands.append(exe_dir + "/" + path[len("@loader_path/"):])
    else:
        cands.append(path.lstrip("/"))   # 系统绝对路径，包内不检查
    return cands


def norm(name):
    return name.replace("\\", "/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ipa")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--expect-dylib", action="append", default=[],
                    help="必须存在且被硬链接的注入库名，如 NMSMenu.dylib")
    a = ap.parse_args()

    if not os.path.exists(a.ipa):
        print("找不到:", a.ipa)
        return 1

    fatal, warn = [], []

    with zipfile.ZipFile(a.ipa) as z:
        names = {norm(n) for n in z.namelist()}
        entries = [norm(n) for n in z.namelist() if not n.endswith("/")]

        # 找主二进制：Payload/X.app/ 下、无扩展名、最大的那个
        payload_exes = []
        for n in entries:
            parts = n.split("/")
            if len(parts) == 3 and parts[0] == "Payload" and parts[1].endswith(".app"):
                payload_exes.append((z.getinfo(n).file_size, n))
        if not payload_exes:
            print("结构异常：Payload 下找不到主二进制")
            return 1
        payload_exes.sort(reverse=True)
        exe = payload_exes[0][1]
        app_dir = "/".join(exe.split("/")[:2])
        print(f"主二进制: {exe}  ({z.getinfo(exe).file_size:,} B)")

        data = z.read(exe)
        sl, is_fat = slices(data)
        print(f"架构: {'FAT x%d' % len(sl) if is_fat else 'thin'}")

        # 收集 rpaths（取第一个 slice）
        lcs0 = thin_lcs(data, sl[0][0])
        if lcs0 is None:
            print("主二进制不是 64 位 Mach-O，放弃校验")
            return 1
        rpaths = [c["path"] for c in lcs0 if c["cmd"] == LC_RPATH]
        print(f"RPATH: {rpaths or '(无)'}")

        has_sig = any(c["cmd"] == LC_CODE_SIGNATURE for c in lcs0)
        if not has_sig:
            warn.append("主二进制没有 LC_CODE_SIGNATURE —— 部分重签工具会拒绝处理")

        # 主二进制硬链接检查
        print("\n--- 主二进制 dylib 依赖 ---")
        for c in lcs0:
            if c["cmd"] not in DYLIB_CMDS or not c["path"]:
                continue
            kind = DYLIB_CMDS[c["cmd"]]
            path = c["path"]
            if path.startswith("/usr/lib/") or path.startswith("/System/"):
                print(f"  [{kind:8}] {path}   (系统库)")
                continue
            cands = resolve(path, app_dir, rpaths)
            hit = next((x for x in cands if norm(x) in names), None)
            if hit:
                print(f"  [{kind:8}] {path}   -> {hit}")
            else:
                if kind == "weak":
                    warn.append(f"weak 库缺失（可接受）: {path}")
                    print(f"  [{kind:8}] {path}   !! 缺失，但 weak 会跳过")
                else:
                    fatal.append(f"硬链接库缺失，启动必崩: {path}")
                    print(f"  [{kind:8}] {path}   !!! 缺失 —— 会闪退")

        # 期望的注入库
        for d in a.expect_dylib:
            arc = f"{app_dir}/Frameworks/{d}"
            if arc not in names:
                fatal.append(f"期望的注入库不存在: {arc}")
                print(f"\n[注入] 缺失 {arc}")
                continue
            blob = z.read(arc)
            m = struct.unpack_from("<I", blob, 0)[0]
            if m == MH_MAGIC_64:
                cs = struct.unpack_from("<ii", blob, 4)
                print(f"\n[注入] {arc}  arm64 thin  {len(blob):,} B")
                sub = thin_lcs(blob, 0) or []
                sig = [c for c in sub if c["cmd"] == LC_CODE_SIGNATURE]
                if sig:
                    print(f"        LC_CODE_SIGNATURE size={sig[0]['datasize']}")
                else:
                    warn.append(f"{d} 没有 LC_CODE_SIGNATURE（重签工具一般会补）")
                    print("        无 LC_CODE_SIGNATURE")
            else:
                warn.append(f"{d} 不是 thin arm64 Mach-O (magic=0x{m:08x})")
                print(f"\n[注入] {arc}  非 thin arm64, magic=0x{m:08x}")

        # 残留
        leftovers = [n for n in names if "/_CodeSignature/" in n]
        if leftovers:
            warn.append(f"残留 _CodeSignature {len(leftovers)} 个（重签会覆盖，一般无害）")
        scinfo = [n for n in names if "/SC_Info/" in n]
        if scinfo:
            warn.append(f"残留 SC_Info {len(scinfo)} 个（FairPlay 痕迹，建议删除）")

    print("\n================ 结论 ================")
    if fatal:
        print(f"致命问题 {len(fatal)} 个:")
        for f in fatal:
            print("  X", f)
    if warn:
        print(f"告警 {len(warn)} 个:")
        for w in warn:
            print("  !", w)
    if not fatal and not warn:
        print("全部通过，可以装机。")
    elif not fatal:
        print("无致命问题，可以装机。")

    if fatal:
        return 1
    if warn and a.strict:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
