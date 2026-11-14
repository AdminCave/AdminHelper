#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

#
# pkg_repo_build_test.sh — verifies apps/agent/build-pkg.sh end to end with pkg built from the
# freebsd/pkg sources (scripts/release/build-pkg-tool.sh) and a throwaway PKCS#8 RSA key, the
# format of the release secret PKG_REPO_SIGNING_KEY: for both ABIs the packages, meta.conf and the
# signed catalogue must be there, and pkg itself must accept the catalogue with the key's public
# part and reject it with a foreign one, as a FreeBSD host does on `pkg update`.
#
# Native when PKG_TOOL_PREFIX names a prefix with sbin/pkg (the CI job builds and caches it);
# otherwise the test re-execs itself in an ubuntu container that installs the build dependencies
# and builds pkg first. Without either it exits 75 (not run).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="9.9.9"
ABIS="FreeBSD:14:amd64 FreeBSD:15:amd64"
IMAGE="ubuntu:24.04"

# --- Container re-exec without a prebuilt pkg ---------------------------------
if [ ! -x "${PKG_TOOL_PREFIX:-/nonexistent}/sbin/pkg" ]; then
    if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
        echo "SKIP: no PKG_TOOL_PREFIX with sbin/pkg and no usable Docker — cannot build pkg." >&2
        exit 75
    fi
    echo "[pkg-test] no prebuilt pkg -> re-exec in container ${IMAGE} ..."
    exec docker run --rm -v "${REPO_ROOT}:/src:ro" -w /src "$IMAGE" bash -c '
        set -e
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends \
            $(bash scripts/release/build-pkg-tool.sh --deps) openssl >/dev/null
        bash scripts/release/build-pkg-tool.sh /opt/pkg
        export PKG_TOOL_PREFIX=/opt/pkg
        exec bash scripts/tests/pkg_repo_build_test.sh
    '
fi

# --- Native run ------------------------------------------------------------------
PKG="${PKG_TOOL_PREFIX}/sbin/pkg"
export PATH="${PKG_TOOL_PREFIX}/sbin:${PATH}"
for t in openssl bsdtar; do
    command -v "$t" >/dev/null 2>&1 || { echo "FAIL: $t not on the PATH" >&2; exit 1; }
done
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "  ok: $*"; }

# Dummy binaries: build-pkg.sh only packs them.
printf '#!/bin/sh\necho agent\n' > "$WORK/agent"
printf '#!/bin/sh\necho frpc\n' > "$WORK/frpc"
# PKCS#8 ("BEGIN PRIVATE KEY") as the secret; the foreign key for the counter-probe.
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$WORK/key.pem" 2>/dev/null
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$WORK/foreign.pem" 2>/dev/null
head -1 "$WORK/key.pem" | grep -qx -- '-----BEGIN PRIVATE KEY-----' || fail "throwaway key is not PKCS#8"
openssl pkey -in "$WORK/key.pem" -pubout -out "$WORK/key.pub"
openssl pkey -in "$WORK/foreign.pem" -pubout -out "$WORK/foreign.pub"

OUT="$WORK/out"
VERSION="$VERSION" AGENT_BINARY="$WORK/agent" FRPC_BINARY="$WORK/frpc" OUT_DIR="$OUT" \
    PKG_REPO_KEY="$WORK/key.pem" bash "$REPO_ROOT/apps/agent/build-pkg.sh" > "$WORK/build.log" 2>&1 \
    || { cat "$WORK/build.log" >&2; fail "build-pkg.sh failed"; }

# pkg update against the repo as a host with the given public key would run it; prints the output.
pkg_update() { # <repo dir> <abi> <pubkey> <client dir>
    local repo="$1" abi="$2" pub="$3" c="$4" osversion
    osversion="${abi#FreeBSD:}"; osversion="${osversion%%:*}00000"
    mkdir -p "$c/repos" "$c/db" "$c/cache"
    printf 'T: { url: "file://%s", signature_type: "pubkey", pubkey: "%s", enabled: yes }\n' \
        "$repo" "$pub" > "$c/repos/t.conf"
    "$PKG" -o ABI="$abi" -o OSVERSION="$osversion" -o PKG_DBDIR="$c/db" -o PKG_CACHEDIR="$c/cache" \
        -o REPOS_DIR="$c/repos" update -f 2>&1 || true
}
pkg_rquery() { # <abi> <client dir>
    "$PKG" -o ABI="$1" -o PKG_DBDIR="$2/db" -o REPOS_DIR="$2/repos" rquery -a '%n %v %q' 2>/dev/null | sort || true
}

for abi in $ABIS; do
    repo="$OUT/freebsd/$abi"
    for f in "All/adminhelper-agent-${VERSION}.pkg" "All/os-adminhelper-${VERSION}.pkg" \
             meta.conf packagesite.pkg data.pkg; do
        [ -s "$repo/$f" ] || fail "[$abi] missing or empty: $f"
    done
    for a in packagesite data; do
        bsdtar -tf "$repo/$a.pkg" | grep -qx signature || fail "[$abi] $a.pkg carries no signature"
    done
    ok "[$abi] packages, meta.conf and signed catalogue present"

    # The plugin ships the public part of the signing key, which its repository config names.
    keyentry="$(bsdtar -tf "$repo/All/os-adminhelper-${VERSION}.pkg" | grep 'etc/pkg/keys/AdminHelper.pub$' || true)"
    [ -n "$keyentry" ] || fail "[$abi] os-adminhelper carries no etc/pkg/keys/AdminHelper.pub"
    bsdtar -xOf "$repo/All/os-adminhelper-${VERSION}.pkg" "$keyentry" | cmp -s - "$WORK/key.pub" \
        || fail "[$abi] AdminHelper.pub in the plugin is not the signing key's public part"
    ok "[$abi] plugin carries the signing key's public part"

    c="$WORK/client-${abi//:/-}"
    out="$(pkg_update "$repo" "$abi" "$WORK/key.pub" "$c")"
    grep -q 'update completed' <<<"$out" || fail "[$abi] pkg update with the right key failed: $out"
    want="$(printf 'adminhelper-agent %s %s\nos-adminhelper %s %s\n' "$VERSION" "$abi" "$VERSION" "$abi")"
    got="$(pkg_rquery "$abi" "$c")"
    [ "$got" = "$want" ] || fail "[$abi] catalogue lists '$got', expected '$want'"
    ok "[$abi] pkg accepts the catalogue with the right key and lists both packages"

    # Counter-probe: a host pinned to another key must refuse the catalogue (pkg update still
    # exits 0 and drops the repository, so the evidence is its message and the empty catalogue).
    c="$WORK/foreign-${abi//:/-}"
    out="$(pkg_update "$repo" "$abi" "$WORK/foreign.pub" "$c")"
    grep -q 'signature verification failure' <<<"$out" \
        || fail "[$abi] pkg did not report a signature failure with a foreign key: $out"
    [ -z "$(pkg_rquery "$abi" "$c")" ] || fail "[$abi] catalogue readable with a foreign key"
    ok "[$abi] pkg rejects the catalogue with a foreign key"
done

echo "[pkg-test] PASS — pkg repo for ${ABIS// /, } built and signed with a PKCS#8 key."
