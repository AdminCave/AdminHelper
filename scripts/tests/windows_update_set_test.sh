#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# windows_update_set_test.sh - apps/agent/build-windows-update.sh with a
# throwaway minisign key: the set holds exactly the files the agent's
# self-update expects, SHA256SUMS matches them, the signature verifies with the
# trusted comment the agent compares against VERSION, and the script refuses a
# key other than the pinned one and a malformed VERSION.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/apps/agent/build-windows-update.sh"
command -v minisign >/dev/null || { echo "SKIP: minisign missing"; exit 75; }

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
fail=0
ok()  { echo "  ok: $*"; }
bad() { echo "  FAIL: $*"; fail=1; }

minisign -G -W -p "$T/test.pub" -s "$T/test.key" >/dev/null </dev/null
minisign -G -W -p "$T/other.pub" -s "$T/other.key" >/dev/null </dev/null
PUB="$(sed -n 2p "$T/test.pub")"
printf 'agent-bytes\n' > "$T/agent.exe"
printf 'frpc-bytes\n' > "$T/frpc.exe"

build() { # <out> <key> <version> [pub]
    OUT_DIR="$1" MINISIGN_KEY="$2" VERSION="$3" MINISIGN_PUBKEY="${4:-$PUB}" \
        AGENT_EXE="$T/agent.exe" FRPC_EXE="$T/frpc.exe" bash "$SCRIPT" >"$T/out.log" 2>&1
}

# Happy path
rc=0; build "$T/win" "$T/test.key" 1.2.3 || rc=$?
if [ "$rc" -eq 0 ]; then ok "builds with the pinned key"; else bad "build rc=$rc: $(cat "$T/out.log")"; fi
files="$(cd "$T/win" 2>/dev/null && LC_ALL=C ls | tr '\n' ' ')"
[ "$files" = "SHA256SUMS SHA256SUMS.minisig VERSION adminhelper-agent.exe frpc.exe " ] \
    && ok "exactly the five files" || bad "files: $files"
[ "$(cat "$T/win/VERSION" 2>/dev/null)" = "1.2.3" ] && ok "VERSION" || bad "VERSION content"
cmp -s "$T/win/adminhelper-agent.exe" "$T/agent.exe" && cmp -s "$T/win/frpc.exe" "$T/frpc.exe" \
    && ok "binaries copied" || bad "binaries differ"
names="$(awk '{print $2}' "$T/win/SHA256SUMS" 2>/dev/null | tr '\n' ' ')"
[ "$names" = "VERSION adminhelper-agent.exe frpc.exe " ] && ok "SHA256SUMS names" || bad "SHA256SUMS names: $names"
(cd "$T/win" && sha256sum -c --quiet SHA256SUMS) && ok "SHA256SUMS matches" || bad "SHA256SUMS mismatch"
minisign -V -q -P "$PUB" -m "$T/win/SHA256SUMS" -x "$T/win/SHA256SUMS.minisig" >/dev/null \
    && ok "minisign -V" || bad "signature does not verify"
tc="$(sed -n 3p "$T/win/SHA256SUMS.minisig" 2>/dev/null)"
[ "$tc" = "trusted comment: adminhelper-agent windows v1.2.3" ] && ok "trusted comment" || bad "trusted comment: $tc"
sigalg="$(sed -n 2p "$T/win/SHA256SUMS.minisig" | base64 -d 2>/dev/null | head -c2)"
[ "$sigalg" = "ED" ] && ok "prehashed ED signature" || bad "signature algorithm: $sigalg"

# A key other than the pinned one: refused, with a message
rc=0; build "$T/wrong" "$T/other.key" 1.2.3 || rc=$?
if [ "$rc" -ne 0 ] && grep -q "pinned public key" "$T/out.log"; then ok "wrong key refused"; else bad "wrong key: rc=$rc $(cat "$T/out.log")"; fi

# Default pin: without MINISIGN_PUBKEY the key of scripts/update.sh applies,
# which the throwaway key is not
rc=0; OUT_DIR="$T/default" MINISIGN_KEY="$T/test.key" VERSION=1.2.3 \
    AGENT_EXE="$T/agent.exe" FRPC_EXE="$T/frpc.exe" bash "$SCRIPT" >"$T/out.log" 2>&1 || rc=$?
if [ "$rc" -ne 0 ] && grep -q "pinned public key" "$T/out.log"; then ok "default pin is update.sh's key"; else bad "default pin: rc=$rc"; fi

# Malformed versions
for v in v1.2.3 1.2 01.2.3 1.2.3-beta ""; do
    rc=0; build "$T/badver" "$T/test.key" "$v" || rc=$?
    if [ "$rc" -ne 0 ] && [ ! -e "$T/badver" ]; then ok "VERSION '$v' refused"; else bad "VERSION '$v' accepted (rc=$rc)"; fi
done

# R-1679: under a locale like de_DE.UTF-8, [0-9] in =~ also matches digits outside ASCII ("²").
# R-1683: the locale is compiled into $T, so the check runs live where de_DE.UTF-8 is not installed
# (CI) too; the installed one is the fallback, and only without either does the static check remain.
loc_path=""
if command -v localedef >/dev/null 2>&1 && mkdir -p "$T/locale" \
    && localedef -i de_DE -f UTF-8 "$T/locale/de_DE.UTF-8" >/dev/null 2>&1; then
    loc_path="$T/locale"
elif ! locale -a 2>/dev/null | grep -qix 'de_DE.utf8'; then
    loc_path=none
fi
if [ "$loc_path" != none ]; then
    # A locale that did not load would make the refusal below prove nothing.
    if LOCPATH="$loc_path" LC_ALL=de_DE.UTF-8 bash -c '[[ ² =~ ^[0-9]$ ]]' 2>/dev/null; then
        ok "de_DE.UTF-8 active (${loc_path:-installed}): [0-9] matches a non-ASCII digit"
    else
        bad "de_DE.UTF-8 did not load (LOCPATH='$loc_path')"
    fi
    rc=0; LOCPATH="$loc_path" LC_ALL=de_DE.UTF-8 build "$T/locver" "$T/test.key" "1.².3" || rc=$?
    if [ "$rc" -ne 0 ] && [ ! -e "$T/locver" ]; then ok "non-ASCII digit refused under de_DE.UTF-8"; else bad "VERSION '1.².3' accepted under de_DE.UTF-8 (rc=$rc)"; fi
else
    grep -qx 'export LC_ALL=C' "$SCRIPT" && ok "script pins LC_ALL=C (de_DE.UTF-8 not installed)" \
        || bad "script does not pin LC_ALL=C"
fi

if [ "$fail" -ne 0 ]; then echo "windows_update_set_test: FAIL"; exit 1; fi
echo "windows_update_set_test: PASS"
