#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# run_flags_test.sh — hermetic test for the run.sh flag parser, strict mode and the
# shared lock of the heavy python steps.
#
# Runs the real aggregator against a PATH that contains coreutils and nothing
# else: no go, no cargo, no node, no docker, no shellcheck. Every dependency-gated
# step therefore SKIPs, which is exactly the situation --strict exists for — a run
# where nothing executed must not read as green. --step keeps each case down to
# one step, so the whole file runs in seconds without a suite ever firing.
#
# Run: bash scripts/tests/run_flags_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

# Every case sets what it needs explicitly, so inherited AH_* would only corrupt
# results. It WILL be inherited: from T9 on this file runs inside `run.sh unit
# --strict --only scripts`, which exports AH_ONLY=scripts and AH_STRICT=1.
unset AH_ONLY AH_STRICT AH_STEP AH_REQUIRED AH_ALLOW_REAL AH_CAPTURE AH_TEST_DB \
      AH_SCRIPT_TESTS AH_SCRIPT_TESTS_DIR AH_HEAD AH_TREE_HASH AH_ARGS AH_PART

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
RUN="$REPO_ROOT/scripts/tests/run.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ── a PATH with the plumbing but none of the toolchains ───────────────────────
BARE="$WORK/bin"; mkdir -p "$BARE"

# Ein venv, das es nicht gibt — fuer JEDEN Aufruf hier, nicht nur die, die es
# einzeln setzen. ensure_venv AKTIVIERT das venv, auf das AH_VENV zeigt, und legt
# dessen bin/ auf PATH: ein gesetztes AH_VENV des Aufrufers (verify.sh setzt eins)
# greift damit an "$BARE" vorbei und gibt den dependency-gegatterten Schritten ein
# python MIT den Paketen. `--step schemathesis` und `all --strict` fuzzen dann
# wirklich alle drei Dienste, statt zu SKIPpen — die Datei lief zehn Minuten statt
# der Sekunden, die sie oben verspricht, und pruefte dabei etwas anderes als sie
# behauptet. Einzelne Aufrufe duerfen weiter ueberschreiben.
export AH_VENV="$WORK/no-venv"
for t in bash sh git mktemp sed grep awk cat tee date rm mv cp ls wc head tail tr cut sort paste env dirname basename find touch mkdir printf; do
  src=$(command -v "$t" 2>/dev/null) && ln -sf "$src" "$BARE/$t"
done
for leaked in go cargo node npm docker shellcheck ruff python3; do
  [ -e "$BARE/$leaked" ] && { echo "fixture broken: $leaked leaked into the bare PATH" >&2; exit 1; }
done

# A second PATH that additionally offers a shellcheck stub, so one step can
# actually PASS — needed to tell "nothing ran" apart from "something ran and
# other steps skipped".
WITHSC="$WORK/bin-sc"; mkdir -p "$WITHSC"
cp -a "$BARE/." "$WITHSC/"
rm -f "$WITHSC/shellcheck"
printf '#!/bin/sh\nexit 0\n' > "$WITHSC/shellcheck"; chmod +x "$WITHSC/shellcheck"

# run_bare <args…> — run.sh on the bare PATH; stdout+stderr in $OUT, code in $rc
OUT=""; rc=0
run_bare() {
  OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" "$BARE/bash" "$RUN" "$@" 2>&1); rc=$?
}

# ══ parser ════════════════════════════════════════════════════════════════════
echo "── flag parser ──"
run_bare lint --bogus
[ $rc -eq 2 ] && grep -q "unknown flag: --bogus" <<<"$OUT" && ok "unknown flag -> exit 2" || bad "unknown flag: rc=$rc"

run_bare lint unit
[ $rc -eq 2 ] && grep -q "unexpected argument: unit" <<<"$OUT" && ok "second positional -> exit 2" || bad "second positional: rc=$rc"

run_bare lint --only
[ $rc -eq 2 ] && grep -q "needs at least one key" <<<"$OUT" && ok "--only without a key -> exit 2" || bad "--only bare: rc=$rc"

run_bare lint --step
[ $rc -eq 2 ] && grep -q "needs a step name" <<<"$OUT" && ok "--step without a name -> exit 2" || bad "--step bare: rc=$rc"

run_bare lint --only nixkey
[ $rc -eq 2 ] && grep -q "unknown AH_ONLY key: 'nixkey'" <<<"$OUT" && ok "unknown --only key -> exit 2" || bad "unknown key: rc=$rc"

# --only must swallow every following non-flag word instead of reading the second
# one as a layer — the multi-key form is what iter.sh/verify.sh pass.
run_bare unit --only web desktop-ui --step "web vitest"
[ $rc -eq 0 ] && ! grep -q "unexpected argument" <<<"$OUT" \
  && ok "--only takes a multi-key list" || bad "--only list: rc=$rc $(grep -m1 unexpected <<<"$OUT")"

# The env form has to keep working: scripts on a box run without an allowlist.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_ONLY=scripts AH_STEP="shellcheck" "$BARE/bash" "$RUN" lint 2>&1); rc=$?
grep -q "SKIP  shellcheck" <<<"$OUT" && ok "AH_ONLY/AH_STEP envs still work" || bad "env form broke: $OUT"

# ══ --step ════════════════════════════════════════════════════════════════════
echo "── --step ──"
run_bare lint --step nixda
[ $rc -eq 2 ] && grep -q "unknown step: 'nixda'" <<<"$OUT" && ok "unknown step -> exit 2" || bad "unknown step: rc=$rc"

# Four candidates since scripts/ got its own ruff step: check and format
# check, for apps/ and for scripts/.
run_bare lint --step ruff
[ $rc -eq 2 ] && grep -q "ambiguous step: 'ruff' matches 4 steps" <<<"$OUT" \
  && grep -q "ruff format check" <<<"$OUT" && grep -q "ruff check (scripts)" <<<"$OUT" \
  && ok "ambiguous step -> exit 2, candidates listed" || bad "ambiguous step: rc=$rc"

# The dry pass must reject BEFORE running anything: an ambiguous --step may not
# have executed one of its candidates on the way to the error.
grep -qE '^  (PASS|SKIP|FAIL)' <<<"$OUT" && bad "ambiguous --step ran a step anyway" || ok "ambiguous --step runs nothing"

# scripts/ has to be reachable as its own step, or `verify.sh scripts` could
# not lint it without linting apps/ too.
run_bare lint --step "ruff check (scripts)"
[ "$(grep -cE '^  (PASS|SKIP|FAIL)' <<<"$OUT")" -eq 1 ] \
  && ok "the scripts ruff step is addressable on its own" \
  || bad "--step 'ruff check (scripts)' ran $(grep -cE '^  (PASS|SKIP|FAIL)' <<<"$OUT") steps"

# What the two ruff steps really lint, read off a stub's argv: roadmap.py and
# doc-smoke.py sat outside every gate while the step covered scripts/vm only.
RUFFSTUB="$WORK/bin-ruff"; mkdir -p "$RUFFSTUB"
cp -a "$BARE/." "$RUFFSTUB/"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "$RUFF_LOG"\nexit 0\n' > "$RUFFSTUB/ruff"; chmod +x "$RUFFSTUB/ruff"
RUFF_LOG="$WORK/ruff.log"; : > "$RUFF_LOG"
OUT=$(PATH="$RUFFSTUB" RUFF_LOG="$RUFF_LOG" AH_OUT_DIR="$WORK/out" "$RUFFSTUB/bash" "$RUN" lint --only scripts 2>&1); rc=$?
grep -qx 'check scripts' "$RUFF_LOG" && grep -qx 'format --check scripts' "$RUFF_LOG" \
  && grep -q "PASS  ruff check (scripts)" <<<"$OUT" \
  && ok "lint --only scripts runs ruff check and format over all of scripts/" \
  || bad "ruff was called as: $(tr '\n' '|' < "$RUFF_LOG")"

# CI and run.sh lint the same paths. The set run.sh covers is the union of its
# two ruff steps; ci.yml names it in one line each for check and format.
: > "$RUFF_LOG"
OUT=$(PATH="$RUFFSTUB" RUFF_LOG="$RUFF_LOG" AH_OUT_DIR="$WORK/out" "$RUFFSTUB/bash" "$RUN" lint --only server monitoring ca-issuer scripts 2>&1)
CI_YML="$REPO_ROOT/.github/workflows/ci.yml"
for verb in 'check' 'format --check'; do
  run_paths=$(sed -n "s/^$verb //p" "$RUFF_LOG" | tr ' ' '\n' | grep -v '^$' | sort)
  ci_paths=$(sed -n "s/^[[:space:]]*run: ruff $verb //p" "$CI_YML" | tr ' ' '\n' | grep -v '^$' | sort)
  [ -n "$run_paths" ] && [ "$run_paths" = "$ci_paths" ] \
    && ok "ruff $verb: ci.yml and run.sh cover the same paths" \
    || bad "ruff $verb: run.sh [$(echo $run_paths)] vs ci.yml [$(echo $ci_paths)]"
done

# Counted, not grepped: the error "unknown step: 'vm.py pytest'" contains the
# name too, so a grep would pass against a run.sh that has no such step at all.
run_bare unit --step "vm.py pytest"
[ "$(grep -cE '^  (PASS|SKIP|FAIL)' <<<"$OUT")" -eq 1 ] \
  && grep -qE '^  (PASS|SKIP|FAIL)  vm\.py pytest' <<<"$OUT" \
  && ok "the vm.py suite is a step of its own" || bad "vm-pytest step: $OUT"
run_bare unit --step "scripts/dev pytest"
[ "$(grep -cE '^  (PASS|SKIP|FAIL)' <<<"$OUT")" -eq 1 ] \
  && grep -qE '^  (PASS|SKIP|FAIL)  scripts/dev pytest' <<<"$OUT" \
  && ok "the scripts/dev suite is a step of its own" || bad "dev-pytest step: $OUT"

