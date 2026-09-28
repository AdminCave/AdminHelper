#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# stack_pytest.sh — the three tests that need a real Postgres or Redis, run
# against the compose stack's own (run.sh integration, step stack-pytest).
#
#   monitoring  tests/test_migrations_smoke.py                             DATABASE_URL
#   server      tests/test_stream_redis.py                                 AH_TEST_REDIS_URL
#   ca-issuer   tests/test_db_token_store.py::test_concurrent_consume_...  AH_TEST_DB
#
# In the unit layer each of them skips wherever its service is missing, and a
# skip inside a passing suite reads as green. Here the service IS there, so a
# skip is a failure: every test writes $AH_OUT_DIR/junit/stack-<name>.xml, and
# the verdict is read from that file. The PR CI keeps running the same tests
# against its own service containers (ci.yml).
#
# Only postgres and redis are started. The tests run on the host and reach both
# on 127.0.0.1 (docker-compose.test.yml, ITEST_DATABASE_URL / ITEST_REDIS_URL
# from lib_e2e_stack.sh); nothing else of the stack is involved.
#
# python3 must be the one with the components' deps at hand: run.sh activates
# the shared venv before this step, and each component's requirements-dev.txt is
# installed into it here, as the unit steps do.
#
# Exit: 0 all three passed · 1 a test failed, skipped or wrote no XML, or the
# services did not come up · 75 docker/compose/openssl/curl/python3 missing
#
# Run: bash scripts/tests/stack_pytest.sh

set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=scripts/tests/lib_e2e_stack.sh
. "$HERE/lib_e2e_stack.sh"

e2e_require
e2e_init false
JUNIT="${AH_OUT_DIR:-$E2E_REPO_ROOT/.ah-out}/junit"
# Absolute: pytest writes after a cd into its component, the verdict reads from here.
case "$JUNIT" in /*) ;; *) JUNIT="$PWD/$JUNIT" ;; esac
mkdir -p "$JUNIT" || { echo "[stack-pytest] cannot create $JUNIT"; exit 1; }

echo "[stack-pytest] starting postgres + redis (pg :$E2E_PG_PORT, redis :$E2E_REDIS_PORT)..."
if ! e2e_dc up -d --wait --wait-timeout 180 postgres redis; then
  echo "[stack-pytest] postgres/redis did not become healthy"
  e2e_dc logs --tail 40 postgres redis
  exit 1
fi
# `healthy` is pg_isready over the socket, which the image's first-boot init
# server already answers; that one listens on no TCP address
# (docker-entrypoint.sh: listen_addresses=''). Over TCP only the final server does.
pg_up=0
for _ in $(seq 1 60); do
  if e2e_dc exec -T postgres pg_isready -h 127.0.0.1 -U adminhelper -d adminhelper >/dev/null 2>&1; then
    pg_up=1; break
  fi
  sleep 2
done
[ "$pg_up" = 1 ] || { echo "[stack-pytest] postgres never accepted TCP connections"; exit 1; }

# junit_verdict <xml> — 0 only if the file holds a testsuite that ran at least
# one test and skipped none. pytest writes one <testsuite> element carrying the
# counts; `tests` includes the skipped ones.
junit_verdict() {
  local head tests skipped
  head="$(grep -ao '<testsuite [^>]*>' "$1" 2>/dev/null | head -1)"
  [ -n "$head" ] || { echo "  no JUnit XML at $1"; return 1; }
  tests="$(sed -n 's/.* tests="\([0-9]*\)".*/\1/p' <<<"$head")"
  skipped="$(sed -n 's/.* skipped="\([0-9]*\)".*/\1/p' <<<"$head")"
  [ "${tests:-0}" -gt 0 ] || { echo "  $1: no test ran"; return 1; }
  [ "${skipped:-0}" -eq 0 ] \
    || { echo "  $1: $skipped skipped — the service is up, so a skip is a failure"; return 1; }
}

PASSED=0; FAILED=()
# stack_test <name> <component dir> <test> <VAR=value…> — one test, its XML, its verdict.
stack_test() {
  local name="$1" dir="$2" test="$3"; shift 3
  local xml="$JUNIT/stack-$name.xml" rc=0
  echo "[stack-pytest] $name: $dir/$test"
  # A pytest that dies before writing must not be judged by last run's file.
  rm -f "$xml"
  ( cd "$E2E_REPO_ROOT/$dir" \
      && python3 -m pip install -q -r requirements-dev.txt \
      && env "$@" python3 -m pytest -q -rs "$test" --junitxml="$xml" ) || rc=$?
  junit_verdict "$xml" || rc=1
  if [ "$rc" = 0 ]; then PASSED=$((PASSED + 1)); echo "  PASS  $name"
  else FAILED+=("$name"); echo "  FAIL  $name (rc=$rc)"; fi
}

stack_test monitoring-migrations apps/monitoring tests/test_migrations_smoke.py \
  "DATABASE_URL=$ITEST_DATABASE_URL"
stack_test server-redis apps/server tests/test_stream_redis.py \
  "AH_TEST_REDIS_URL=$ITEST_REDIS_URL"
stack_test ca-issuer-toctou apps/ca-issuer \
  tests/test_db_token_store.py::test_concurrent_consume_only_one_wins \
  "AH_TEST_DB=$ITEST_DATABASE_URL"

echo "stack_pytest: $PASSED passed, ${#FAILED[@]} failed${FAILED[*]:+ (${FAILED[*]})}"
[ "${#FAILED[@]}" -eq 0 ]
