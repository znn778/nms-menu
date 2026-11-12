#!/usr/bin/env bash
# build.sh - 不依赖 Theos，直接用 clang + lld 编 iOS dylib（Linux / macOS 都能跑）
#
# 用法:
#   ./build.sh /path/to/iPhoneOS16.5.sdk
#   SDK=/path/to/iPhoneOS16.5.sdk ./build.sh
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
    Tweak.m
)

echo "SDK      : $SDK"
echo "MIN_IOS  : $MIN_IOS"
echo "输出     : $OUT"

clang \
    -target "arm64-apple-ios${MIN_IOS}" \
    -isysroot "$SDK" \
    -fobjc-arc \
    -O2 \
    -I. \
    -dynamiclib \
    -fuse-ld=lld \
    -Wl,-install_name,@executable_path/Frameworks/NMSMenu.dylib \
    -Wl,-platform_version -Wl,ios -Wl,"${MIN_IOS}" -Wl,"${MIN_IOS}" \
    -Wl,-undefined -Wl,dynamic_lookup \
    -Wl,-dead_strip \
    -framework UIKit \
    -framework Foundation \
    -framework QuartzCore \
    -lz \
    -o "$OUT" \
    "${SRC[@]}"

echo "链接完成: $(ls -lh "$OUT" | awk '{print $5}')"

if command -v ldid >/dev/null 2>&1; then
    ldid -S "$OUT" && echo "ldid 签名完成（伪签名，供后续重签使用）"
else
    echo "没有 ldid，跳过签名（重签工具会处理）"
fi

file "$OUT" 2>/dev/null || true
