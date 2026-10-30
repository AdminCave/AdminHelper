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
# Only the keyring cases start real processes: a gnome-keyring-daemon,
# each in a D-Bus session, runtime dir and home of the test's own (see there).
#
# Run: bash scripts/tests/lib_e2e_stack_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0; SKIP=0
ok()   { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad()  { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
skip() { echo "  SKIP $*"; SKIP=$((SKIP + 1)); }

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
[ "$ENV_KEYS" = "DOMAIN SECRET_KEY POSTGRES_PASSWORD SERVER_DB_PASSWORD SCHEDULER_DB_PASSWORD MONITOR_DB_PASSWORD CA_DB_PASSWORD CA_ROOT_PASSPHRASE MONITOR_API_KEY ADMIN_PASSWORD MTLS_ENFORCE ITEST_HTTPS_PORT ITEST_ENROLL_PORT ITEST_REPO_PORT ITEST_PG_PORT ITEST_REDIS_PORT " ] \
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
# creates, shows there. show <S> prints every global a stack owns as <S>.<name>; exported,
# so the shells below have it.
show() {
  local v
  for v in E2E_PROJECT E2E_WORK E2E_HTTPS_PORT E2E_ENROLL_PORT E2E_REPO_PORT E2E_PG_PORT \
    E2E_REDIS_PORT E2E_BIND_IP E2E_FRP_BIND_PORT E2E_FRP_HTTPS_PORT E2E_SERVER_URL \
    E2E_ADMIN_PW ITEST_DATABASE_URL ITEST_REDIS_URL; do echo "$1.$v=${!v}"; done
}
export -f show
TWO="$WORK/two"; mkdir -p "$TWO"
: > "$STUB_LOG/docker.args"; : > "$STUB_LOG/pkill.args"
OUT2=$(PATH="$SHIM:$PATH" TMPDIR="$TWO" bash -c '
  . "$1/scripts/tests/lib_e2e_stack.sh"
  echo "PID=$$"
  e2e_init false c 2>/dev/null; echo "INIT_C=$?"
  e2e_init false a; echo "INIT_A=$?"; show A; cp "$E2E_WORK/.env" "$STUB_LOG/env.a"
  e2e_init false x 2>/dev/null; echo "INIT_X=$?"; show AX
  e2e_init false b; echo "INIT_B=$?"; show B; cp "$E2E_WORK/.env" "$STUB_LOG/env.b"
  echo "DIRS=$(ls -A "$TMPDIR" | tr "\n" " ")"
  e2e_init false a 2>/dev/null; echo "INIT_A2=$?"; show DUPA
  e2e_init false b 2>/dev/null; echo "INIT_B2=$?"; show DUPB
  e2e_init false 2>/dev/null; echo "INIT_NOKEY=$?"; show NOKEY
  echo "DIRS_AFTER=$(ls -A "$TMPDIR" | tr "\n" " ")"
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
    && [ "$(envf "$1" EXTRA_SANS)" = "$(v2 "$2.E2E_BIND_IP")" ] \
    && [ "$(envf "$1" FRP_BIND_PORT)" = "$(v2 "$2.E2E_FRP_BIND_PORT")" ] \
    && [ "$(envf "$1" FRP_HTTPS_PORT)" = "$(v2 "$2.E2E_FRP_HTTPS_PORT")" ] \
    && [ "$(envf "$1" ITEST_HTTPS_PORT)" = "$(v2 "$2.E2E_HTTPS_PORT")" ] \
    && [ "$(envf "$1" ITEST_PG_PORT)" = "$(v2 "$2.E2E_PG_PORT")" ] \
    && [ "$(envf "$1" ITEST_REDIS_PORT)" = "$(v2 "$2.E2E_REDIS_PORT")" ] \
    && [ "$(envf "$1" ADMIN_PASSWORD)" = "$(v2 "$2.E2E_ADMIN_PW")" ] \
    && [ "$(v2 "$2.ITEST_DATABASE_URL")" = "postgresql+psycopg://adminhelper:$(envf "$1" POSTGRES_PASSWORD)@127.0.0.1:$(v2 "$2.E2E_PG_PORT")/adminhelper" ]
}
env_is a A && env_is b B \
  && ok "two stacks: each .env names its stack's bind address (as a SAN of its gateway too), FRP ports, ports and admin password" \
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

# A rejected e2e_init sets no global and makes no work dir: the stack before it stays
# whole, and the teardown knows every dir there is.
[ "$(v2 INIT_X)" = 1 ] && [ -n "$(blk A)" ] && [ "$(blk AX)" = "$(blk A)" ] \
  && ok "e2e_init with key x after a: rc 1, every global still stack a's" \
  || bad "e2e_init x after a: rc '$(v2 INIT_X)', globals '$(blk AX | tr '\n' ' ')'"
[ -n "$(blk B)" ] && [ "$(v2 INIT_A2)" = 1 ] && [ "$(blk DUPA)" = "$(blk B)" ] \
  && [ "$(v2 INIT_B2)" = 1 ] && [ "$(blk DUPB)" = "$(blk B)" ] \
  && ok "e2e_init a or b a second time: rc 1, every global still stack b's" \
  || bad "second e2e_init: a rc '$(v2 INIT_A2)', globals '$(blk DUPA | tr '\n' ' ')'; b rc '$(v2 INIT_B2)', globals '$(blk DUPB | tr '\n' ' ')'"
[ "$(v2 INIT_NOKEY)" = 1 ] && [ -n "$(blk B)" ] && [ "$(blk NOKEY)" = "$(blk B)" ] \
  && ok "e2e_init without a key beside a and b: rc 1, every global still stack b's" \
  || bad "e2e_init without a key after a and b: rc '$(v2 INIT_NOKEY)', globals '$(blk NOKEY | tr '\n' ' ')'"
[ "$(wc -w <<<"$(v2 DIRS)")" = 2 ] && [ "$(v2 DIRS_AFTER)" = "$(v2 DIRS)" ] \
  && ok "the rejected calls made no work dir (two before, the same two after)" \
  || bad "work dirs before the rejected calls '$(v2 DIRS)', after '$(v2 DIRS_AFTER)'"

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
  && ok "the teardown removes both work dirs; the rejected calls made none" \
  || bad "two stacks: pkill $(wc -l < "$STUB_LOG/pkill.args") call(s), left in $TWO: $(ls -A "$TWO" 2>&1)"

# ── a stack without a key stands alone ───────────────────────────────────────
# Every suite but the two-installations one runs e2e_init once without a key. A keyed or a
# second call after it is rc 1 and keeps its globals; the teardown then takes down that one
# project and removes its work dir, the only one there is.
ONE="$WORK/one"; mkdir -p "$ONE"
: > "$STUB_LOG/docker.args"
OUT3=$(PATH="$SHIM:$PATH" TMPDIR="$ONE" bash -c '
  . "$1/scripts/tests/lib_e2e_stack.sh"
  echo "PID=$$"
  e2e_init false; echo "INIT=$?"; show K
  echo "DIRS=$(ls -A "$TMPDIR" | tr "\n" " ")"
  e2e_init false a 2>/dev/null; echo "INIT_A=$?"; show KA
  e2e_init false 2>/dev/null; echo "INIT_AGAIN=$?"; show KK
  echo "DIRS_AFTER=$(ls -A "$TMPDIR" | tr "\n" " ")"
' _ "$REPO_ROOT" 2>&1); rc=$?
v3()  { sed -n "s/^$1=//p" <<<"$OUT3" | head -1; }
blk3() { sed -n "s/^$1\.//p" <<<"$OUT3"; }
PID3="$(v3 PID)"; K_WORK="$(v3 K.E2E_WORK)"

[ "$rc" = 0 ] && [ "$(v3 INIT)" = 0 ] && [ -n "$PID3" ] && [ "$(v3 K.E2E_PROJECT)" = "ah-e2e-$PID3" ] \
  && ok "without a key: e2e_init returns 0, project ah-e2e-<pid>" || bad "without a key: rc=$rc, $OUT3"
[ "$(v3 INIT_A)" = 1 ] && [ -n "$(blk3 K)" ] && [ "$(blk3 KA)" = "$(blk3 K)" ] \
  && ok "e2e_init a after a stack without a key: rc 1, every global still that stack's" \
  || bad "e2e_init a after no key: rc '$(v3 INIT_A)', globals '$(blk3 KA | tr '\n' ' ')'"
[ "$(v3 INIT_AGAIN)" = 1 ] && [ -n "$(blk3 K)" ] && [ "$(blk3 KK)" = "$(blk3 K)" ] \
  && ok "e2e_init without a key a second time: rc 1, every global still the first one's" \
  || bad "second e2e_init without a key: rc '$(v3 INIT_AGAIN)', globals '$(blk3 KK | tr '\n' ' ')'"
[ "$(v3 DIRS)" = "${K_WORK##*/} " ] && [ "$(v3 DIRS_AFTER)" = "$(v3 DIRS)" ] \
  && ok "without a key: the rejected calls made no work dir" \
  || bad "without a key: work dirs before '$(v3 DIRS)', after '$(v3 DIRS_AFTER)'"
DC_K="-p ah-e2e-$PID3 -f $REPO_ROOT/docker-compose.yml -f $REPO_ROOT/docker-compose.test.yml --env-file $K_WORK/.env"
[ "$(cat "$STUB_LOG/docker.args")" = "compose $DC_K down -v --remove-orphans" ] && [ -z "$(ls -A "$ONE")" ] \
  && ok "without a key: the teardown takes down that one project and leaves no work dir" \
  || bad "without a key, teardown: $(cat "$STUB_LOG/docker.args"), left in $ONE: $(ls -A "$ONE" 2>&1)"

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
[ "$SUITES" = 9 ] && [ -z "$WRONG" ] \
  && ok "all 9 desktop suites call e2e_npm_ready after the tauri-cli check, none by [ -d node_modules ]" \
  || bad "desktop suites ($SUITES of 9 expected):$WRONG"

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

# ── e2e_keyring_start ────────────────────────────────────────────────────────
# Without a control directory of its own the daemon of a suite took
# $XDG_RUNTIME_DIR/keyring (R-0566): on a box the socket systemd holds there for the user,
# on a developer's machine the running keyring. So every case here runs with a runtime dir,
# home, XDG dirs and TMPDIR of the test's own, GNOME_KEYRING_CONTROL unset and, outside a
# session, a bus address where no socket is: the keyring of the machine the test runs on
# must never be reached. All of it under $WORK, a short mktemp -d: a socket path has at
# most 107 bytes. The sessions run as a suite runs them, in a shell that sourced the lib.
KR="$WORK/kr"
# kr_own <runtime dir> — the PIDs of the keyring daemons that run with that XDG_RUNTIME_DIR.
kr_own() {
  local p
  for p in $(pgrep -x gnome-keyring-d); do
    grep -qzxF "XDG_RUNTIME_DIR=$1" "/proc/$p/environ" 2>/dev/null && echo "$p"
  done
}
# kr_owner — yes if org.freedesktop.secrets has an owner on the session bus, else no.
kr_owner() {
  local r
  r=$(dbus-send --session --print-reply --reply-timeout=1000 --dest=org.freedesktop.DBus \
    /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner string:org.freedesktop.secrets 2>&1)
  case "$r" in *"boolean true"*) echo yes ;; *) echo no ;; esac
}
export -f kr_own kr_owner
# kr_gone — waits up to 5 s until no daemon of the test runs; rc 1 if one still does.
kr_gone() {
  local _
  for _ in $(seq 1 50); do
    [ -z "$(kr_own "$KR/run")" ] && return 0
    sleep 0.1
  done
  return 1
}
# kr_connect <socket> — rc 0 if something accepts a connection there.
kr_connect() {
  python3 -c 'import socket, sys; s = socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect(sys.argv[1])' \
    "$1" 2>/dev/null
}
# kr_env <cmd...> — the command with the test's runtime dir, home, XDG dirs, TMPDIR and no bus.
kr_env() {
  env -u GNOME_KEYRING_CONTROL -u SSH_AUTH_SOCK -u DISPLAY -u WAYLAND_DISPLAY \
    XDG_RUNTIME_DIR="$KR/run" HOME="$KR/home" XDG_DATA_HOME="$KR/data" \
    XDG_CONFIG_HOME="$KR/config" XDG_CACHE_HOME="$KR/cache" TMPDIR="$KR/tmp" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=$KR/no-bus" KR="$KR" "$@"
}
# kr_session <script> — the script in a dbus-run-session of a shell that sourced the lib.
kr_session() {
  kr_env bash -c '. "$1/scripts/tests/lib_e2e_stack.sh"; dbus-run-session -- bash -c "$2"' \
    _ "$REPO_ROOT" "$1"
}
# kr_box <extra PATH dir> — the copy of box_desktopbox.sh for one spec, as iter.sh calls it,
# with $KR/boxbin on PATH; sets KOUT and rc, empties $KR/box.log first.
kr_box() {
  : > "$KR/box.log"
  KOUT=$(kr_env env -u AH_E2E_WORKSPACE -u AH_DESKTOP_ENROLL_TOKENS PATH="$1$KR/boxbin:$PATH" \
    bash "$BOX/scripts/tests/box_desktopbox.sh" 192.0.2.10 pw key one.live.js 2>&1)
  rc=$?
}
kv() { sed -n "s/^$1=//p" <<<"$KOUT" | head -1; }
PLACEHOLDER=""
kr_placeholder_stop() {
  [ -n "$PLACEHOLDER" ] || return 0
  kill "$PLACEHOLDER" 2>/dev/null; wait "$PLACEHOLDER" 2>/dev/null; PLACEHOLDER=""
}
kr_cleanup() {
  local p
  kr_placeholder_stop
  command -v pgrep >/dev/null 2>&1 || return 0
  for p in $(kr_own "$KR/run"); do kill "$p" 2>/dev/null; done
}
trap 'kr_cleanup; rm -rf "$WORK"' EXIT

keyring_cases() {
  local ino rc secs err gkc left
  mkdir -p "$KR/home" "$KR/data" "$KR/config" "$KR/cache" "$KR/tmp" "$KR/stub"
  mkdir -m 0700 "$KR/run" "$KR/run/keyring"
  kr_env dbus-send --session --print-reply --dest=org.freedesktop.DBus \
      /org/freedesktop/DBus org.freedesktop.DBus.GetId >/dev/null 2>&1 \
    && bad "keyring: outside a session the test reaches a bus" \
    || ok "keyring: outside a session the test reaches no bus"

  # (a) What systemd keeps at $XDG_RUNTIME_DIR/keyring/control, or a running keyring: here
  # a socket that accepts and closes. The session's daemon must leave it as it was.
  python3 -c '
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.bind(sys.argv[1])
s.listen(16)
open(sys.argv[2], "w").close()
while True:
    s.accept()[0].close()
' "$KR/run/keyring/control" "$KR/placeholder.up" &
  PLACEHOLDER=$!
  for _ in $(seq 1 50); do [ -e "$KR/placeholder.up" ] && break; sleep 0.1; done
  ino=$(stat -c %i "$KR/run/keyring/control" 2>/dev/null)
  [ -n "$ino" ] && kr_connect "$KR/run/keyring/control" \
    && ok "keyring: a placeholder listens at \$XDG_RUNTIME_DIR/keyring/control" \
    || bad "keyring: the placeholder did not come up"

  KOUT=$(kr_session '
    e2e_keyring_start; echo "RC=$?"
    echo "GKC=${GNOME_KEYRING_CONTROL-}"
    echo "OWNER=$(kr_owner)"
    echo "OWN=$(kr_own "$XDG_RUNTIME_DIR" | wc -l)"
  ' 2>&1)
  [ "$(kv RC)" = 0 ] && [ "$(kv OWNER)" = yes ] \
    && ok "keyring (a): e2e_keyring_start returns 0, org.freedesktop.secrets has an owner on the session bus" \
    || bad "keyring (a): $KOUT"
  [[ $(kv GKC) == "$KR/tmp/"?* ]] && [ "$(kv OWN)" -ge 1 ] 2>/dev/null \
    && ok "keyring (a): the control directory is a fresh one under TMPDIR; the daemon runs with the test's runtime dir" \
    || bad "keyring (a): GNOME_KEYRING_CONTROL '$(kv GKC)', $(kv OWN) daemon(s) of the test seen in the session"
  kr_gone || true
  [ "$(stat -c %i "$KR/run/keyring/control" 2>/dev/null)" = "$ino" ] && kr_connect "$KR/run/keyring/control" \
    && [ "$(ls -A "$KR/run/keyring")" = control ] \
    && ok "keyring (a): after the session the placeholder is the same socket, listening, alone in \$XDG_RUNTIME_DIR/keyring" \
    || bad "keyring (a): after the session \$XDG_RUNTIME_DIR/keyring holds: $(ls -Ai "$KR/run/keyring" 2>&1 | tr '\n' ' ')(inode before: $ino)"

  # box_desktopbox.sh sources no lib and starts the keyring inline as e2e_keyring_start does.
  # Its copy from the box section above runs with the real dbus-run-session and daemon; npm
  # is a stub, and so is xvfb-run, which notes what the spec would find in the session.
  mkdir -p "$KR/boxbin"
  printf '#!/bin/sh\nexit 0\n' > "$KR/boxbin/npm"
  cat > "$KR/boxbin/xvfb-run" <<'EOF'
#!/usr/bin/env bash
{ echo "OWNER=$(kr_owner)"; echo "GKC=${GNOME_KEYRING_CONTROL-}"
  echo "OWN=$(kr_own "$XDG_RUNTIME_DIR" | wc -l)"; } >> "$KR/box.log"
EOF
  chmod +x "$KR/boxbin/npm" "$KR/boxbin/xvfb-run"
  kr_box ""
  gkc=$(sed -n 's/^GKC=//p' "$KR/box.log")
  [ "$rc" = 0 ] && grep -qx 'DESKTOP_SPEC_OK one.live.js' <<<"$KOUT" \
    && [ "$(sed -n 's/^OWNER=//p' "$KR/box.log")" = yes ] && [[ $gkc == "$KR/tmp/"?* ]] \
    && [ "$(sed -n 's/^OWN=//p' "$KR/box.log")" -ge 1 ] 2>/dev/null \
    && ok "keyring, box_desktopbox.sh (a): the spec runs with an owner of org.freedesktop.secrets, a control directory under TMPDIR, the test's runtime dir" \
    || bad "keyring, box_desktopbox.sh (a): rc $rc, the spec saw '$(tr '\n' ' ' < "$KR/box.log")': $KOUT"
  kr_gone || true
  [ "$(stat -c %i "$KR/run/keyring/control" 2>/dev/null)" = "$ino" ] && kr_connect "$KR/run/keyring/control" \
    && [ "$(ls -A "$KR/run/keyring")" = control ] && [ -n "$gkc" ] && [ ! -e "$gkc" ] \
    && ok "keyring, box_desktopbox.sh (a): afterwards the placeholder is the same socket, listening, and the control directory is gone" \
    || bad "keyring, box_desktopbox.sh (a): afterwards \$XDG_RUNTIME_DIR/keyring holds: $(ls -Ai "$KR/run/keyring" 2>&1 | tr '\n' ' ')(inode before: $ino), control directory '$gkc'$([ -e "$gkc" ] && echo ' still there')"

  # Counter-check: the inline start the suites had before, in a session of the same kind.
  # It waits for the owner as e2e_keyring_start does, so the daemon is up when the session ends.
  KOUT=$(kr_session '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    for _ in $(seq 1 50); do [ "$(kr_owner)" = yes ] && break; sleep 0.1; done
  ' 2>&1)
  kr_gone || true
  if [ "$(stat -c %i "$KR/run/keyring/control" 2>/dev/null)" != "$ino" ] || ! kr_connect "$KR/run/keyring/control"; then
    ok "keyring, counter-check: the inline start of before replaces the placeholder"
  else
    bad "keyring, counter-check: the inline start left the placeholder alone, so (a) proves nothing: $KOUT"
  fi
  kr_placeholder_stop

  # (b) A daemon that ends without serving the bus: rc 1 after the wait of 4 to 5 s, the
  # message and the daemon's stderr. Still no owner after the wait: NameHasOwner starts
  # nothing, or the real daemon behind the bus's service file would own the name now.
  printf '#!/bin/sh\necho "gnome-keyring-daemon stub: no daemon today" >&2\n' > "$KR/stub/gnome-keyring-daemon"
  chmod +x "$KR/stub/gnome-keyring-daemon"
  KOUT=$(kr_session '
    s=$SECONDS
    err=$(PATH="$KR/stub:$PATH" e2e_keyring_start 2>&1 >/dev/null); echo "RC=$?"
    echo "SECS=$((SECONDS - s))"
    printf "%s\n" "$err" | sed "s/^/ERR=/"
    echo "OWNER=$(kr_owner)"
  ' 2>&1)
  rc=$(kv RC); secs=$(kv SECS); err=$(sed -n 's/^ERR=//p' <<<"$KOUT")
  [ -n "$rc" ] && [ "$rc" != 0 ] && [ -n "$secs" ] && [ "$secs" -ge 4 ] && [ "$secs" -le 7 ] \
    && [ "$(kv OWNER)" = no ] \
    && ok "keyring (b): a daemon that serves no bus: rc $rc after ${secs} s, still no owner" \
    || bad "keyring (b): rc '$rc' after '$secs' s: $KOUT"
  grep -qx 'keyring: no unlocked secret service on this session bus' <<<"$err" \
    && grep -qx 'gnome-keyring-daemon stub: no daemon today' <<<"$err" \
    && ok "keyring (b): the message on stderr, and the daemon's stderr with it" \
    || bad "keyring (b): stderr '$err'"

  # The same daemon in the box: the spec is red without having run, with the message.
  kr_box "$KR/stub:"
  [ "$rc" = 1 ] && grep -qx 'DESKTOP_SPEC_FAIL one.live.js' <<<"$KOUT" && [ ! -s "$KR/box.log" ] \
    && grep -qx 'keyring: no unlocked secret service on this session bus' <<<"$KOUT" \
    && grep -qx 'gnome-keyring-daemon stub: no daemon today' <<<"$KOUT" \
    && ok "keyring, box_desktopbox.sh (b): a daemon that serves no bus: the spec fails unrun (rc 1), with the message and the daemon's stderr" \
    || bad "keyring, box_desktopbox.sh (b): rc $rc, the spec saw '$(tr '\n' ' ' < "$KR/box.log")': $KOUT"

  # (d) The control directory goes with the session shell: e2e_keyring_start leaves an EXIT
  # trap there. The block ends as a suite's does, `cd … && <command>`, and the session keeps
  # that command's status. Checked once the daemon is gone: it outlives the directory until
  # the bus goes and must not bring it back. (a), (b) and the box's runs left nothing under
  # TMPDIR either.
  KOUT=$(kr_session '
    e2e_keyring_start || exit 1
    echo "GKC=$GNOME_KEYRING_CONTROL"
    cd "$KR" && sh -c "exit 3"
  ' 2>&1); rc=$?
  kr_gone || true
  gkc=$(kv GKC)
  [ "$rc" = 3 ] && [[ $gkc == "$KR/tmp/"?* ]] && [ ! -e "$gkc" ] && [ -z "$(ls -A "$KR/tmp")" ] \
    && ok "keyring (d): after the session its control directory is gone, nothing is left under TMPDIR, the session keeps the block's status (3)" \
    || bad "keyring (d): rc $rc, GNOME_KEYRING_CONTROL '$gkc', left under TMPDIR: $(ls -A "$KR/tmp" | tr '\n' ' ')$KOUT"
  # Counter-check: with the trap cleared the directory stays, so (d) can see one.
  KOUT=$(kr_session '
    e2e_keyring_start || exit 1
    trap - EXIT
    echo "GKC=$GNOME_KEYRING_CONTROL"
  ' 2>&1)
  kr_gone || true
  gkc=$(kv GKC)
  if [[ $gkc == "$KR/tmp/"?* ]] && [ -d "$gkc" ]; then
    ok "keyring, counter-check: without the trap the control directory stays after the session"
    rm -rf -- "$gkc"
  else
    bad "keyring, counter-check: without the trap, GNOME_KEYRING_CONTROL '$gkc': $KOUT"
  fi

  # (c) Every daemon of the test is gone once its session ended, (d)'s included; one that is
  # not is killed.
  if kr_gone; then
    ok "keyring (c): no keyring daemon of the test runs after the cases"
  else
    left=$(kr_own "$KR/run" | tr '\n' ' ')
    kr_cleanup
    bad "keyring (c): still running after their sessions, killed now: $left"
  fi
}

KR_MISSING=""
for b in gnome-keyring-daemon dbus-run-session dbus-send python3 pgrep; do
  command -v "$b" >/dev/null 2>&1 || KR_MISSING+=" $b"
done
if [ -z "$KR_MISSING" ]; then
  keyring_cases
else
  for c in "(a) the user's keyring socket stays" "box_desktopbox.sh (a) the same in the box" \
    "(b) no owner is rc 1" "box_desktopbox.sh (b) no owner fails the spec" \
    "(d) the control directory goes with the session" "(c) no daemon is left"; do
    skip "keyring $c: not available:$KR_MISSING"
  done
fi

# ── who starts gnome-keyring-daemon ──────────────────────────────────────────
# A desktop suite starts its keyring through e2e_keyring_start, and box_desktopbox.sh, which
# sources no lib, through its copy of it (R-0566): a start without --control-directory takes
# the user's $XDG_RUNTIME_DIR/keyring. Left out: the lib, and this file, whose cases hold the
# start of before and a stub of that name.
# kr_starts <file> — each start of the daemon in the file, as a logical line (joined at a
# trailing backslash), comment lines left out. A start: the name with an option after it, or
# in a command position (line start, after | ; & or $( ). A name in a list, as e2e_require
# and desktop_e2e_skip_test.sh's stubs take it, is none.
kr_starts() {
  sed -e :a -e '/\\$/N; s/\\\n//; ta' "$1" | grep -vE '^[[:space:]]*#' \
    | grep -E 'gnome-keyring-daemon[[:space:]]+-|(^|[|;&]|\$\()[[:space:]]*gnome-keyring-daemon([^-[:alnum:]_.]|$)'
}
# kr_lint <dir> — "<file>: <start>" for each start in <dir>/*.sh that must not be there.
kr_lint() {
  local f b
  for f in "$1"/*.sh; do
    b=${f##*/}
    case "$b" in
      lib_e2e_stack.sh|lib_e2e_stack_test.sh) ;;
      box_desktopbox.sh) kr_starts "$f" | grep -vF -- --control-directory | sed "s|^|$b: |" ;;
      *) kr_starts "$f" | sed "s|^|$b: |" ;;
    esac
  done
}
# kr_require <dir> — "<file>: <tool>" for each tool e2e_keyring_start runs that a suite in
# <dir> calling it leaves out of its e2e_require, or "none" when no suite calls it. Without
# dbus-send in e2e_require a machine without it fails the session instead of reporting SKIP.
kr_require() {
  local f b t req n=0
  for f in "$1"/*.sh; do
    b=${f##*/}
    case "$b" in lib_e2e_stack.sh|lib_e2e_stack_test.sh) continue ;; esac
    grep -qE '^[^#]*e2e_keyring_start' "$f" || continue
    n=$((n + 1))
    req=$(grep -E '^[[:space:]]*e2e_require ' "$f")
    for t in dbus-run-session dbus-send gnome-keyring-daemon; do
      grep -qw -- "$t" <<<"$req" || echo "$b: $t"
    done
  done
  [ "$n" -gt 0 ] || echo none
}
LINT_OUT=$(kr_lint "$HERE")
[ -z "$LINT_OUT" ] \
  && ok "lint: no scripts/tests/*.sh but the lib starts gnome-keyring-daemon, box_desktopbox.sh only with --control-directory" \
  || bad "lint: started outside e2e_keyring_start:"$'\n'"$(sed 's/^/    /' <<<"$LINT_OUT")"
