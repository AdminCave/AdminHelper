#!/usr/bin/env bash
#
# run.sh — single-entry test aggregator for AdminHelper.
#
# One command that crabbox (or a dev) runs on a real Linux box. It mirrors the
# per-component commands in .github/workflows/ci.yml and delegates the heavy
# docker/display suites to the existing scripts/tests/*.sh (which self-SKIP when
# their deps are missing). Every step is dependency-gated, so the SAME command
# degrades gracefully on a bare box and runs fully on a hydrated crabbox box
# (see scripts/tests/crabbox_bootstrap.sh).
#
# Usage:
#   bash scripts/tests/run.sh [lint|unit|quick|integration|e2e|all] [flags]
#     lint         ruff + gofmt + shellcheck            (fast, no stack)
#     unit         all language unit suites             (no docker/display needed;
#                                                         server pytest needs docker/DATABASE_URL)
#     quick        lint + unit                          (default)
#     integration  docker-backed integration/e2e-stack  (needs docker; opt-in)
#     e2e          desktop GUI + web Playwright          (needs docker + display; opt-in)
#     all          everything                            (opt-in)
#
#   Flags (they set the AH_* envs below; the envs stay valid because scripts on a
#   box run without an allowlist, while the flag form is what a Bash allow-rule
#   can match — an env prefix never matches one):
#     --strict         a SKIP of a required step is a FAILURE, not a pass
#     --only <keys…>   restrict lint/unit to the named components (= AH_ONLY)
#     --step <name>    run exactly one step (substring of its name, unambiguous)
#
# The heavy layers (integration|e2e|all) refuse to run unless AH_ALLOW_REAL=1,
# so they never fire by accident on a dev box. The crabbox /test skill sets it.
#
# AH_ONLY="server web …" limits the lint/unit steps to the named components —
# the per-task fast loop of a parallel lane (see crabbox_iter.sh). Filtered
# steps report SKIP (reason AH_ONLY). Keys: server monitoring ca-issuer agent
# desktop (or desktop-rs|desktop-ui|desktop-e2e) web scripts.
#
# AH_REQUIRED="<step-ids…>" (space-separated, usually set in .devenv.sh) is the
# set of steps that MUST really run under --strict; it overrides the built-in
# AH_REQUIRED_DEFAULT per host, because the dev box has no docker and no display
# while a crabbox box has both. Step ids are listed next to AH_REQUIRED_DEFAULT.
#
# Exit code: non-zero if any step FAILED. Without --strict a SKIP never fails the
# run; with --strict a skipped required step does ("SKIP heisst nicht verifiziert").

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1

# Layer is positional and optional; everything after it is flags. --only eats all
# following non-flag words, so `--only web desktop-ui` is one list, not a layer.
LAYER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --strict) AH_STRICT=1; shift ;;
    --only)
      shift; _only=""
      while [ $# -gt 0 ]; do case "$1" in --*) break ;; *) _only="$_only $1"; shift ;; esac; done
      [ -n "$_only" ] || { echo "--only needs at least one key"; exit 2; }
      AH_ONLY="${_only# }" ;;
    --step)
      shift; [ $# -gt 0 ] || { echo "--step needs a step name"; exit 2; }
      case "$1" in --*) echo "--step needs a step name, got the flag '$1'"; exit 2 ;; esac
      AH_STEP="$1"; shift ;;
    --*) echo "unknown flag: $1 (use --strict, --only <keys…>, --step <name>)"; exit 2 ;;
    *)
      [ -z "$LAYER" ] || { echo "unexpected argument: $1 (layer is already '$LAYER')"; exit 2; }
      LAYER="$1"; shift ;;
  esac
done
LAYER="${LAYER:-quick}"
AH_STRICT="${AH_STRICT:-0}"
AH_ONLY="${AH_ONLY:-}"
AH_STEP="${AH_STEP:-}"
export AH_ONLY AH_STRICT

# Steps that MUST really run under --strict. Ids (not display names) so a host can
# override the set in one space-separated line; the effective set is printed with
# the summary so it can never silently shrink a run to nothing.
#   lint/unit: ruff · gofmt · shellcheck · server-pytest · monitoring-pytest
#              ca-issuer-pytest · go-agent · desktop-cargo · desktop-ui-vitest
#              desktop-e2e-lint · web-vitest
#   integration: integration · integration-stack · backup-restore · sse-push
#                agent-monitoring · repo-build · update-test · agent-install-test
#                diagnostics-test
#   e2e: web-playwright · desktop-e2e-smoke · desktop-e2e-gui · desktop_e2e_<name>
#        (the seven GUI suites carry their script name as id, underscores and all)
AH_REQUIRED_DEFAULT="ruff server-pytest monitoring-pytest ca-issuer-pytest go-agent desktop-cargo desktop-ui-vitest web-vitest"
AH_REQUIRED="${AH_REQUIRED:-$AH_REQUIRED_DEFAULT}"

