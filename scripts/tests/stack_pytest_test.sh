#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# stack_pytest_test.sh — hermetic test for stack_pytest.sh's verdict.
#
# The step exists because a skip inside a passing pytest run reads as green, so
# its one job is to turn exactly that into a failure. Here docker, openssl,
# curl, pkill and python3 are PATH stubs: no stack starts, and the python3 stub
# plays pytest — it writes the JUnit XML --junitxml asks for, with the counts a
# SHIM_PYTEST mode dictates. The real run against a real stack is the heavy
# layer's (run.sh integration on a VM).
#
# Run: bash scripts/tests/stack_pytest_test.sh

set -uo pipefail

# The calls are checked for exactly the variable each test gets; one inherited
# from the caller (.devenv.sh exports AH_TEST_DB) would show up in all three.
unset DATABASE_URL AH_TEST_DB AH_TEST_REDIS_URL

HERE=$(cd "$(dirname "$0")" && pwd)
STACK="$HERE/stack_pytest.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
SHIM="$WORK/bin"; mkdir -p "$SHIM"

# docker answers e2e_require's probes and every compose call; SHIM_UP_RC makes
# `up` fail. pkill must never reach a real process: e2e_teardown sends -9.
cat > "$SHIM/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_LOG/docker.args"
case "$*" in *" up "*) exit "${SHIM_UP_RC:-0}" ;; esac
exit 0
EOF
for t in curl pkill; do printf '#!/usr/bin/env bash\nexit 0\n' > "$SHIM/$t"; done
cat > "$SHIM/openssl" <<'EOF'
#!/usr/bin/env bash
n=$(( $(cat "$STUB_LOG/openssl.n" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$STUB_LOG/openssl.n"
printf '%032x\n' "$n"
EOF
# python3 as pip and pytest. SHIM_PYTEST: pass (default) · skip · empty (no test
# ran) · none (exit 0, no XML written) · fail (exit 1). SHIM_PYTEST_ONLY limits
# the mode to the one call whose test argument contains it; the others pass.
cat > "$SHIM/python3" <<'EOF'
#!/usr/bin/env bash
case "$*" in *"-m pip"*) exit 0 ;; esac
xml="" test=""
for a in "$@"; do
  case "$a" in --junitxml=*) xml="${a#--junitxml=}" ;; tests/*) test="$a" ;; esac
done
printf 'cwd=%s test=%s DATABASE_URL=%s AH_TEST_REDIS_URL=%s AH_TEST_DB=%s\n' \
  "$PWD" "$test" "${DATABASE_URL:-}" "${AH_TEST_REDIS_URL:-}" "${AH_TEST_DB:-}" >> "$STUB_LOG/pytest.calls"
mode="${SHIM_PYTEST:-pass}"
[ -n "${SHIM_PYTEST_ONLY:-}" ] && case "$test" in *"$SHIM_PYTEST_ONLY"*) ;; *) mode=pass ;; esac
suite() { printf '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest" errors="0" failures="%s" skipped="%s" tests="%s" time="0.1"></testsuite></testsuites>\n' "$1" "$2" "$3" > "$xml"; }
case "$mode" in
  pass)  suite 0 0 1; exit 0 ;;
  skip)  suite 0 1 1; echo "SKIPPED [1] $test: Redis not reachable"; exit 0 ;;
  empty) suite 0 0 0; exit 0 ;;
  none)  exit 0 ;;
  fail)  suite 1 0 1; exit 1 ;;
esac
EOF
chmod +x "$SHIM"/*
export STUB_LOG

# run_stack <case> [VAR=value…] — stack_pytest.sh against the stubs, its own
# AH_OUT_DIR and log per case. Output in $OUT, exit code in $rc.
OUT=""; rc=0
run_stack() {
  local c="$1"; shift
  STUB_LOG="$WORK/log-$c"; mkdir -p "$STUB_LOG"
  OUT=$(env PATH="$SHIM:$PATH" TMPDIR="$WORK" AH_OUT_DIR="$WORK/out-$c" "$@" bash "$STACK" 2>&1); rc=$?
}

# ── all three pass ───────────────────────────────────────────────────────────
run_stack green
[ "$rc" = 0 ] && grep -q '^stack_pytest: 3 passed, 0 failed$' <<<"$OUT" \
  && ok "three passing tests -> exit 0, summary 3 passed" || bad "green: rc=$rc; $OUT"
for n in monitoring-migrations server-redis ca-issuer-toctou; do
  [ -f "$WORK/out-green/junit/stack-$n.xml" ] && ok "junit/stack-$n.xml written" \
    || bad "no junit/stack-$n.xml: $(ls "$WORK/out-green/junit" 2>&1)"
done
CALLS="$WORK/log-green/pytest.calls"
DB=$(grep -o 'postgresql+psycopg://adminhelper:[0-9a-f]*@127\.0\.0\.1:[0-9]*/adminhelper' "$CALLS" | head -1)
REDIS=$(grep -o 'redis://127\.0\.0\.1:[0-9]*/0' "$CALLS" | head -1)
grep -q "cwd=.*/apps/monitoring test=tests/test_migrations_smoke.py DATABASE_URL=$DB AH_TEST_REDIS_URL= " "$CALLS" \
  && [ -n "$DB" ] && ok "monitoring's migration smoke gets DATABASE_URL = the stack's Postgres" \
  || bad "monitoring call: $(grep monitoring "$CALLS")"
grep -q "cwd=.*/apps/server test=tests/test_stream_redis.py DATABASE_URL= AH_TEST_REDIS_URL=$REDIS " "$CALLS" \
  && [ -n "$REDIS" ] && ok "server's stream test gets AH_TEST_REDIS_URL = the stack's Redis" \
  || bad "server call: $(grep apps/server "$CALLS")"
grep -q "cwd=.*/apps/ca-issuer test=tests/test_db_token_store.py::test_concurrent_consume_only_one_wins .*AH_TEST_DB=$DB$" "$CALLS" \
  && ok "ca-issuer's TOCTOU test gets AH_TEST_DB = the stack's Postgres" \
  || bad "ca-issuer call: $(grep ca-issuer "$CALLS")"
grep -q -- 'up -d --wait --wait-timeout 180 postgres redis' "$WORK/log-green/docker.args" \
  && ok "only postgres and redis are started, waited for healthy" \
  || bad "docker up: $(grep ' up ' "$WORK/log-green/docker.args")"
grep -q -- 'exec -T postgres pg_isready -h 127.0.0.1' "$WORK/log-green/docker.args" \
  && ok "Postgres is waited for over TCP, not only the socket" || bad "no TCP readiness probe"

# ── the one thing the step exists for: a skip is a failure ───────────────────
run_stack skip SHIM_PYTEST=skip SHIM_PYTEST_ONLY=test_stream_redis
[ "$rc" = 1 ] && grep -q 'stack-server-redis.xml: 1 skipped' <<<"$OUT" \
  && grep -q '^stack_pytest: 2 passed, 1 failed (server-redis)$' <<<"$OUT" \
  && ok "a test that skips although pytest exits 0 fails the step and is named" \
  || bad "skip: rc=$rc; $OUT"

# ...and so is a run in which no test was collected, or no XML was written.
run_stack empty SHIM_PYTEST=empty SHIM_PYTEST_ONLY=test_db_token_store
[ "$rc" = 1 ] && grep -q 'stack-ca-issuer-toctou.xml: no test ran' <<<"$OUT" \
  && ok "a run with zero tests fails the step" || bad "empty: rc=$rc; $OUT"
# A passing XML from an earlier run is already in place: it must not stand in
# for a pytest that wrote nothing this time.
mkdir -p "$WORK/out-none/junit"
printf '<testsuites><testsuite name="pytest" errors="0" failures="0" skipped="0" tests="1"></testsuite></testsuites>\n' \
  > "$WORK/out-none/junit/stack-monitoring-migrations.xml"
run_stack none SHIM_PYTEST=none SHIM_PYTEST_ONLY=test_migrations_smoke
[ "$rc" = 1 ] && grep -q 'no JUnit XML at .*stack-monitoring-migrations.xml' <<<"$OUT" \
  && ok "no XML from this run fails the step, an old one does not count" \
  || bad "none: rc=$rc; $OUT"

run_stack red SHIM_PYTEST=fail SHIM_PYTEST_ONLY=test_migrations_smoke
[ "$rc" = 1 ] && grep -q 'FAIL  monitoring-migrations (rc=1)' <<<"$OUT" \
  && ok "a failing test fails the step" || bad "fail: rc=$rc; $OUT"

# ── the services never came up ───────────────────────────────────────────────
run_stack noup SHIM_UP_RC=1
[ "$rc" = 1 ] && grep -q 'did not become healthy' <<<"$OUT" \
  && [ ! -s "$WORK/log-noup/pytest.calls" ] \
  && ok "no healthy postgres/redis -> exit 1 before any test" || bad "noup: rc=$rc; $OUT"

echo ""
echo "stack_pytest_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
