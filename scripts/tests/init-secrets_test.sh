#!/usr/bin/env bash
#
# init-secrets_test.sh — hermetic test for scripts/init-secrets.sh.
#
# Pure .env manipulation (openssl-generated secrets + upsert), no docker. Covers:
# fresh generation, idempotence (a re-run leaves existing secrets stable — the
# POSTGRES_PASSWORD stability the stale-volume auth guard depends on), placeholder
# replacement, quoted-value recognition (audit 6.71), a write that hits a full
# disk (R-0516), CA_ROOT_PASSPHRASE only in the run that generates
# POSTGRES_PASSWORD, a .env with bytes outside UTF-8 or a NUL byte (R-0530), and a
# read-only .env with a terminal on stdin (R-0538).
#
# Run: bash scripts/tests/init-secrets_test.sh   (needs bash, openssl, coreutils, the
#      locale C.UTF-8: without it test 7 cannot run, and the test ends with 75;
#      script from util-linux and a user that file rights bind: as root or without
#      script test 8 cannot run, and the test ends with 75 as well)

# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
INIT="$REPO_ROOT/scripts/init-secrets.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

val() { grep -E "^$1=" "$2" | head -1 | sed -E "s/^$1=//; s/^\"//; s/\"\$//"; }

# ── 1. fresh generation: empty secrets get 64-hex values ─────────────────────
ENV="$WORK/env1"
printf 'SECRET_KEY=\nMONITOR_API_KEY=\nPOSTGRES_PASSWORD=\nCA_ROOT_PASSPHRASE=\nDOMAIN=localhost\n' > "$ENV"
bash "$INIT" "$ENV" >/dev/null 2>&1
allgen=1
for k in SECRET_KEY MONITOR_API_KEY POSTGRES_PASSWORD CA_ROOT_PASSPHRASE; do
  v=$(val "$k" "$ENV"); [ "${#v}" -eq 64 ] || allgen=0
done
[ "$allgen" = 1 ] && ok "fresh: all four secrets generated (64-hex)" || bad "fresh generation incomplete"
[ "$(val DOMAIN "$ENV")" = "localhost" ] && ok "unrelated key (DOMAIN) untouched" || bad "DOMAIN mutated"

# ── 2. idempotence: a second run leaves the existing secrets stable ──────────
before=$(val POSTGRES_PASSWORD "$ENV")
bash "$INIT" "$ENV" >/dev/null 2>&1
after=$(val POSTGRES_PASSWORD "$ENV")
{ [ -n "$before" ] && [ "$before" = "$after" ]; } \
  && ok "idempotent: POSTGRES_PASSWORD stable across re-run" || bad "POSTGRES_PASSWORD changed on re-run (stale-volume risk)"
[ "$(grep -c '^POSTGRES_PASSWORD=' "$ENV")" -eq 1 ] && ok "no duplicate key line" || bad "duplicate POSTGRES_PASSWORD lines"

# ── 3. placeholder is treated as unset and replaced ──────────────────────────
ENV="$WORK/env2"
printf 'SECRET_KEY=change-me-in-production\nMONITOR_API_KEY=x\nPOSTGRES_PASSWORD=x\nCA_ROOT_PASSPHRASE=x\n' > "$ENV"
bash "$INIT" "$ENV" >/dev/null 2>&1
v=$(val SECRET_KEY "$ENV")
{ [ "$v" != "change-me-in-production" ] && [ "${#v}" -eq 64 ]; } \
  && ok "placeholder SECRET_KEY replaced" || bad "placeholder not replaced: $v"

# ── 4. quoted value counts as set (not regenerated) ──────────────────────────
ENV="$WORK/env3"
printf 'SECRET_KEY="already-quoted-secret-value"\nMONITOR_API_KEY=y\nPOSTGRES_PASSWORD=y\nCA_ROOT_PASSPHRASE=y\n' > "$ENV"
bash "$INIT" "$ENV" >/dev/null 2>&1
grep -q '^SECRET_KEY="already-quoted-secret-value"' "$ENV" \
  && ok "quoted existing value left alone" || bad "quoted value regenerated"