# Under --strict the python suites must report their own skips; without -rs a
# skipped test leaves no trace in `pytest -q` output at all. Exported because the
# suite commands run in `bash -c` subshells.
AH_PYTEST_RS=""; [ "$AH_STRICT" = "1" ] && AH_PYTEST_RS="-rs"
export AH_PYTEST_RS

# AH_ARGS — extra arguments for the suite runner itself, how verify.sh forwards
# `verify.sh server -- tests/test_x.py`. run.sh does not interpret them; they are
# word-split by the suite's shell, so a single argument cannot contain spaces.
AH_ARGS="${AH_ARGS:-}"
export AH_ARGS

# Python suites install into a venv (AH_VENV, default /tmp/ah-venv) so a dev's
# default `run.sh quick` never mutates the host's system site-packages (PEP 668) —
# no host-wide PIP_BREAK_SYSTEM_PACKAGES. ensure_venv (called at the top of
# layer_unit) creates + activates it; the activation reaches the run_step `bash -c`
# subshells via the exported PATH/VIRTUAL_ENV. Ephemeral boxes reuse it too (6.140).
AH_VENV="${AH_VENV:-/tmp/ah-venv}"
ensure_venv() {
  [ -x "$AH_VENV/bin/python" ] || python3 -m venv "$AH_VENV" \
    || { echo "  (venv creation failed; python suites may hit PEP 668)" >&2; return 1; }
  # shellcheck disable=SC1091
  . "$AH_VENV/bin/activate"
}

# Auto-debug: e2e specs (wdio afterTest) drop screenshots here on failure, and the
# finalizer below runs the on-box collector when AH_CAPTURE=1. crabbox_iter.sh pulls
# this dir back via -artifact-glob. No effect on plain dev/CI runs (AH_CAPTURE unset).
export AH_OUT_DIR="${AH_OUT_DIR:-$ROOT/.crabbox-out}"

PASS=0 FAIL=0 SKIP=0
# --only is honoured by the lint/unit layers only; integration/e2e always run
# their whole set. Without the distinction, `integration --strict --only server`
# would strict-fail steps nobody asked for — a false red.
ONLY_APPLIES=0
FAILED_STEPS=()
STRICT_FAILED=()
STEP_RESULTS=()   # "name|result|seconds" per step, for the run artifact
TEST_SKIPS=()     # tests pytest itself skipped (-rs), invisible in the summary before
RERUNS=0          # always 0 in stage 1; the field exists so stage 3 can fill it
SKIP_VERDICT=""   # set by _skip: "skip" or "strict-failed"
STEP_NAMES=()
STEP_PROBE=0   # 1 = --step dry pass: collect names, run nothing
hdr()  { printf '\n\033[1m### %s\033[0m\n' "$*"; }
pass() { echo   "  PASS  $*"; PASS=$((PASS+1)); }
fail() { echo   "  FAIL  $*"; FAIL=$((FAIL+1)); FAILED_STEPS+=("$1"); }

required() {  # required <id> -> 0 if the id is in the effective required set
  case " $AH_REQUIRED " in *" $1 "*) return 0 ;; esac
  return 1
}

# skip <id> <name> <reason> — a SKIP is a non-result. Under --strict it becomes a
# FAILURE when the step was either required or explicitly asked for via --only;
# a step filtered away BY --only (reason AH_ONLY) is never one of those.
# The wrapper honours --step (a step that CAN only skip on this box is still a
# valid --step target); run_step calls _skip directly, having filtered already.
skip() {
  want_step "$2" || return 0
  [ "$STEP_PROBE" = "1" ] && return 0
  _skip "$@"
  record_step "$2" "$SKIP_VERDICT" 0
}
_skip() {
  local id="$1" name="$2" reason="$3"
  echo "  SKIP  $name ($reason)"; SKIP=$((SKIP+1)); SKIP_VERDICT="skip"
  [ "$AH_STRICT" = "1" ] || return 0
  [ "$reason" = "AH_ONLY" ] && return 0
  # Counted as a SKIP *and* a FAIL on purpose: both are true, so the summary line
  # is informative, not additive. The artifact carries one verdict per step
  # instead ("strict-failed"), which is where a single value belongs.
  if { [ "$ONLY_APPLIES" = 1 ] && [ -n "$AH_ONLY" ]; } || required "$id"; then
    echo "  strict-failed: $name (SKIP)"
    STRICT_FAILED+=("$name"); FAIL=$((FAIL+1)); FAILED_STEPS+=("$name")
    SKIP_VERDICT="strict-failed"
  fi
}
record_step() { STEP_RESULTS+=("$1|$2|$3"); }

