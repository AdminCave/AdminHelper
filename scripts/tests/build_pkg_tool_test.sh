#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# build_pkg_tool_test.sh — scripts/release/build-pkg-tool.sh reuses a cached prefix only if its
# pkg runs and reports the pinned version (R-1454): a binary that no longer loads on a newer
# runner image, or one of another version, is rebuilt instead of trusted.
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

echo "build_pkg_tool_test: $PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