# ── 5. full disk while writing: abort, .env stays whole (R-0516) ─────────────
# The filter that drops the old SECRET_KEY line hits ENOSPC. A cut-down copy in
# place of .env would make the checks after it take the lost secrets for empty
# and regenerate them, so POSTGRES_PASSWORD and CA_ROOT_PASSPHRASE would no
# longer match the volumes. grep wrapper: real grep for everything, except that
# AH_TEST_GREP_ENOSPC=1 sends upsert's filter of the SECRET_KEY line to /dev/full
# (a real ENOSPC). Only this case runs with it on PATH.
BIN="$WORK/bin"; mkdir -p "$BIN"
AH_TEST_REAL_GREP=$(command -v grep); export AH_TEST_REAL_GREP
cat > "$BIN/grep" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"-vE ^#?[[:space:]]*SECRET_KEY="*)
    [ "${AH_TEST_GREP_ENOSPC:-}" != 1 ] || exec "$AH_TEST_REAL_GREP" "$@" > /dev/full ;;
esac
exec "$AH_TEST_REAL_GREP" "$@"
EOF
chmod +x "$BIN/grep"
ENV="$WORK/env4"
printf '%s\n' SECRET_KEY= MONITOR_API_KEY=already-set POSTGRES_PASSWORD=already-set \
  CA_ROOT_PASSPHRASE=already-set DOMAIN=old.example > "$ENV"
