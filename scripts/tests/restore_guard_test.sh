#!/usr/bin/env bash
#
# restore_guard_test.sh — hermetic test for restore.sh's tar-escape guard.
#
# The guard (reject absolute / ../ paths and sym/hardlink members) runs BEFORE any
# docker call or the confirm prompt, so it's testable with just tar + crafted
# archives — no stack needed. A genuine archive passes the guard and stops at the
# confirm (exit 0); a crafted one is rejected (exit 1). The grep patterns are
# fragile (locale-dependent tar output), so a regression could silently disable
# the guard and let a hostile backup write outside the target (audit 6.66).
#
# Run: bash scripts/tests/restore_guard_test.sh   (needs bash, tar, coreutils)

# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
RESTORE="$REPO_ROOT/scripts/restore.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# --- craft archives ---------------------------------------------------------
# clean: a normal backup-shaped archive
mkdir -p "$WORK/good"
printf 'services: {}\n' > "$WORK/good/docker-compose.yml"
printf 'test\n'        > "$WORK/good/MANIFEST.txt"
tar czf "$WORK/good.tar.gz" -C "$WORK/good" .

# absolute path member (-P keeps the leading /, else tar strips it)
printf 'x\n' > "$WORK/evil"
tar -Pczf "$WORK/abs.tar.gz" "$WORK/evil" 2>/dev/null

# ../ escape member (-P keeps the leading ../, else tar strips it)
mkdir -p "$WORK/sub"; printf 'x\n' > "$WORK/sub/evil"
( cd "$WORK/sub" && tar -Pczf "$WORK/dotdot.tar.gz" ../sub/evil 2>/dev/null )

# symlink member
ln -sf /etc/passwd "$WORK/link"
tar czf "$WORK/sym.tar.gz" -C "$WORK" link

run_restore() { ( cd "$WORK" && bash "$RESTORE" "$1" </dev/null 2>&1 ); }

# --- 1. clean archive passes the guard, stops at the confirm ────────────────
out=$(run_restore "$WORK/good.tar.gz")
# The guard passes (no rejection); restore then reaches the confirm and stops on the
# EOF read — the point is that the guard did NOT reject a legitimate archive.
{ echo "$out" | grep -q 'Fortfahren' && ! echo "$out" | grep -qiE 'absolute oder|Sym-/Hardlink'; } \
  && ok "clean archive passes the guard (reaches the confirm)" || bad "clean archive: [$out]"

# --- 2. absolute path member rejected ──────────────────────────────────────
out=$(run_restore "$WORK/abs.tar.gz"); rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q 'absolute'; } && ok "absolute path rejected" || bad "absolute not rejected: rc=$rc out=[$out]"

# --- 3. ../ escape member rejected ──────────────────────────────────────────
out=$(run_restore "$WORK/dotdot.tar.gz"); rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q 'absolute oder'; } && ok "../ escape rejected" || bad "../ not rejected: rc=$rc out=[$out]"

# --- 4. symlink member rejected ─────────────────────────────────────────────
out=$(run_restore "$WORK/sym.tar.gz"); rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q 'Sym-/Hardlink'; } && ok "symlink member rejected" || bad "symlink not rejected: rc=$rc out=[$out]"

echo
echo "──────────────────────────────────────────"
echo "  restore_guard_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
