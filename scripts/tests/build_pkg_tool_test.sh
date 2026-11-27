#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# build_pkg_tool_test.sh — scripts/release/build-pkg-tool.sh reuses a cached prefix only if its
# pkg runs and reports the pinned version (R-1454): a binary that no longer loads on a newer
# runner image, or one of another version, is rebuilt instead of trusted. --bundle-libs copies
# the libraries pkg loads next to it (R-1787).
# Hermetic: stub prefixes with a fake sbin/pkg and the real pin; clang is pointed at an empty
# directory, so a rebuild stops at the clang check before any clone. The positive case proves the
# check can pass at all.
#
# Run: bash scripts/tests/build_pkg_tool_test.sh
# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SCRIPT="$HERE/../release/build-pkg-tool.sh"
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
mkdir "$WORK/no-clang"

tag=$(sed -nE 's/^PKG_TAG="([^"]+)"$/\1/p' "$SCRIPT")
commit=$(sed -nE 's/^PKG_COMMIT="([^"]+)"$/\1/p' "$SCRIPT")
[ -n "$tag" ] && [ -n "$commit" ] || { echo "FAIL: pin not found in $SCRIPT"; exit 1; }

# prefix <name> <body of sbin/pkg> — a cached prefix with the real pin and a stub pkg.
prefix() {
  local p="$WORK/$1"
  mkdir -p "$p/sbin"
  printf '#!/bin/sh\n%s\n' "$2" > "$p/sbin/pkg"
  chmod +x "$p/sbin/pkg"
  echo "$tag $commit" > "$p/.pkg-pin"
  echo "$p"
}

# run <prefix> — the script's output; its exit in $rc.
run() {
  out=$(PKG_TOOL_CLANG_BINDIR="$WORK/no-clang" bash "$SCRIPT" "$1" 2>&1)
  rc=$?
}

run "$(prefix good "echo $tag")"
[ "$rc" = 0 ] && [[ "$out" == *"already in"* ]] \
  && ok "a prefix whose pkg reports $tag is reused" \
  || bad "good prefix: rc=$rc out=$out"

run "$(prefix broken 'exit 127')"
[ "$rc" != 0 ] && [[ "$out" != *"already in"* ]] && [[ "$out" == *"rebuilding"* ]] && [[ "$out" == *"clang-18 not found"* ]] \
  && ok "a prefix whose pkg does not run is rebuilt" \
  || bad "broken prefix: rc=$rc out=$out"

run "$(prefix other 'echo 1.0.0')"
[ "$rc" != 0 ] && [[ "$out" != *"already in"* ]] && [[ "$out" == *"rebuilding"* ]] \
  && ok "a prefix whose pkg reports another version is rebuilt" \
  || bad "other version: rc=$rc out=$out"

p=$(prefix stale "echo $tag")
echo "0.0.0 0000" > "$p/.pkg-pin"
run "$p"
[ "$rc" != 0 ] && [[ "$out" != *"already in"* ]] && [[ "$out" == *"clang-18 not found"* ]] \
  && ok "a prefix with another pin is rebuilt" \
  || bad "stale pin: rc=$rc out=$out"

# --bundle-libs (R-1787): the release's signing job installs nothing, so pkg's libraries travel
# with it. A real binary (xz, linked to liblzma) stands in for pkg; a stub ldd covers the rest.
xz_bin=$(command -v xz) || { echo "SKIP: xz missing"; exit 75; }
p="$WORK/bundle"; mkdir -p "$p/sbin"; cp "$xz_bin" "$p/sbin/pkg"
out=$(bash "$SCRIPT" --bundle-libs "$p" 2>&1); rc=$?
[ "$rc" = 0 ] && [ -f "$p/lib/liblzma.so.5" ] && [ ! -e "$p/lib/libc.so.6" ] && [ ! -L "$p/lib/liblzma.so.5" ] \
  && ok "--bundle-libs copies the libraries of pkg but not glibc's" \
  || bad "bundle: rc=$rc out=$out lib=$(ls "$p/lib" 2>&1)"
out=$(env -i PATH=/usr/bin:/bin LD_LIBRARY_PATH="$p/lib" "$p/sbin/pkg" --version 2>&1); rc=$?
[ "$rc" = 0 ] && ok "the bundled stand-in runs with LD_LIBRARY_PATH on the bundle" || bad "bundled run: rc=$rc out=$out"

printf '#!/bin/sh\nprintf "\\tlibgone.so.1 => not found\\n\\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x1)\\n"\n' > "$WORK/ldd-missing"
chmod +x "$WORK/ldd-missing"
out=$(PKG_TOOL_LDD="$WORK/ldd-missing" bash "$SCRIPT" --bundle-libs "$p" 2>&1); rc=$?
[ "$rc" != 0 ] && [[ "$out" == *"libgone.so.1"* ]] \
  && ok "--bundle-libs fails on a library the runner lacks" \
  || bad "missing library: rc=$rc out=$out"

printf '#!/bin/sh\nprintf "\\tlibpkg.so.4 => %s/lib/libpkg.so.4 (0x1)\\n"\n' "$p" > "$WORK/ldd-own"
chmod +x "$WORK/ldd-own"
: > "$p/lib/libpkg.so.4"
out=$(PKG_TOOL_LDD="$WORK/ldd-own" bash "$SCRIPT" --bundle-libs "$p" 2>&1); rc=$?
[ "$rc" = 0 ] && [[ "$out" == *"bundled 0 libraries"* ]] \
  && ok "--bundle-libs leaves a library already in the bundle" \
  || bad "own library: rc=$rc out=$out"

out=$(bash "$SCRIPT" --bundle-libs "$WORK/no-such-prefix" 2>&1); rc=$?
[ "$rc" = 2 ] && ok "--bundle-libs without sbin/pkg is a usage error" || bad "no pkg: rc=$rc out=$out"

echo "build_pkg_tool_test: $PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