# want_step <name> -> 0 if this step should run at all. With --step it also
# records the name, so the dry pass can reject an unknown or ambiguous one
# BEFORE a single suite has run.
want_step() {
  [ -n "$AH_STEP" ] || return 0
  case "$1" in *"$AH_STEP"*) STEP_NAMES+=("$1"); return 0 ;; esac
  return 1
}

# run_step <id> <name> -- <command...> : run, classify by exit code. Exit 75
# (EX_TEMPFAIL) is the self-SKIP sentinel: a suite that can't run (no venv, no go,
# e2e_require unmet) exits 75 so it's reported SKIP, not PASS — a bare exit 0 would
# silently become a green PASS though nothing ran, and the summary line is the
# authoritative result ("SKIP heisst nicht verifiziert") (6.9).
run_step() { local id="$1" name="$2"; shift 2; [ "$1" = "--" ] && shift
  want_step "$name" || return 0
  [ "$STEP_PROBE" = "1" ] && return 0
  hdr "$name"; local rc=0 t0=$SECONDS result=""
  ( "$@" ) || rc=$?
  case "$rc" in
    0)  pass "$name"; result="pass" ;;
    75) _skip "$id" "$name" "self-skipped"; result="$SKIP_VERDICT" ;;
    *)  fail "$name"; result="fail" ;;
  esac
  record_step "$name" "$result" "$((SECONDS - t0))"
}

# run_py_step — run_step for the python suites, keeping the output so pytest's
# OWN skips can be judged. A test that skipped inside a passing suite is
# invisible in "N passed": test_migrations_smoke and test_stream_redis have been
# skipping for months while the summary read green.
run_py_step() { local id="$1" name="$2"; shift 2; [ "$1" = "--" ] && shift
  want_step "$name" || return 0
  [ "$STEP_PROBE" = "1" ] && return 0
  mkdir -p "$AH_OUT_DIR" 2>/dev/null
  local log="$AH_OUT_DIR/step-$id.log"
  hdr "$name"; local rc=0 t0=$SECONDS result=""
  ( "$@" ) 2>&1 | tee "$log"; rc=${PIPESTATUS[0]}
  case "$rc" in
    0)  pass "$name"; result="pass" ;;
    75) _skip "$id" "$name" "self-skipped"; result="$SKIP_VERDICT" ;;
    *)  fail "$name"; result="fail" ;;
  esac
  record_step "$name" "$result" "$((SECONDS - t0))"
  scan_test_skips "$log"
}

# Tests that MUST NOT skip once their precondition is met. Each guards a path
# nothing else covers, and a skip inside an otherwise passing suite is invisible:
# "N passed" quietly means "N minus this one". Each precondition mirrors what
# that test gates on, so a box that truly cannot run it stays honest while a box
# that can may not hide the hole. test_auth_token_lifecycle has no skipif today
# and therefore never skips; it is listed because the spec names it and because
# the entry costs nothing if one is ever added.
#   test_migrations_smoke     reads DATABASE_URL from the environment. The dev box
#     deliberately leaves it unset (.devenv.sh: a global DATABASE_URL would arm
#     this very test against the wrong database); CI's postgres service sets it.
#   test_auth_token_lifecycle runs in the server suite, which run.sh feeds from
#     DATABASE_URL or AH_TEST_DB, and which can also fall back to testcontainers.
#   test_stream_redis         needs a reachable Redis on the port it names.
#   test_db_token_store       needs AH_TEST_DB to point at a real Postgres; the
#     TOCTOU test needs true concurrency, so SQLite is not a substitute.
# Port from test_stream_redis.py's REDIS_URL (redis://localhost:6380/0).
redis_reachable() { (exec 3<>/dev/tcp/localhost/6380) >/dev/null 2>&1; }

