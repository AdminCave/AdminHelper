#!/usr/bin/env bash
#
# restore_guard_test.sh — hermetic tests for restore.sh.
#
# 1-4: the tar-escape guard. It (reject absolute / ../ paths and sym/hardlink
# members) runs BEFORE any docker call or the confirm prompt, so it's testable
# with just tar + crafted archives — no stack needed. A genuine archive passes the
# guard and stops at the confirm (exit 0); a crafted one is rejected (exit 1). The
# grep patterns are fragile (locale-dependent tar output), so a regression could
# silently disable the guard and let a hostile backup write outside the target
# (audit 6.66).
# 5: the wait for postgres, against a docker stub that plays a fresh host.
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

# --- 5. the wait for postgres takes the path restore_db takes ────────────────
# On a fresh volume the image's init server listens on the socket only: a socket
# pg_isready says ready at once, while 127.0.0.1 refuses until the restart. The
# stub plays that — TCP answers from its third probe on, a psql over TCP before
# then fails — and logs every call, so the order is checkable.
mkdir -p "$WORK/bin" "$WORK/dr"
cat > "$WORK/bin/docker" <<'STUB'
#!/usr/bin/env bash
tcp=$(cat "$STUB_DIR/tcp" 2>/dev/null || echo 0)
case "$*" in
  *"pg_isready -h 127.0.0.1"*) tcp=$((tcp + 1)); echo "$tcp" > "$STUB_DIR/tcp"
                               rc=1; [ "$tcp" -ge 3 ] && rc=0 ;;
  *pg_isready*)                rc=0 ;;
  *psql*)                      rc=0; [ "$tcp" -ge 3 ] || rc=2 ;;
  *pg_restore*)                cat >/dev/null; rc=0 ;;
  *)                           rc=0 ;;
esac
echo "rc=$rc $*" >> "$STUB_DIR/calls.log"
exit "$rc"
STUB
chmod +x "$WORK/bin/docker"
printf 'dump\n' > "$WORK/dr/adminhelper.dump"
tar czf "$WORK/dr.tar.gz" -C "$WORK/dr" .
out=$( cd "$WORK" && STUB_DIR="$WORK" PATH="$WORK/bin:$PATH" bash "$RESTORE" "$WORK/dr.tar.gz" --yes </dev/null 2>&1 ); rc=$?
ready=$(grep -n '^rc=0 .*pg_isready -h 127.0.0.1' "$WORK/calls.log" 2>/dev/null | head -n1 | cut -d: -f1)
first_psql=$(grep -n 'psql' "$WORK/calls.log" 2>/dev/null | head -n1 | cut -d: -f1)
[ $rc -eq 0 ] && ok "restore.sh finishes on a fresh host" || bad "fresh host: rc=$rc out=[$out]"
{ [ -n "$ready" ] && [ -n "$first_psql" ] && [ "$ready" -lt "$first_psql" ]; } \
  && ok "TCP is ready before the first psql" \
  || bad "no TCP pg_isready before psql: $(cat "$WORK/calls.log" 2>/dev/null)"

echo
echo "──────────────────────────────────────────"
echo "  restore_guard_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
