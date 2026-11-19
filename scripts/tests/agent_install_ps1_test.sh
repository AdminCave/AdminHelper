#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# agent_install_ps1_test.sh — hermetic invariants of scripts/agent-install.ps1.
#
# The dev box has no PowerShell; the script runs for real in the windows-latest CI
# job. This test pins the properties a later edit must not lose: release files are
# hash-checked before the first change, the token never becomes a program argument,
# nothing loaded is executed as code, and no `exit` closes the caller's shell.
# Needs: bash, grep, awk.
#
# Run: bash scripts/tests/agent_install_ps1_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SCRIPT="${AH_PS1_SCRIPT:-$HERE/../agent-install.ps1}"
RELEASE_YML="$HERE/../../.github/workflows/release.yml"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

[ -f "$SCRIPT" ] || { echo "FAIL: $SCRIPT missing"; exit 1; }

# Code lines only: comments say "exit" and "Invoke-Expression" on purpose.
CODE=$(grep -v '^[[:space:]]*#' "$SCRIPT")
line_of() { grep -n -F -- "$1" "$SCRIPT" | grep -v ':[[:space:]]*#' | head -1 | cut -d: -f1; }

echo "agent-install.ps1 invariants"

head -3 "$SCRIPT" | grep -q 'SPDX-License-Identifier: GPL-3.0-or-later' \
    && ok "SPDX header" || bad "SPDX header missing"

n=$(printf '%s\n' "$CODE" | grep -ciE '(invoke-expression|\biex\b|scriptblock\]::create)' || true)
[ "$n" = 0 ] && ok "no loaded content is executed as code" || bad "Invoke-Expression/iex/ScriptBlock::Create in code ($n)"

# exit as a statement (line start or after ; { }), not inside a message string.
n=$(printf '%s\n' "$CODE" | grep -cE '(^|[;{}])[[:space:]]*exit([[:space:]]|;|$)' || true)
[ "$n" = 0 ] && ok "no exit (it would close the caller's PowerShell)" || bad "exit used ($n lines)"

hash_at=$(line_of 'Assert-FileHash (Join-Path $work $name)')
install_at=$(line_of '@("service", "install")')
dl_at=$(line_of 'Invoke-WebRequest -UseBasicParsing')
if [ -n "$hash_at" ] && [ -n "$install_at" ] && [ -n "$dl_at" ] \
    && [ "$dl_at" -lt "$hash_at" ] && [ "$hash_at" -lt "$install_at" ]; then
    ok "download < hash check < service install (lines $dl_at < $hash_at < $install_at)"
else
    bad "hash check not between download and service install (dl=$dl_at hash=$hash_at install=$install_at)"
fi

# The hash loop covers both executables.
loop=$(grep -n -F 'foreach ($name in @($AgentAsset, $FrpcAsset))' "$SCRIPT" | cut -d: -f1)
[ -n "$loop" ] && [ $((hash_at - loop)) -eq 1 ] \
    && ok "agent and frpc both hash-checked" || bad "hash loop does not cover agent and frpc"

grep -qF "throw \"SHA-256 of" "$SCRIPT" \
    && ok "hash mismatch throws" || bad "hash mismatch does not throw"
grep -qF 'if ($found.Count -ne 1) { throw' "$SCRIPT" \
    && ok "a file missing from SHA256SUMS (or listed twice) throws" || bad "missing SHA256SUMS entry not fatal"

prov=$(grep -F '$provArgs = @(' "$SCRIPT")
case "$prov" in
    *'--token-stdin'*) ok "provision reads the token from stdin" ;;
    *) bad "provision without --token-stdin" ;;
esac
n=$(grep -E '\$provArgs \+?=' "$SCRIPT" | grep -c '\$Token' || true)
[ "$n" = 0 ] && ok "token never in the provision arguments" || bad "token in the provision arguments ($n)"
grep -qF 'Invoke-Native $agent $provArgs $Token' "$SCRIPT" \
    && ok "token passed as stdin of provision" || bad "token not passed via stdin"
grep -qF 'Read-Host -AsSecureString' "$SCRIPT" \
    && ok "token prompt is hidden" || bad "token prompt not -AsSecureString"

grep -qF '$uri.Scheme -eq "http" -and $uri.IsLoopback' "$SCRIPT" \
    && ok "plain http only on loopback" || bad "http override not limited to loopback"
grep -qF -- '-not $Server.StartsWith("https://")' "$SCRIPT" \
    && ok "-Server must be https" || bad "-Server not forced to https"
grep -qF 'if (-not (Test-Administrator)) { throw' "$SCRIPT" \
    && ok "admin check is fatal" || bad "admin check missing"

# The asset names must be the ones release.yml publishes.
for a in adminhelper-agent-windows-x86_64.exe frpc-windows-x86_64.exe; do
    if grep -qF "\"$a\"" "$SCRIPT" && grep -qF "dist/$a" "$RELEASE_YML"; then
        ok "asset $a in script and release.yml"
    else
        bad "asset $a not in both script and release.yml"
    fi
done

echo "agent_install_ps1_test: $PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