test_skip_is_required() {  # test_skip_is_required <skip line> -> 0 if it must not skip
  case "$1" in
    *test_migrations_smoke*)     [ -n "${DATABASE_URL:-}" ] ;;
    *test_auth_token_lifecycle*) [ -n "${DATABASE_URL:-${AH_TEST_DB:-}}" ] || have_docker ;;
    *test_stream_redis*)         redis_reachable ;;
    *test_db_token_store*)       case "${AH_TEST_DB:-}" in *postgres*) return 0 ;; *) return 1 ;; esac ;;
    *) return 1 ;;
  esac
}

# scan_test_skips <logfile> — read pytest's `-rs` short summary. Only populated
# under --strict, where the suites are told to report their skips at all.
scan_test_skips() {
  local log="$1" line name
  [ -f "$log" ] || return 0
  while IFS= read -r line; do
    # Strip pytest's own "SKIPPED [n] " prefix, count included.
    name="${line#SKIPPED }"; name="${name#\[*\] }"
    TEST_SKIPS+=("$name")
    [ "$AH_STRICT" = "1" ] || continue
    if test_skip_is_required "$line"; then
      echo "  strict-failed: $name (test-skip)"
      STRICT_FAILED+=("$name"); FAIL=$((FAIL+1)); FAILED_STEPS+=("$name")
    fi
  # -a because a single NUL byte anywhere in the log makes GNU grep treat the
  # file as binary and print NOTHING — the skips would vanish and the run would
  # report green, which is the exact failure this function exists to catch. The
  # pattern is anchored on pytest's short-summary format so a test that merely
  # PRINTS a line starting with SKIPPED cannot forge one. No 2>/dev/null: a grep
  # that fails must be visible.
  done < <(grep -aE '^SKIPPED \[[0-9]+\] ' "$log")
}

# py_step_possible -> 0 unless --step names something no python step matches.
# The three names must stay in sync with the run_step calls in layer_unit below.
py_step_possible() {
  [ -n "$AH_STEP" ] || return 0
  local n; for n in "monitoring pytest" "ca-issuer pytest" "server pytest"; do
    case "$n" in *"$AH_STEP"*) return 0 ;; esac
  done
  return 1
}

# ── run artifact ──────────────────────────────────────────────────────────────
# Written by every run so a "green" can be checked against a tree instead of
# believed. No python3 here on purpose: run.sh must stay runnable on a box whose
# python is exactly what a step is about to install.
# Control characters (a tab in a pytest skip reason) are invalid inside a JSON
# string and would make the artifact unparseable for the very readers it exists
# for (verify.sh, the ledger's own Verify line). Replace them with a space.
json_str() {
  printf '"%s"' "$(printf '%s' "$1" \
    | LC_ALL=C tr '\000-\037' ' ' \
    | sed 's/\\/\\\\/g; s/"/\\"/g')"
}
json_list() {  # json_list <item…>
  local first=1 i
  printf '['
  for i in "$@"; do [ "$first" = 1 ] && first=0 || printf ', '; json_str "$i"; done
  printf ']'
}
write_artifact() {
  local f="$AH_OUT_DIR/last-$LAYER.json" e name result secs first=1
  mkdir -p "$AH_OUT_DIR" 2>/dev/null \
    || { echo "  artifact: cannot create $AH_OUT_DIR — not written" >&2; return 0; }
  # Drop the previous run's file first: if writing fails below, a stale artifact
  # left in place would be read as the evidence of THIS run. Missing evidence is
  # honest, outdated evidence is not.
  rm -f "$f"
  {
    printf '{\n'
    printf '  "layer": %s,\n'      "$(json_str "$LAYER")"
    printf '  "strict": %s,\n'     "$([ "$AH_STRICT" = 1 ] && echo true || echo false)"
    printf '  "only": %s,\n'       "$(json_str "$AH_ONLY")"
    printf '  "step": %s,\n'       "$(json_str "$AH_STEP")"
    printf '  "required": %s,\n'   "$(json_str "$AH_REQUIRED")"
    printf '  "head": %s,\n'       "$(json_str "$(git rev-parse HEAD 2>/dev/null)")"
    printf '  "tree_hash": %s,\n'  "$(json_str "$(bash "$ROOT/scripts/dev/tree-hash.sh" 2>/dev/null)")"
    printf '  "started": %s,\n'    "$(json_str "$STARTED")"
    printf '  "finished": %s,\n'   "$(json_str "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
    printf '  "passed": %s,\n'     "$PASS"
    printf '  "failed": %s,\n'     "$FAIL"
    printf '  "skipped": %s,\n'    "$SKIP"
    printf '  "reruns": %s,\n'     "$RERUNS"
    printf '  "steps": ['
    for e in ${STEP_RESULTS+"${STEP_RESULTS[@]}"}; do
      name="${e%%|*}"; result="${e#*|}"; secs="${result#*|}"; result="${result%%|*}"
      [ "$first" = 1 ] && { first=0; printf '\n'; } || printf ',\n'
      printf '    {"name": %s, "result": %s, "seconds": %s}' \
        "$(json_str "$name")" "$(json_str "$result")" "$secs"
    done
    [ "$first" = 1 ] || printf '\n  '
    printf '],\n'
    printf '  "test_skips": %s\n' "$(json_list ${TEST_SKIPS+"${TEST_SKIPS[@]}"})"
    printf '}\n'
  } > "$f" || { echo "  artifact: could not write $f" >&2; return 0; }
  echo "  artifact: $f"
}

