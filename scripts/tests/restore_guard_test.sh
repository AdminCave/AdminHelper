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
# 12-14: backup.sh's env.sanitized, against the same stubs and an awk wrapper: under
# C.UTF-8 it is .env byte for byte without the CA_ROOT_PASSPHRASE lines, a Latin-1
# and a NUL byte included; a failing filter aborts the backup and leaves the output
# dir empty; a .env with nothing but the passphrase gives an empty env.sanitized.
# 15: env.sanitized drops CA_ROOT_PASSPHRASE in every key form compose reads
# (export, whitespace around the separator, ':' as the separator) and keeps a key
# that only starts with it.
# 16: backup.sh, against the same stubs and a date stub that fixes the archive
# name: a directory under that name fails the backup and takes no archive, and no
# temp file stays; a symlink under it is replaced by the archive, its target
# stays untouched.
# 17: backup.sh, against the same stubs and a sync wrapper: the archive is synced
# before the rename and the output dir after it; a failing sync fails the backup
# and leaves the output dir empty.
# 18: backup.sh --help prints the comment header and stops at the usage line.
# 19: under C.UTF-8, env.sanitized also drops CA_ROOT_PASSPHRASE commented out,
# behind a BOM or Unicode whitespace, with NBSP before the separator, and the
# continuation lines of a quoted value over several lines, to the end of the file
# if it never closes; a quote after an even number of backslashes closes the
# value, as compose reads it.
# 20: backup.sh writes the archive only into the temp file it created: a link to a
# file, an own file or a FIFO under the temp name, a temp file another tool made 0644
# (a mount without Unix mode) or one with a second hard link fails the backup with
# the hint to back up locally, leaves the other file as it was and no archive; so
# does a temp name swapped for a link after the open (a stat wrapper does the swap) and
# a temp path that leads out of the output dir through a linked dir; a name swapped
# for a dangling link just before the open creates nothing through it.
# 21: the archive is 0600 in an output dir with a default ACL.
# 22: --output with a trailing slash: the temp file still counts as in the output dir.
# 23-25: restore.sh and the service roles, against a docker stub that logs argv and the
# PGPASSWORD it gets: a missing role password in .env stops the restore before any
# docker call, with the hint to init-secrets.sh, and the environment stands in for
# .env as it does for compose; db-init runs before the first pg_restore, each DB goes
# back as its role, nothing as adminhelper, and no password shows in an argv.
#
# Run: bash scripts/tests/restore_guard_test.sh   (needs bash, tar, coreutils, the
#      locale C.UTF-8: without it tests 12 and 19 cannot run, and the test ends with 75)

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

# restore.sh reads the role passwords from the environment before .env, as compose
# does: none may leak in from the caller.
unset SERVER_DB_PASSWORD SCHEDULER_DB_PASSWORD MONITOR_DB_PASSWORD CA_DB_PASSWORD
ROLE_ENV='SERVER_DB_PASSWORD=pw-server
SCHEDULER_DB_PASSWORD=pw-scheduler
MONITOR_DB_PASSWORD=pw-monitor
CA_DB_PASSWORD=pw-ca'
printf '%s\n' "$ROLE_ENV" > "$WORK/.env"

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
first_psql=$(grep -nE 'psql|pg_restore|db-init' "$WORK/calls.log" 2>/dev/null | head -n1 | cut -d: -f1)
[ $rc -eq 0 ] && ok "restore.sh finishes on a fresh host" || bad "fresh host: rc=$rc out=[$out]"
{ [ -n "$ready" ] && [ -n "$first_psql" ] && [ "$ready" -lt "$first_psql" ]; } \
  && ok "TCP is ready before the first database call" \
  || bad "no TCP pg_isready before the first database call: $(cat "$WORK/calls.log" 2>/dev/null)"

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
# wrapper runs the real tar for the archive write (czf <file> -C <dir> ., or czf - into
# a regular file on stdout), then logs the mode and the name the file had while tar
# wrote it; AH_TEST_TAR_FAIL=1
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
if [ "$#" -eq 5 ] && [ "$1" = czf ] && [ "$3" = -C ] && [ "$5" = . ] \
    && { [ "$2" != - ] || [ -f "/proc/$$/fd/1" ]; }; then
  "$AH_TEST_REAL_TAR" "$@" || exit
  # An archive written to stdout (a file descriptor of backup.sh) is logged by the
  # file behind it, the name included.
  if [ "$2" = - ]; then
    printf '%s %s\n' "$(stat -L -c '%a' "/proc/$$/fd/1")" "$(readlink "/proc/$$/fd/1")" >> "$STUB_DIR/tar.log"
  else
    stat -c '%a %n' "$2" >> "$STUB_DIR/tar.log"
  fi
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

