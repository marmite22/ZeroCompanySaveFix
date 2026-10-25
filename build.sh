#!/bin/sh
# Builds dist/version.dll (and copies the default settings next to it) with Zig 0.13.0
# (https://ziglang.org). Set ZIG to the zig executable if it isn't on PATH.
# ./build.sh test  also builds and runs the logic test.
set -e
cd "$(dirname "$0")"
ZIG="${ZIG:-zig}"
mkdir -p dist
"$ZIG" cc -target x86_64-windows-gnu -shared -O2 -Wall -Wextra -Wno-unused-parameter \
  -fno-stack-protector -o dist/version.dll src/savefix.c src/version.def -lkernel32
rm -f dist/*.lib dist/*.pdb
cp src/SWZeroCompanyFix.ini dist/
echo "built dist/version.dll"
if [ "$1" = "test" ]; then
  mkdir -p test/out
  "$ZIG" cc -target x86_64-windows-gnu -O2 -o test/out/test_logic.exe test/test_logic.c -lkernel32
  test/out/test_logic.exe
fi