have()        { command -v "$1" >/dev/null 2>&1; }
only() {  # only <key…> -> 0 if AH_ONLY is unset or names any of the given keys
  [ -n "${AH_ONLY:-}" ] || return 0
  local k; for k in "$@"; do case " $AH_ONLY " in *" $k "*) return 0 ;; esac; done
  return 1
}
have_docker() { have docker && docker info >/dev/null 2>&1; }
have_compose(){ docker compose version >/dev/null 2>&1; }
have_node()   { have node && have npm; }
have_display(){ have xvfb-run && have WebKitWebDriver && have tauri-driver; }
FRPC_SIDECAR="apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu"

# npm ci wipes node_modules every run, defeating warm-box node_modules survival
# (crabbox_iter excludes it from the delete-sync). Install only when the lockfile is
# newer or node_modules is missing — deterministic when it matters, fast otherwise (5.26).
npm_ci_if_stale() {
  if [ ! -d node_modules ] || [ package-lock.json -nt node_modules ]; then npm ci --no-audit --no-fund; fi
}
export -f npm_ci_if_stale  # the run_step `bash -c` subshells need it in their env

require_real() {
  if [ "${AH_ALLOW_REAL:-0}" != "1" ]; then
    echo "REFUSED: layer '$LAYER' runs real docker/GUI suites. Set AH_ALLOW_REAL=1 to proceed"
    echo "         (the crabbox /test skill sets it automatically on the leased box)."
    exit 2
  fi
}

