#!/bin/bash

# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Build FreeBSD's pkg(8) from the freebsd/pkg sources on Linux, so CI and the release can run
# pkg create and pkg repo (apps/agent/build-pkg.sh) on an Ubuntu runner without a FreeBSD box.
#
#   bash scripts/release/build-pkg-tool.sh <prefix>     build and install below <prefix>
#   bash scripts/release/build-pkg-tool.sh --deps       print the Ubuntu packages the build needs
#
# The tag and its commit are both pinned: the clone is checked against the commit, so a moved tag
# stops the build instead of building other sources. A prefix that already holds this pin
# (<prefix>/.pkg-pin) is reused, which is what the CI cache keys on.
#
# The build follows freebsd/pkg's own CI (.github/workflows/build.yaml at the tag: Ubuntu 24.04,
# clang-18, configure --with-libarchive.pc --with-openssl.pc), without its tests.
set -euo pipefail

PKG_TAG="2.9.2"
PKG_COMMIT="0c5adcef3aaf44ade79c19cab394be6d22a8ec3b"
PKG_REPO_URL="https://github.com/freebsd/pkg.git"
# Upstream's package list at the tag, without its test tools (libatf-dev, kyua, atf-sh).
PKG_BUILD_DEPS="clang-18 libsqlite3-dev libbsd-dev libarchive-tools libarchive-dev libssl-dev
liblzma-dev liblua5.2-dev liblzo2-dev libattr1-dev libacl1-dev build-essential zlib1g-dev
libbz2-dev python3 pkg-config m4 git ca-certificates"
CLANG_BINDIR="/usr/lib/llvm-18/bin"

if [ "${1:-}" = "--deps" ]; then
    echo $PKG_BUILD_DEPS
    exit 0
fi
if [ $# -ne 1 ] || [ -z "$1" ]; then
    echo "usage: $0 <prefix> | --deps" >&2
    exit 2
fi
mkdir -p "$1"
PREFIX="$(cd "$1" && pwd)"
PIN="$PKG_TAG $PKG_COMMIT"

if [ -x "$PREFIX/sbin/pkg" ] && [ "$(cat "$PREFIX/.pkg-pin" 2>/dev/null)" = "$PIN" ]; then
    echo "pkg $PKG_TAG already in $PREFIX"
    exit 0
fi
[ -x "$CLANG_BINDIR/clang" ] || {
    echo "ERROR: clang-18 not found in $CLANG_BINDIR; install: $(echo $PKG_BUILD_DEPS)" >&2
    exit 1
}

WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$PKG_TAG" "$PKG_REPO_URL" "$WORK/src"
head="$(git -C "$WORK/src" rev-parse HEAD)"
if [ "$head" != "$PKG_COMMIT" ]; then
    echo "ERROR: tag $PKG_TAG of $PKG_REPO_URL is $head, pinned is $PKG_COMMIT." >&2
    exit 1
fi

mkdir "$WORK/build"
(
    cd "$WORK/build"
    export CC="$CLANG_BINDIR/clang" CXX="$CLANG_BINDIR/clang++" CPP="$CLANG_BINDIR/clang-cpp" \
        CC_FOR_BUILD="$CLANG_BINDIR/clang"
    "$WORK/src/configure" --prefix="$PREFIX" --with-libarchive.pc --with-openssl.pc
    make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
    make install
) > "$WORK/build.log" 2>&1 || {
    echo "ERROR: building pkg $PKG_TAG failed; last lines of the build log:" >&2
    tail -n 40 "$WORK/build.log" >&2
    exit 1
}
"$PREFIX/sbin/pkg" --version >/dev/null
echo "$PIN" > "$PREFIX/.pkg-pin"
echo "pkg $("$PREFIX/sbin/pkg" --version) installed in $PREFIX"