# --- 12.-14. backup.sh: env.sanitized is .env without the passphrase lines ───
# The filter was a grep once, and grep takes a file for binary once it holds a NUL
# byte or a byte the caller's locale cannot decode, and leaves lines out (exit 0,
# "binary file matches" on stderr): env.sanitized lost the Latin-1 line, with a
# NUL byte every line, and `|| true` passed any grep error off as an empty file.
# The awk wrapper runs the real awk, except that AH_TEST_AWK_FAIL=1 makes the
# filter on CA_ROOT_PASSPHRASE fail with exit 2 and logs that it did. The
# expectation is written down apart, never read back from .env. The filter ends
# the last line with a newline, so the expectation has one after Z=last although
# .env has none.
AH_TEST_REAL_AWK=$(command -v awk); export AH_TEST_REAL_AWK
cat > "$WORK/bk/bin/awk" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *CA_ROOT_PASSPHRASE*)
    if [ "${AH_TEST_AWK_FAIL:-}" = 1 ]; then echo "$*" >> "$STUB_DIR/awk.log"; exit 2; fi ;;
esac
exec "$AH_TEST_REAL_AWK" "$@"
STUB
chmod +x "$WORK/bk/bin/awk"
mkdir -p "$WORK/bk/c" "$WORK/bk/d" "$WORK/bk/e"
# bk_env <stub dir> — extracts env.sanitized from the archive in <stub dir>/out to
# <stub dir>/x and prints its path (a missing archive or member leaves no file).
bk_env() {
  mkdir -p "$1/x"
  tar xzf "$1/out/"adminhelper-backup-*.tar.gz -C "$1/x" ./env.sanitized >/dev/null 2>&1
  echo "$1/x/env.sanitized"
}

LOCALE_SKIP=""
if [ "$(LC_ALL=C.UTF-8 locale charmap 2>/dev/null)" != UTF-8 ]; then
  LOCALE_SKIP="tests 12 and 19 (non-ASCII bytes in .env under a UTF-8 locale) need the locale C.UTF-8, this system has none"
  echo "  SKIP $LOCALE_SKIP"
else
  printf 'SECRET_KEY=abc\nX=caf\xe9-latin1\nCA_ROOT_PASSPHRASE=pp\n  CA_ROOT_PASSPHRASE=pp2\nY=a\0b\nZ=last' > "$WORK/bk/run/.env"
  printf 'SECRET_KEY=abc\nX=caf\xe9-latin1\nY=a\0b\nZ=last\n' > "$WORK/bk/c/expected"
  out=$(bk_run "$WORK/bk/c" "$WORK/bk/c/out" LC_ALL=C.UTF-8); rc=$?
  sanitized=$(bk_env "$WORK/bk/c")
  { [ $rc -eq 0 ] && cmp -s "$WORK/bk/c/expected" "$sanitized"; } \
    && ok "env.sanitized is .env without the passphrase lines, byte for byte (Latin-1 and NUL line too)" \
    || bad "Latin-1/NUL .env: rc=$rc env.sanitized=[$(cat -v "$sanitized" 2>/dev/null | tr '\n' ' ')] out=[$out]"
fi

printf 'SECRET_KEY=sk9secret\nCA_ROOT_PASSPHRASE=pp9secret\n' > "$WORK/bk/run/.env"
out=$(bk_run "$WORK/bk/d" "$WORK/bk/d/out" AH_TEST_AWK_FAIL=1); rc=$?
entries=$(ls -A "$WORK/bk/d/out" 2>/dev/null)
{ [ $rc -ne 0 ] && [ -s "$WORK/bk/d/awk.log" ] && [ ! -e "$WORK/bk/d/tar.log" ] \
    && [ -d "$WORK/bk/d/out" ] && [ -z "$entries" ]; } \
  && ok "a failing .env filter aborts the backup and leaves the output dir empty" \
  || bad "failing filter: rc=$rc entries=[$entries] awk=[$(cat "$WORK/bk/d/awk.log" 2>/dev/null)] tar=[$(cat "$WORK/bk/d/tar.log" 2>/dev/null)] out=[$out]"
{ grep -q 'ERROR.*\.env' <<<"$out" && ! grep -qE 'sk9secret|pp9secret' <<<"$out"; } \
  && ok "the abort says why and names no value" || bad "abort message: [$out]"

printf 'CA_ROOT_PASSPHRASE=pp\n' > "$WORK/bk/run/.env"
out=$(bk_run "$WORK/bk/e" "$WORK/bk/e/out"); rc=$?
sanitized=$(bk_env "$WORK/bk/e")
{ [ $rc -eq 0 ] && [ -f "$sanitized" ] && [ ! -s "$sanitized" ]; } \
  && ok "a .env with nothing but the passphrase gives an empty env.sanitized" \
  || bad "passphrase-only .env: rc=$rc size=$(stat -c '%s' "$sanitized" 2>/dev/null) out=[$out]"

# --- 15. backup.sh: the passphrase in every key form compose reads ───────────
# Compose also takes `export KEY=…`, whitespace around the separator and ':' as
# the separator (diagnostics.sh reads the .env alike); CA_ROOT_PASSPHRASE_OLD is
# another key and stays.
mkdir -p "$WORK/bk/f"
printf 'A=1\nexport CA_ROOT_PASSPHRASE=pp1\nCA_ROOT_PASSPHRASE = pp2\nCA_ROOT_PASSPHRASE: pp3\n\texport\tCA_ROOT_PASSPHRASE\t:\tpp4\nCA_ROOT_PASSPHRASE_OLD=keep\nB=2\n' > "$WORK/bk/run/.env"
printf 'A=1\nCA_ROOT_PASSPHRASE_OLD=keep\nB=2\n' > "$WORK/bk/f/expected"
out=$(bk_run "$WORK/bk/f" "$WORK/bk/f/out"); rc=$?
sanitized=$(bk_env "$WORK/bk/f")
{ [ $rc -eq 0 ] && cmp -s "$WORK/bk/f/expected" "$sanitized"; } \
  && ok "env.sanitized drops the passphrase in every key form compose reads" \
  || bad "passphrase key forms: rc=$rc env.sanitized=[$(cat -A "$sanitized" 2>/dev/null | tr '\n' ' ')] out=[$out]"

