#!/usr/bin/env python3
"""repack.py - 从 IPA 里剔除注入的插件并重新打包（纯 Python，Windows 可用）

默认剔除:
  Myiosgods.dylib        弹窗引流注入器
  libnomanssky.dylib     iOSGods 作弊包（伪装成引擎库名）
  iGameGod.framework     iOSGods mod menu 框架

同时把主二进制里对它们的 LC_LOAD_DYLIB 降级为 LC_LOAD_WEAK_DYLIB
（weak 缺失时 dyld 直接跳过，且不改变 dylib ordinal），并删掉旧签名。

用法:
  python repack.py --src 原包.ipa --dst 干净.ipa
  python repack.py --src 原包.ipa --dst 成品.ipa --inject-dylib NMSMenu.dylib
  python repack.py --src 原包.ipa --dst 纯净.ipa --drop "libnomanssky.dylib" --drop "iGameGod"
  python repack.py --src 原包.ipa --dst x.ipa --keep-iosgods     # 保留 iOSGods 那套
"""
import argparse
import os
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_macho as pm
import macho_inject as mi
import patch_binary as pb

MAIN_EXE = "Payload/No Man's Sky.app/No Man's Sky"
APP = "Payload/No Man's Sky.app"
DEFAULT_DROPS = ["Myiosgods.dylib", "libnomanssky.dylib", "iGameGod.framework"]
DEFAULT_WEAKEN = ["Myiosgods", "libnomanssky", "iGameGod"]

# 「换壳」模式下被替换成空壳的文件
NEUTRALIZE_MAP = {
    f"{APP}/Frameworks/libnomanssky.dylib": "stub_libnomanssky.dylib",
    f"{APP}/Frameworks/iGameGod.framework/iGameGod": "stub_iGameGod.dylib",
}


def build_filters(a):
    drops = list(a.drop or [])
    weaken = list(a.weaken or [])
    if a.neutralize_iosgods:
        # 换壳模式：只删弹窗库（本来就是 weak 链接），两个硬链接库用空壳顶替，
        # 主二进制一个字节都不改
        drops.append("Myiosgods.dylib")
        return list(dict.fromkeys(drops)), []
    if not a.keep_iosgods:
        drops += DEFAULT_DROPS
        weaken += DEFAULT_WEAKEN
    if a.drop_igg:
        drops.append("iGameGod.framework")
        weaken.append("iGameGod")
    return list(dict.fromkeys(drops)), list(dict.fromkeys(weaken))


def build_replacements(a):
    """返回 {包内路径: 本地文件} """
    rep = {}
    if not a.neutralize_iosgods:
        return rep
    d = a.stub_dir
    for arc, fname in NEUTRALIZE_MAP.items():
        p = os.path.join(d, fname)
        if not os.path.exists(p):
            print(f"找不到空壳: {p}")
            sys.exit(1)
        rep[arc] = p
    return rep


def should_skip(name, drops, strip_scinfo=False):
    if "/_CodeSignature/" in name:
        return True, "旧签名"
    if strip_scinfo and "/SC_Info/" in name:
        return True, "FairPlay 残留"
    for d in drops:
        if d and d in name:
            return True, d
    return False, None


def bake_patches(buf, keys):
    """把代码补丁直接写进主二进制，返回 (成功数, 失败列表)"""
    ok, bad = 0, []
    for key, title, off, patch, expect in pb.PATCHES:
        if keys and key not in keys:
            continue
        cur = struct.unpack_from("<Q", buf, off)[0]
        if cur == patch:
            ok += 1
            print(f"    = {key:9} 已是补丁状态")
            continue
        if cur != expect:
            bad.append(key)
            print(f"    X {key:9} 原始字节不匹配 (实际 {cur:016x} 期望 {expect:016x})，跳过")
            continue
        struct.pack_into("<Q", buf, off, patch)
        ok += 1
        print(f"    + {key:9} {expect:016x} -> {patch:016x}  {title}")
    return ok, bad