# Schemathesis is its own step for the same reason: an own verdict and an own
# budget only exist if --step can reach it without dragging a pytest step along.
run_bare unit --step "schemathesis"
[ "$(grep -cE '^  (PASS|SKIP|FAIL)' <<<"$OUT")" -eq 1 ] \
  && grep -qE '^  (PASS|SKIP|FAIL)  schemathesis' <<<"$OUT" \
  && ok "the schemathesis suite is a step of its own" || bad "schemathesis step: $OUT"

run_bare lint --step shellcheck
[ "$(grep -cE '^  (PASS|SKIP|FAIL)' <<<"$OUT")" -eq 1 ] \
  && ok "--step runs exactly one step" || bad "--step ran $(grep -cE '^  (PASS|SKIP|FAIL)' <<<"$OUT") steps"

# A step that can only SKIP on this box is still a valid --step target.
run_bare unit --step "go agent"
grep -q "SKIP  go agent (vet+test+cross)" <<<"$OUT" && ok "--step reaches a skipping step" || bad "--step on a skipping step: $OUT"

# ══ strict ════════════════════════════════════════════════════════════════════
echo "── --strict ──"
run_bare unit --step "go agent"
[ $rc -eq 0 ] && grep -q "0 passed, 0 failed, 1 skipped" <<<"$OUT" \
  && ok "without --strict a SKIP stays a SKIP (exit 0)" || bad "lenient run: rc=$rc $(grep -m1 'run.sh\[' <<<"$OUT")"
grep -q "strict-failed" <<<"$OUT" && bad "strict-failed without --strict" || ok "no strict-failed without --strict"
grep -q "required (strict)" <<<"$OUT" && bad "required set printed without --strict" || ok "required set only under --strict"

OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_REQUIRED="go-agent" "$BARE/bash" "$RUN" unit --strict --step "go agent" 2>&1); rc=$?
[ $rc -eq 1 ] && ok "required step SKIP -> exit 1" || bad "required SKIP: rc=$rc"
grep -q "strict-failed: go agent (vet+test+cross) (SKIP)" <<<"$OUT" \
  && ok "strict-failed line names the step" || bad "strict-failed line: $(grep -m1 strict <<<"$OUT")"
grep -q "required (strict): go-agent" <<<"$OUT" && ok "summary names the effective required set" || bad "required set not in summary"

OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_REQUIRED="web-vitest" "$BARE/bash" "$RUN" unit --strict --step "go agent" 2>&1); rc=$?
grep -q "strict-failed: go agent" <<<"$OUT" \
  && bad "non-required step strict-failed" || ok "a non-required SKIP does not strict-fail the step"

# A strict run in which a step really executed stays green. Pinned to one step:
# a whole layer would pick up the repo's component venvs (run.sh falls back to
# apps/*/.venv/bin/ruff, which no PATH shim can hide) and this test would then
# fail on an unrelated lint error somewhere in the tree.
OUT=$(PATH="$WITHSC" AH_OUT_DIR="$WORK/out" AH_REQUIRED="shellcheck" \
      "$WITHSC/bash" "$RUN" lint --strict --step "shellcheck (ops" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "1 passed, 0 failed" <<<"$OUT" && ! grep -q "strict-failed" <<<"$OUT" \
  && ok "a strict run with one real PASS -> exit 0" || bad "executed strict run: rc=$rc $(grep -m1 'run.sh\[' <<<"$OUT")"

# ...but a strict run in which NOTHING executed is the failure this stage exists
# for: no step failed, so without the guard the summary would read green.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_REQUIRED="web-vitest" "$BARE/bash" "$RUN" unit --strict --step "go agent" 2>&1); rc=$?
[ $rc -eq 1 ] && grep -q "strict-failed: no step ran" <<<"$OUT" \
  && ok "strict run with no executed step -> exit 1" || bad "empty strict run: rc=$rc"
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" "$BARE/bash" "$RUN" unit --step "go agent" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "no step ran" <<<"$OUT" && bad "empty run failed without --strict" \
  || ok "an empty run without --strict stays exit 0"

# --only is a lint/unit concept: the heavy layers do not read it, so a step of
# theirs must not be treated as "explicitly requested".
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_ALLOW_REAL=1 AH_REQUIRED="go-agent" \
      "$BARE/bash" "$RUN" integration --strict --only server 2>&1); rc=$?
grep -q "strict-failed: integration suite" <<<"$OUT" \
  && bad "--only strict-failed a step of a layer that ignores --only" \
  || ok "--only does not make integration steps required"

# --only makes a step explicitly requested: skipping it fails even though that
# lint step is not in the required set.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_REQUIRED="go-agent" "$BARE/bash" "$RUN" lint --strict --only scripts 2>&1); rc=$?
[ $rc -eq 1 ] && grep -qF "strict-failed: shellcheck (ops scripts) (SKIP)" <<<"$OUT" \
  && ok "--only makes a non-required step required" || bad "--only strictness: rc=$rc"
# ...while the steps --only filtered away must not fail: they were never asked
# for. Named, not counted: how many of the INCLUDED steps can run depends on
# what the box has installed (a venv ruff makes the scripts pair pass here
# and skip in CI), and a count would make this assertion box-dependent.
FILTERED_FAILED=0
for step in "ruff check (SKIP)" "ruff format check (SKIP)" "gofmt (agent) (SKIP)"; do
  grep -qF "strict-failed: $step" <<<"$OUT" && FILTERED_FAILED=1
done
[ "$FILTERED_FAILED" -eq 0 ] && ok "AH_ONLY-filtered steps do not strict-fail" \
  || bad "filtered steps failed too: $(grep -m1 'strict-failed:' <<<"$OUT")"

# ══ pytest-internal skips + the run artifact (T4) ═════════════════════════════
echo "── test-skips and the run artifact ──"
# A python3 stub standing in for a pytest run that PASSES while quietly skipping
# a test — the shape that made "N passed" mean "N minus this one" for months.
PYSHIM="$WORK/bin-py"; mkdir -p "$PYSHIM"
cp -a "$BARE/." "$PYSHIM/"
rm -f "$PYSHIM/python3"
cat > "$PYSHIM/python3" <<'EOF'
#!/bin/sh
# `-m pip install …` and `-m venv …` succeed silently; `-m pytest …` prints a
# short summary. The SHIM_* knobs reproduce the shapes real suites produce.
case "$*" in
  # SHIM_VENV_LOG records where run.sh asks for the venv. Before the pip arm: a
  # temp path may well contain "pip".
  *"-m venv "*) [ -n "${SHIM_VENV_LOG:-}" ] && printf '%s\n' "$*" >> "$SHIM_VENV_LOG"; exit 0 ;;
  *pip*|*venv*) exit 0 ;;
  # The schemathesis step probes for its package before running anything;
  # SHIM_NO_SCHEMATHESIS stands in for a box where it is not installed.
  *"import schemathesis"*) [ -n "${SHIM_NO_SCHEMATHESIS:-}" ] && exit 1; exit 0 ;;
esac
[ -n "${SHIM_ECHO_ARGV:-}" ] && echo "ARGV: $*"
# pytest writes its JUnit XML wherever --junitxml points, creating the directory;
# the stub does the same, so a test sees WHERE run.sh asks for the file.
for a in "$@"; do
  case "$a" in --junitxml=*) f="${a#--junitxml=}"; mkdir -p "$(dirname "$f")" && echo '<testsuites/>' > "$f" ;; esac
done
[ -n "${SHIM_NUL:-}" ] && printf 'a binary blob: \000 \001\n'
[ -n "${SHIM_FAKE_LINE:-}" ] && echo "SKIPPED this is plain test output, not a summary line"
echo "1 passed, 1 skipped in 0.01s"
echo "=========================== short test summary info ============================"
[ -n "${SHIM_SKIP-unset}" ] && [ -n "${SHIM_SKIP:-}" ] && echo "SKIPPED [1] $SHIM_SKIP"
# The schemathesis step loops over the three service directories, so its exit
# code is an accumulation. SHIM_RC_<SERVICE> gives each `cd` its own result and
# is the only way to reach the mixed cases (one service red, another with no
# tests collected) from here; unset means 0, so every other case is unaffected.
rc=0
case "$PWD" in
  */apps/server)     rc="${SHIM_RC_SERVER:-0}" ;;
  */apps/monitoring) rc="${SHIM_RC_MONITORING:-0}" ;;
  */apps/ca-issuer)  rc="${SHIM_RC_CA_ISSUER:-0}" ;;
esac
exit "$rc"
EOF
chmod +x "$PYSHIM/python3"

# A skip whose precondition is NOT met stays a note: visible in the summary,
# but not a failure — a box without Redis must not be forced to lie.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest"       SHIM_SKIP="tests/test_stream_redis.py:30: Redis not reachable on :6380"       "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "an unmet-precondition test-skip does not fail the run" || bad "redis skip: rc=$rc"
grep -q "1 test-skips" <<<"$OUT" && ok "the summary counts test-skips" || bad "summary: $(grep -m1 'run.sh\[' <<<"$OUT")"
grep -q "strict-failed" <<<"$OUT" && bad "unmet precondition strict-failed" || ok "no strict-fail without the precondition"

# A Redis URL with credentials names the same host and port as without them —
# redis.from_url connects there. A listener stands in for the Redis (the probe
# only opens TCP); the real python3, not the shim, and stopped by its own PID.
python3 - "$WORK/listener.port" <<'PY' &
import socket, sys, time
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(8)
open(sys.argv[1], "w").write(str(s.getsockname()[1]))
time.sleep(60)
PY
LPID=$!
for _ in $(seq 1 50); do [ -s "$WORK/listener.port" ] && break; sleep 0.1; done
LPORT=$(cat "$WORK/listener.port" 2>/dev/null)
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest" \
      AH_TEST_REDIS_URL="redis://:secret@127.0.0.1:${LPORT:-1}/0" \
      SHIM_SKIP="tests/test_stream_redis.py:38: Redis not reachable at redis://:secret@127.0.0.1:${LPORT:-1}/0" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