# --- 16. backup.sh: the archive lands under its name as a file ───────────────
# Without -T, mv takes a directory under the archive name (or a symlink to one)
# for the target dir and puts the archive inside it, and backup.sh reports OK.
# The date stub gives backup.sh's timestamp a fixed value, so the name is known
# before the run; any other date call goes to the real date.
AH_TEST_REAL_DATE=$(command -v date); export AH_TEST_REAL_DATE
cat > "$WORK/bk/bin/date" <<'STUB'
#!/usr/bin/env bash
if [ "$#" -eq 1 ] && [ "$1" = '+%Y-%m-%d_%H-%M-%S' ]; then echo 2026-10-22_10-00-00; exit 0; fi
exec "$AH_TEST_REAL_DATE" "$@"
STUB
chmod +x "$WORK/bk/bin/date"
FIXED_NAME=adminhelper-backup-2026-10-22_10-00-00.tar.gz

mkdir -p "$WORK/bk/g/out/$FIXED_NAME"
out=$(bk_run "$WORK/bk/g" "$WORK/bk/g/out"); rc=$?
entries=$(ls -A "$WORK/bk/g/out" 2>/dev/null)
inside=$(ls -A "$WORK/bk/g/out/$FIXED_NAME" 2>/dev/null)
{ [ $rc -ne 0 ] && [ -d "$WORK/bk/g/out/$FIXED_NAME" ] && [ -z "$inside" ] && [ "$entries" = "$FIXED_NAME" ] \
    && grep -q "^\[backup\] ERROR: .*$FIXED_NAME" <<<"$out"; } \
  && ok "a directory under the archive name fails the backup, takes no archive and keeps no temp file" \
  || bad "directory in the way: rc=$rc entries=[$entries] inside=[$inside] out=[$out]"

mkdir -p "$WORK/bk/h/out" "$WORK/bk/h/elsewhere"
ln -s "$WORK/bk/h/elsewhere" "$WORK/bk/h/out/$FIXED_NAME"
out=$(bk_run "$WORK/bk/h" "$WORK/bk/h/out"); rc=$?
archive="$WORK/bk/h/out/$FIXED_NAME"
entries=$(ls -A "$WORK/bk/h/out" 2>/dev/null)
elsewhere=$(ls -A "$WORK/bk/h/elsewhere" 2>/dev/null)
members=$(tar tzf "$archive" 2>/dev/null)
{ [ $rc -eq 0 ] && [ -f "$archive" ] && [ ! -L "$archive" ] && [ "$(stat -c '%a' "$archive")" = 600 ] \
    && [ "$entries" = "$FIXED_NAME" ] && grep -qx './MANIFEST.txt' <<<"$members" && [ -z "$elsewhere" ]; } \
  && ok "a symlink under the archive name is replaced by the archive, its target stays empty" \
  || bad "symlink in the way: rc=$rc type=$(stat -c '%F %a' "$archive" 2>/dev/null) entries=[$entries] elsewhere=[$elsewhere] members=[$members] out=[$out]"

# --- 17. backup.sh: the archive's data is on disk before its name ────────────
# The rename can reach the disk before the data: after a power loss the name would
# point at an empty or truncated file. The sync wrapper logs each call as
# "<args>|<type> <size> of the last arg>[|<entries of that dir>]" and runs the
# real sync; AH_TEST_SYNC_FAIL=1 makes it fail instead. The date stub of 16
# still fixes the archive name.
AH_TEST_REAL_SYNC=$(command -v sync); export AH_TEST_REAL_SYNC
cat > "$WORK/bk/bin/sync" <<'STUB'
#!/usr/bin/env bash
last="${!#}"
line="$*|$(stat -c '%F %s' -- "$last" 2>&1)"
[ ! -d "$last" ] || line="$line|$(ls -A -- "$last" | paste -sd ' ' -)"
printf '%s\n' "$line" >> "$STUB_DIR/sync.log"
[ "${AH_TEST_SYNC_FAIL:-}" != 1 ] || exit 1
exec "$AH_TEST_REAL_SYNC" "$@"
STUB
chmod +x "$WORK/bk/bin/sync"

