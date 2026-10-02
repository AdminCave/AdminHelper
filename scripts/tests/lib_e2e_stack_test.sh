#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# lib_e2e_stack_test.sh — hermetic test for what e2e_init hands the tests that
# run on the host against the stack: ITEST_DATABASE_URL and ITEST_REDIS_URL.
#
# The URLs only work if three things agree — the ports e2e_init writes into the
# throwaway .env, the password it generates there, and the loopback bindings in
# docker-compose.test.yml — and none of that is visible before a real stack is
# up on a VM. Here docker, pkill and openssl are PATH stubs: nothing starts, and
# e2e_teardown's `pkill -9 -f tauri-driver` can never reach a real process.
#
# Run: bash scripts/tests/lib_e2e_stack_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
SHIM="$WORK/bin"; mkdir -p "$SHIM"

cat > "$SHIM/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_LOG/docker.args"
EOF
cat > "$SHIM/pkill" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_LOG/pkill.args"
EOF
# A different 32-hex value per call, so the test can tell which secret ended up
# in the URL — a constant would let the wrong one pass.
cat > "$SHIM/openssl" <<'EOF'
#!/usr/bin/env bash
n=$(( $(cat "$STUB_LOG/openssl.n" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$STUB_LOG/openssl.n"
printf '%032x\n' "$n"
EOF
chmod +x "$SHIM"/*
export STUB_LOG="$WORK/log"; mkdir -p "$STUB_LOG"

# e2e_init in its own shell, as a suite would run it; its mktemp lands under
# $WORK. Prints what a suite sees afterwards, then exits so the EXIT teardown
# runs against the stubs.
OUT=$(PATH="$SHIM:$PATH" TMPDIR="$WORK" bash -c '
  . "$1/scripts/tests/lib_e2e_stack.sh"
  e2e_init false
  echo "WORK=$E2E_WORK"
  echo "DB=$ITEST_DATABASE_URL"
  echo "REDIS=$ITEST_REDIS_URL"
  bash -c "echo CHILD_DB=\$ITEST_DATABASE_URL; echo CHILD_REDIS=\$ITEST_REDIS_URL"
  cp "$E2E_WORK/.env" "$STUB_LOG/env"
  e2e_dc up -d postgres redis
' _ "$REPO_ROOT" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "e2e_init runs against the stubs" || bad "e2e_init: rc=$rc, $OUT"

val()  { sed -n "s/^$1=//p" <<<"$OUT" | head -1; }
envv() { sed -n "s/^$1=//p" "$STUB_LOG/env" 2>/dev/null | head -1; }
DB="$(val DB)"; REDIS="$(val REDIS)"
PG_PORT="$(envv ITEST_PG_PORT)"; REDIS_PORT="$(envv ITEST_REDIS_PORT)"
HTTPS_PORT="$(envv ITEST_HTTPS_PORT)"; PG_PW="$(envv POSTGRES_PASSWORD)"

# ── the URLs ─────────────────────────────────────────────────────────────────
[ -n "$PG_PORT" ] && [ -n "$REDIS_PORT" ] \
  && ok "the .env names ITEST_PG_PORT and ITEST_REDIS_PORT" \
  || bad ".env: $(cat "$STUB_LOG/env" 2>/dev/null)"
[ -n "$PG_PW" ] && [ "$DB" = "postgresql+psycopg://adminhelper:$PG_PW@127.0.0.1:$PG_PORT/adminhelper" ] \
  && ok "ITEST_DATABASE_URL: the .env's password and port, on 127.0.0.1" \
  || bad "ITEST_DATABASE_URL '$DB' (pw '$PG_PW', port '$PG_PORT')"
[ "$REDIS" = "redis://127.0.0.1:$REDIS_PORT/0" ] \
  && ok "ITEST_REDIS_URL: the .env's port, on 127.0.0.1" \
  || bad "ITEST_REDIS_URL '$REDIS' (port '$REDIS_PORT')"
# Exported, not just set: stack_pytest.sh hands them to pytest processes.
[ "$(val CHILD_DB)" = "$DB" ] && [ "$(val CHILD_REDIS)" = "$REDIS" ] \
  && ok "both URLs reach a child process" \
  || bad "child sees DB='$(val CHILD_DB)' REDIS='$(val CHILD_REDIS)'"

# ── the ports ────────────────────────────────────────────────────────────────
# Disjoint ranges: the data plane is 21000-38999, so no PID can make one run's
# Postgres port another run's gateway port. Both new ranges stay below Linux's
# ephemeral ports (32768 up), which outgoing connections take at random.
[ "${PG_PORT:-0}" -ge 11000 ] && [ "$PG_PORT" -lt 16000 ] \
  && [ "${REDIS_PORT:-0}" -ge 16000 ] && [ "$REDIS_PORT" -lt 21000 ] \
  && [ "${HTTPS_PORT:-0}" -ge 21000 ] \
  && ok "Postgres, Redis and the data plane get ports from separate ranges below 32768 for the first two" \
  || bad "ports: https=$HTTPS_PORT pg=$PG_PORT redis=$REDIS_PORT"

# ── what docker was asked ────────────────────────────────────────────────────
WORKDIR="$(val WORK)"
grep -qF -- "-f $REPO_ROOT/docker-compose.yml -f $REPO_ROOT/docker-compose.test.yml --env-file $WORKDIR/.env up -d postgres redis" "$STUB_LOG/docker.args" 2>/dev/null \
  && ok "e2e_dc runs the test overlay with the run's .env" \
  || bad "docker args: $(cat "$STUB_LOG/docker.args" 2>/dev/null)"
grep -q -- 'down -v --remove-orphans' "$STUB_LOG/docker.args" 2>/dev/null \
  && ok "the EXIT teardown takes the stack down" || bad "no teardown: $(cat "$STUB_LOG/docker.args" 2>/dev/null)"
[ -s "$STUB_LOG/pkill.args" ] && ok "the teardown's pkill reached the stub, not a real process" \
  || bad "pkill stub not called"
[ -n "$WORKDIR" ] && [ ! -e "$WORKDIR" ] && ok "the teardown removes the run's work dir" \
  || bad "work dir '$WORKDIR' still there"

# ── the compose files ────────────────────────────────────────────────────────
# ports_of <file> <service> — the entries under one service's `ports:` key.
ports_of() {
  awk -v svc="  $2:" '
    $0 == svc                 { inside = 1; next }
    /^  [a-z]/                { inside = 0; inports = 0 }
    inside && /^    [a-z]/    { inports = ($0 ~ /^    ports:/) }
    inports && /^      - /    { sub(/^      - /, ""); gsub(/"/, ""); print }' "$1"
}
[ "$(ports_of "$REPO_ROOT/docker-compose.test.yml" postgres)" = '127.0.0.1:${ITEST_PG_PORT:-15432}:5432' ] \
  && ok "the overlay publishes Postgres on 127.0.0.1:ITEST_PG_PORT only" \
  || bad "postgres ports: $(ports_of "$REPO_ROOT/docker-compose.test.yml" postgres)"
[ "$(ports_of "$REPO_ROOT/docker-compose.test.yml" redis)" = '127.0.0.1:${ITEST_REDIS_PORT:-16379}:6379' ] \
  && ok "the overlay publishes Redis on 127.0.0.1:ITEST_REDIS_PORT only" \
  || bad "redis ports: $(ports_of "$REPO_ROOT/docker-compose.test.yml" redis)"
# Production stays network-internal — the overlay is the only place they open.
[ -z "$(ports_of "$REPO_ROOT/docker-compose.yml" postgres)$(ports_of "$REPO_ROOT/docker-compose.yml" redis)" ] \
  && ok "docker-compose.yml publishes neither" \
  || bad "production publishes: $(ports_of "$REPO_ROOT/docker-compose.yml" postgres) $(ports_of "$REPO_ROOT/docker-compose.yml" redis)"

# ── e2e_npm_ready ────────────────────────────────────────────────────────────
# node_modules from the template outlived a lockfile change (R-0131): the suites
# checked only `[ -d node_modules ]`. npm is a stub that logs where it ran.
cat > "$SHIM/npm" <<'EOF'
#!/usr/bin/env bash
printf '%s %s\n' "$PWD" "$*" >> "$STUB_LOG/npm.args"
[ "${STUB_NPM_FAIL:-0}" = 0 ]
EOF
chmod +x "$SHIM/npm"
NPM="$WORK/npm"
mkdir -p "$NPM/missing" "$NPM/stale/node_modules" "$NPM/fresh/node_modules"
for d in missing stale fresh; do : > "$NPM/$d/package-lock.json"; done
touch -d '2026-01-01' "$NPM/stale/node_modules" "$NPM/fresh/package-lock.json"
touch -d '2026-02-01' "$NPM/stale/package-lock.json" "$NPM/fresh/node_modules"
npm_ready() {  # npm_ready <dir>... — e2e_npm_ready in a shell of its own, like a suite
  PATH="$SHIM:$PATH" bash -c '. "$1/scripts/tests/lib_e2e_stack.sh"; shift; e2e_npm_ready "$@"' \
    _ "$REPO_ROOT" "$@" > "$WORK/npm.out" 2>&1
}
npm_ready "$NPM/missing" "$NPM/stale" "$NPM/fresh"; rc=$?
[ "$rc" = 0 ] && ok "e2e_npm_ready runs against the npm stub" || bad "e2e_npm_ready: rc=$rc $(cat "$WORK/npm.out")"
grep -qx "$NPM/missing ci --no-audit --no-fund" "$STUB_LOG/npm.args" 2>/dev/null \
  && ok "node_modules missing: npm ci" || bad "missing: $(cat "$STUB_LOG/npm.args" 2>/dev/null)"
grep -qx "$NPM/stale ci --no-audit --no-fund" "$STUB_LOG/npm.args" 2>/dev/null \
  && ok "package-lock.json newer than node_modules: npm ci" || bad "stale: $(cat "$STUB_LOG/npm.args" 2>/dev/null)"
! grep -q "^$NPM/fresh " "$STUB_LOG/npm.args" 2>/dev/null \
  && ok "node_modules newer than the lockfile: no npm call" || bad "fresh: $(cat "$STUB_LOG/npm.args")"
STUB_NPM_FAIL=1 npm_ready "$NPM/missing"; rc=$?
[ "$rc" != 0 ] && ok "a failing npm ci is a non-zero exit (rc=$rc)" || bad "a failing npm ci returned 0"
npm_ready "$NPM/nowhere"; rc=$?
[ "$rc" != 0 ] && ok "a directory that is not there is a non-zero exit" || bad "a missing directory returned 0"

# Every desktop suite keeps ui/ and e2e/ node_modules as the lockfile says — after
# its tauri-cli check, so desktop_e2e_skip_test.sh (which ends there with 75) runs
# without npm. The skip test itself is no suite.
SUITES=0; WRONG=""
for f in "$REPO_ROOT"/scripts/tests/desktop_e2e_*.sh; do
  [ "${f##*/}" = desktop_e2e_skip_test.sh ] && continue
  SUITES=$((SUITES + 1))
  call="$(grep -n '^e2e_npm_ready "\$E2E_REPO_ROOT/apps/desktop/ui" "\$E2E_DIR" || exit 1$' "$f" | head -1 | cut -d: -f1)"
  tauri="$(grep -n 'SKIP: tauri-cli' "$f" | head -1 | cut -d: -f1)"
  [ -n "$call" ] && [ -n "$tauri" ] && [ "$call" -gt "$tauri" ] \
    || WRONG+=" ${f##*/}(call ${call:-?}, tauri ${tauri:-?})"
  ! grep -q '\[ -d node_modules \]' "$f" || WRONG+=" ${f##*/}([ -d node_modules ])"
done
[ "$SUITES" = 8 ] && [ -z "$WRONG" ] \
  && ok "all 8 desktop suites call e2e_npm_ready after the tauri-cli check, none by [ -d node_modules ]" \
  || bad "desktop suites ($SUITES of 8 expected):$WRONG"

echo ""
echo "lib_e2e_stack_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