kill "$LPID" 2>/dev/null; wait "$LPID" 2>/dev/null
[ -n "$LPORT" ] && [ $rc -eq 1 ] && grep -q "strict-failed: .*test_stream_redis.*(test-skip)" <<<"$OUT" \
  && ok "a reachable Redis behind a URL with credentials makes its skip strict-failed" \
  || bad "redis URL with credentials: port=${LPORT:-none} rc=$rc $(grep -m1 -E 'strict-failed|run.sh\[' <<<"$OUT")"

# The same skip with its precondition met is a hole, not a note.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest"       DATABASE_URL="postgresql://x@localhost/y"       SHIM_SKIP="tests/test_migrations_smoke.py:21: DATABASE_URL nicht gesetzt"       "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 1 ] && ok "a required test-skip fails the run" || bad "required test-skip: rc=$rc"
grep -q "strict-failed: .*test_migrations_smoke.*(test-skip)" <<<"$OUT"   && ok "the strict-failed line names the test" || bad "line: $(grep -m1 strict-failed <<<"$OUT")"

# test_db_session_utc under a Postgres DATABASE_URL: its skip is a hole (R-0277). Under a
# SQLite URL monitoring's copy skips honestly.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest" \
      DATABASE_URL="postgresql://x@localhost/y" \
      SHIM_SKIP="tests/test_db_session_utc.py:26: needs a postgres DATABASE_URL: the app engine connects to it" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 1 ] && grep -q "strict-failed: .*test_db_session_utc.*(test-skip)" <<<"$OUT" \
  && ok "a test_db_session_utc skip under a Postgres DATABASE_URL fails the run" \
  || bad "session-utc skip, postgres: rc=$rc $(grep -m1 -E 'strict-failed|run.sh\[' <<<"$OUT")"
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest" \
      DATABASE_URL="sqlite:///$WORK/x.db" \
      SHIM_SKIP="tests/test_db_session_utc.py:26: needs a postgres DATABASE_URL: the app engine connects to it" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "1 test-skips" <<<"$OUT" && ! grep -q "strict-failed" <<<"$OUT" \
  && ok "the same skip under a SQLite URL is an honest test-skip" \
  || bad "session-utc skip, sqlite: rc=$rc $(grep -m1 -E 'strict-failed|run.sh\[' <<<"$OUT")"

# The rules read the URL the step gives its suite. The server step falls back to
# AH_TEST_DB, so with an empty DATABASE_URL its copies count; monitoring's do not.
for t in "test_db_session_utc.py:22: needs DATABASE_URL: the app engine connects to it" \
         "test_alembic_builtin.py:47: kein Postgres in DATABASE_URL — die Migrationskette braucht ein echtes Postgres"; do
  OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="server-pytest" \
        DATABASE_URL='' AH_TEST_DB="postgresql://x@localhost/y" SHIM_SKIP="tests/$t" \
        "$PYSHIM/bash" "$RUN" unit --strict --step "server pytest" 2>&1); rc=$?
  [ $rc -eq 1 ] && grep -q "strict-failed: .*${t%%.py*}.*(test-skip)" <<<"$OUT" \
    && ok "server step: a ${t%%.py*} skip with AH_TEST_DB on Postgres fails the run" \
    || bad "server ${t%%.py*} skip: rc=$rc $(grep -m1 -E 'strict-failed|run.sh\[' <<<"$OUT")"
done
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest" \
      DATABASE_URL='' AH_TEST_DB="postgresql://x@localhost/y" \
      SHIM_SKIP="tests/test_db_session_utc.py:26: needs a postgres DATABASE_URL: the app engine connects to it" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "1 test-skips" <<<"$OUT" && ! grep -q "strict-failed" <<<"$OUT" \
  && ok "monitoring step: the same skip with only AH_TEST_DB set is an honest test-skip" \
  || bad "monitoring session-utc skip, AH_TEST_DB only: rc=$rc $(grep -m1 -E 'strict-failed|run.sh\[' <<<"$OUT")"

# The Postgres rules hold the start of the URL, as their tests do: a postgres in a
# SQLite path is no Postgres, and its skip is honest.
for t in "test_db_session_utc.py:26: needs a postgres DATABASE_URL: the app engine connects to it" \
         "test_alembic_builtin.py:41: kein Postgres in DATABASE_URL — die Migrationskette braucht ein echtes Postgres" \
         "test_check_engine_concurrency.py:54: kein Postgres in DATABASE_URL — FOR UPDATE ist sonst ein No-op"; do
  OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest" \
        DATABASE_URL="sqlite:///$WORK/postgres/x.db" SHIM_SKIP="tests/$t" \
        "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
  [ $rc -eq 0 ] && grep -q "1 test-skips" <<<"$OUT" && ! grep -q "strict-failed" <<<"$OUT" \
    && ok "a ${t%%.py*} skip under a SQLite URL with postgres in its path is an honest test-skip" \
    || bad "${t%%.py*} skip, sqlite path with postgres: rc=$rc $(grep -m1 -E 'strict-failed|run.sh\[' <<<"$OUT")"
done

# In the server step DATABASE_URL wins over AH_TEST_DB, as in the step itself: a
# SQLite DATABASE_URL beside a Postgres AH_TEST_DB is no Postgres for the suite.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="server-pytest" \
      DATABASE_URL="sqlite:///$WORK/x.db" AH_TEST_DB="postgresql://x@localhost/y" \
      SHIM_SKIP="tests/test_alembic_builtin.py:47: kein Postgres in DATABASE_URL — die Migrationskette braucht ein echtes Postgres" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "server pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "1 test-skips" <<<"$OUT" && ! grep -q "strict-failed" <<<"$OUT" \
  && ok "server step: DATABASE_URL wins over AH_TEST_DB, a SQLite one makes the skip honest" \
  || bad "server precedence: rc=$rc $(grep -m1 -E 'strict-failed|run.sh\[' <<<"$OUT")"

# ...and without --strict pytest is not even asked for its skips, so the step
# behaves exactly as it did before this stage.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" DATABASE_URL="postgresql://x@localhost/y"       SHIM_SKIP="tests/test_migrations_smoke.py:21: DATABASE_URL nicht gesetzt"       "$PYSHIM/bash" "$RUN" unit --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "without --strict a test-skip changes nothing" || bad "lenient test-skip: rc=$rc"

# The artifact ties the verdict to a tree instead of to a claim.
ART="$WORK/out/last-unit.json"
[ -f "$ART" ] && ok "the run writes last-<layer>.json" || bad "no artifact at $ART"
# Explicit values rather than whatever the surrounding checkout has: a box may
# answer nothing at all, and these two would otherwise pass by inheriting the
# very variables this file unsets — proving nothing about the code under test.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out-ev" \
      AH_HEAD=4444444444444444444444444444444444444444 \
      AH_TREE_HASH=5555555555555555555555555555555555555555 \
      SHIM_SKIP="" "$PYSHIM/bash" "$RUN" unit --step "monitoring pytest" 2>&1)
grep -qE '"tree_hash": "[0-9a-f]{40}"' "$WORK/out-ev/last-unit.json" \
  && ok "artifact: 40-hex tree_hash" || bad "tree_hash: $(grep tree_hash "$WORK/out-ev/last-unit.json")"
grep -qE '"head": "[0-9a-f]{40}"' "$WORK/out-ev/last-unit.json" \
  && ok "artifact: head commit" || bad "head: $(grep head "$WORK/out-ev/last-unit.json")"
grep -q '"reruns": 0' "$ART" && ok "artifact: reruns field (0 in stage 1)" || bad "reruns missing"
grep -q '"name": "monitoring pytest", "result": "pass"' "$ART"   && ok "artifact: step name and verdict" || bad "steps: $(grep -A2 '"steps"' "$ART" | tr -d '\n')"

# JUnit: each pytest step writes junit/<step-id>.xml under AH_OUT_DIR, which is
# what heavy.sh collects. A file left by an earlier run is gone first — the pull
# from the box would otherwise hand it to the report as this run's.
mkdir -p "$WORK/out-junit/junit" && echo '<testsuites/>' > "$WORK/out-junit/junit/stale.xml"
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out-junit" SHIM_SKIP="" \
      "$PYSHIM/bash" "$RUN" unit --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && [ -f "$WORK/out-junit/junit/monitoring-pytest.xml" ] \
  && ok "the monitoring pytest step writes junit/monitoring-pytest.xml" \
  || bad "junit: rc=$rc, dir: $(ls "$WORK/out-junit/junit" 2>&1)"
[ -e "$WORK/out-junit/junit/stale.xml" ] \
  && bad "a JUnit XML from an earlier run survived the new one" \
  || ok "the run drops the JUnit XMLs of earlier runs"
# The schemathesis step runs pytest once per service: one XML each, or the last
# service's file would silently replace the other two.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out-junit" SHIM_SKIP="" \
      "$PYSHIM/bash" "$RUN" unit --step "schemathesis" 2>&1); rc=$?
[ $rc -eq 0 ] && [ -f "$WORK/out-junit/junit/schemathesis-server.xml" ] \
  && [ -f "$WORK/out-junit/junit/schemathesis-monitoring.xml" ] \
  && [ -f "$WORK/out-junit/junit/schemathesis-ca-issuer.xml" ] \
  && ok "schemathesis writes one JUnit XML per service" \
  || bad "schemathesis junit: rc=$rc, dir: $(ls "$WORK/out-junit/junit" 2>&1)"

# A NUL byte anywhere in a suite's output used to make grep treat the log as
# binary and report NOTHING — every skip vanished and the run went green. This is
# the regression guard for the failure mode inside the feature against it.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest" \
      DATABASE_URL="postgresql://x@localhost/y" SHIM_NUL=1 \
      SHIM_SKIP="tests/test_migrations_smoke.py:21: DATABASE_URL nicht gesetzt" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1 | tr -d '\000'); rc=$?
# `set -o pipefail` is on, so rc is run.sh's 1, not tr's 0. The tr only keeps the
# NUL out of the capture, where bash would warn about it on every run.
[ $rc -eq 1 ] && grep -q "test_migrations_smoke.*(test-skip)" <<<"$OUT" \
  && ok "a NUL byte in the log does not hide the skips" || bad "binary log: rc=$rc"