mkdir -p "$WORK/bk/i"
out=$(bk_run "$WORK/bk/i" "$WORK/bk/i/out"); rc=$?
calls=$(cat "$WORK/bk/i/sync.log" 2>/dev/null)
IFS='|' read -r args1 type1 _ <<<"$(sed -n 1p <<<"$calls")"
IFS='|' read -r args2 type2 seen2 <<<"$(sed -n 2p <<<"$calls")"
entries=$(ls -A "$WORK/bk/i/out" 2>/dev/null)
case "$args1" in "-- $WORK/bk/i/out/.adminhelper-backup-"*) temp_synced=1 ;; *) temp_synced=0 ;; esac
{ [ $rc -eq 0 ] && [ -n "$calls" ] && [ "$(wc -l <<<"$calls")" -eq 2 ] \
    && [ "$temp_synced" = 1 ] && [ "${type1% *}" = 'regular file' ] && [ "${type1##* }" -gt 0 ] \
    && [ "$args2" = "-- $WORK/bk/i/out" ] && [ "${type2% *}" = directory ] && [ "$seen2" = "$FIXED_NAME" ] \
    && [ "$entries" = "$FIXED_NAME" ]; } \
  && ok "backup.sh syncs the full temp file before the rename, then the output dir with the archive" \
  || bad "sync calls: rc=$rc calls=[$calls] entries=[$entries] out=[$out]"

mkdir -p "$WORK/bk/j"
out=$(bk_run "$WORK/bk/j" "$WORK/bk/j/out" AH_TEST_SYNC_FAIL=1); rc=$?
entries=$(ls -A "$WORK/bk/j/out" 2>/dev/null)
calls=$(cat "$WORK/bk/j/sync.log" 2>/dev/null)
{ [ $rc -ne 0 ] && [ -n "$calls" ] && [ "$(wc -l <<<"$calls")" -eq 1 ] \
    && [ -d "$WORK/bk/j/out" ] && [ -z "$entries" ] && grep -q '^\[backup\] ERROR: ' <<<"$out"; } \
  && ok "a failing sync fails the backup and leaves the output dir empty" \
  || bad "failing sync: rc=$rc calls=[$calls] entries=[$entries] out=[$out]"

# --- 18. backup.sh --help: the comment header, no code ──────────────────────
out=$(bash "$BACKUP" --help 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -qF '# backup.sh — full AdminHelper backup' <<<"$out" \
    && [ "$(tail -n1 <<<"$out")" = '#   ./scripts/backup.sh [--with-victoria] [--output DIR]' ] \
    && ! grep -qv '^#' <<<"$out"; } \
  && ok "backup.sh --help prints the comment header up to the usage line" \
  || bad "--help: rc=$rc out=[$out]"

# --- 19. backup.sh: the passphrase commented out, behind BOM or Unicode space, over lines
# Compose reads a key behind a BOM or Unicode whitespace (NBSP, EM SPACE) and with
# NBSP before the separator, and a quoted value runs over lines until its closing
# quote; a commented-out line holds the value too. The expectations are written
# down apart; the .env bytes are escapes, so this file stays ASCII.
if [ -n "$LOCALE_SKIP" ]; then
  echo "  SKIP test 19 (needs the locale C.UTF-8)"
else
  mkdir -p "$WORK/bk/k" "$WORK/bk/l" "$WORK/bk/m"
  printf '\xef\xbb\xbfCA_ROOT_PASSPHRASE=bom1\nA=1\n#CA_ROOT_PASSPHRASE=old1\n  # export CA_ROOT_PASSPHRASE = old2\n\xc2\xa0CA_ROOT_PASSPHRASE=nbsp1\n\xe2\x80\x83CA_ROOT_PASSPHRASE=em1\nCA_ROOT_PASSPHRASE\xc2\xa0=sep1\nCA_ROOT_PASSPHRASE="ml1\nml2\nml3"\nB=2\nCA_ROOT_PASSPHRASE=\x27sq1\nsq2\x27\nCA_ROOT_PASSPHRASE="esc\\"q1\nesc2"\nCA_ROOT_PASSPHRASE_OLD=keep\n#CA_ROOT_PASSPHRASE_OLD=keep2\nY=caf\xc3\xa9\nZ=last' > "$WORK/bk/run/.env"
  printf 'A=1\nB=2\nCA_ROOT_PASSPHRASE_OLD=keep\n#CA_ROOT_PASSPHRASE_OLD=keep2\nY=caf\xc3\xa9\nZ=last\n' > "$WORK/bk/k/expected"
  out=$(bk_run "$WORK/bk/k" "$WORK/bk/k/out" LC_ALL=C.UTF-8); rc=$?
  sanitized=$(bk_env "$WORK/bk/k")
  { [ $rc -eq 0 ] && cmp -s "$WORK/bk/k/expected" "$sanitized"; } \
    && ok "env.sanitized drops the passphrase commented out, behind BOM or Unicode space, and over lines" \
    || bad "passphrase line forms: rc=$rc env.sanitized=[$(cat -A "$sanitized" 2>/dev/null | tr '\n' ' ')] out=[$out]"

  printf 'A=1\nCA_ROOT_PASSPHRASE="open1\nrest1\nrest2\n' > "$WORK/bk/run/.env"
  printf 'A=1\n' > "$WORK/bk/l/expected"
  out=$(bk_run "$WORK/bk/l" "$WORK/bk/l/out" LC_ALL=C.UTF-8); rc=$?
  sanitized=$(bk_env "$WORK/bk/l")
  { [ $rc -eq 0 ] && cmp -s "$WORK/bk/l/expected" "$sanitized"; } \
    && ok "a passphrase value that never closes is dropped to the end of the file" \
    || bad "unclosed passphrase value: rc=$rc env.sanitized=[$(cat -A "$sanitized" 2>/dev/null | tr '\n' ' ')] out=[$out]"

  # Compose pairs backslashes in both quote kinds: after two of them the quote
  # closes the value (probe: A='a\\' gives a\\, the next line is a key again).
  printf 'CA_ROOT_PASSPHRASE=\x27ev1\\\\\x27\nC=3\nCA_ROOT_PASSPHRASE="ev2\\\\"\nD=4\n' > "$WORK/bk/run/.env"
  printf 'C=3\nD=4\n' > "$WORK/bk/m/expected"
  out=$(bk_run "$WORK/bk/m" "$WORK/bk/m/out" LC_ALL=C.UTF-8); rc=$?
  sanitized=$(bk_env "$WORK/bk/m")
  { [ $rc -eq 0 ] && cmp -s "$WORK/bk/m/expected" "$sanitized"; } \
    && ok "a quote after two backslashes closes the passphrase value, the next lines stay" \
    || bad "even backslashes: rc=$rc env.sanitized=[$(cat -A "$sanitized" 2>/dev/null | tr '\n' ' ')] out=[$out]"
