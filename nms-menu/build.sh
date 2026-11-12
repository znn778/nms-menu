#!/usr/bin/env bash
# build.sh - 不依赖 Theos，直接用 clang + lld 编 iOS dylib（Linux / macOS 都能跑）
#
# 用法:
#   ./build.sh /path/to/iPhoneOS16.5.sdk
#   SDK=/path/to/iPhoneOS16.5.sdk ./build.sh
#
# 产出:
#   NMSMenu.dylib            悬浮菜单
#   stub_libnomanssky.dylib  空壳，install_name = @executable_path/Frameworks/libnomanssky.dylib
#   stub_iGameGod.dylib      空壳，install_name = @rpath/iGameGod.framework/iGameGod
set -euo pipefail

SDK="${1:-${SDK:-}}"
if [ -z "$SDK" ]; then
    echo "用法: ./build.sh <iPhoneOS.sdk 路径>" >&2
    exit 1
fi
if [ ! -d "$SDK" ]; then
    echo "SDK 不存在: $SDK" >&2
    exit 1
fi

OUT="${OUT:-NMSMenu.dylib}"
MIN_IOS="${MIN_IOS:-15.0}"

SRC=(
    NMSPrefs.m
    NMSCheatEngine.m
    NMSSaveTool.m
    NMSMenuWindow.m
    NMSHooks.m
    Tweak.m
)

COMMON=(
    -target "arm64-apple-ios${MIN_IOS}"
    -isysroot "$SDK"
    -fobjc-arc
    -O2
    -I.
    -dynamiclib
    -fuse-ld=lld
    -Wl,-platform_version -Wl,ios -Wl,"${MIN_IOS}" -Wl,"${MIN_IOS}"
    -Wl,-undefined -Wl,dynamic_lookup
    -Wl,-dead_strip
)

echo "SDK      : $SDK"
echo "MIN_IOS  : $MIN_IOS"

# ------------------------------------------------------------- 悬浮菜单
echo "--- 1/3 $OUT ---"
clang "${COMMON[@]}" \
    -Wl,-install_name,@executable_path/Frameworks/NMSMenu.dylib \
    -framework UIKit \
    -framework Foundation \
    -framework QuartzCore \
    -lz \
    -o "$OUT" \
    "${SRC[@]}"
echo "链接完成: $(ls -lh "$OUT" | awk '{print $5}')"

# ------------------------------------------------------------- 空壳 x2
build_stub() {
    local out="$1" name="$2"
    echo "--- $out  (install_name=$name) ---"
    clang "${COMMON[@]}" \
        -Wl,-install_name,"$name" \
        -o "$out" \
        empty.m
    echo "链接完成: $(ls -lh "$out" | awk '{print $5}')"
}

build_stub stub_libnomanssky.dylib '@executable_path/Frameworks/libnomanssky.dylib'
build_stub stub_iGameGod.dylib     '@rpath/iGameGod.framework/iGameGod'

# ------------------------------------------------------------- 伪签名
if command -v ldid >/dev/null 2>&1; then
    for f in "$OUT" stub_libnomanssky.dylib stub_iGameGod.dylib; do
        ldid -S "$f" && echo "ldid 签名完成: $f"
    done
else
    echo "没有 ldid，跳过签名（重签工具会处理）"
fi

file "$OUT" 2>/dev/null || true