cp "$ENV" "$WORK/env4.orig"
out=$(PATH="$BIN:$PATH" AH_TEST_GREP_ENOSPC=1 bash "$INIT" "$ENV" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
[ $rc -ne 0 ] && ok "full disk on .env aborts" || bad "full disk on .env: exit $rc"
{ grep -q '^Fehler: .*SECRET_KEY' <<<"$out" && ! grep -qE '[0-9a-f]{64}' <<<"$out"; } \
  && ok "error names the key SECRET_KEY, not its value" || bad "no error line naming SECRET_KEY, or a value in the output"
cmp -s "$WORK/env4.orig" "$ENV" && ok ".env byte-identical after the failed write" \
  || bad ".env changed by the failed write: $(tr '\n' ' ' < "$ENV")"
! compgen -G "$ENV.ah-*" >/dev/null && ok "no .env.ah-* copy left behind" \
  || bad "copies left: $(compgen -G "$ENV.ah-*" | tr '\n' ' ')"

# ── 6. .env holding only the key: grep -v filters every line (exit 1), no error ─
ENV="$WORK/env5"
printf 'SECRET_KEY=\n' > "$ENV"
out=$(bash "$INIT" "$ENV" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "upsert into a one-key .env exit 0" || { echo "$out" | sed 's/^/    │ /'; bad "one-key .env: exit $rc"; }
allgen=1
for k in SECRET_KEY MONITOR_API_KEY POSTGRES_PASSWORD CA_ROOT_PASSPHRASE; do
  v=$(val "$k" "$ENV"); [ "${#v}" -eq 64 ] || allgen=0
done
{ [ "$allgen" = 1 ] && [ "$(grep -c '^SECRET_KEY=' "$ENV")" -eq 1 ]; } \
  && ok "one-key .env: all four secrets generated, one SECRET_KEY line" || bad "one-key .env: not all four secrets or a duplicate SECRET_KEY line"

# ── 6b. CA_ROOT_PASSPHRASE only in the run that generates POSTGRES_PASSWORD ──
# Only the ca-issuer's first start needs the passphrase; after it the value is
# meant to be empty, and update.sh runs init-secrets.sh on every update. A set
# POSTGRES_PASSWORD means the volumes exist already: a new passphrase would not
# match the root key in ca-pki. (a) set POSTGRES_PASSWORD: the empty line stays,
# with a hint on stdout; (b) a fresh install: both generated, no hint.
CA_HINT="→ CA_ROOT_PASSPHRASE stays empty"
ENV="$WORK/env-ca-update"
printf '%s\n' SECRET_KEY=already-set MONITOR_API_KEY=already-set POSTGRES_PASSWORD=already-set CA_ROOT_PASSPHRASE= > "$ENV"
out=$(bash "$INIT" "$ENV" 2>/dev/null); rc=$?
[ $rc -eq 0 ] && ok "set POSTGRES_PASSWORD, empty CA_ROOT_PASSPHRASE: exit 0" \
  || { echo "$out" | sed 's/^/    │ /'; bad "set POSTGRES_PASSWORD, empty CA_ROOT_PASSPHRASE: exit $rc"; }
[ "$(LC_ALL=C grep -a '^CA_ROOT_PASSPHRASE=' "$ENV")" = CA_ROOT_PASSPHRASE= ] \
  && ok "set POSTGRES_PASSWORD: CA_ROOT_PASSPHRASE stays one empty line" \
  || bad "set POSTGRES_PASSWORD: CA_ROOT_PASSPHRASE lines $(LC_ALL=C grep -a '^CA_ROOT_PASSPHRASE=' "$ENV" | tr '\n' ' ')"
grep -qF "$CA_HINT" <<<"$out" && ok "set POSTGRES_PASSWORD: the hint on stdout" || bad "set POSTGRES_PASSWORD: no hint on stdout: $out"
ENV="$WORK/env-ca-fresh"
printf '%s\n' SECRET_KEY=already-set MONITOR_API_KEY=already-set POSTGRES_PASSWORD= CA_ROOT_PASSPHRASE= > "$ENV"
out=$(bash "$INIT" "$ENV" 2>/dev/null); rc=$?
[ $rc -eq 0 ] && ok "empty POSTGRES_PASSWORD and CA_ROOT_PASSPHRASE: exit 0" \
  || { echo "$out" | sed 's/^/    │ /'; bad "empty POSTGRES_PASSWORD and CA_ROOT_PASSPHRASE: exit $rc"; }
both=1
for k in POSTGRES_PASSWORD CA_ROOT_PASSPHRASE; do
  [ "$(LC_ALL=C grep -a -c -x -E "$k=[0-9a-f]{64}" "$ENV")" = 1 ] || both=0
done
[ "$both" = 1 ] && ok "fresh install: POSTGRES_PASSWORD and CA_ROOT_PASSPHRASE generated (64-hex, one line each)" \
  || bad "fresh install: .env now $(tr '\n' ' ' < "$ENV")"
! grep -qF "$CA_HINT" <<<"$out" && ok "fresh install: no hint" || bad "fresh install: the hint, though both were generated: $out"

# ── 7. bytes outside UTF-8 or a NUL byte: no line lost, no set secret renewed ─
# grep takes a file for binary once it holds a NUL byte or a byte the caller's
# locale cannot decode, and leaves lines out (exit 0, "binary file matches" on
# stderr): with a Latin-1 byte the lines that hold one, with a NUL byte all of
# them. upsert wrote .env back without them, and is_set_safely read a set
# POSTGRES_PASSWORD as empty and made a new one (R-0530). The runs use C.UTF-8;
# the test reads .env byte for byte (-a, LC_ALL=C) and holds it against lines
# written down apart, never read back from the file. Without C.UTF-8 the case
# cannot run, and not run is not green: the test then ends with 75.
LOCALE_SKIP=""
if [ "$(LC_ALL=C.UTF-8 locale charmap 2>/dev/null)" != UTF-8 ]; then
  LOCALE_SKIP="test 7 (bytes outside UTF-8 in .env) needs the locale C.UTF-8, this system has none"
  echo "  SKIP $LOCALE_SKIP"
else
  for how in latin1 nul; do
    ENV="$WORK/env-$how"
    case $how in
      latin1) printf 'MONITOR_API_KEY=m\nPOSTGRES_PASSWORD=gr\374n\n# Zug\344nge\nCA_ROOT_PASSPHRASE=c\nSERVER_DB_PASSWORD=s\nSCHEDULER_DB_PASSWORD=s\nMONITOR_DB_PASSWORD=s\nCA_DB_PASSWORD=s\n' > "$ENV.keep" ;;
      nul)    printf 'MONITOR_API_KEY=m\nX=a\0b\nPOSTGRES_PASSWORD=p\nCA_ROOT_PASSPHRASE=c\nSERVER_DB_PASSWORD=s\nSCHEDULER_DB_PASSWORD=s\nMONITOR_DB_PASSWORD=s\nCA_DB_PASSWORD=s\n' > "$ENV.keep" ;;
    esac
    { printf 'SECRET_KEY=\n'; cat "$ENV.keep"; } > "$ENV"
    out=$(LC_ALL=C.UTF-8 bash "$INIT" "$ENV" 2>&1); rc=$?
    [ $rc -eq 0 ] && ok "$how: exit 0" || { echo "$out" | sed 's/^/    │ /'; bad "$how: exit $rc"; }
    LC_ALL=C grep -a -v '^SECRET_KEY=' "$ENV" | cmp -s - "$ENV.keep" \
      && ok "$how: every line but SECRET_KEY byte for byte as it was" \
      || bad "$how: .env now $(cat -v "$ENV" | tr '\n' ' ')"
    [ "$(LC_ALL=C grep -a -c -x -E 'SECRET_KEY=[0-9a-f]{64}' "$ENV")" = 1 ] \
      && ok "$how: SECRET_KEY generated (64-hex), one line" || bad "$how: no single 64-hex SECRET_KEY line"
    grep -qxF "→ Generiert in $ENV: SECRET_KEY" <<<"$out" \
      && ok "$how: only SECRET_KEY reported as generated" || bad "$how: output $out"
  done