# ── lint ─────────────────────────────────────────────────────────────────────
layer_lint() {
  ONLY_APPLIES=1
  # ruff usually lives in a component venv, not on PATH — `have ruff` alone made
  # the whole Python lint gate SKIP while the summary still read "N passed",
  # which reads as "ok" and is exactly what CLAUDE.md warns SKIP does not mean.
  # Fall back to the venvs before giving up. ca-issuer is linted too: CLAUDE.md
  # names all THREE Python components, the step only ever covered two.
  local ruff_bin=""
  if have ruff; then ruff_bin="ruff"
  else
    local c
    for c in apps/server apps/monitoring apps/ca-issuer; do
      if [ -x "$c/.venv/bin/ruff" ]; then ruff_bin="$ROOT/$c/.venv/bin/ruff"; break; fi
    done
  fi
  if ! only server monitoring ca-issuer; then
    skip ruff "ruff check" "AH_ONLY"; skip ruff "ruff format check" "AH_ONLY"
  elif [ -n "$ruff_bin" ]; then
    run_step ruff "ruff check"        -- "$ruff_bin" check apps/server apps/monitoring apps/ca-issuer
    run_step ruff "ruff format check" -- "$ruff_bin" format --check apps/server apps/monitoring apps/ca-issuer
  else
    skip ruff "ruff check" "ruff not installed (not on PATH, no component venv)"
    skip ruff "ruff format check" "ruff not installed (not on PATH, no component venv)"
  fi

  if ! only agent; then skip gofmt "gofmt (agent)" "AH_ONLY"
  elif have gofmt; then
    run_step gofmt "gofmt (agent)" -- bash -c 'u=$(cd apps/agent && gofmt -l .); [ -z "$u" ] || { echo "unformatted:"; echo "$u"; exit 1; }'
  else skip gofmt "gofmt (agent)" "go not installed"; fi

  if ! only scripts; then skip shellcheck "shellcheck (ops scripts)" "AH_ONLY"
  elif have shellcheck; then
    run_step shellcheck "shellcheck (ops scripts)" -- shellcheck --severity=warning scripts/*.sh scripts/tests/*.sh scripts/dev/*.sh
  else skip shellcheck "shellcheck (ops scripts)" "shellcheck not installed"; fi
}

# ── unit ─────────────────────────────────────────────────────────────────────
layer_unit() {
  ONLY_APPLIES=1
  # All python suites share one venv so pip never mutates system site-packages (6.140).
  # Skip the setup entirely when --step cannot reach a python step: creating a venv
  # for `--step shellcheck` is a side effect nobody asked for.
  [ "$STEP_PROBE" = "1" ] || ! py_step_possible || ensure_venv || true
  # Monitoring pytest — bulk is pure logic; the migrations-smoke self-skips w/o DATABASE_URL.
  if ! only monitoring; then skip monitoring-pytest "monitoring pytest" "AH_ONLY"
  elif have python3; then
    run_py_step monitoring-pytest "monitoring pytest" -- bash -c 'cd apps/monitoring && python3 -m pip install -q -r requirements.in pytest pytest-cov && python3 -m pytest -q $AH_PYTEST_RS $AH_ARGS'
  else skip monitoring-pytest "monitoring pytest" "python3 not installed"; fi

  # ca-issuer pytest — pure PKI logic. NOT covered by CI today (closes a gap).
  if ! only ca-issuer; then skip ca-issuer-pytest "ca-issuer pytest" "AH_ONLY"
  elif have python3 && [ -d apps/ca-issuer/tests ]; then
    run_py_step ca-issuer-pytest "ca-issuer pytest" -- bash -c 'cd apps/ca-issuer && { python3 -m pip install -q -r requirements.in pytest 2>/dev/null || python3 -m pip install -q pytest cryptography; }; python3 -m pytest -q $AH_PYTEST_RS $AH_ARGS'
  else skip ca-issuer-pytest "ca-issuer pytest" "python3 missing or no tests"; fi

  # Server pytest — needs a Postgres: testcontainers (docker) or an injected
  # DATABASE_URL. AH_TEST_DB (from .devenv.sh) IS that injection on the dev box;
  # without the fallback the step skipped there silently, every single run.
  if ! only server; then skip server-pytest "server pytest" "AH_ONLY"
  elif have python3 && { [ -n "${DATABASE_URL:-${AH_TEST_DB:-}}" ] || have_docker; }; then
    run_py_step server-pytest "server pytest" -- bash -c 'cd apps/server && export DATABASE_URL="${DATABASE_URL:-${AH_TEST_DB:-}}" && python3 -m pip install -q -r requirements-dev.txt && python3 -m pytest -q $AH_PYTEST_RS $AH_ARGS'
  else skip server-pytest "server pytest" "needs docker (testcontainers) or DATABASE_URL"; fi

  # Go agent — fmt + vet + test + cross-compile (matches CI).
  if ! only agent; then skip go-agent "go agent (vet+test+cross)" "AH_ONLY"
  elif have go; then
    run_step go-agent "go agent (vet+test+cross)" -- bash -c '
      cd apps/agent &&
      go vet ./... &&
      go test -cover ./... $AH_ARGS &&
      GOOS=linux   GOARCH=amd64 go build -o /dev/null ./cmd/adminhelper-agent &&
      GOOS=windows GOARCH=amd64 go build -o /dev/null ./cmd/adminhelper-agent'
  else skip go-agent "go agent (vet+test+cross)" "go not installed"; fi

  # Rust/Tauri backend — needs tauri system libs + the frpc sidecar (externalBin).
  if ! only desktop desktop-rs; then skip desktop-cargo "cargo test (desktop)" "AH_ONLY"
  elif have cargo && [ -f "$FRPC_SIDECAR" ]; then
    run_step desktop-cargo "cargo test (desktop)" -- bash -c 'cd apps/desktop/src-tauri && cargo fmt --check && cargo clippy -- -D warnings && cargo test $AH_ARGS'
  else skip desktop-cargo "cargo test (desktop)" "cargo or frpc sidecar ($FRPC_SIDECAR) missing"; fi

  # Desktop UI (Svelte) — check + lint + vitest.
  if ! only desktop desktop-ui; then skip desktop-ui-vitest "desktop-ui vitest" "AH_ONLY"
  elif have_node; then
    run_step desktop-ui-vitest "desktop-ui vitest" -- bash -c 'cd apps/desktop/ui && npm_ci_if_stale && npm run check && npm run lint && npm run test ${AH_ARGS:+-- $AH_ARGS}'
  else skip desktop-ui-vitest "desktop-ui vitest" "node/npm not installed"; fi

  # Desktop E2E specs — lint only. The suite itself needs a display + Docker (heavy
  # tier), but linting the ~600 lines of wdio JS is cheap and catches spec bugs
  # before a costly build (2.89).
  if ! only desktop desktop-e2e; then skip desktop-e2e-lint "desktop-e2e lint" "AH_ONLY"
  elif have_node; then
    run_step desktop-e2e-lint "desktop-e2e lint" -- bash -c 'cd apps/desktop/e2e && npm_ci_if_stale && npm run lint'
  else skip desktop-e2e-lint "desktop-e2e lint" "node/npm not installed"; fi

  # Web frontend — check + lint + vitest unit.
  if ! only web; then skip web-vitest "web vitest" "AH_ONLY"
  elif have_node; then
    run_step web-vitest "web vitest" -- bash -c 'cd apps/web && npm_ci_if_stale && npm run check && npm run lint && npm run test:unit ${AH_ARGS:+-- $AH_ARGS}'
  else skip web-vitest "web vitest" "node/npm not installed"; fi
}

# ── integration (docker) ──────────────────────────────────────────────────────
layer_integration() {
  ONLY_APPLIES=0
  require_real
  if ! have_docker || ! have_compose; then
    skip integration "integration suite" "docker + compose v2 required"; return
  fi
  run_step integration-stack "integration_stack (mTLS gateway)" -- bash scripts/tests/integration_stack_test.sh
  run_step backup-restore "backup_restore (crown-jewel DR)"  -- bash scripts/tests/backup_restore_test.sh
  run_step sse-push "sse_push_e2e (Redis fan-out)"     -- bash scripts/tests/sse_push_e2e.sh
  run_step agent-monitoring "agent_monitoring (push pipeline)" -- bash scripts/tests/agent_monitoring_test.sh
  run_step repo-build "repo_build (apt/rpm + sign)"      -- bash scripts/tests/repo_build_test.sh
  # Hermetic (no docker) but cheap and valuable to keep green here too.
  run_step update-test "update.sh sandbox"                -- bash scripts/tests/update_test.sh
  run_step agent-install-test "agent-install.sh sandbox"         -- bash scripts/tests/agent_install_test.sh
  run_step diagnostics-test "diagnostics.sh redaction"         -- bash scripts/tests/diagnostics_test.sh
}

# ── e2e (docker + display) ─────────────────────────────────────────────────────
layer_e2e() {
  ONLY_APPLIES=0
  require_real
  if have_node; then
    run_step web-playwright "web Playwright E2E" -- bash -c 'cd apps/web && npm_ci_if_stale && npx playwright install --with-deps chromium && npx playwright test'
  else skip web-playwright "web Playwright E2E" "node not installed"; fi

  # Smoke first (cheapest, no backend): tauri-driver->WebKitWebDriver->window+mount.
  # Needs only a display; `npm test` matches the *.e2e.js glob (smoke), not the
  # *.live.js wrappers. Fastest fault localization when all live specs go red (6.141).
  if have_node && have_display; then
    run_step desktop-e2e-smoke "desktop-e2e smoke" -- bash -c 'cd apps/desktop/e2e && npm_ci_if_stale && npm test'
  else skip desktop-e2e-smoke "desktop-e2e smoke" "node + display required"; fi

  if ! have_docker || ! have_display; then
    skip desktop-e2e-gui "desktop GUI E2E" "docker + xvfb + WebKitWebDriver + tauri-driver required"; return
  fi
  local s
  for s in desktop_e2e_live desktop_e2e_crud desktop_e2e_connect desktop_e2e_connect_tunnel \
           desktop_e2e_tunnel desktop_e2e_monitoring desktop_e2e_sse_push; do
    run_step "$s" "$s" -- bash "scripts/tests/$s.sh"
  done
}

# Validate AH_ONLY tokens HARD before anything runs: an unknown key (typo, comma
# separator) would otherwise SKIP every step and still exit 0 — a false green in
# the autonomous chain ("SKIP heißt nicht verifiziert", CLAUDE.md).
# INVARIANT: no key here may ever equal a layer name (lint unit quick integration
# e2e all). --only eats every following non-flag word, so a key named `e2e` would
# make `run.sh --only web e2e` swallow the layer instead of rejecting it.
AH_KEYS="server monitoring ca-issuer agent desktop desktop-rs desktop-ui desktop-e2e web scripts"
if [ -n "${AH_ONLY:-}" ]; then
  # Charset first: the key loop tokenizes on IFS (tab/newline too), but only()
  # matches spaces only — a tab-separated list would pass the key check and then
  # skip everything (false green). Space is the ONLY allowed separator.
  case "$AH_ONLY" in *[!a-z0-9\ -]*)
    echo "invalid AH_ONLY (lowercase keys, SPACE-separated): '$AH_ONLY'"; exit 2 ;;
  esac
  for k in $AH_ONLY; do
    case " $AH_KEYS " in *" $k "*) ;; *)
      echo "unknown AH_ONLY key: '$k' — known (space-separated): $AH_KEYS"; exit 2 ;;
    esac
  done
fi

STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "AdminHelper test aggregator — layer=$LAYER  root=$ROOT"
echo "docker=$(have_docker && echo yes || echo no) node=$(have_node && echo yes || echo no) go=$(have go && echo yes || echo no) cargo=$(have cargo && echo yes || echo no) display=$(have_display && echo yes || echo no)"

run_layer() {
  case "$LAYER" in
    lint)        layer_lint ;;
    unit)        layer_unit ;;
    quick)       layer_lint; layer_unit ;;
    integration) layer_integration ;;
    e2e)         layer_e2e ;;
    all)         require_real; layer_lint; layer_unit; layer_integration; layer_e2e ;;
    *) echo "unknown layer: $LAYER (use lint|unit|quick|integration|e2e|all)"; exit 2 ;;
  esac
}

# --step: a dry pass first, so a typo or an ambiguous substring is rejected
# BEFORE a suite has run — otherwise "--step test" would quietly run five of them.
if [ -n "$AH_STEP" ]; then
  STEP_PROBE=1; run_layer; STEP_PROBE=0
  case "${#STEP_NAMES[@]}" in
    0) echo "unknown step: '$AH_STEP' (no step of layer '$LAYER' matches — note that"
       echo "  steps behind an unmet precondition, e.g. a missing docker, are not reached)"
       exit 2 ;;
    1) ;;
    *) echo "ambiguous step: '$AH_STEP' matches ${#STEP_NAMES[@]} steps:"
       printf '  %s\n' "${STEP_NAMES[@]}"; exit 2 ;;
  esac
  PASS=0 FAIL=0 SKIP=0; FAILED_STEPS=(); STRICT_FAILED=()
fi

run_layer

# On failure, collect on-box debug artifacts (container/agent logs, framebuffer
# screenshot) so a crabbox_iter run leaves them locally without a re-run. Opt-in.
if [ "$FAIL" -gt 0 ] && [ "${AH_CAPTURE:-0}" = 1 ]; then
  bash "$ROOT/scripts/tests/crabbox_debug.sh" 2>/dev/null || true
  echo "  auto-debug captured -> $AH_OUT_DIR"
fi

echo ""
echo "──────────────────────────────────────────────"
# The same lie one level up: no step failed, so a run in which NOTHING executed
# would report green. Under --strict that is a failure — an empty run verifies
# nothing, whatever narrowed it (a typo in --only, an over-trimmed AH_REQUIRED,
# a box without the toolchain).
if [ "$AH_STRICT" = "1" ] && [ "$PASS" -eq 0 ] && [ "$FAIL" -eq 0 ]; then
  echo "  strict-failed: no step ran (layer=$LAYER, only=${AH_ONLY:-none}, step=${AH_STEP:-none})"
  STRICT_FAILED+=("no step ran"); FAIL=$((FAIL+1)); FAILED_STEPS+=("no step ran")
fi

echo "  run.sh[$LAYER]: $PASS passed, $FAIL failed, $SKIP skipped, ${#TEST_SKIPS[@]} test-skips, $RERUNS reruns"
# Under --strict the required set decides what a SKIP costs, so print it: a run
# narrowed to nothing by an over-trimmed AH_REQUIRED must be visible, not implied.
[ "$AH_STRICT" = "1" ] && echo "  required (strict): $AH_REQUIRED"
[ "${#STRICT_FAILED[@]}" -gt 0 ] && printf '  strict-failed: %s\n' "${STRICT_FAILED[*]}"
write_artifact
[ "$FAIL" -gt 0 ] && { printf '  failed: %s\n' "${FAILED_STEPS[*]}"; exit 1; }
exit 0