[ "$(kr_starts "$HERE/box_desktopbox.sh" | grep -cF -- --control-directory)" = 1 ] \
  && ok "lint: box_desktopbox.sh starts the daemon in one place, with --control-directory" \
  || bad "lint: box_desktopbox.sh starts: $(kr_starts "$HERE/box_desktopbox.sh")"
LINT_OUT=$(kr_require "$HERE")
[ -z "$LINT_OUT" ] \
  && ok "lint: each suite that calls e2e_keyring_start requires dbus-run-session, dbus-send and gnome-keyring-daemon" \
  || bad "lint: e2e_require of a suite that calls e2e_keyring_start leaves out: ${LINT_OUT//$'\n'/, }"

# Counter-check: a copy of scripts/tests, with the start of before in a suite, the box's
# start without its control directory and a suite's e2e_require without dbus-send.
LINT="$WORK/lint"; mkdir -p "$LINT"
cp "$HERE"/*.sh "$LINT/"
OLD_START='eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true'
printf '    %s\n' "$OLD_START" >> "$LINT/desktop_e2e_crud.sh"
sed -i 's/ --control-directory="[^"]*"//' "$LINT/box_desktopbox.sh"
sed -i 's/^\(e2e_require .*\) dbus-send /\1 /' "$LINT/desktop_e2e_live.sh"
LINT_OUT=$(kr_lint "$LINT")
grep -qxF "desktop_e2e_crud.sh:     $OLD_START" <<<"$LINT_OUT" \
  && grep -q '^box_desktopbox\.sh: .*gnome-keyring-daemon --unlock' <<<"$LINT_OUT" \
  && [ "$(grep -c . <<<"$LINT_OUT")" = 2 ] \
  && ok "lint, counter-check: the copy is reported for the start of before and the box's start without --control-directory, nothing else" \
  || bad "lint, counter-check: reported for the copy:"$'\n'"$(sed 's/^/    /' <<<"$LINT_OUT")"
LINT_OUT=$(kr_require "$LINT")
[ "$LINT_OUT" = "desktop_e2e_live.sh: dbus-send" ] \
  && ok "lint, counter-check: the copy is reported for the e2e_require without dbus-send, nothing else" \
  || bad "lint, counter-check: e2e_require in the copy, reported: '${LINT_OUT//$'\n'/, }'"

# ── e2e_wait_enroll_plane ────────────────────────────────────────────────────
# :8444 answered 502 right after e2e_up until the ca-issuer listened, and the enroll step
# of the stack suite failed flaky (R-0935, R-0955). curl is a stub that answers the codes
# of STUB_SEQ one call at a time and then repeats the last; 000 is a refused connection.
WAIT="$WORK/wait"; mkdir -p "$WAIT"
cat > "$WAIT/curl" <<'EOF'
#!/usr/bin/env bash
seq_file="$STUB_LOG/wait.seq"; calls="$STUB_LOG/wait.calls"
printf '%s\n' "$*" >> "$calls"
read -r code rest < "$seq_file"
[ -z "$rest" ] || echo "$rest" > "$seq_file"
printf '%s' "$code"
[ "$code" != 000 ] || exit 7
EOF
chmod +x "$WAIT/curl"
wait_plane() {  # wait_plane <seconds> <codes...> — e2e_wait_enroll_plane against the stub
  local secs=$1; shift
  echo "$*" > "$STUB_LOG/wait.seq"; : > "$STUB_LOG/wait.calls"
  PATH="$WAIT:$PATH" bash -c '. "$1/scripts/tests/lib_e2e_stack.sh"; E2E_ENROLL_PORT=8444; e2e_wait_enroll_plane "$2"' \
    _ "$REPO_ROOT" "$secs" > "$WORK/wait.out" 2>&1
}
wait_plane 10 000 502 503 404; rc=$?
[ "$rc" = 0 ] && [ "$(wc -l < "$STUB_LOG/wait.calls")" = 4 ] \
  && ok "enroll plane: refused, 502 and 503 are waited out, the 404 of the issuer ends the wait (4 curl calls)" \
  || bad "enroll plane: rc=$rc, $(wc -l < "$STUB_LOG/wait.calls") calls: $(cat "$WORK/wait.out")"
grep -qF -- "https://localhost:8444/" "$STUB_LOG/wait.calls" \
  && ok "enroll plane: asks https://localhost:<E2E_ENROLL_PORT>/" || bad "enroll plane: curl args $(head -1 "$STUB_LOG/wait.calls")"
wait_plane 2 502; rc=$?
[ "$rc" = 1 ] && grep -q "never reached the ca-issuer (last HTTP '502')" "$WORK/wait.out" \
  && ok "enroll plane: a 502 that stays is rc 1 and names the last status" \
  || bad "enroll plane: always 502 gave rc=$rc: $(cat "$WORK/wait.out")"
wait_plane 10 200; rc=$?
[ "$rc" = 0 ] && [ "$(wc -l < "$STUB_LOG/wait.calls")" = 1 ] \
  && ok "enroll plane: an issuer that answers at once costs one call" || bad "enroll plane: 200 gave rc=$rc, $(wc -l < "$STUB_LOG/wait.calls") calls"

echo ""
echo "lib_e2e_stack_test: $PASS passed, $FAIL failed, $SKIP skipped"
[ "$FAIL" -eq 0 ] || exit 1
# Keyring cases that did not run are not verified: 75, so --strict sees a SKIP, not a green test.
[ -z "$KR_MISSING" ] || { echo "SKIP: the keyring cases need:$KR_MISSING"; exit 75; }