fi

# ── 8. a read-only .env and a terminal on stdin: replaced without a question ─
# GNU mv asks before it replaces a file it may not write when stdin is a terminal
# and -f is missing, and waits for the answer: init-secrets.sh hung on a .env
# 0444, the question unseen under a wrapper that collects the output (R-0538).
# The run gets a pseudo-terminal from script (util-linux) whose input never comes
# and never ends: a FIFO this test holds open, so no process outlives the test.
# With /dev/null, script passes on an EOF, mv takes it for "no" and leaves the
# file out instead of waiting. timeout ends a run that waits with 124. mv asks
# only about a file it may not write, so as root the case proves nothing; that
# and a system without script mean it cannot run, and the test then ends with 75.
TTY_SKIP=""
probe="$WORK/rights-probe"; : > "$probe"; chmod 000 "$probe"
if ! command -v script >/dev/null 2>&1; then
  TTY_SKIP="test 8 (a read-only .env on a terminal) needs script from util-linux, this system has none"
elif ( : >> "$probe" ) 2>/dev/null || ( : < "$probe" ) 2>/dev/null; then
  TTY_SKIP="test 8 (a read-only .env on a terminal) needs a user that file rights bind, $(id -un) is not one"
fi
if [ -n "$TTY_SKIP" ]; then
  echo "  SKIP $TTY_SKIP"