# ...and a test that merely PRINTS a SKIPPED-looking line may not forge one.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest" \
      DATABASE_URL="postgresql://x@localhost/y" SHIM_FAKE_LINE=1 SHIM_SKIP="" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "0 test-skips" <<<"$OUT" \
  && ok "printed output cannot forge a test-skip" || bad "forged skip: rc=$rc $(grep -m1 'run.sh\[' <<<"$OUT")"

# The package is the schemathesis step's only precondition. Without it the step
# self-SKIPs, and a required SKIP under --strict is a failure, not a note: a run
# that never fuzzed an API may not read as one that did.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="schemathesis" \
      SHIM_NO_SCHEMATHESIS=1 SHIM_SKIP="" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "schemathesis" 2>&1); rc=$?
[ $rc -eq 1 ] && grep -qF "strict-failed: schemathesis (SKIP)" <<<"$OUT" \
  && ok "a missing schemathesis package strict-fails the step" \
  || bad "schemathesis dep-gate: rc=$rc $(grep -m1 -E 'SKIP|strict-failed' <<<"$OUT")"

# A targeted run (verify.sh … -- <test> exports AH_ARGS) leaves the fuzz suite to the
# PR CI: the step SKIPs as AH_ARGS and, like an AH_ONLY skip, does not strict-fail,
# while the suite the caller asked for still runs (R-0380). The check below shows the
# same strict run without AH_ARGS still fuzzing.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_PY_LOCK=0 \
      AH_REQUIRED="server-pytest schemathesis" DATABASE_URL="postgresql://x@localhost/y" \
      AH_ARGS="tests/test_x.py" SHIM_SKIP="" \
      "$PYSHIM/bash" "$RUN" unit --strict --only server 2>&1); rc=$?
[ $rc -eq 0 ] && grep -qF "SKIP  schemathesis (AH_ARGS)" <<<"$OUT" \
  && grep -qE '^  PASS  server pytest' <<<"$OUT" && ! grep -q "strict-failed" <<<"$OUT" \
  && ok "a targeted strict run skips schemathesis and still runs the asked suite" \
  || bad "targeted schemathesis: rc=$rc $(grep -m1 -E 'schemathesis|strict-failed' <<<"$OUT")"

# With the package present the step runs — otherwise the check above would pass
# against a run.sh whose step can never do anything at all.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="schemathesis" \
      SHIM_SKIP="" "$PYSHIM/bash" "$RUN" unit --strict --step "schemathesis" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -qE '^  PASS  schemathesis' <<<"$OUT" \
  && ok "with the package installed the step really runs" \
  || bad "schemathesis with package: rc=$rc $(grep -m1 -E 'SKIP|FAIL' <<<"$OUT")"

# pytest's exit 5 means "no tests collected" — a service whose suite is not there
# yet. Alone that is a self-SKIP, and required under --strict it is a failure: a
# run that fuzzed nothing may not read like one that did.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="schemathesis" \
      SHIM_SKIP="" SHIM_RC_SERVER=5 \
      "$PYSHIM/bash" "$RUN" unit --strict --step "schemathesis" 2>&1); rc=$?
[ $rc -eq 1 ] && grep -qF "strict-failed: schemathesis (SKIP)" <<<"$OUT" \
  && grep -q "no schemathesis tests collected" <<<"$OUT" \
  && ok "a service without collected tests self-SKIPs the step" \
  || bad "empty collection: rc=$rc $(grep -m1 -E 'SKIP|FAIL' <<<"$OUT")"

# ...but a real failure in ANY service outranks that self-SKIP, in both orders —
# the accumulation must neither let a later error hide behind an earlier skip nor
# let a later skip overwrite an error that already happened.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="schemathesis" \
      SHIM_SKIP="" SHIM_RC_SERVER=5 SHIM_RC_MONITORING=1 \
      "$PYSHIM/bash" "$RUN" unit --strict --step "schemathesis" 2>&1); rc=$?
[ $rc -eq 1 ] && grep -qE '^  FAIL  schemathesis' <<<"$OUT" \
  && ok "a real failure after a self-SKIP is a FAIL, not a SKIP" \
  || bad "skip-then-fail: rc=$rc $(grep -m1 -E '^  (SKIP|FAIL)' <<<"$OUT")"

OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="schemathesis" \
      SHIM_SKIP="" SHIM_RC_SERVER=1 SHIM_RC_MONITORING=5 \
      "$PYSHIM/bash" "$RUN" unit --strict --step "schemathesis" 2>&1); rc=$?
[ $rc -eq 1 ] && grep -qE '^  FAIL  schemathesis' <<<"$OUT" \
  && ok "a later self-SKIP does not bury an earlier failure" \
  || bad "fail-then-skip: rc=$rc $(grep -m1 -E '^  (SKIP|FAIL)' <<<"$OUT")"

# The counter prefix pytest writes belongs to pytest, not to the test's name.
grep -q "strict-failed: \[1\]" <<<"$OUT" && bad "the pytest counter prefix leaked into the name" \
  || ok "the skip name has no pytest counter prefix"

# A tab in a skip reason is a control character: invalid inside a JSON string.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out3" \
      SHIM_SKIP="$(printf 'tests/test_x.py:1: reason\twith a tab')" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1)
if command -v python3 >/dev/null 2>&1; then
  python3 -c "import json;json.load(open('$WORK/out3/last-unit.json'))" 2>/dev/null \
    && ok "a control character keeps the artifact valid JSON" || bad "artifact is not valid JSON"
fi

# AH_ARGS is what verify.sh forwards `-- <args>` through; it must arrive at the
# suite and must be a true no-op when empty. The `-m "not schemathesis"` in
# between is the pytest steps' own marker filter — the fuzz suite has its own
# step with its own example budget and may not be collected twice — and the
# step's JUnit file.
JX="--junitxml=$WORK/out/junit/monitoring-pytest.xml"
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_ARGS="-k lifecycle" \
      SHIM_ECHO_ARGV=1 "$PYSHIM/bash" "$RUN" unit --step "monitoring pytest" 2>&1)
grep -qF "ARGV: -m pytest -q -m not schemathesis $JX -k lifecycle" <<<"$OUT" \
  && ok "AH_ARGS reaches the suite command" || bad "AH_ARGS: $(grep -m1 'ARGV: -m' <<<"$OUT")"
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" \
      SHIM_ECHO_ARGV=1 "$PYSHIM/bash" "$RUN" unit --step "monitoring pytest" 2>&1)
grep -qxF "ARGV: -m pytest -q -m not schemathesis $JX" <<<"$OUT" \
  && ok "an empty AH_ARGS adds nothing" || bad "empty AH_ARGS: $(grep -m1 'ARGV: -m' <<<"$OUT")"

# Where git cannot answer, run.sh must take the evidence fields from the client
# that synced the tree — otherwise last-<layer>.json comes back with an empty
# head and tree_hash, and the artifact proves nothing exactly where the heavy
# runs happen. Simulated with a git that cannot answer.
NOGIT="$WORK/bin-nogit"; mkdir -p "$NOGIT"
cp -a "$BARE/." "$NOGIT/"
# rm first: the copy left a SYMLINK to the real git here, and `>` on a symlink
# writes through it — straight into /usr/bin/git.
rm -f "$NOGIT/git"
printf '#!/bin/sh\nexit 128\n' > "$NOGIT/git"; chmod +x "$NOGIT/git"
OUT=$(PATH="$NOGIT" AH_OUT_DIR="$WORK/out4" \
      AH_HEAD=1111111111111111111111111111111111111111 \
      AH_TREE_HASH=2222222222222222222222222222222222222222 \
      "$NOGIT/bash" "$RUN" lint --step "shellcheck (ops" 2>&1)
grep -q '"head": "1111111111111111111111111111111111111111"' "$WORK/out4/last-lint.json" \
  && ok "no .git: head comes from the client" || bad "head: $(grep head "$WORK/out4/last-lint.json")"
grep -q '"tree_hash": "2222222222222222222222222222222222222222"' "$WORK/out4/last-lint.json" \
  && ok "no .git: tree_hash comes from the client" || bad "tree_hash: $(grep tree_hash "$WORK/out4/last-lint.json")"

# A client value that is not exactly 40 hex characters is no identity: with no
# git to ask, the field stays empty instead of carrying it.
OUT=$(PATH="$NOGIT" AH_OUT_DIR="$WORK/out4b" \
      AH_HEAD=111111111111111111111111111111111111111 \
      AH_TREE_HASH=not-a-tree-hash \
      "$NOGIT/bash" "$RUN" lint --step "shellcheck (ops" 2>&1)
grep -q '"head": ""' "$WORK/out4b/last-lint.json" && grep -q '"tree_hash": ""' "$WORK/out4b/last-lint.json" \
  && ok "no .git and a malformed client value: the fields stay empty" \
  || bad "malformed client value: $(grep -E '"(head|tree_hash)"' "$WORK/out4b/last-lint.json" | tr -d '\n')"

# ...and where git DOES answer, the client's values still win (Kevin, 2026-09-25:
# the box needs no repository, head and tree hash come from the client). Synced
# from the main checkout the box's git does answer — but over a tree the sync
# shaped and the run changed, so its tree hash never matched the client's and
# heavy.sh threw away every artifact. Checked with a stub rather than the
# surrounding checkout: "a real repo that answers" is not a precondition this test
# can assume — that is exactly what made the first heavy run red.
FAKEGIT="$WORK/bin-fakegit"; mkdir -p "$FAKEGIT"
cp -a "$BARE/." "$FAKEGIT/"
rm -f "$FAKEGIT/git"
# Answers run.sh's own question and every call scripts/dev/tree-hash.sh makes:
# the checkout as toplevel, add/rm into its throwaway index, write-tree.
cat > "$FAKEGIT/git" <<EOF
#!/bin/sh
case "\$*" in
  "rev-parse HEAD"|write-tree) echo 3333333333333333333333333333333333333333; exit 0 ;;
  "rev-parse --show-toplevel") echo "$REPO_ROOT"; exit 0 ;;
  "add "*|"rm "*) exit 0 ;;
