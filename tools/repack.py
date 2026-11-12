#!/usr/bin/env python3
"""repack.py - 从 IPA 里摘掉注入的插件并重新打包（纯 Python，Windows 可用）

默认行为:
  1. 删除弹窗/引流注入库  Myiosgods.dylib
  2. 把主二进制里对它的 LC_LOAD_WEAK_DYLIB 保留（weak 缺失会被 dyld 忽略，安全）
  3. 删除 _CodeSignature（交给重签工具重新生成）
  4. 流式重打包成新 IPA（3.6GB 也能跑，不占额外内存）

可选:
  --drop-igg        连同 iOSGods 的 iGameGod.framework 一起删掉，
                    并把主二进制里的 LC_LOAD_DYLIB 降级为 WEAK，保证能启动
  --keep-provision  保留原 embedded.mobileprovision（默认保留）
  --dry-run         只打印将要做什么，不写文件

用法:
  python repack.py --src 原包.ipa --dst 干净.ipa
  python repack.py --src 原包.ipa --dst 干净.ipa --drop-igg
"""
import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_macho as pm
import macho_inject as mi

POPUP_DYLIB = "Payload/No Man's Sky.app/Myiosgods.dylib"
MAIN_EXE = "Payload/No Man's Sky.app/No Man's Sky"
IGG_PREFIX = "Payload/No Man's Sky.app/Frameworks/iGameGod.framework/"


def should_skip(name, drop_igg):
    if name == POPUP_DYLIB:
        return True, "弹窗注入库"
    if drop_igg and name.startswith(IGG_PREFIX):
        return True, "iGameGod"
    if "/_CodeSignature/" in name:
        return True, "旧签名"
    return False, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--drop-igg", action="store_true")
    ap.add_argument("--keep-provision", action="store_true")
    ap.add_argument("--inject-dylib", help="把编译好的 .dylib 注入进 Frameworks/ 并加 LC")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        print("找不到源文件:", a.src)
        return 1

    with zipfile.ZipFile(a.src) as z:
        infos = z.infolist()
        names = {i.filename for i in infos}
        if MAIN_EXE not in names:
            print("结构异常，找不到主二进制:", MAIN_EXE)
            return 1

        skipped, total_bytes = [], 0
        for i in infos:
            skip, why = should_skip(i.filename, a.drop_igg)
            if skip:
                skipped.append((i.filename, i.file_size, why))
            total_bytes += i.file_size

        print(f"源包: {a.src}")
        print(f"条目: {len(infos)}  解压后大小: {total_bytes/1e9:.2f} GB")
        print(f"\n将移除 {len(skipped)} 个条目:")
        agg = {}
        for n, s, why in skipped:
            agg[why] = agg.get(why, 0) + s
            if len([x for x in skipped if x[2] == why]) <= 3:
                print(f"   [{why}] {n}  ({s:,} B)")
        print("\n按类别汇总:")
        for k, v in agg.items():
            print(f"   {k}: {v/1e6:.1f} MB")

        if a.dry_run:
            print("\n--dry-run，未写文件。")
            return 0

        if a.inject_dylib:
            if not os.path.exists(a.inject_dylib):
                print("找不到 dylib:", a.inject_dylib)
                return 1

        # 主二进制：需要时降级 iGameGod 的 LC
        main_data = bytearray(z.read(MAIN_EXE))
        patched = 0
        if a.drop_igg:
            sl, _ = pm.slices(bytes(main_data))
            for base, _size, _label in sl:
                _is64, _n, _sz, cmds = pm.walk(bytes(main_data), base)
                for c in cmds:
                    if c["path"] and "iGameGod" in c["path"] and c["cmd"] == pm.LC_LOAD_DYLIB:
                        import struct
                        struct.pack_into("<I", main_data, c["off"], pm.LC_LOAD_WEAK_DYLIB)
                        patched += 1
            print(f"\n主二进制: 把 {patched} 条 iGameGod 的 LC_LOAD_DYLIB 降级为 WEAK")

        if a.inject_dylib:
            import struct as _struct
            dylib_name = os.path.basename(a.inject_dylib)
            lc_path = f"@executable_path/Frameworks/{dylib_name}"
            sl, _ = pm.slices(bytes(main_data))
            for base, _size, _label in sl:
                ok, msg = mi.add_dylib(main_data, base, lc_path)
                print(f"注入 LC [{_label}]: {msg}")
                if not ok:
                    return 1

        tmp = a.dst + ".part"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as out:
            for i in infos:
                skip, _why = should_skip(i.filename, a.drop_igg)
                if skip:
                    continue
                if i.filename == MAIN_EXE:
                    zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
                    zi.external_attr = i.external_attr
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    out.writestr(zi, bytes(main_data))
                else:
                    # 大文件（pak/mp4 等已压缩资源）直接 STORED，避免无意义的重压缩
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
                arc = f"Payload/No Man's Sky.app/Frameworks/{os.path.basename(a.inject_dylib)}"
                out.write(a.inject_dylib, arcname=arc)
                print(f"已放入 {arc}")
        os.replace(tmp, a.dst)
        print(f"\n完成: {a.dst}  ({os.path.getsize(a.dst)/1e9:.2f} GB)")
        print("\n下一步: 用你的签名工具重签后安装")
        print("  macOS : codesign -f -s - --deep 'Payload/No Man's Sky.app'")
        print("  Linux : ldid -S9 'Payload/No Man's Sky.app/No Man's Sky'")
        print("  手机端: 轻松签 / Esign / Sideloadly 直接导入新 IPA 重签")
    return 0


if __name__ == "__main__":
    sys.exit(main())