def weaken_lcs(buf, patterns):
    changed = 0
    slices, _ = pm.slices(bytes(buf))
    for base, _size, _label in slices:
        _is64, _n, _sz, cmds = pm.walk(bytes(buf), base)
        for c in cmds:
            if not c["path"]:
                continue
            if c["cmd"] == pm.LC_LOAD_DYLIB and any(p in c["path"] for p in patterns):
                struct.pack_into("<I", buf, c["off"], pm.LC_LOAD_WEAK_DYLIB)
                changed += 1
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--drop", action="append", help="路径含该字符串的条目删除，可重复")
    ap.add_argument("--weaken", action="append", help="LC 路径含该字符串的降级为 weak，可重复")
    ap.add_argument("--keep-iosgods", action="store_true", help="保留 libnomanssky / iGameGod")
    ap.add_argument("--drop-igg", action="store_true", help="只额外处理 iGameGod（兼容旧参数）")
    ap.add_argument("--inject-dylib", help="把编译好的 .dylib 注入 Frameworks/ 并加 LC")
    ap.add_argument("--patch-binary", nargs="?", const="all", default=None,
                    help="把代码补丁烧进主二进制，可写 all 或 key 列表(逗号分隔)")
    ap.add_argument("--neutralize-iosgods", action="store_true",
                    help="换壳模式：两个硬链接库替换为空壳，主二进制零改动")
    ap.add_argument("--stub-dir", default="dist", help="空壳 dylib 所在目录（默认 dist）")
    ap.add_argument("--strip-scinfo", action="store_true", default=True,
                    help="删除 SC_Info（FairPlay 残留，重签前应清掉）")
    ap.add_argument("--keep-scinfo", dest="strip_scinfo", action="store_false")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        print("找不到源文件:", a.src)
        return 1
    if a.inject_dylib and not os.path.exists(a.inject_dylib):
        print("找不到 dylib:", a.inject_dylib)
        return 1

    drops, weaken = build_filters(a)
    reps = build_replacements(a)
    print("剔除规则:", drops)
    print("弱化规则:", weaken or "(不改主二进制)")
    if reps:
        print("替换为空壳:")
        for k, v in reps.items():
            print(f"   {k}  <-  {v} ({os.path.getsize(v):,} B)")

    with zipfile.ZipFile(a.src) as z:
        infos = z.infolist()
        if MAIN_EXE not in {i.filename for i in infos}:
            print("结构异常，找不到主二进制")
            return 1

        skipped, total = [], 0
        for i in infos:
            skip, why = should_skip(i.filename, drops, a.strip_scinfo)
            if skip:
                skipped.append((i.filename, i.file_size, why))
            total += i.file_size

        print(f"\n源包 {total/1e9:.2f} GB，{len(infos)} 条目，将移除 {len(skipped)} 个:")
        for n, s, why in skipped:
            print(f"   [{why}] {n}  ({s:,} B)")

        if a.dry_run:
            print("\n--dry-run，未写文件。")
            return 0

        main_data = bytearray(z.read(MAIN_EXE))
        touched = False
        if weaken:
            n = weaken_lcs(main_data, weaken)
            print(f"\n主二进制: 弱化 {n} 条 LC_LOAD_DYLIB")
            touched = True

        if a.patch_binary:
            keys = None if a.patch_binary == "all" else {
                s.strip() for s in a.patch_binary.split(",") if s.strip()}
            print("\n主二进制: 烧入代码补丁")
            okc, bad = bake_patches(main_data, keys)
            print(f"  成功 {okc} 处" + (f"，失败 {bad}" if bad else ""))
            if bad:
                print("  警告：有补丁点不匹配，已跳过（不影响启动）")
            touched = True

        if a.inject_dylib:
            name = os.path.basename(a.inject_dylib)
            lc = f"@executable_path/Frameworks/{name}"
            slices, _ = pm.slices(bytes(main_data))
            for base, _s, label in slices:
                ok, msg = mi.add_dylib(main_data, base, lc)
                print(f"注入 LC [{label}]: {msg}")
                if not ok:
                    return 1
            touched = True

        if not touched:
            print("\n主二进制: 逐字节保持原样（零改动）")

        tmp = a.dst + ".part"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as out:
            for i in infos:
                skip, _ = should_skip(i.filename, drops, a.strip_scinfo)
                if skip:
                    continue
                if i.filename == MAIN_EXE:
                    zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
                    zi.external_attr = i.external_attr
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    out.writestr(zi, bytes(main_data))
                elif i.filename in reps:
                    zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
                    zi.external_attr = i.external_attr
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    with open(reps[i.filename], "rb") as f:
                        out.writestr(zi, f.read())
                    print(f"换壳: {i.filename}  ({i.file_size:,} -> {os.path.getsize(reps[i.filename]):,} B)")
                else:
                    zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
                    zi.external_attr = i.external_attr
                    zi.compress_type = (zipfile.ZIP_STORED if i.file_size >= 8 << 20
                                        else zipfile.ZIP_DEFLATED)
                    with z.open(i) as src, out.open(zi, "w") as dst:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            dst.write(chunk)
            if a.inject_dylib:
                arc = f"{APP}/Frameworks/{os.path.basename(a.inject_dylib)}"
                out.write(a.inject_dylib, arcname=arc)
                print(f"已放入 {arc}")

        os.replace(tmp, a.dst)
        print(f"\n完成: {a.dst}  ({os.path.getsize(a.dst)/1e9:.2f} GB)")
        print("下一步: 重签后安装（Esign / 轻松签 / Sideloadly）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