fi

# --- 20. backup.sh: tar writes only into the temp file it created ────────────
# The mktemp stub plays a name that is something else once backup.sh opens it: with
# AH_TEST_MKTEMP_LINK set, the archive template gets a fresh name with a symlink to
# that target under it; with AH_TEST_MKTEMP_MODE the real temp file gets that mode (a
# mount without Unix mode shows its fixed one); with AH_TEST_MKTEMP_HARDLINK it gets a
# second hard link at that path. Every other call goes to the real mktemp. Each run
# under timeout 30, so a FIFO that would block the write shows as 124.
AH_TEST_REAL_MKTEMP=$(command -v mktemp); export AH_TEST_REAL_MKTEMP
cat > "$WORK/bk/bin/mktemp" <<'STUB'
#!/usr/bin/env bash
if [ "$#" -eq 1 ] && [[ "$1" == */.adminhelper-backup-*.XXXXXX ]]; then
  if [ -n "${AH_TEST_MKTEMP_LINK:-}" ]; then
    name=$("$AH_TEST_REAL_MKTEMP" -u "$1") || exit
    ln -s "$AH_TEST_MKTEMP_LINK" "$name" || exit
    printf '%s\n' "$name"
    exit 0
  fi
  if [ -n "${AH_TEST_MKTEMP_DIRLINK:-}" ]; then
    exec "$AH_TEST_REAL_MKTEMP" "$AH_TEST_MKTEMP_DIRLINK/${1##*/}"
  fi
  if [ -n "${AH_TEST_MKTEMP_MODE:-}${AH_TEST_MKTEMP_HARDLINK:-}" ]; then
    name=$("$AH_TEST_REAL_MKTEMP" "$1") || exit
    [ -z "${AH_TEST_MKTEMP_MODE:-}" ] || chmod "$AH_TEST_MKTEMP_MODE" "$name" || exit
    [ -z "${AH_TEST_MKTEMP_HARDLINK:-}" ] || ln "$name" "$AH_TEST_MKTEMP_HARDLINK" || exit
    printf '%s\n' "$name"
    exit 0
  fi
fi
exec "$AH_TEST_REAL_MKTEMP" "$@"
STUB
chmod +x "$WORK/bk/bin/mktemp"
# bk_tmp_run <stub dir> [VAR=value…] — backup.sh as in bk_run, under timeout 30.
bk_tmp_run() {
  local stub="$1"; shift
  ( cd "$WORK/bk/run" && umask 022 \
      && env "$@" STUB_DIR="$stub" PATH="$WORK/bk/bin:$PATH" \
         timeout 30 bash "$BACKUP" --output "$stub/out" </dev/null 2>&1 )
}
# bk_link_run <stub dir> <link target> — the temp name a symlink to <link target>.
bk_link_run() { bk_tmp_run "$1" AH_TEST_MKTEMP_LINK="$2"; }

mkdir -p "$WORK/bk/n" "$WORK/bk/n/elsewhere"
: > "$WORK/bk/n/elsewhere/foreign"
out=$(bk_link_run "$WORK/bk/n" "$WORK/bk/n/elsewhere/foreign"); rc=$?
entries=$(ls -A "$WORK/bk/n/out" 2>/dev/null)
{ [ $rc -ne 0 ] && [ $rc -ne 124 ] && [ -f "$WORK/bk/n/elsewhere/foreign" ] && [ ! -s "$WORK/bk/n/elsewhere/foreign" ] \
    && [ -z "$entries" ] && grep -q '^\[backup\] ERROR: ' <<<"$out"; } \
  && ok "a link to another file under the temp name fails the backup, the file stays empty" \
  || bad "link to another file: rc=$rc size=$(stat -c %s "$WORK/bk/n/elsewhere/foreign" 2>&1) entries=[$entries] out=[$out]"