esac
exit 128
EOF
chmod +x "$FAKEGIT/git"
OUT=$(PATH="$FAKEGIT" AH_OUT_DIR="$WORK/out5" \
      AH_HEAD=1111111111111111111111111111111111111111 \
      "$FAKEGIT/bash" "$RUN" lint --step "shellcheck (ops" 2>&1)
grep -q '"head": "1111111111111111111111111111111111111111"' "$WORK/out5/last-lint.json" \
  && ok "the client's head wins over a git that answers" \
  || bad "precedence: $(grep '"head"' "$WORK/out5/last-lint.json")"
OUT=$(PATH="$FAKEGIT" AH_OUT_DIR="$WORK/out6" \
      AH_TREE_HASH=2222222222222222222222222222222222222222 \
      "$FAKEGIT/bash" "$RUN" lint --step "shellcheck (ops" 2>&1)
grep -q '"tree_hash": "2222222222222222222222222222222222222222"' "$WORK/out6/last-lint.json" \
  && ok "the client's tree_hash wins over a git that answers tree-hash.sh" \
  || bad "tree_hash precedence: $(grep '"tree_hash"' "$WORK/out6/last-lint.json")"

# Without client values the box keeps asking its own git (a run without sync, or
# a local one). This is also the proof that the stub answers tree-hash.sh: if it
# did not, the case above would pass on the fallback alone.
OUT=$(PATH="$FAKEGIT" AH_OUT_DIR="$WORK/out7" \
      "$FAKEGIT/bash" "$RUN" lint --step "shellcheck (ops" 2>&1)
grep -q '"head": "3333333333333333333333333333333333333333"' "$WORK/out7/last-lint.json" \
  && grep -q '"tree_hash": "3333333333333333333333333333333333333333"' "$WORK/out7/last-lint.json" \
  && ok "without client values the box's git answers both fields" \
  || bad "no client values: $(grep -E '"(head|tree_hash)"' "$WORK/out7/last-lint.json" | tr -d '\n')"

# A client value counts only as exactly 40 lowercase hex characters; anything
# else is not an identity, and the box's git answers instead.
n=0
for v in 111111111111111111111111111111111111111 \
         11111111111111111111111111111111111111111 \
         111111111111111111111111111111111111111g \
         AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA; do
  n=$((n + 1))
  OUT=$(PATH="$FAKEGIT" AH_OUT_DIR="$WORK/out8-$n" AH_HEAD="$v" AH_TREE_HASH="$v" \
        "$FAKEGIT/bash" "$RUN" lint --step "shellcheck (ops" 2>&1)
  grep -q '"head": "3333333333333333333333333333333333333333"' "$WORK/out8-$n/last-lint.json" \
    && grep -q '"tree_hash": "3333333333333333333333333333333333333333"' "$WORK/out8-$n/last-lint.json" \
    && ok "client value '$v' (${#v} chars) does not count — the box's git answers" \
    || bad "client value '$v': $(grep -E '"(head|tree_hash)"' "$WORK/out8-$n/last-lint.json" | tr -d '\n')"
done

# The box's own answer counts only as hex too: a git that exits 0 with text
# that is no commit leaves the field empty instead of filling it.
TEXTGIT="$WORK/bin-textgit"; mkdir -p "$TEXTGIT"
cp -a "$BARE/." "$TEXTGIT/"
rm -f "$TEXTGIT/git"
printf '#!/bin/sh\necho "not a commit"\nexit 0\n' > "$TEXTGIT/git"; chmod +x "$TEXTGIT/git"
OUT=$(PATH="$TEXTGIT" AH_OUT_DIR="$WORK/out9" \
      "$TEXTGIT/bash" "$RUN" lint --step "shellcheck (ops" 2>&1)
grep -q '"head": ""' "$WORK/out9/last-lint.json" \
  && ok "a git answering with text that is no hex leaves head empty" \
  || bad "non-hex git answer: $(grep '"head"' "$WORK/out9/last-lint.json")"

# A strict-failed SKIP carries its own verdict rather than being folded into
# "fail" or "skip" — the summary counts it twice, the artifact must not.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out2" AH_REQUIRED="go-agent"       "$BARE/bash" "$RUN" unit --strict --step "go agent" 2>&1)
grep -q '"result": "strict-failed"' "$WORK/out2/last-unit.json"   && ok "artifact: a strict-failed skip has its own verdict"   || bad "verdict: $(grep -A2 '"steps"' "$WORK/out2/last-unit.json" | tr -d '\n')"

# ══ where the python venv lives (R-0057) ══════════════════════════════════════
echo "── the venv default ──"
# Not under /tmp: systemd-tmpfiles clears it after ten days, and a venv half gone
# there turned four suites red without a code change. This file exports AH_VENV
# for every case; this one unsets it and gives run.sh a fixture HOME.
VLOG="$WORK/venv.log"; : > "$VLOG"
env -u AH_VENV PATH="$PYSHIM" HOME="$WORK/home" SHIM_VENV_LOG="$VLOG" AH_OUT_DIR="$WORK/out" \
  "$PYSHIM/bash" "$RUN" unit --step "monitoring pytest" >/dev/null 2>&1
grep -qxF -- "-m venv $WORK/home/.cache/ah-venv" "$VLOG" \
  && ok "AH_VENV unset -> run.sh builds the venv under \$HOME/.cache" \
  || bad "run.sh asked for the venv as: $(tr '\n' '|' < "$VLOG")"
# One default in three places: run.sh builds the venv, iter.sh activates it on a
# box for a Verify: command, sse_push_e2e.sh starts the server from it. Each
# expression is evaluated as written, with AH_VENV/VENV unset and the same HOME.
WANT_VENV="$WORK/home/.cache/ah-venv"
ITER_EXPR=$(sed -n "s/^[[:space:]]*VENVPRE='\(v=\"[^;]*\"\);.*/\1/p" "$REPO_ROOT/scripts/vm/iter.sh")
SSE_EXPR=$(grep -m1 '^VENV=' "$REPO_ROOT/scripts/tests/sse_push_e2e.sh")
got=$(env -u AH_VENV HOME="$WORK/home" bash -c "$ITER_EXPR"'; printf %s "$v"')
[ -n "$ITER_EXPR" ] && [ "$got" = "$WANT_VENV" ] \
  && ok "iter.sh activates the same venv on a box" || bad "iter.sh: '$ITER_EXPR' -> '$got'"
got=$(env -u AH_VENV -u VENV HOME="$WORK/home" bash -c "$SSE_EXPR"'; printf %s "$VENV"')
[ -n "$SSE_EXPR" ] && [ "$got" = "$WANT_VENV" ] \
  && ok "sse_push_e2e.sh starts the server from the same venv" || bad "sse_push_e2e.sh: '$SSE_EXPR' -> '$got'"
got=$(env -u VENV AH_VENV="$WORK/host-venv" HOME="$WORK/home" bash -c "$SSE_EXPR"'; printf %s "$VENV"')
[ "$got" = "$WORK/host-venv" ] \
  && ok "sse_push_e2e.sh follows an AH_VENV the host sets" || bad "sse_push_e2e.sh with AH_VENV: '$got'"

# ══ the scripts block's own aggregation logic (T9) ════════════════════════════
echo "── the scripts block ──"
# Thirteen tests, one result: the mapping from their exit codes to that result is
# logic in its own right — and it was wrong once, reporting PASS while two tests
# had not run. Fixture scripts stand in for the real ones.
BLOCK="$WORK/block"; mkdir -p "$BLOCK"
mk_case() { printf '#!/bin/sh\nexit %s\n' "$2" > "$BLOCK/$1.sh"; chmod +x "$BLOCK/$1.sh"; }
mk_case blockpass 0
mk_case blockskip 75
mk_case blockfail 1
mk_case blockfail2 2
printf '#!/bin/sh\n[ -z "$AH_ARGS" ]\n' > "$BLOCK/blockargs.sh"; chmod +x "$BLOCK/blockargs.sh"
# AH_SCRIPT_TESTS_DIR keeps the fixtures in the temp dir: a leftover under
# scripts/tests/ would shift every later tree_hash — the evidence this stage is
# built on. AH_IN_SCRIPTS_BLOCK is cleared per call rather than for the whole
# file, so the nesting guard stays live for every other case: from T9 on this
# test runs INSIDE the block, and only these cases need it out of the way. Each
# passes a two- or three-entry list, so nothing recurses.
block_run() { OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_SCRIPT_TESTS="$1" \
  AH_SCRIPT_TESTS_DIR="$BLOCK" AH_IN_SCRIPTS_BLOCK='' \
  "$BARE/bash" "$RUN" unit --only scripts "${@:2}" 2>&1); rc=$?; }

block_run "blockpass blockpass"
[ $rc -eq 0 ] && grep -q "PASS  scripts (hermetic)" <<<"$OUT" \
  && ok "block: all green -> PASS" || bad "all green: rc=$rc"

block_run "blockpass blockskip"
[ $rc -eq 0 ] && grep -q "SKIP  scripts (hermetic)" <<<"$OUT" \
  && grep -q "1 of the block's tests could not run" <<<"$OUT" \
  && ok "block: one skip -> SKIP, not a PASS that buries it" || bad "one skip: rc=$rc"

block_run "blockskip blockskip" --strict
[ $rc -eq 1 ] && grep -q "strict-failed: scripts (hermetic) (SKIP)" <<<"$OUT" \
  && ok "block: a skip under --strict fails with the same wording as any step" || bad "strict skip: rc=$rc"
grep -q "2 of the block's tests could not run" <<<"$OUT" \
  && ok "block: every skip stays visible, not just the first" || bad "only the first skip reported"

block_run "blockpass blockfail blockpass blockfail2"
[ $rc -eq 1 ] && grep -q "blockfail: FAILED (rc=1)" <<<"$OUT" \
  && ok "block: a failing test fails the block" || bad "failing test: rc=$rc"
# A red test does not end the block: the weekly run of 2026-09-25 stopped at the
# first one, and 19 of 31 tests behind it never ran.
[ "$(grep -c '^  ── block' <<<"$OUT")" -eq 4 ] \
  && ok "block: runs on past a failure, every test runs" || bad "stopped early: $(grep -c '^  ── block' <<<"$OUT") of 4 ran"