else
  mkfifo "$WORK/tty-in"; exec {TTY_IN}<>"$WORK/tty-in"
  # "$@" in dir $1 on that terminal; prints the output without the terminal's \r.
  on_tty() {
    local dir="$1"; shift
    ( cd "$dir" && SHELL="$BASH" timeout 60 script -qec "$(printf '%q ' "$@")" /dev/null <&"$TTY_IN" ) | tr -d '\r'
    return "${PIPESTATUS[0]}"
  }
  ENV="$WORK/env-ro"
  printf '%s\n' MONITOR_API_KEY=m POSTGRES_PASSWORD=p CA_ROOT_PASSPHRASE=c SERVER_DB_PASSWORD=s \
    SCHEDULER_DB_PASSWORD=s MONITOR_DB_PASSWORD=s CA_DB_PASSWORD=s > "$ENV.keep"
  { printf 'SECRET_KEY=\n'; cat "$ENV.keep"; } > "$ENV"; chmod 444 "$ENV"
  out=$(on_tty "$WORK" bash "$INIT" "$ENV" 2>&1); rc=$?
  [ $rc -eq 0 ] && ok "read-only .env on a terminal: exit 0, no question" \
    || { echo "$out" | sed 's/^/    │ /'; bad "read-only .env on a terminal: exit $rc (124: mv waited for an answer)"; }
  v=$(val SECRET_KEY "$ENV")
  [ "${#v}" -eq 64 ] && ok "read-only .env on a terminal: SECRET_KEY generated (64-hex)" \
    || bad "read-only .env on a terminal: SECRET_KEY '$v'"
  grep -v '^SECRET_KEY=' "$ENV" | cmp -s - "$ENV.keep" \
    && ok "read-only .env on a terminal: the set secrets as they were" || bad "read-only .env on a terminal: .env now $(tr '\n' ' ' < "$ENV")"
  [ "$(stat -c %a "$ENV")" = 600 ] && ok "read-only .env on a terminal: mode 600 afterwards" \
    || bad "read-only .env on a terminal: mode $(stat -c %a "$ENV")"
fi

# ── 9. the Postgres role passwords: fresh, and added to an existing .env ─────
# db-init sets each service role's password from these on every start, so an update
# fills in the missing ones and leaves every set secret as it was.
ROLE_KEYS="SERVER_DB_PASSWORD SCHEDULER_DB_PASSWORD MONITOR_DB_PASSWORD CA_DB_PASSWORD"
ENV="$WORK/env9"
printf 'SECRET_KEY=\nMONITOR_API_KEY=\nPOSTGRES_PASSWORD=\nCA_ROOT_PASSPHRASE=\n' > "$ENV"
bash "$INIT" "$ENV" >/dev/null 2>&1
rolegen=1
for k in $ROLE_KEYS; do v=$(val "$k" "$ENV"); [ "${#v}" -eq 64 ] || rolegen=0; done
[ "$rolegen" = 1 ] && ok "fresh: the four role passwords generated (64-hex)" || bad "fresh: role passwords missing"
ENV="$WORK/env9b"
printf '%s\n' SECRET_KEY=s1 MONITOR_API_KEY=m1 POSTGRES_PASSWORD=p1 CA_ROOT_PASSPHRASE= SERVER_DB_PASSWORD=keep > "$ENV"
bash "$INIT" "$ENV" >/dev/null 2>&1
{ [ "$(val POSTGRES_PASSWORD "$ENV")" = p1 ] && [ "$(val SERVER_DB_PASSWORD "$ENV")" = keep ] \
  && [ -z "$(val CA_ROOT_PASSPHRASE "$ENV")" ]; } \
  && ok "existing .env: set secrets and an existing role password unchanged" || bad "existing .env: $(tr '\n' ' ' < "$ENV")"
added=1
for k in SCHEDULER_DB_PASSWORD MONITOR_DB_PASSWORD CA_DB_PASSWORD; do
  v=$(val "$k" "$ENV"); [ "${#v}" -eq 64 ] || added=0
done
[ "$added" = 1 ] && ok "existing .env: the missing role passwords added" || bad "existing .env: role passwords not added"

echo
echo "──────────────────────────────────────────"
echo "  init-secrets_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ] || exit 1
[ -z "$LOCALE_SKIP" ] || echo "SKIP: $LOCALE_SKIP"
[ -z "$TTY_SKIP" ] || echo "SKIP: $TTY_SKIP"
[ -z "$LOCALE_SKIP$TTY_SKIP" ] || exit 75
