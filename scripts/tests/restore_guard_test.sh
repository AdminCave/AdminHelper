#!/usr/bin/env bash
#
# restore_guard_test.sh — hermetic tests for restore.sh, pg-restore.sh and backup.sh.
#
# 1-4: the tar-escape guard. It (reject absolute / ../ paths and sym/hardlink
# members) runs BEFORE any docker call or the confirm prompt, so it's testable
# with just tar + crafted archives — no stack needed. A genuine archive passes the
# guard and stops at the confirm (exit 0); a crafted one is rejected (exit 1). The
# grep patterns are fragile (locale-dependent tar output), so a regression could
# silently disable the guard and let a hostile backup write outside the target
# (audit 6.66).
# 5: the wait for postgres, against a docker stub that plays a fresh host.
# 6-9: after a restore of the server DB, restore.sh and pg-restore.sh move the
# install time of the certificate register to now (R-0224), against stubs; without
# the server DB nothing is moved.
# 10-11: backup.sh, against a docker stub and a tar wrapper that logs the mode of
# the archive right after writing it, under umask 022: the archive is 0600 from the
# first byte and gets its name only once complete, a new output dir is 0700; a
# failed archive write leaves the output dir empty.
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
{ grep -q 'Fortfahren' <<<"$out" && ! grep -qiE 'absolute oder|Sym-/Hardlink' <<<"$out"; } \
  && ok "clean archive passes the guard (reaches the confirm)" || bad "clean archive: [$out]"

# --- 2. absolute path member rejected ──────────────────────────────────────
out=$(run_restore "$WORK/abs.tar.gz"); rc=$?
{ [ $rc -ne 0 ] && grep -q 'absolute' <<<"$out"; } && ok "absolute path rejected" || bad "absolute not rejected: rc=$rc out=[$out]"

# --- 3. ../ escape member rejected ──────────────────────────────────────────
out=$(run_restore "$WORK/dotdot.tar.gz"); rc=$?
{ [ $rc -ne 0 ] && grep -q 'absolute oder' <<<"$out"; } && ok "../ escape rejected" || bad "../ not rejected: rc=$rc out=[$out]"

# --- 4. symlink member rejected ─────────────────────────────────────────────
out=$(run_restore "$WORK/sym.tar.gz"); rc=$?
{ [ $rc -ne 0 ] && grep -q 'Sym-/Hardlink' <<<"$out"; } && ok "symlink member rejected" || bad "symlink not rejected: rc=$rc out=[$out]"

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

# --- 6./7. restore.sh reopens the register transition after the server DB ───
REOPEN="UPDATE certificate_register_state SET installed_at = timezone('UTC', now())"
mkdir -p "$WORK/reg/bin" "$WORK/reg/full" "$WORK/reg/mon" "$WORK/reg/a" "$WORK/reg/b"
cat > "$WORK/reg/bin/docker" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *ON_ERROR_STOP*) cat > "$STUB_DIR/register.sql" ;;
  *pg_restore*)    cat >/dev/null ;;
esac
echo "$*" >> "$STUB_DIR/calls.log"
exit 0
STUB
chmod +x "$WORK/reg/bin/docker"
printf 'dump\n' > "$WORK/reg/full/adminhelper.dump"
printf 'dump\n' > "$WORK/reg/mon/adminhelper_monitor.dump"
tar czf "$WORK/reg/full.tar.gz" -C "$WORK/reg/full" .
tar czf "$WORK/reg/mon.tar.gz" -C "$WORK/reg/mon" .
reg_restore() { ( cd "$WORK" && STUB_DIR="$1" PATH="$WORK/reg/bin:$PATH" bash "$RESTORE" "$2" --yes </dev/null 2>&1 ); }