grep -q "blockfail2: FAILED (rc=2)" <<<"$OUT" && grep -q "2 of 4 failed: blockfail blockfail2" <<<"$OUT" \
  && ok "block: every red test is named, with the count" || bad "failures not summed up: $(grep 'failed' <<<"$OUT")"
# A failure outranks a skip: the block is red, not SKIP.
block_run "blockskip blockfail"
[ $rc -eq 1 ] && grep -q "FAIL  scripts (hermetic)" <<<"$OUT" && grep -q "1 of 2 failed: blockfail" <<<"$OUT" \
  && ok "block: a failure next to a skip is a FAIL, not a SKIP" || bad "fail+skip: rc=$rc"

block_run ""
[ $rc -ne 0 ] && grep -q "AH_SCRIPT_TESTS is empty" <<<"$OUT" \
  && ok "block: an empty list is refused, not trivially green" || bad "empty list: rc=$rc"

block_run "blockpass"
grep -q "refusing to nest" <<<"$OUT" && bad "nesting guard fired on a normal run" \
  || ok "block: the nesting guard does not fire on a normal run"
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_SCRIPT_TESTS="blockpass" \
  AH_SCRIPT_TESTS_DIR="$BLOCK" AH_IN_SCRIPTS_BLOCK=1 \
  "$BARE/bash" "$RUN" unit --only scripts 2>&1); rc=$?
grep -q "refusing to nest" <<<"$OUT" && ok "block: refuses to nest inside itself" || bad "no nesting guard"

# Whitespace-only is the same "nothing to verify" as empty — a string check let
# a lone newline through and reported a green block for zero tests.
block_run "$(printf '\n\t ')"
[ $rc -ne 0 ] && grep -q "AH_SCRIPT_TESTS is empty" <<<"$OUT" \
  && ok "block: a whitespace-only list is refused too" || bad "whitespace list: rc=$rc"

block_run "blockpass"
grep -q "not the default list" <<<"$OUT" \
  && ok "block: a narrowed list is announced, not silent" || bad "narrowed list not announced"

# R-0263: `verify.sh scripts -- <name…>` runs only the named tests of the list.
AH_ARGS="blockpass" block_run "blockpass blockfail"
[ $rc -eq 0 ] && grep -q "PASS  scripts (hermetic)" <<<"$OUT" && [ "$(grep -c '^  ── block' <<<"$OUT")" -eq 1 ] \
  && grep -q "not the default list" <<<"$OUT" \
  && ok "block: -- blockpass runs only blockpass, and says the list is narrowed" || bad "named test: rc=$rc $(grep '──' <<<"$OUT")"
AH_ARGS="blockfail blockpass" block_run "blockpass blockfail"
[ $rc -eq 1 ] && grep -q "blockfail: FAILED (rc=1)" <<<"$OUT" \
  && ok "block: a named test that fails still fails the run" || bad "named failing test: rc=$rc"
AH_ARGS="blockargs" block_run "blockargs blockpass"
[ $rc -eq 0 ] && grep -q "PASS  scripts (hermetic)" <<<"$OUT" \
  && ok "block: a named test does not inherit the names (it may call run.sh itself)" || bad "names leak into the test: rc=$rc"
AH_ARGS="nosuch_test" block_run "blockpass blockfail"
[ $rc -eq 2 ] && grep -q "not on the list: nosuch_test" <<<"$OUT" && ! grep -q '^  ── block' <<<"$OUT" \
  && ok "block: a name not on the list -> 2, nothing runs" || bad "unknown name: rc=$rc"
AH_ARGS='*' block_run "blockpass blockfail"
[ $rc -eq 2 ] && grep -qF "not on the list: *" <<<"$OUT" \
  && ok "block: a glob after -- is a name, not expanded against the checkout" || bad "glob name: rc=$rc $(grep 'not on the list' <<<"$OUT")"

# ══ heavy layers derive their own required set ═══════════════════════════════
echo "── heavy layers ──"
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_ALLOW_REAL=1 "$BARE/bash" "$RUN" all --strict 2>&1); rc=$?
[ $rc -eq 1 ] && grep -q "strict-failed: integration suite (SKIP)" <<<"$OUT" \
  && ok "unset AH_REQUIRED + all: the skipped integration layer is strict-failed" \
  || bad "all --strict without AH_REQUIRED: rc=$rc $(grep -m2 -E 'strict-failed|run.sh\[' <<<"$OUT")"
grep -q "strict-failed: desktop GUI E2E (SKIP)" <<<"$OUT" \
  && ok "the skipped GUI layer is strict-failed too" || bad "GUI layer not strict-failed"
grep -q "required (strict): .*upgrade-path" <<<"$OUT" \
  && ok "the printed set names the heavy ids" || bad "required line: $(grep -m1 'required (strict)' <<<"$OUT")"
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_ALLOW_REAL=1 AH_REQUIRED="ruff" "$BARE/bash" "$RUN" all --strict 2>&1); rc=$?
grep -q "strict-failed: integration suite" <<<"$OUT" \
  && bad "a host-given AH_REQUIRED was extended anyway" || ok "a host-given AH_REQUIRED is kept as is"
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" "$BARE/bash" "$RUN" unit --strict --step "go agent" 2>&1); rc=$?
grep -q "required (strict): .*upgrade-path" <<<"$OUT" \
  && bad "a lint/unit layer picked up heavy ids" || ok "lint/unit layers keep the default set"
# Every GUI suite in the directory must be in the derived set — the list is globbed,
# not hand-kept, so a new desktop_e2e_*.sh can never run without being required.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_ALLOW_REAL=1 "$BARE/bash" "$RUN" e2e --strict 2>&1); rc=$?
missing=""
for f in "$(dirname "$RUN")"/desktop_e2e_*.sh; do
  s=$(basename "$f" .sh); [ "$s" = desktop_e2e_skip_test ] && continue
  grep -q "required (strict): .*\b$s\b" <<<"$OUT" || missing="$missing $s"
done
[ -z "$missing" ] && ok "every globbed desktop_e2e_* suite is required under e2e --strict" || bad "not required:$missing"
# An empty AH_REQUIRED counts as unset (iter.sh does not forward an empty value either).
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_ALLOW_REAL=1 AH_REQUIRED="" "$BARE/bash" "$RUN" integration --strict 2>&1); rc=$?
grep -q "strict-failed: integration suite (SKIP)" <<<"$OUT" \
  && ok "an empty AH_REQUIRED is treated as unset" || bad "empty AH_REQUIRED: $(grep -m1 'required (strict)' <<<"$OUT")"

# ══ --part: the two parts heavy.sh runs on two boxes at once (R-0603) ═════════
echo "── --part ──"
run_bare lint --part
[ $rc -eq 2 ] && grep -q "needs gui or rest" <<<"$OUT" && ok "--part without a value -> exit 2" || bad "--part bare: rc=$rc $OUT"
run_bare lint --part nope
[ $rc -eq 2 ] && grep -q "unknown part: 'nope'" <<<"$OUT" && ! grep -qE '^  (PASS|SKIP|FAIL)' <<<"$OUT" \
  && ok "--part nope -> exit 2 before any step" || bad "--part nope: rc=$rc $(grep -m1 -E 'part|run.sh\[' <<<"$OUT")"
# The env form is checked the same way: want_step reads it just like the flag.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_PART=nope "$BARE/bash" "$RUN" lint 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q "unknown part: 'nope'" <<<"$OUT" && ok "AH_PART=nope -> exit 2" || bad "AH_PART=nope: rc=$rc"
run_bare lint --bogus
grep -qF -- "--part <gui|rest>" <<<"$OUT" && ok "the unknown-flag message names --part" \
  || bad "unknown-flag message: $(grep -m1 'unknown flag' <<<"$OUT")"

# The e2e layer on the bare PATH: no node, no docker, no display, so every step
# SKIPs, and the artifact still lists exactly the steps of the run's part.
artifact_steps() { sed -n 's/^    {"name": "\(.*\)", "result": .*/\1/p' "$1" | LC_ALL=C sort; }
part_run() {  # part_run <out dir> <run.sh args…>
  local d="$1"; shift
  OUT=$(PATH="$BARE" AH_OUT_DIR="$d" AH_ALLOW_REAL=1 "$BARE/bash" "$RUN" e2e "$@" 2>&1); rc=$?
}
part_run "$WORK/part-none"
NONE_STEPS=$(artifact_steps "$WORK/part-none/last-e2e.json")
part_run "$WORK/part-gui" --part gui; GUI_OUT="$OUT"; GUI_RC=$rc
GUI_STEPS=$(artifact_steps "$WORK/part-gui/last-e2e.json")
part_run "$WORK/part-rest" --part rest; REST_OUT="$OUT"; REST_RC=$rc
REST_STEPS=$(artifact_steps "$WORK/part-rest/last-e2e.json")
[ "$GUI_STEPS" = "$(printf '%s\n' 'desktop GUI E2E' 'desktop-e2e smoke' | LC_ALL=C sort)" ] \
  && ok "e2e --part gui: exactly the smoke test and the GUI guard row" \
  || bad "part gui steps: $(tr '\n' '|' <<<"$GUI_STEPS")"
[ "$REST_STEPS" = "web Playwright E2E" ] \
  && ok "e2e --part rest: exactly web Playwright E2E" || bad "part rest steps: $(tr '\n' '|' <<<"$REST_STEPS")"
[ -n "$NONE_STEPS" ] && [ "$(printf '%s\n%s\n' "$GUI_STEPS" "$REST_STEPS" | LC_ALL=C sort)" = "$NONE_STEPS" ] \
  && ok "the two parts together are the layer without --part" \
  || bad "union: gui+rest [$(printf '%s|%s' "$GUI_STEPS" "$REST_STEPS" | tr '\n' '|')] vs [$(tr '\n' '|' <<<"$NONE_STEPS")]"
