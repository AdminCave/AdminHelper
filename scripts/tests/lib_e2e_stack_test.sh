#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# lib_e2e_stack_test.sh — hermetic test for what e2e_init hands the tests that
# run on the host against the stack: ITEST_DATABASE_URL and ITEST_REDIS_URL; and
# for two stacks side by side (e2e_init <mtls> a|b, e2e_stack_use).
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
  echo "PID=$$"
  echo "PROJECT=$E2E_PROJECT"
  echo "URL=$E2E_SERVER_URL"
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

# ── the workspace the desktop suites open ────────────────────────────────────
# The suites seed the settings.json from before workspaces, which the app moves into
# the workspace "standard"; wdio.conf.js opens the one AH_E2E_WORKSPACE names. Exported
# on source, as wdio runs in a child under dbus-run-session, and over a value left in
# the caller's shell: no other workspace is there to open.
for outside in "" other-ws; do
  WS=$(env -u AH_E2E_WORKSPACE ${outside:+"AH_E2E_WORKSPACE=$outside"} bash -c '
    . "$1/scripts/tests/lib_e2e_stack.sh"
    bash -c "printf %s \"\${AH_E2E_WORKSPACE-unset}\""
  ' _ "$REPO_ROOT" 2>&1)
  [ "$WS" = standard ] \
    && ok "outside ${outside:-unset}: a child of a shell that sourced the lib gets AH_E2E_WORKSPACE=standard" \
    || bad "outside ${outside:-unset}: the child sees AH_E2E_WORKSPACE '$WS'"
done

# ── the ports ────────────────────────────────────────────────────────────────
# Disjoint ranges: the data plane is 21000-38999, so no PID can make one run's
# Postgres port another run's gateway port. Both new ranges stay below Linux's
# ephemeral ports (32768 up), which outgoing connections take at random.
[ "${PG_PORT:-0}" -ge 11000 ] && [ "$PG_PORT" -lt 16000 ] \
  && [ "${REDIS_PORT:-0}" -ge 16000 ] && [ "$REDIS_PORT" -lt 21000 ] \
  && [ "${HTTPS_PORT:-0}" -ge 21000 ] \
  && ok "Postgres, Redis and the data plane get ports from separate ranges below 32768 for the first two" \
  || bad "ports: https=$HTTPS_PORT pg=$PG_PORT redis=$REDIS_PORT"

# ── without a stack key: as before two stacks could run ──────────────────────
# Every suite but the two-installations one calls e2e_init without a key; for them the
# project, the ports, the URL and the .env stay what they were.
PID="$(val PID)"
[ -n "$PID" ] && [ "$(val PROJECT)" = "ah-e2e-$PID" ] \
  && [ "$HTTPS_PORT" = $(( 21000 + PID % 18000 )) ] && [ "$PG_PORT" = $(( 11000 + PID % 5000 )) ] \
  && [ "$REDIS_PORT" = $(( 16000 + PID % 5000 )) ] && [ "$(val URL)" = "https://localhost:$HTTPS_PORT" ] \
  && ok "without a key: project ah-e2e-<pid>, ports from the pid, the URL on localhost" \
  || bad "without a key: pid '$PID', project '$(val PROJECT)', https=$HTTPS_PORT pg=$PG_PORT redis=$REDIS_PORT, URL '$(val URL)'"
ENV_KEYS="$(sed 's/=.*//' "$STUB_LOG/env" 2>/dev/null | tr '\n' ' ')"
[ "$ENV_KEYS" = "DOMAIN SECRET_KEY POSTGRES_PASSWORD CA_ROOT_PASSPHRASE MONITOR_API_KEY ADMIN_PASSWORD MTLS_ENFORCE ITEST_HTTPS_PORT ITEST_ENROLL_PORT ITEST_REPO_PORT ITEST_PG_PORT ITEST_REDIS_PORT " ] \
  && ok "without a key: the .env names no bind address and no FRP ports (gateway with no host address, frps on 7000/7443)" \
  || bad "without a key, the .env names: $ENV_KEYS"

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

# ── two stacks side by side ──────────────────────────────────────────────────
# e2e_init <mtls> a and b in one shell, as the two-installations suite runs them. Their
# work dirs land in a dir of their own: whatever the teardown leaves, or a rejected key
# creates, shows there. show <S> prints every global a stack owns as <S>.<name>.
TWO="$WORK/two"; mkdir -p "$TWO"
: > "$STUB_LOG/docker.args"; : > "$STUB_LOG/pkill.args"
OUT2=$(PATH="$SHIM:$PATH" TMPDIR="$TWO" bash -c '
  . "$1/scripts/tests/lib_e2e_stack.sh"
  show() {
    local v
    for v in E2E_PROJECT E2E_WORK E2E_HTTPS_PORT E2E_ENROLL_PORT E2E_REPO_PORT E2E_PG_PORT \
      E2E_REDIS_PORT E2E_BIND_IP E2E_FRP_BIND_PORT E2E_FRP_HTTPS_PORT E2E_SERVER_URL \
      E2E_ADMIN_PW ITEST_DATABASE_URL ITEST_REDIS_URL; do echo "$1.$v=${!v}"; done
  }
  echo "PID=$$"
  e2e_init false c 2>/dev/null; echo "INIT_C=$?"
  e2e_init false a; echo "INIT_A=$?"; show A; cp "$E2E_WORK/.env" "$STUB_LOG/env.a"
  e2e_init false b; echo "INIT_B=$?"; show B; cp "$E2E_WORK/.env" "$STUB_LOG/env.b"
  e2e_stack_use a; echo "USE_A=$?"; show UA
  bash -c "echo CHILD_A_DB=\$ITEST_DATABASE_URL"
  e2e_dc up -d gateway
  e2e_stack_use b; echo "USE_B=$?"; show UB
  e2e_stack_use c 2>/dev/null; echo "USE_C=$?"
  e2e_stack_use "" 2>/dev/null; echo "USE_EMPTY=$?"
  show KEPT
' _ "$REPO_ROOT" 2>&1); rc=$?
v2()   { sed -n "s/^$1=//p" <<<"$OUT2" | head -1; }
blk()  { sed -n "s/^$1\.//p" <<<"$OUT2"; }
envf() { sed -n "s/^$2=//p" "$STUB_LOG/env.$1" 2>/dev/null | head -1; }
PID2="$(v2 PID)"; A_WORK="$(v2 A.E2E_WORK)"; B_WORK="$(v2 B.E2E_WORK)"

[ "$rc" = 0 ] && [ "$(v2 INIT_A)" = 0 ] && [ "$(v2 INIT_B)" = 0 ] && [ "$(v2 USE_A)" = 0 ] && [ "$(v2 USE_B)" = 0 ] \
  && ok "two stacks: e2e_init a and b, e2e_stack_use a and b return 0" || bad "two stacks: rc=$rc, $OUT2"
[ -n "$PID2" ] && [ "$(v2 A.E2E_PROJECT)" = "ah-e2e-$PID2-a" ] && [ "$(v2 B.E2E_PROJECT)" = "ah-e2e-$PID2-b" ] \
  && ok "two stacks: projects ah-e2e-<pid>-a and ah-e2e-<pid>-b" \
  || bad "two stacks: projects '$(v2 A.E2E_PROJECT)' and '$(v2 B.E2E_PROJECT)' (pid '$PID2')"
[ -n "$A_WORK" ] && [ -n "$B_WORK" ] && [ "$A_WORK" != "$B_WORK" ] \
  && [ "${A_WORK%/*}" = "$TWO" ] && [ "${B_WORK%/*}" = "$TWO" ] \
  && ok "two stacks: a work dir each" || bad "two stacks: work dirs '$A_WORK' and '$B_WORK'"

# Postgres and Redis of both sit on 127.0.0.1 and frps of both on every interface, so
# these ten must all differ; the data plane would not have to (two addresses).
PORTS="$(for s in A B; do for p in HTTPS PG REDIS FRP_BIND FRP_HTTPS; do v2 "$s.E2E_${p}_PORT"; done; done)"
[ "$(sort -u <<<"$PORTS" | grep -c .)" = 10 ] \
  && ok "two stacks: data plane, Postgres, Redis and both frps ports, ten different ports" \
  || bad "two stacks: ports $(tr '\n' ' ' <<<"$PORTS")"
in_ranges=1
for s in A B; do
  h="$(v2 "$s.E2E_HTTPS_PORT")"; p="$(v2 "$s.E2E_PG_PORT")"; r="$(v2 "$s.E2E_REDIS_PORT")"
  { [ "${p:-0}" -ge 11000 ] && [ "$p" -lt 16000 ] && [ "${r:-0}" -ge 16000 ] && [ "$r" -lt 21000 ] \
    && [ "${h:-0}" -ge 21000 ] && [ "$h" -lt 39000 ]; } || in_ranges=0
done
[ "$in_ranges" = 1 ] && ok "two stacks: both keep the port ranges of a stack without a key" \
  || bad "two stacks: a port out of its range: $(tr '\n' ' ' <<<"$PORTS")"
[ "$(v2 A.E2E_BIND_IP)" = 127.0.0.1 ] && [ "$(v2 B.E2E_BIND_IP)" = 127.0.0.2 ] \
  && [ "$(v2 A.E2E_ENROLL_PORT)" = 8444 ] && [ "$(v2 B.E2E_ENROLL_PORT)" = 8444 ] \
  && [ "$(v2 A.E2E_REPO_PORT)" = 8445 ] && [ "$(v2 B.E2E_REPO_PORT)" = 8445 ] \
  && ok "two stacks: both gateways hold 8444 and 8445, a on 127.0.0.1, b on 127.0.0.2" \
  || bad "two stacks: a $(v2 A.E2E_BIND_IP):$(v2 A.E2E_ENROLL_PORT)/$(v2 A.E2E_REPO_PORT), b $(v2 B.E2E_BIND_IP):$(v2 B.E2E_ENROLL_PORT)/$(v2 B.E2E_REPO_PORT)"
[ "$(v2 A.E2E_FRP_BIND_PORT)/$(v2 A.E2E_FRP_HTTPS_PORT)" = 7000/7443 ] \
  && [ "$(v2 B.E2E_FRP_BIND_PORT)/$(v2 B.E2E_FRP_HTTPS_PORT)" = 7001/7444 ] \
  && ok "two stacks: frps on 7000/7443 for a, on 7001/7444 for b" \
  || bad "two stacks: frps a $(v2 A.E2E_FRP_BIND_PORT)/$(v2 A.E2E_FRP_HTTPS_PORT), b $(v2 B.E2E_FRP_BIND_PORT)/$(v2 B.E2E_FRP_HTTPS_PORT)"
[ "$(v2 A.E2E_SERVER_URL)" = "https://127.0.0.1:$(v2 A.E2E_HTTPS_PORT)" ] \
  && [ "$(v2 B.E2E_SERVER_URL)" = "https://127.0.0.2:$(v2 B.E2E_HTTPS_PORT)" ] \
  && ok "two stacks: each URL on its stack's address, so the app finds its enrollment plane there" \
  || bad "two stacks: URLs '$(v2 A.E2E_SERVER_URL)' and '$(v2 B.E2E_SERVER_URL)'"

# env_is <a|b> <S> — the .env of stack a or b carries what the globals <S>.* say.
env_is() {
  [ -n "$(envf "$1" ITEST_BIND_IP)" ] && [ -n "$(envf "$1" FRP_BIND_PORT)" ] && [ -n "$(envf "$1" FRP_HTTPS_PORT)" ] \
    && [ "$(envf "$1" ITEST_BIND_IP)" = "$(v2 "$2.E2E_BIND_IP")" ] \
    && [ "$(envf "$1" FRP_BIND_PORT)" = "$(v2 "$2.E2E_FRP_BIND_PORT")" ] \
    && [ "$(envf "$1" FRP_HTTPS_PORT)" = "$(v2 "$2.E2E_FRP_HTTPS_PORT")" ] \
    && [ "$(envf "$1" ITEST_HTTPS_PORT)" = "$(v2 "$2.E2E_HTTPS_PORT")" ] \
    && [ "$(envf "$1" ITEST_PG_PORT)" = "$(v2 "$2.E2E_PG_PORT")" ] \
    && [ "$(envf "$1" ITEST_REDIS_PORT)" = "$(v2 "$2.E2E_REDIS_PORT")" ] \
    && [ "$(envf "$1" ADMIN_PASSWORD)" = "$(v2 "$2.E2E_ADMIN_PW")" ] \
    && [ "$(v2 "$2.ITEST_DATABASE_URL")" = "postgresql+psycopg://adminhelper:$(envf "$1" POSTGRES_PASSWORD)@127.0.0.1:$(v2 "$2.E2E_PG_PORT")/adminhelper" ]
}
env_is a A && env_is b B \
  && ok "two stacks: each .env names its stack's bind address, FRP ports, ports and admin password" \
  || bad "two stacks: .env a: $(tr '\n' ' ' < "$STUB_LOG/env.a" 2>/dev/null) .env b: $(tr '\n' ' ' < "$STUB_LOG/env.b" 2>/dev/null)"
[ -n "$(envf a POSTGRES_PASSWORD)" ] && [ "$(envf a POSTGRES_PASSWORD)" != "$(envf b POSTGRES_PASSWORD)" ] \
  && [ -n "$(envf a SECRET_KEY)" ] && [ "$(envf a SECRET_KEY)" != "$(envf b SECRET_KEY)" ] \
  && [ -n "$(v2 A.E2E_ADMIN_PW)" ] && [ "$(v2 A.E2E_ADMIN_PW)" != "$(v2 B.E2E_ADMIN_PW)" ] \
  && ok "two stacks: secrets of their own" || bad "two stacks: a secret is shared or empty"

# e2e_stack_use puts every global back, the export included, and a key it does not know
# changes nothing.
[ -n "$(blk A)" ] && [ "$(blk UA)" = "$(blk A)" ] && [ "$(blk UB)" = "$(blk B)" ] \
  && ok "e2e_stack_use a and b: every global of the stack, as e2e_init set it" \
  || bad "e2e_stack_use: a after use '$(blk UA | tr '\n' ' ')', b after use '$(blk UB | tr '\n' ' ')'"
[ "$(v2 CHILD_A_DB)" = "$(v2 A.ITEST_DATABASE_URL)" ] \
  && ok "e2e_stack_use a: a child process sees stack a's ITEST_DATABASE_URL" \
  || bad "e2e_stack_use a: the child sees '$(v2 CHILD_A_DB)'"
[ "$(v2 USE_C)" != 0 ] && [ "$(v2 USE_EMPTY)" != 0 ] && [ "$(blk KEPT)" = "$(blk B)" ] \
  && ok "e2e_stack_use c and '': non-zero, the globals stay stack b's" \
  || bad "e2e_stack_use c: rc '$(v2 USE_C)', '': rc '$(v2 USE_EMPTY)', globals '$(blk KEPT | tr '\n' ' ')'"
[ "$(v2 INIT_C)" != 0 ] && ok "e2e_init with key c: non-zero (rc $(v2 INIT_C))" || bad "e2e_init with key c returned '$(v2 INIT_C)'"

DC_A="-p ah-e2e-$PID2-a -f $REPO_ROOT/docker-compose.yml -f $REPO_ROOT/docker-compose.test.yml --env-file $A_WORK/.env"
DC_B="-p ah-e2e-$PID2-b -f $REPO_ROOT/docker-compose.yml -f $REPO_ROOT/docker-compose.test.yml --env-file $B_WORK/.env"
grep -qxF -- "compose $DC_A up -d gateway" "$STUB_LOG/docker.args" 2>/dev/null \
  && ok "e2e_dc after e2e_stack_use a: stack a's project and .env" \
  || bad "e2e_dc after use a: $(cat "$STUB_LOG/docker.args" 2>/dev/null)"
grep -qxF -- "compose $DC_A down -v --remove-orphans" "$STUB_LOG/docker.args" 2>/dev/null \
  && grep -qxF -- "compose $DC_B down -v --remove-orphans" "$STUB_LOG/docker.args" 2>/dev/null \
  && ok "the EXIT teardown takes both stacks down" \
  || bad "two stacks, teardown: $(cat "$STUB_LOG/docker.args" 2>/dev/null)"
[ -s "$STUB_LOG/pkill.args" ] && [ -d "$TWO" ] && [ -z "$(ls -A "$TWO")" ] \
  && ok "the teardown removes both work dirs; key c made none" \
  || bad "two stacks: pkill $(wc -l < "$STUB_LOG/pkill.args") call(s), left in $TWO: $(ls -A "$TWO" 2>&1)"

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
# The gateway's three planes under ITEST_BIND_IP, the address e2e_init writes for a key;
# unset, no host address at all, exactly as before.
GW_WANT='${ITEST_BIND_IP:+${ITEST_BIND_IP}:}${ITEST_HTTPS_PORT:-18443}:443
${ITEST_BIND_IP:+${ITEST_BIND_IP}:}${ITEST_ENROLL_PORT:-8444}:8444
${ITEST_BIND_IP:+${ITEST_BIND_IP}:}${ITEST_REPO_PORT:-8445}:8445'
[ "$(ports_of "$REPO_ROOT/docker-compose.test.yml" gateway)" = "$GW_WANT" ] \
  && ok "the overlay publishes the gateway's three ports on ITEST_BIND_IP, with no host address unless set" \
  || bad "gateway ports: $(ports_of "$REPO_ROOT/docker-compose.test.yml" gateway | tr '\n' ' ')"
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

# ── e2e_login ────────────────────────────────────────────────────────────────
# A red login in the stack suite said only that it failed, not why (R-0515). curl is
# a stub that logs its args, prints STUB_BODY and then the -w format with STUB_CODE
# as the status, and exits with STUB_RC; an empty STUB_CODE writes no status at all.
cat > "$SHIM/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_LOG/curl.args"
w=""; prev=""
for a in "$@"; do [ "$prev" = -w ] && w=$a; prev=$a; done
printf '%s' "${STUB_BODY-}"
[ -z "${STUB_CODE-}" ] || printf '%b' "${w//'%{http_code}'/$STUB_CODE}"
exit "${STUB_RC:-0}"
EOF
chmod +x "$SHIM/curl"
PW="e2e-pw-5f1c0ffee0ddba11"
TOK="eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1pbiJ9.access-sig"
RTOK="eyJhbGciOiJIUzI1NiJ9.eyJ0eXAiOiJyZWZyZXNoIn0.refresh-sig"
URL="https://localhost:21443"

# login <case> <body> <code> <curl-rc> — e2e_login in a shell of its own against the
# stub, a client cert as its args; sets RC, JWT_OUT and ERR. Checks what holds in every
# case: no output of its own, neither password nor a token in E2E_LOGIN_ERR, exactly
# one curl call with the cert args, --max-time 5 and the admin's credentials.
login() {
  : > "$STUB_LOG/curl.args"
  STUB_BODY=$2 STUB_CODE=$3 STUB_RC=$4 PATH="$SHIM:$PATH" bash -c '
    . "$1/scripts/tests/lib_e2e_stack.sh"
    E2E_SERVER_URL=$2; E2E_ADMIN_PW=$3; w=$4
    e2e_login --cert "$w/c.pem" --key "$w/c.key" > "$w/login.out" 2>&1
    echo "$?" > "$w/login.rc"
    printf "%s|" "$E2E_JWT" > "$w/login.jwt"
    printf "%s|" "$E2E_LOGIN_ERR" > "$w/login.err"
  ' _ "$REPO_ROOT" "$URL" "$PW" "$WORK"
  # The trailing | keeps a trailing newline in E2E_LOGIN_ERR visible.
  RC=$(cat "$WORK/login.rc"); JWT_OUT=$(cat "$WORK/login.jwt"); JWT_OUT=${JWT_OUT%|}
  ERR=$(cat "$WORK/login.err"); ERR=${ERR%|}
  local calls; calls=$(wc -l < "$STUB_LOG/curl.args")
  if [ ! -s "$WORK/login.out" ] && [[ $ERR != *"$PW"* && $ERR != *"$TOK"* && $ERR != *"$RTOK"* ]] \
    && [ "$calls" = 1 ] \
    && grep -qF -- "-k -s --cert $WORK/c.pem --key $WORK/c.key --max-time 5 -X POST $URL/api/auth/login " "$STUB_LOG/curl.args" \
    && grep -qF -- "-d {\"username\":\"admin\",\"password\":\"$PW\"}" "$STUB_LOG/curl.args"; then
    ok "$1: no output of its own, no secret in E2E_LOGIN_ERR, one curl call with the cert and --max-time 5"
  else
    bad "$1: output '$(cat "$WORK/login.out")', ERR '$ERR', $calls curl call(s): $(cat "$STUB_LOG/curl.args")"
  fi
}
# failed <case> <expected E2E_LOGIN_ERR> — rc 1, no JWT, exactly this line.
failed() {
  [ "$RC" = 1 ] && [ -z "$JWT_OUT" ] && [ "$ERR" = "$2" ] \
    && ok "$1: rc 1, E2E_JWT empty, E2E_LOGIN_ERR '$2'" || bad "$1: rc=$RC JWT='$JWT_OUT' ERR='$ERR'"
}

login "200 with access_token" \
  '{"access_token":"'"$TOK"'","refresh_token":"'"$RTOK"'","token_type":"bearer"}' 200 0
[ "$RC" = 0 ] && [ "$JWT_OUT" = "$TOK" ] && [ -z "$ERR" ] \
  && ok "200 with access_token: E2E_JWT is the token, E2E_LOGIN_ERR empty, rc 0" \
  || bad "200 with access_token: rc=$RC JWT='$JWT_OUT' ERR='$ERR'"

login "401" '{"detail":"Ungültige Zugangsdaten"}' 401 0
failed "401" "HTTP 401, curl exit 0, detail: Ungültige Zugangsdaten"

# A newline in the detail would start a line of its own in the suite's log, where
# heavy.sh's first_marker takes any line that begins with FAIL.
X300=$(printf 'x%.0s' {1..300}); D="one FAIL two $X300"
login "401 with control characters" '{"detail":"one\nFAIL two\t'"$X300"'"}' 401 0
failed "401 with control characters" "HTTP 401, curl exit 0, detail: ${D:0:200}"

# FastAPI's 422 echoes the request in "input": the password must not get through.
login "422" '{"detail":[{"type":"missing","loc":["body","username"],"msg":"Field required","input":{"password":"'"$PW"'"}},{"type":"string_too_long","loc":["body","password"],"msg":"String should have at most 128 characters","input":"'"$PW"'","ctx":{"max_length":128}}]}' 422 0
failed "422" "HTTP 422, curl exit 0, detail: body.username: Field required; body.password: String should have at most 128 characters"

login "curl timeout" '' 000 28
failed "curl timeout" "HTTP 000, curl exit 28, no JSON detail"

login "no status from curl" '' '' 7
failed "no status from curl" "HTTP 000, curl exit 7, no JSON detail"

login "502 page from the gateway" '<html><body>502 Bad Gateway</body></html>' 502 0
failed "502 page from the gateway" "HTTP 502, curl exit 0, no JSON detail"

login "200 without access_token" '{"refresh_token":"'"$RTOK"'","detail":"'"$TOK"'"}' 200 0
failed "200 without access_token" "HTTP 200, curl exit 0, no access_token"

# null is no token: the suite only checks that E2E_JWT is non-empty, and "None" is.
login "200 with access_token null" '{"access_token":null,"refresh_token":"'"$RTOK"'","token_type":"bearer"}' 200 0
failed "200 with access_token null" "HTTP 200, curl exit 0, no access_token"

# login_twice <case> <body1> <code1> <body2> <code2> — two e2e_login calls in one shell,
# as integration_stack_test.sh makes them: the second must not keep what the first set.
# Sets RC, JWT_OUT and ERR after the second call, JWT1 and ERR1 after the first (so a
# case can show the first call did leave something behind) and CALLS.
login_twice() {
  : > "$STUB_LOG/curl.args"
  PATH="$SHIM:$PATH" bash -c '
    . "$1/scripts/tests/lib_e2e_stack.sh"
    E2E_SERVER_URL=$2; E2E_ADMIN_PW=$3; w=$4
    STUB_BODY=$5 STUB_CODE=$6 e2e_login --cert "$w/c.pem" --key "$w/c.key" > /dev/null 2>&1
    printf "%s|" "$E2E_JWT" > "$w/login1.jwt"
    printf "%s|" "$E2E_LOGIN_ERR" > "$w/login1.err"
    STUB_BODY=$7 STUB_CODE=$8 e2e_login --cert "$w/c.pem" --key "$w/c.key" > /dev/null 2>&1
    echo "$?" > "$w/login.rc"
    printf "%s|" "$E2E_JWT" > "$w/login.jwt"
    printf "%s|" "$E2E_LOGIN_ERR" > "$w/login.err"
  ' _ "$REPO_ROOT" "$URL" "$PW" "$WORK" "$2" "$3" "$4" "$5"
  RC=$(cat "$WORK/login.rc"); JWT_OUT=$(cat "$WORK/login.jwt"); JWT_OUT=${JWT_OUT%|}
  ERR=$(cat "$WORK/login.err"); ERR=${ERR%|}
  JWT1=$(cat "$WORK/login1.jwt"); JWT1=${JWT1%|}
  ERR1=$(cat "$WORK/login1.err"); ERR1=${ERR1%|}
  CALLS=$(wc -l < "$STUB_LOG/curl.args")
}
E401="HTTP 401, curl exit 0, detail: Ungültige Zugangsdaten"

login_twice "200, then 401" '{"access_token":"'"$TOK"'"}' 200 '{"detail":"Ungültige Zugangsdaten"}' 401
[ "$CALLS" = 2 ] && [ "$JWT1" = "$TOK" ] \
  && ok "200, then 401: two curl calls, the first set E2E_JWT" \
  || bad "200, then 401: $CALLS curl call(s), first E2E_JWT '$JWT1'"
failed "200, then 401" "$E401"

login_twice "401, then 200" '{"detail":"Ungültige Zugangsdaten"}' 401 '{"access_token":"'"$TOK"'"}' 200
[ "$CALLS" = 2 ] && [ "$ERR1" = "$E401" ] \
  && ok "401, then 200: two curl calls, the first set E2E_LOGIN_ERR" \
  || bad "401, then 200: $CALLS curl call(s), first E2E_LOGIN_ERR '$ERR1'"
[ "$RC" = 0 ] && [ "$JWT_OUT" = "$TOK" ] && [ -z "$ERR" ] \
  && ok "401, then 200: E2E_JWT is the token, E2E_LOGIN_ERR empty, rc 0" \
  || bad "401, then 200: rc=$RC JWT='$JWT_OUT' ERR='$ERR'"

# ── box_desktopbox.sh: the workspace and its seed ────────────────────────────
# The box script sources no lib and exports AH_E2E_WORKSPACE itself. iter.sh calls it
# again on the same box, where $ROOT/.dt-xdg keeps what the run before left, and the app
# moves the seeded settings.json only while workspaces.json is missing. It runs here in
# a copy of its tree: bootstrap, npm and dbus-run-session are stubs. The dbus stub logs
# what the spec would find, then leaves what the app's migration leaves.
BOX="$WORK/box"; BOX_DATA="$BOX/.dt-xdg/com.admincave.adminhelper"
mkdir -p "$BOX/scripts/tests" "$BOX/scripts/vm" "$BOX/apps/desktop/ui" "$BOX/apps/desktop/e2e" \
  "$WORK/home" "$WORK/rm-fails"
cp "$REPO_ROOT/scripts/tests/box_desktopbox.sh" "$BOX/scripts/tests/"
printf '#!/usr/bin/env bash\nexit 0\n' > "$BOX/scripts/vm/bootstrap_linux.sh"
cat > "$SHIM/dbus-run-session" <<'EOF'
#!/usr/bin/env bash
d="$XDG_DATA_HOME/com.admincave.adminhelper"; left=""
for f in workspaces.json workspaces prefs.json; do [ -e "$d/$f" ] && left+=" $f"; done
printf 'ws=%s left=%s settings=%s\n' "${AH_E2E_WORKSPACE-unset}" "${left# }" \
  "$(cat "$d/settings.json" 2>/dev/null)" >> "$STUB_LOG/dbus.log"
mkdir -p "$d/workspaces/standard"
for f in workspaces.json workspaces/standard/workspace.json prefs.json; do echo '{}' > "$d/$f"; done
EOF
printf '#!/usr/bin/env bash\nexit 1\n' > "$WORK/rm-fails/rm"
chmod +x "$SHIM/dbus-run-session" "$WORK/rm-fails/rm"
: > "$STUB_LOG/dbus.log"
box() {  # box <extra PATH dir> — one call as iter.sh makes it; sets RC
  env -u AH_E2E_WORKSPACE -u AH_DESKTOP_ENROLL_TOKENS HOME="$WORK/home" PATH="$1$SHIM:$PATH" \
    bash "$BOX/scripts/tests/box_desktopbox.sh" 192.0.2.10 pw key one.live.js > "$WORK/box.out" 2>&1
  RC=$?
}
SEED='{"mode": "server", "allowSelfSignedCerts": true}'
SPEC_SAW="ws=standard left= settings=$SEED"

box ""
[ "$RC" = 0 ] && grep -q '^DESKTOP_ALL_OK' "$WORK/box.out" \
  && [ "$(sed -n 1p "$STUB_LOG/dbus.log")" = "$SPEC_SAW" ] \
  && ok "box, first call: the spec opens standard on the seeded settings.json alone" \
  || bad "box, first call: rc=$RC, spec saw '$(sed -n 1p "$STUB_LOG/dbus.log")': $(cat "$WORK/box.out")"

echo '{}' > "$BOX_DATA/port-registry.json"
box ""
[ "$RC" = 0 ] && [ "$(sed -n 2p "$STUB_LOG/dbus.log")" = "$SPEC_SAW" ] \
  && ok "box, second call on the same box: no workspaces.json, workspaces or prefs.json before the spec" \
  || bad "box, second call: rc=$RC, spec saw '$(sed -n 2p "$STUB_LOG/dbus.log")': $(cat "$WORK/box.out")"
[ -f "$BOX_DATA/port-registry.json" ] \
  && ok "box: the other files of the app data dir stay" || bad "box: port-registry.json is gone"

box "$WORK/rm-fails:"
[ "$RC" = 1 ] && grep -q 'could not remove the workspaces of an earlier run' "$WORK/box.out" \
  && [ "$(wc -l < "$STUB_LOG/dbus.log")" = 2 ] \
  && ok "box: a failing rm ends the script before any spec (rc 1)" \
  || bad "box, failing rm: rc=$RC, $(wc -l < "$STUB_LOG/dbus.log") spec call(s): $(cat "$WORK/box.out")"

echo ""
echo "lib_e2e_stack_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