out=$(reg_restore "$WORK/reg/a" "$WORK/reg/full.tar.gz"); rc=$?
restored=$(grep -n 'pg_restore' "$WORK/reg/a/calls.log" 2>/dev/null | head -n1 | cut -d: -f1)
reopened=$(grep -n 'ON_ERROR_STOP' "$WORK/reg/a/calls.log" 2>/dev/null | head -n1 | cut -d: -f1)
{ [ $rc -eq 0 ] && grep -qF "$REOPEN" "$WORK/reg/a/register.sql" 2>/dev/null; } \
  && ok "restore.sh moves the install time of the register to now" \
  || bad "register not reopened: rc=$rc out=[$out] calls=[$(cat "$WORK/reg/a/calls.log" 2>/dev/null)]"
{ [ -n "$restored" ] && [ -n "$reopened" ] && [ "$restored" -lt "$reopened" ]; } \
  && ok "the register is reopened after the server DB is restored" \
  || bad "order: pg_restore at ${restored:-none}, reopen at ${reopened:-none}"

out=$(reg_restore "$WORK/reg/b" "$WORK/reg/mon.tar.gz"); rc=$?
{ [ $rc -eq 0 ] && grep -q 'pg_restore' "$WORK/reg/b/calls.log" 2>/dev/null \
    && ! grep -q 'ON_ERROR_STOP' "$WORK/reg/b/calls.log"; } \
  && ok "without the server DB the register is left alone" \
  || bad "monitor-only restore: rc=$rc calls=[$(cat "$WORK/reg/b/calls.log" 2>/dev/null)]"

# --- 8./9. pg-restore.sh does the same, for the server DB only ──────────────
mkdir -p "$WORK/pg/bin" "$WORK/pg/a" "$WORK/pg/b"
cat > "$WORK/pg/bin/pg_restore" <<'STUB'
#!/usr/bin/env bash
echo "pg_restore $*" >> "$STUB_DIR/calls.log"
STUB
cat > "$WORK/pg/bin/psql" <<'STUB'
#!/usr/bin/env bash
echo "psql $*" >> "$STUB_DIR/calls.log"
cat >> "$STUB_DIR/psql.in"
STUB
chmod +x "$WORK/pg/bin/pg_restore" "$WORK/pg/bin/psql"
printf 'dump\n' > "$WORK/pg/x.dump"
pg_restore_run() { STUB_DIR="$1" PATH="$WORK/pg/bin:$PATH" sh "$REPO_ROOT/scripts/pg-restore.sh" "$2" "$WORK/pg/x.dump" 2>&1; }

out=$(pg_restore_run "$WORK/pg/a" adminhelper); rc=$?
first=$(head -n1 "$WORK/pg/a/calls.log" 2>/dev/null)
{ [ $rc -eq 0 ] && grep -qF "$REOPEN" "$WORK/pg/a/psql.in" 2>/dev/null && [ "${first%% *}" = pg_restore ]; } \
  && ok "pg-restore.sh reopens the register after restoring the server DB" \
  || bad "pg-restore adminhelper: rc=$rc out=[$out] calls=[$(cat "$WORK/pg/a/calls.log" 2>/dev/null)]"

out=$(pg_restore_run "$WORK/pg/b" adminhelper_monitor); rc=$?
{ [ $rc -eq 0 ] && grep -q '^pg_restore' "$WORK/pg/b/calls.log" 2>/dev/null \
    && ! grep -q '^psql' "$WORK/pg/b/calls.log"; } \
  && ok "pg-restore.sh leaves the register alone for the monitoring DB" \
  || bad "pg-restore adminhelper_monitor: rc=$rc calls=[$(cat "$WORK/pg/b/calls.log" 2>/dev/null)]"

# --- 10./11. backup.sh: archive 0600 from the first byte, named once complete ──
# The docker stub plays a running stack: postgres is up, every service tars its
# data dir (non-empty output), pg_dump writes bytes; any other call fails. The tar
# wrapper runs the real tar for the archive write (czf <file> -C <dir> .), then
# logs the mode and the name the file had while tar wrote it; AH_TEST_TAR_FAIL=1
# makes that write fail (exit 2) after the bytes are on disk.
BACKUP="$REPO_ROOT/scripts/backup.sh"
mkdir -p "$WORK/bk/bin" "$WORK/bk/run" "$WORK/bk/a" "$WORK/bk/b"
printf 'services: {}\n' > "$WORK/bk/run/docker-compose.yml"
cat > "$WORK/bk/bin/docker" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  "compose ps --status running --quiet postgres") echo 0123456789ab ;;
  "compose exec -T postgres sh -c "*)             printf 'PGDMP-stub\n' ;;
  "compose exec -T "*" tar czf - -C "*" .")       printf 'tar-stub\n' ;;
  *) echo "unexpected docker call: $*" >&2; exit 1 ;;