mkdir -p "$WORK/bk/o" "$WORK/bk/o/elsewhere"
printf 'own data\n' > "$WORK/bk/o/elsewhere/own"
cp -p "$WORK/bk/o/elsewhere/own" "$WORK/bk/o/own.before"
out=$(bk_link_run "$WORK/bk/o" "$WORK/bk/o/elsewhere/own"); rc=$?
entries=$(ls -A "$WORK/bk/o/out" 2>/dev/null)
{ [ $rc -ne 0 ] && [ $rc -ne 124 ] && cmp -s "$WORK/bk/o/own.before" "$WORK/bk/o/elsewhere/own" \
    && [ -z "$entries" ] && grep -q '^\[backup\] ERROR: ' <<<"$out"; } \
  && ok "a link to an own file under the temp name fails the backup, the file stays as it was" \
  || bad "link to an own file: rc=$rc entries=[$entries] own=[$(cat "$WORK/bk/o/elsewhere/own" | head -c 64 | od -c | head -2)] out=[$out]"

mkdir -p "$WORK/bk/p" "$WORK/bk/p/elsewhere"
mkfifo "$WORK/bk/p/elsewhere/fifo"
out=$(bk_link_run "$WORK/bk/p" "$WORK/bk/p/elsewhere/fifo"); rc=$?
entries=$(ls -A "$WORK/bk/p/out" 2>/dev/null)
{ [ $rc -ne 0 ] && [ $rc -ne 124 ] && [ -p "$WORK/bk/p/elsewhere/fifo" ] \
    && [ -z "$entries" ] && grep -q '^\[backup\] ERROR: ' <<<"$out"; } \
  && ok "a link to a FIFO under the temp name fails the backup without blocking" \
  || bad "link to a FIFO: rc=$rc entries=[$entries] out=[$out]"

# The checks on the open descriptor: a temp file that is not 0600 (as on a CIFS or vfat
# mount) or that has a second link passes the checks on the name but not those on the
# descriptor, and the backup stops with the hint to back up locally.
mkdir -p "$WORK/bk/r"
out=$(bk_tmp_run "$WORK/bk/r" AH_TEST_MKTEMP_MODE=644); rc=$?
entries=$(ls -A "$WORK/bk/r/out" 2>/dev/null)
{ [ $rc -ne 0 ] && [ $rc -ne 124 ] && [ -z "$entries" ] && grep -q '^\[backup\] ERROR: ' <<<"$out" \
    && grep -q 'back up to a local directory' <<<"$out"; } \
  && ok "a temp file without mode 600 fails the backup with the hint to back up locally" \
  || bad "temp file 0644: rc=$rc entries=[$entries] out=[$out]"

mkdir -p "$WORK/bk/s" "$WORK/bk/s/elsewhere"
out=$(bk_tmp_run "$WORK/bk/s" AH_TEST_MKTEMP_HARDLINK="$WORK/bk/s/elsewhere/second"); rc=$?
entries=$(ls -A "$WORK/bk/s/out" 2>/dev/null)
{ [ $rc -ne 0 ] && [ $rc -ne 124 ] && [ -z "$entries" ] && [ ! -s "$WORK/bk/s/elsewhere/second" ] \
    && grep -q 'back up to a local directory' <<<"$out"; } \
  && ok "a temp file with a second hard link fails the backup, the other name stays empty" \
  || bad "temp file with two links: rc=$rc entries=[$entries] second=$(stat -c %s "$WORK/bk/s/elsewhere/second" 2>&1) out=[$out]"

# A name swapped after the open: the stat wrapper, on the first check of fd 3, moves
# the temp file out of the output dir and leaves a symlink to it under the temp name.
# The descriptor still passes owner, mode, links and size; only the comparison of its
# inode with the name's own (no link followed) sees the swap.
AH_TEST_REAL_STAT=$(command -v stat); export AH_TEST_REAL_STAT
cat > "$WORK/bk/bin/stat" <<'STUB'
#!/usr/bin/env bash
if [ -n "${AH_TEST_STAT_SWAP:-}" ] && [ "$*" = "-L -c %u %a %h %s /dev/fd/3" ] && [ ! -e "$STUB_DIR/swapped" ]; then
  : > "$STUB_DIR/swapped"
  name=$(readlink "/proc/$PPID/fd/3") || exit
  mv -- "$name" "$AH_TEST_STAT_SWAP" && ln -s "$AH_TEST_STAT_SWAP" "$name" || exit
fi
exec "$AH_TEST_REAL_STAT" "$@"
STUB
chmod +x "$WORK/bk/bin/stat"
mkdir -p "$WORK/bk/t" "$WORK/bk/t/elsewhere"
out=$(bk_tmp_run "$WORK/bk/t" AH_TEST_STAT_SWAP="$WORK/bk/t/elsewhere/moved"); rc=$?
entries=$(ls -A "$WORK/bk/t/out" 2>/dev/null)
{ [ $rc -ne 0 ] && [ $rc -ne 124 ] && [ -e "$WORK/bk/t/swapped" ] && [ -z "$entries" ] \
    && [ -f "$WORK/bk/t/elsewhere/moved" ] && [ ! -s "$WORK/bk/t/elsewhere/moved" ] \
    && grep -q '^\[backup\] ERROR: ' <<<"$out"; } \
  && ok "a temp name swapped for a link after the open fails the backup, nothing is written" \
  || bad "name swapped after the open: rc=$rc swapped=$([ -e "$WORK/bk/t/swapped" ] && echo y || echo n) entries=[$entries] moved=$(stat -c %s "$WORK/bk/t/elsewhere/moved" 2>&1) out=[$out]"

