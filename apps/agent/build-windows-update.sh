#!/bin/bash

# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Build the signed Windows release set the agent's self-update fetches from the
# gateway's repo plane (:8445/windows/, apps/agent/internal/selfupdate).
#
# Output ($OUT_DIR, default ./windows):
#   VERSION                 the release version, X.Y.Z
#   adminhelper-agent.exe   the agent
#   frpc.exe                the frpc the agent pins (frpcpin.go)
#   SHA256SUMS              sha256sum of exactly these three files
#   SHA256SUMS.minisig      minisign signature; its trusted comment binds the
#                           version ("adminhelper-agent windows v<VERSION>"),
#                           which the agent compares against VERSION
#
# Inputs (env):
#   VERSION           (required) X.Y.Z, no "v"
#   AGENT_EXE         (required) path to adminhelper-agent.exe
#   FRPC_EXE          (required) path to frpc.exe
#   MINISIGN_KEY      (required) path to a passwordless minisign secret key file
#   MINISIGN_PUBKEY   (optional) public key to verify against; default: the one
#                     scripts/update.sh pins, which the agent pins as well
#   OUT_DIR           (optional) default ./windows
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
die() { echo "build-windows-update: $*" >&2; exit 1; }

[ -n "${VERSION:-}" ] || die "VERSION is not set"
[[ "$VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] \
    || die "VERSION must be X.Y.Z without a leading v: $VERSION"
for v in AGENT_EXE FRPC_EXE MINISIGN_KEY; do
    [ -f "${!v:-}" ] || die "$v does not name a file"
done
command -v minisign >/dev/null || die "minisign missing"

PUB="${MINISIGN_PUBKEY:-}"
if [ -z "$PUB" ]; then
    PUB="$(grep -m1 '^MINISIGN_PUBKEY=' "$ROOT/scripts/update.sh" | cut -d'"' -f2 || true)"
fi
[ -n "$PUB" ] || die "no MINISIGN_PUBKEY pinned in scripts/update.sh"

OUT="${OUT_DIR:-./windows}"
rm -rf "$OUT"
mkdir -p "$OUT"
printf '%s\n' "$VERSION" > "$OUT/VERSION"
cp "$AGENT_EXE" "$OUT/adminhelper-agent.exe"
cp "$FRPC_EXE" "$OUT/frpc.exe"
(cd "$OUT" && sha256sum VERSION adminhelper-agent.exe frpc.exe > SHA256SUMS)
minisign -S -s "$MINISIGN_KEY" -m "$OUT/SHA256SUMS" -x "$OUT/SHA256SUMS.minisig" \
    -t "adminhelper-agent windows v$VERSION" < /dev/null >/dev/null
# Against the key the fleet pins, not the one just used: a wrong secret signs
# validly, and every agent would refuse the set only in the field.
minisign -V -q -P "$PUB" -m "$OUT/SHA256SUMS" -x "$OUT/SHA256SUMS.minisig" >/dev/null \
    || die "SHA256SUMS.minisig does not verify against the pinned public key - wrong MINISIGN_KEY?"
echo "build-windows-update: $OUT holds the signed set for v$VERSION"