BOTH=$(LC_ALL=C comm -12 <(printf '%s\n' "$GUI_STEPS") <(printf '%s\n' "$REST_STEPS"))
# Both parts non-empty and both runs through, or the two checks below would also
# hold for a run.sh that rejects --part and runs nothing.
[ -n "$GUI_STEPS" ] && [ -n "$REST_STEPS" ] && [ -z "$BOTH" ] \
  && ok "no step lies in both parts" || bad "in both parts: $(tr '\n' '|' <<<"$BOTH")"
[ "$GUI_RC" -eq 0 ] && [ "$REST_RC" -eq 0 ] \
  && ! grep -q "web Playwright" <<<"$GUI_OUT" && ! grep -qE "desktop-e2e smoke|desktop GUI E2E" <<<"$REST_OUT" \
  && ok "a step outside the part is not run, not even as a SKIP" \
  || bad "rc gui/rest=$GUI_RC/$REST_RC; gui run: $(grep -m1 'web Playwright' <<<"$GUI_OUT"); rest run: $(grep -m1 -E 'desktop-e2e smoke|desktop GUI E2E' <<<"$REST_OUT")"
grep -q '"part": "gui"' "$WORK/part-gui/last-e2e.json" && grep -q '"part": "rest"' "$WORK/part-rest/last-e2e.json" \
  && grep -q '"part": ""' "$WORK/part-none/last-e2e.json" \
  && ok "artifact: the part field (empty without --part)" \
  || bad "part field: $(grep -h '"part"' "$WORK"/part-*/last-e2e.json | tr -d '\n')"
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/part-env" AH_ALLOW_REAL=1 AH_PART=gui "$BARE/bash" "$RUN" e2e 2>&1)
[ "$(artifact_steps "$WORK/part-env/last-e2e.json")" = "$GUI_STEPS" ] && grep -q '"part": "gui"' "$WORK/part-env/last-e2e.json" \
  && ok "AH_PART is the env form of --part" || bad "AH_PART=gui: $(grep '"part"' "$WORK/part-env/last-e2e.json")"

# A part with no step in the layer verifies nothing; under --strict that stays red.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" "$BARE/bash" "$RUN" lint --part gui --strict 2>&1); rc=$?
[ $rc -eq 1 ] && grep -q "strict-failed: no step ran (.*part=gui)" <<<"$OUT" \
  && ok "lint --part gui --strict: no step ran is a failure" \
  || bad "lint --part gui --strict: rc=$rc $(grep -m1 -E 'strict-failed|run.sh\[' <<<"$OUT")"

# With docker and a display stubbed, layer_e2e reaches its suite loop, so the
# GUI suites exist as --step targets. Every case below ends in the dry pass of
# --step (unknown, ambiguous, or a step that SKIPs here: no node on this PATH);
# the stubs log every call, so a suite that started anyway would leave a call
# other than `docker info` behind.
GUISTUB="$WORK/bin-guistub"; mkdir -p "$GUISTUB"
cp -a "$BARE/." "$GUISTUB/"
GUI_STUB_LOG="$WORK/guistub.log"; : > "$GUI_STUB_LOG"
for t in docker xvfb-run WebKitWebDriver tauri-driver; do
  rm -f "$GUISTUB/$t"
  printf '#!/bin/sh\necho "%s $*" >> "%s"\nexit 0\n' "$t" "$GUI_STUB_LOG" > "$GUISTUB/$t"; chmod +x "$GUISTUB/$t"
done
gui_stub_run() {
  OUT=$(PATH="$GUISTUB" AH_OUT_DIR="$WORK/out-guistub" AH_ALLOW_REAL=1 "$GUISTUB/bash" "$RUN" e2e "$@" 2>&1); rc=$?
}
SUITES=""; NSUITES=0
for f in "$REPO_ROOT"/scripts/tests/desktop_e2e_*.sh; do
  s=$(basename "$f" .sh); [ "$s" = desktop_e2e_skip_test ] && continue
  SUITES="$SUITES $s"; NSUITES=$((NSUITES + 1))
done
# The counter-check first: in part gui every suite is a candidate. Without it the
# "unknown step" below would also hold for stubs that never reach the loop.
gui_stub_run --part gui --step desktop_e2e_
missing=""
for s in $SUITES; do grep -qx "  $s" <<<"$OUT" || missing="$missing $s"; done
[ "$NSUITES" -gt 0 ] && [ $rc -eq 2 ] && grep -q "ambiguous step: 'desktop_e2e_' matches $NSUITES steps" <<<"$OUT" \
  && [ -z "$missing" ] \
  && ok "with the stubs all $NSUITES GUI suites are --step candidates of part gui" \
  || bad "part gui candidates: rc=$rc missing:$missing $(grep -m1 -E 'ambiguous|unknown' <<<"$OUT")"
missing=""
for s in $SUITES; do
  gui_stub_run --part rest --step "$s"
  { [ $rc -eq 2 ] && grep -q "unknown step: '$s'" <<<"$OUT"; } || missing="$missing $s"
done
[ -n "$SUITES" ] && [ -z "$missing" ] \
  && ok "--part rest --step <suite> is an unknown step for every GUI suite" || bad "part rest reaches:$missing"
gui_stub_run --part gui --step "web Playwright"
[ $rc -eq 2 ] && grep -q "unknown step: 'web Playwright' (no step of layer 'e2e', part 'gui'," <<<"$OUT" \
  && ok "--part gui --step 'web Playwright' is an unknown step, and the message names the part" \
  || bad "part gui, web Playwright: rc=$rc $(grep -m1 -E 'step' <<<"$OUT")"
gui_stub_run --part rest --step "web Playwright"
[ $rc -eq 0 ] && grep -q "SKIP  web Playwright E2E" <<<"$OUT" \
  && ok "...while part rest reaches it" || bad "part rest, web Playwright: rc=$rc $(grep -m1 -E 'step|SKIP' <<<"$OUT")"
# Into a variable first: under pipefail a `grep -v | grep -q` can take the
# writer's SIGPIPE as its answer.
others=$(grep -vx 'docker info' "$GUI_STUB_LOG")
grep -qx 'docker info' "$GUI_STUB_LOG" && [ -z "$others" ] \
  && ok "no suite started (the stubs saw nothing but docker info)" \
  || bad "stub calls: $(tr '\n' '|' < "$GUI_STUB_LOG")"

# ── run.sh: the shared lock for the heavy python steps (T2, T6) ─────────────
# The real run.sh, one step at a time (--step), against a venv whose python is a
# stub: pip succeeds, pytest writes when it starts and ends and sleeps between.
# HOME (set to the temp dir below) puts the per-user lock file there, and
# AH_PY_LOCK_SHARED points at a path under the temp dir too — a real server run on
# this box, or the lock Kevin and the runner share, must neither block this test
# nor be blocked by it.
export HOME="$WORK/lock-home"; mkdir -p "$HOME/.cache"
VENV="$WORK/venv"; mkdir -p "$VENV/bin" "$WORK/run"
export STEP_LOG="$WORK/steps.log"
cat > "$VENV/bin/python3" <<'STUB'
#!/usr/bin/env bash
case "${2:-}" in
  pip) exit 0 ;;
  pytest)
    echo "start $(date +%s.%N) ${STUB_TAG:-?}" >> "$STEP_LOG"
    # STUB_HOLD: stay in the step until that file exists (30 s at most), so a
    # test can decide when this run lets go of the lock instead of guessing.
    if [ -n "${STUB_HOLD:-}" ]; then
      for _ in $(seq 1 300); do [ -e "$STUB_HOLD" ] && break; sleep 0.1; done
    else
      sleep "${STUB_SLEEP:-1}"
    fi
    echo "end $(date +%s.%N) ${STUB_TAG:-?}" >> "$STEP_LOG"
    echo "1 passed" ;;
esac
STUB
chmod +x "$VENV/bin/python3"; ln -sf python3 "$VENV/bin/python"
printf 'export PATH="%s/bin:$PATH"\n' "$VENV" > "$VENV/bin/activate"
LOCKF="$HOME/.cache/adminhelper-py.lock"

# run_step_alone <tag> <step name> [run.sh args…] — one run.sh with a clean env.
run_step_alone() {
  local tag="$1" step="$2"; shift 2
  env -u AH_ONLY -u AH_STRICT -u AH_STEP -u AH_REQUIRED -u AH_SCRIPT_TESTS \
      -u AH_IN_SCRIPTS_BLOCK -u DATABASE_URL -u AH_PY_LOCK_FILE \
      AH_PY_LOCK_SHARED="${SHARED_LOCK:-$WORK/no-shared/py.lock}" ${OWN_LOCK:+"AH_PY_LOCK_FILE=$OWN_LOCK"} \
      AH_VENV="$VENV" XDG_RUNTIME_DIR="${XDG_ALT:-$WORK/run}" AH_OUT_DIR="$WORK/out-$tag" \
      AH_PY_LOCK="${AH_PY_LOCK:-1}" AH_PY_LOCK_WAIT="${AH_PY_LOCK_WAIT:-3600}" \
      AH_TEST_DB="postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test" \
      STUB_TAG="$tag" STUB_HOLD="${STUB_HOLD:-}" bash "$RUN" quick "$@" --step "$step" > "$WORK/run-$tag.log" 2>&1
}
# wait_for <file> <pattern> — until a line matches, 30 s at most; 1 if it never came.
wait_for() {
  local _
  for _ in $(seq 1 300); do grep -q "$2" "$1" 2>/dev/null && return 0; sleep 0.1; done
  return 1
}

echo "── run.sh: two server suites at once run one after the other ──"
# Two different XDG_RUNTIME_DIRs on purpose: one shell has it and the next has
# not, and the two runs must still meet at the same lock (T6). Deterministic, not
# timed: `one` holds its step until `two` has said it waits, then lets go — a
# fixed sleep let a slow second start miss the first run on a busy box.
: > "$STEP_LOG"; rm -f "$WORK/release-one"
XDG_ALT="$WORK/run-a" STUB_HOLD="$WORK/release-one" run_step_alone one "server pytest" --only server & p1=$!
wait_for "$STEP_LOG" "^start .* one$" || bad "run one never reached its step"
XDG_ALT="$WORK/run-b" run_step_alone two "server pytest" --only server & p2=$!
wait_for "$WORK/run-two.log" "waiting for the shared python lock" || bad "run two never said it waits"
touch "$WORK/release-one"
wait "$p1"; rc1=$?; wait "$p2"; rc2=$?
[ "$rc1" = 0 ] && [ "$rc2" = 0 ] && ok "both runs pass" \
  || bad "rc $rc1/$rc2: $(cat "$WORK/run-one.log" "$WORK/run-two.log" | tail -20)"