# A temp path through a linked dir part (the mktemp stub with AH_TEST_MKTEMP_DIRLINK
# prints the template's name under that link): the file there passes every check on
# the descriptor, so only the check that the temp file lies in the output dir stops it.
mkdir -p "$WORK/bk/u/out" "$WORK/bk/u/elsewhere"
ln -s "$WORK/bk/u/elsewhere" "$WORK/bk/u/out/.lnk"
out=$(bk_tmp_run "$WORK/bk/u" AH_TEST_MKTEMP_DIRLINK="$WORK/bk/u/out/.lnk"); rc=$?
entries=$(ls -A "$WORK/bk/u/out" 2>/dev/null)
others=$(find "$WORK/bk/u/elsewhere" -type f -size +0 2>/dev/null)
{ [ $rc -ne 0 ] && [ $rc -ne 124 ] && [ "$entries" = .lnk ] && [ -z "$others" ] \
    && grep -q '^\[backup\] ERROR: ' <<<"$out"; } \
  && ok "a temp path through a linked dir fails the backup, nothing is written there" \
  || bad "temp path through a linked dir: rc=$rc entries=[$entries] others=[$others] out=[$out]"

# The name swapped for a link to a path that does not exist, between the check that it
# is no link and its open (a function named [ under BASH_ENV does the swap): the open
# must not create that path; the backup stops and writes nothing.
cat > "$WORK/bk/swap-env.sh" <<'EOF'
#!/usr/bin/env bash
# Sourced through BASH_ENV: right after the script's check that the temp name is no
# link, the name becomes a link to a path that does not exist yet (once).
[() {
  builtin [ "$@"; local rc=$?
  if [[ -n "${AH_TEST_SWAP_TO:-}" && $# -eq 4 && "$1" == '!' && "$2" == -L \
      && "$3" == */.adminhelper-* && ! -e "$AH_TEST_SWAP_MARK" ]]; then
    : > "$AH_TEST_SWAP_MARK"
    rm -f -- "$3" && ln -s -- "$AH_TEST_SWAP_TO" "$3"
  fi
  return $rc
}
EOF
mkdir -p "$WORK/bk/w" "$WORK/bk/w/elsewhere"
out=$(bk_tmp_run "$WORK/bk/w" BASH_ENV="$WORK/bk/swap-env.sh" AH_TEST_SWAP_TO="$WORK/bk/w/elsewhere/created" \
    AH_TEST_SWAP_MARK="$WORK/bk/w/swapped"); rc=$?
entries=$(ls -A "$WORK/bk/w/out" 2>/dev/null)
{ [ $rc -ne 0 ] && [ $rc -ne 124 ] && [ -e "$WORK/bk/w/swapped" ] && [ ! -e "$WORK/bk/w/elsewhere/created" ] \
    && [ ! -L "$WORK/bk/w/elsewhere/created" ] && [ -z "$entries" ] && grep -q '^\[backup\] ERROR: ' <<<"$out"; } \
  && ok "a temp name swapped for a dangling link before the open creates nothing there" \
  || bad "swap before the open: rc=$rc swapped=$([ -e "$WORK/bk/w/swapped" ] && echo y || echo n) created=$([ -e "$WORK/bk/w/elsewhere/created" ] && echo y || echo n) entries=[$entries] out=[$out]"

# --- 21. backup.sh: the archive stays 0600 under a default ACL ──────────────
# A default ACL on the output dir replaces the umask for new files there; the mode
# must still come from mktemp. Without setfacl or ACL support the case says so
# loudly and checks the mode without the ACL.
mkdir -p "$WORK/bk/q/out"
acl_note=""
if ! command -v setfacl >/dev/null 2>&1; then
  acl_note="setfacl not installed"
elif ! acl_err=$(setfacl -d -m g::rwx,o::rwx "$WORK/bk/q/out" 2>&1); then
  acl_note="no ACL on $(df -T "$WORK/bk/q/out" | awk 'NR==2 {print $2}'): $acl_err"
fi
[ -z "$acl_note" ] || echo "  NOTE  21 ran WITHOUT a default ACL ($acl_note); only the mode is checked"
out=$(bk_run "$WORK/bk/q" "$WORK/bk/q/out"); rc=$?
entries=$(ls -A "$WORK/bk/q/out" 2>/dev/null)
archive="$WORK/bk/q/out/$entries"
{ [ $rc -eq 0 ] && [ "$entries" = "$FIXED_NAME" ] && [ "$(stat -c '%a' "$archive")" = 600 ] \
    && { [ -n "$acl_note" ] || getfacl -p "$WORK/bk/q/out" 2>/dev/null | grep -qx 'default:group::rwx'; }; } \
  && ok "the archive is 0600 in an output dir with a default ACL" \
  || bad "default ACL: rc=$rc entries=[$entries] mode=$(stat -c '%a' "$archive" 2>&1) acl_note=[$acl_note] out=[$out]"

# --- 22. backup.sh: --output with a trailing slash ───────────────────────────
mkdir -p "$WORK/bk/v"
out=$( ( cd "$WORK/bk/run" && umask 022 \
    && env STUB_DIR="$WORK/bk/v" PATH="$WORK/bk/bin:$PATH" bash "$BACKUP" --output "$WORK/bk/v/out/" </dev/null 2>&1 ) ); rc=$?
entries=$(ls -A "$WORK/bk/v/out" 2>/dev/null)
{ [ $rc -eq 0 ] && [ "$entries" = "$FIXED_NAME" ]; } \
  && ok "--output with a trailing slash writes the archive" \
  || bad "trailing slash: rc=$rc entries=[$entries] out=[$out]"

# --- 23./24. restore.sh needs the role passwords before it stops anything ────
mkdir -p "$WORK/roles/bin" "$WORK/roles/miss" "$WORK/roles/envonly" "$WORK/roles/run"
cat > "$WORK/roles/bin/docker" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *pg_restore*|*ON_ERROR_STOP*) cat >/dev/null ;;
esac
echo "pw=[${PGPASSWORD-}] $*" >> "$STUB_DIR/calls.log"
exit 0
STUB
chmod +x "$WORK/roles/bin/docker"
grep -v '^MONITOR_DB_PASSWORD=' <<<"$ROLE_ENV" > "$WORK/roles/miss/.env"
out=$( cd "$WORK/roles/miss" && STUB_DIR="$WORK/roles/miss" PATH="$WORK/roles/bin:$PATH" \
    bash "$RESTORE" "$WORK/reg/full.tar.gz" --yes </dev/null 2>&1 ); rc=$?
{ [ $rc -eq 1 ] && grep -q 'MONITOR_DB_PASSWORD' <<<"$out" && grep -q 'init-secrets.sh' <<<"$out" \
    && [ ! -e "$WORK/roles/miss/calls.log" ]; } \
  && ok "a role password missing in .env stops the restore before any docker call" \
  || bad "missing role password: rc=$rc out=[$out] calls=[$(cat "$WORK/roles/miss/calls.log" 2>/dev/null)]"

out=$( cd "$WORK/roles/envonly" && env $ROLE_ENV STUB_DIR="$WORK/roles/envonly" PATH="$WORK/roles/bin:$PATH" \
    bash "$RESTORE" "$WORK/reg/full.tar.gz" --yes </dev/null 2>&1 ); rc=$?
[ $rc -eq 0 ] \
  && ok "the role passwords may come from the environment instead of .env" \
  || bad "environment only: rc=$rc out=[$out]"

# --- 25. db-init first, each DB as its role, no password in an argv ─────────
mkdir -p "$WORK/roles/both"
printf 'dump\n' > "$WORK/roles/both/adminhelper.dump"
printf 'dump\n' > "$WORK/roles/both/adminhelper_monitor.dump"
tar czf "$WORK/roles/both.tar.gz" -C "$WORK/roles/both" .
cp "$WORK/.env" "$WORK/roles/run/.env"
out=$( cd "$WORK/roles/run" && STUB_DIR="$WORK/roles/run" PATH="$WORK/roles/bin:$PATH" \
    bash "$RESTORE" "$WORK/roles/both.tar.gz" --yes </dev/null 2>&1 ); rc=$?
calls="$WORK/roles/run/calls.log"
init=$(grep -n 'run --rm -T db-init' "$calls" 2>/dev/null | head -n1 | cut -d: -f1)
first_restore=$(grep -n 'pg_restore' "$calls" 2>/dev/null | head -n1 | cut -d: -f1)
{ [ $rc -eq 0 ] && [ -n "$init" ] && [ -n "$first_restore" ] && [ "$init" -lt "$first_restore" ]; } \
  && ok "db-init runs before the first pg_restore" \
  || bad "order: db-init at ${init:-none}, pg_restore at ${first_restore:-none}, rc=$rc out=[$out]"
{ grep -q '^pw=\[pw-server\] .*-e PGPASSWORD postgres pg_restore .*-U ah_server .*--no-privileges -d adminhelper$' "$calls" \
    && grep -q '^pw=\[pw-monitor\] .*-e PGPASSWORD postgres pg_restore .*-U ah_monitor .*--no-privileges -d adminhelper_monitor$' "$calls" \
    && grep -q '^pw=\[pw-server\] .*psql .*-U ah_server -d adminhelper .*ON_ERROR_STOP' "$calls"; } \
  && ok "each DB goes back as its role, the password through the environment" \
  || bad "roles: calls=[$(cat "$calls" 2>/dev/null)]"
# pg_isready probes without logging in; every call that logs in counts. Read into
# variables first: a negated grep -q at the end of a pipe takes the exit of the pipe.
db_calls=$(grep -E 'pg_restore|psql|createdb' "$calls" 2>/dev/null)
argvs=$(sed 's/^pw=\[[^]]*\] //' "$calls" 2>/dev/null)
{ [ -n "$db_calls" ] && ! grep -qE -- '-U adminhelper( |$)|createdb' <<<"$db_calls" \
    && [ -n "$argvs" ] && ! grep -qE 'pw-(server|scheduler|monitor|ca)' <<<"$argvs"; } \
  && ok "nothing as adminhelper, no role password in an argv" \
  || bad "superuser or password in argv: calls=[$(cat "$calls" 2>/dev/null)]"

echo
echo "──────────────────────────────────────────"
echo "  restore_guard_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ] || exit 1
[ -z "$LOCALE_SKIP" ] || { echo "SKIP: $LOCALE_SKIP"; exit 75; }