esac
STUB
AH_TEST_REAL_TAR=$(command -v tar); export AH_TEST_REAL_TAR
cat > "$WORK/bk/bin/tar" <<'STUB'
#!/usr/bin/env bash
if [ "$#" -eq 5 ] && [ "$1" = czf ] && [ "$2" != - ] && [ "$3" = -C ] && [ "$5" = . ]; then
  "$AH_TEST_REAL_TAR" "$@" || exit
  stat -c '%a %n' "$2" >> "$STUB_DIR/tar.log"
  [ "${AH_TEST_TAR_FAIL:-}" != 1 ] || exit 2
  exit 0
fi
exec "$AH_TEST_REAL_TAR" "$@"
STUB
chmod +x "$WORK/bk/bin/docker" "$WORK/bk/bin/tar"
# bk_run <stub dir> <output dir> [VAR=value…] — backup.sh from a compose dir, umask 022.
bk_run() {
  local stub="$1" out="$2"; shift 2
  ( cd "$WORK/bk/run" && umask 022 \
      && env "$@" STUB_DIR="$stub" PATH="$WORK/bk/bin:$PATH" bash "$BACKUP" --output "$out" </dev/null 2>&1 )
}

out=$(bk_run "$WORK/bk/a" "$WORK/bk/a/out"); rc=$?
logged=$(cat "$WORK/bk/a/tar.log" 2>/dev/null)
entries=$(ls -A "$WORK/bk/a/out" 2>/dev/null)
archive="$WORK/bk/a/out/$entries"
written_mode=${logged%% *}; written_name=$(basename "${logged#* }" 2>/dev/null)
case "$written_name" in adminhelper-backup-*.tar.gz) written_final=1 ;; *) written_final=0 ;; esac
case "$entries" in adminhelper-backup-*.tar.gz) one_archive=1 ;; *) one_archive=0 ;; esac
members=$(tar tzf "$archive" 2>/dev/null)
{ [ $rc -eq 0 ] && [ "$(wc -l <<<"$logged")" -eq 1 ] && [ "$written_mode" = 600 ] && [ "$written_final" = 0 ]; } \
  && ok "backup.sh writes the archive 0600 under a temp name" \
  || bad "archive while written: rc=$rc logged=[$logged] out=[$out]"
{ [ "$one_archive" = 1 ] && [ "$(stat -c '%a' "$archive")" = 600 ] \
    && [ "$(stat -c '%a' "$WORK/bk/a/out")" = 700 ] \
    && grep -qx './MANIFEST.txt' <<<"$members" && grep -qx './ca-pki.tar.gz' <<<"$members" \
    && grep -qx './adminhelper.dump' <<<"$members"; } \
  && ok "backup.sh leaves one complete 0600 archive in a new 0700 dir" \
  || bad "after the run: entries=[$entries] dir=$(stat -c '%a' "$WORK/bk/a/out" 2>/dev/null) archive=$(stat -c '%a' "$archive" 2>/dev/null) members=[$members]"

out=$(bk_run "$WORK/bk/b" "$WORK/bk/b/out" AH_TEST_TAR_FAIL=1); rc=$?
entries=$(ls -A "$WORK/bk/b/out" 2>/dev/null)
{ [ $rc -ne 0 ] && [ -s "$WORK/bk/b/tar.log" ] && [ -d "$WORK/bk/b/out" ] && [ -z "$entries" ]; } \
  && ok "a failed archive write leaves the output dir empty" \
  || bad "failed write: rc=$rc entries=[$entries] logged=[$(cat "$WORK/bk/b/tar.log" 2>/dev/null)] out=[$out]"

echo
echo "──────────────────────────────────────────"
echo "  restore_guard_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