# Sorted by time, the log must read start/end/start/end — never two starts in a row.
order=$(sort -k2 -n "$STEP_LOG" | awk '{printf "%s ", $1}')
[ "$order" = "start end start end " ] && ok "the two server steps did not overlap" \
  || bad "the steps overlapped: $(sort -k2 -n "$STEP_LOG" | tr '\n' ';')"
cat "$WORK/run-one.log" "$WORK/run-two.log" | grep -q "waiting for the shared python lock" \
  && ok "the second one said it was waiting, and for what" || bad "no waiting notice in either run"

# A holder that keeps the lock until it is killed: the subshell BECOMES sleep,
# so killing it closes fd 9 and nothing else holds the lock afterwards.
( exec 9>>"$LOCKF"; flock 9; exec sleep 60 ) & holder=$!
for _ in $(seq 1 50); do flock -n "$LOCKF" true 2>/dev/null || break; sleep 0.1; done

echo "── run.sh: a lock held too long is a SKIP with its reason, never a FAIL ──"
AH_PY_LOCK_WAIT=1 run_step_alone held "server pytest" --only server; rc=$?
grep -q "gave up after 1s waiting for the shared python lock" "$WORK/run-held.log" \
  && ok "it gives up after AH_PY_LOCK_WAIT and says why" || bad "no give-up notice: $(tail -15 "$WORK/run-held.log")"
grep -q "SKIP  server pytest" "$WORK/run-held.log" && ! grep -q "FAIL  server pytest" "$WORK/run-held.log" \
  && ok "the step reads SKIP, not FAIL" || bad "not a SKIP: $(tail -15 "$WORK/run-held.log")"
AH_PY_LOCK_WAIT=1 run_step_alone held-strict "server pytest" --only server --strict; rc=$?
[ "$rc" != 0 ] && grep -q "strict-failed: server pytest" "$WORK/run-held-strict.log" \
  && ok "under --strict it is strict-failed: not run, and the run is red" \
  || bad "strict: rc=$rc $(tail -15 "$WORK/run-held-strict.log")"

echo "── run.sh: what the lock leaves alone ──"
AH_PY_LOCK_WAIT=1 run_step_alone mon "monitoring pytest" --only monitoring \
  && grep -q "PASS  monitoring pytest" "$WORK/run-mon.log" \
  && ok "monitoring pytest runs while the lock is held" || bad "monitoring: $(tail -15 "$WORK/run-mon.log")"
AH_PY_LOCK=0 AH_PY_LOCK_WAIT=1 run_step_alone off "server pytest" --only server \
  && grep -q "PASS  server pytest" "$WORK/run-off.log" \
  && ok "AH_PY_LOCK=0 runs the server step despite the held lock" || bad "AH_PY_LOCK=0: $(tail -15 "$WORK/run-off.log")"

kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null

grep -q "server pytest pid" "$LOCKF" \
  && ok "without the shared directory each user keeps its own lock under \$HOME" || bad "per-user lock: $(cat "$LOCKF")"

# ── run.sh: the lock Kevin and the runner share (R-0080) ────────────────────
echo "── run.sh: once the shared lock directory exists, every run meets there ──"
SHARED="$WORK/shared/py.lock"; mkdir -p "$(dirname "$SHARED")"; : > "$SHARED"; chmod 666 "$SHARED"
: > "$STEP_LOG"; rm -f "$WORK/release-s1"
SHARED_LOCK="$SHARED" STUB_HOLD="$WORK/release-s1" run_step_alone s1 "server pytest" --only server & p1=$!
wait_for "$STEP_LOG" "^start .* s1$" || bad "run s1 never reached its step"
SHARED_LOCK="$SHARED" run_step_alone s2 "server pytest" --only server & p2=$!
wait_for "$WORK/run-s2.log" "waiting for the shared python lock ($SHARED)" || bad "run s2 never said it waits on $SHARED"
touch "$WORK/release-s1"
wait "$p1"; rc1=$?; wait "$p2"; rc2=$?
order=$(sort -k2 -n "$STEP_LOG" | awk '{printf "%s ", $1}')
[ "$rc1" = 0 ] && [ "$rc2" = 0 ] && [ "$order" = "start end start end " ] \
  && ok "two runs serialise on the shared file" || bad "shared: rc $rc1/$rc2, order: $order"
grep -q "server pytest pid" "$SHARED" && ok "and the holder line is written there" || bad "no holder line in $SHARED"

echo "── run.sh: AH_PY_LOCK_FILE still comes first ──"
echo "untouched" > "$SHARED"; OWN="$WORK/own/py.lock"
SHARED_LOCK="$SHARED" OWN_LOCK="$OWN" run_step_alone own "server pytest" --only server \
  && grep -q "server pytest pid" "$OWN" && [ "$(cat "$SHARED")" = untouched ] \
  && ok "an explicit lock file wins over the shared one" || bad "own: $(tail -4 "$WORK/run-own.log"); shared: $(cat "$SHARED")"

echo "── run.sh: a shared file this user may only read still locks ──"
chmod 444 "$SHARED"
( exec 9<"$SHARED"; flock 9; exec sleep 60 ) & holder=$!
for _ in $(seq 1 50); do flock -n "$SHARED" true 2>/dev/null || break; sleep 0.1; done
SHARED_LOCK="$SHARED" AH_PY_LOCK_WAIT=1 run_step_alone ro "server pytest" --only server
grep -q "gave up after 1s waiting for the shared python lock" "$WORK/run-ro.log" \
  && ! grep -q "cannot open the python lock" "$WORK/run-ro.log" \
  && ok "a read-only shared file is waited on, not refused" || bad "read-only: $(tail -8 "$WORK/run-ro.log")"
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null
SHARED_LOCK="$SHARED" run_step_alone ro2 "server pytest" --only server \
  && grep -q "PASS  server pytest" "$WORK/run-ro2.log" \
  && ok "and once free it runs, without a holder line to write" || bad "read-only free: $(tail -8 "$WORK/run-ro2.log")"

echo "── run.sh: a holder line reaches the terminal as printable text only ──"
chmod 666 "$SHARED"
{ printf 'evil\033[31mred\033]0;title\007 tail'; printf 'x%.0s' $(seq 1 300); printf 'END\n'; } > "$SHARED"
( exec 9<"$SHARED"; flock 9; exec sleep 60 ) & holder=$!
for _ in $(seq 1 50); do flock -n "$SHARED" true 2>/dev/null || break; sleep 0.1; done
SHARED_LOCK="$SHARED" AH_PY_LOCK_WAIT=1 run_step_alone esc "server pytest" --only server
HELD="$(grep "held by:" "$WORK/run-esc.log")"
grep -q "evil" <<<"$HELD" && ! LC_ALL=C grep -q $'[\x01-\x08\x0b-\x1f\x7f]' <<<"$HELD" \
  && ok "the holder line is shown without control characters" || bad "holder line: $(od -c <<<"$HELD" | head -3)"
SHOWN="${HELD#*held by: }"
[ "${#SHOWN}" -le 200 ] && ! grep -q "END" <<<"$SHOWN" \
  && ok "and cut short (200 bytes of the file at most)" || bad "holder line not cut: ${#SHOWN} chars"
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null

if [ "$(id -u)" != 0 ]; then
  echo "── run.sh: a shared file that cannot be opened is a SKIP, not a lock of its own ──"
  chmod 000 "$SHARED"
  SHARED_LOCK="$SHARED" run_step_alone no "server pytest" --only server
  grep -q "cannot open the python lock $SHARED" "$WORK/run-no.log" && grep -q "SKIP  server pytest" "$WORK/run-no.log" \
    && ok "it says why and skips the step" || bad "unopenable: $(tail -8 "$WORK/run-no.log")"
  SHARED_LOCK="$SHARED" run_step_alone no-strict "server pytest" --only server --strict; rc=$?
  [ "$rc" != 0 ] && grep -q "strict-failed: server pytest" "$WORK/run-no-strict.log" \
    && ok "under --strict that is red" || bad "unopenable strict: rc=$rc $(tail -8 "$WORK/run-no-strict.log")"
  chmod 600 "$SHARED"

  echo "── run.sh: the shared directory decides, not whether this user can see the file ──"
  EMPTY="$WORK/shared-empty"; mkdir "$EMPTY"; chmod 555 "$EMPTY"; : > "$LOCKF"
  SHARED_LOCK="$EMPTY/py.lock" run_step_alone empty "server pytest" --only server
  grep -q "cannot open the python lock $EMPTY/py.lock" "$WORK/run-empty.log" \
    && grep -q "runner-setup.sh again" "$WORK/run-empty.log" && grep -q "SKIP  server pytest" "$WORK/run-empty.log" \
    && [ ! -s "$LOCKF" ] \
    && ok "a shared directory without the file is a SKIP that names the fix" || bad "empty dir: $(tail -8 "$WORK/run-empty.log")"
  CLOSED="$WORK/shared-closed"; mkdir "$CLOSED"; : > "$CLOSED/py.lock"; chmod 000 "$CLOSED"; : > "$LOCKF"
  SHARED_LOCK="$CLOSED/py.lock" run_step_alone closed "server pytest" --only server
  chmod 755 "$CLOSED"
  grep -q "cannot open the python lock $CLOSED/py.lock" "$WORK/run-closed.log" && grep -q "SKIP  server pytest" "$WORK/run-closed.log" \
    && [ ! -s "$LOCKF" ] \
    && ok "a shared directory this user cannot search is a SKIP, not the per-user lock" || bad "closed dir: $(tail -8 "$WORK/run-closed.log"); per-user: $(cat "$LOCKF")"
fi

echo ""
echo "run_flags_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
