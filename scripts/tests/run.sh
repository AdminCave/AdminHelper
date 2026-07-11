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
#   bash scripts/tests/run.sh [lint|unit|quick|integration|e2e|all]
#     lint         ruff + gofmt + shellcheck            (fast, no stack)
#     unit         all language unit suites             (no docker/display needed;
#                                                         server pytest needs docker/DATABASE_URL)
#     quick        lint + unit                          (default)
#     integration  docker-backed integration/e2e-stack  (needs docker; opt-in)
#     e2e          desktop GUI + web Playwright          (needs docker + display; opt-in)
#     all          everything                            (opt-in)
#
# The heavy layers (integration|e2e|all) refuse to run unless AH_ALLOW_REAL=1,
# so they never fire by accident on a dev box. The crabbox /test skill sets it.
#
# Exit code: non-zero if any step FAILED (SKIPs never fail the run).

set -uo pipefail

LAYER="${1:-quick}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1

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
FAILED_STEPS=()
hdr()  { printf '\n\033[1m### %s\033[0m\n' "$*"; }
pass() { echo   "  PASS  $*"; PASS=$((PASS+1)); }
fail() { echo   "  FAIL  $*"; FAIL=$((FAIL+1)); FAILED_STEPS+=("$1"); }
skip() { echo   "  SKIP  $* ($2)"; SKIP=$((SKIP+1)); }

# run_step <name> -- <command...>   : run, classify by exit code. Exit 75
# (EX_TEMPFAIL) is the self-SKIP sentinel: a suite that can't run (no venv, no go,
# e2e_require unmet) exits 75 so it's reported SKIP, not PASS — a bare exit 0 would
# silently become a green PASS though nothing ran, and the summary line is the
# authoritative result ("SKIP heisst nicht verifiziert") (6.9).
run_step() { local name="$1"; shift; [ "$1" = "--" ] && shift
  hdr "$name"; local rc=0; ( "$@" ) || rc=$?
  case "$rc" in
    0)  pass "$name" ;;
    75) skip "$name" "self-skipped" ;;
    *)  fail "$name" ;;
  esac
}

have()        { command -v "$1" >/dev/null 2>&1; }
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
  if have ruff; then
    run_step "ruff check"        -- ruff check apps/server apps/monitoring
    run_step "ruff format check" -- ruff format --check apps/server apps/monitoring
  else skip "ruff" "ruff not installed"; fi

  if have gofmt; then
    run_step "gofmt (agent)" -- bash -c 'u=$(cd apps/agent && gofmt -l .); [ -z "$u" ] || { echo "unformatted:"; echo "$u"; exit 1; }'
  else skip "gofmt" "go not installed"; fi

  if have shellcheck; then
    run_step "shellcheck (ops scripts)" -- shellcheck --severity=warning scripts/*.sh scripts/tests/*.sh
  else skip "shellcheck" "shellcheck not installed"; fi
}

# ── unit ─────────────────────────────────────────────────────────────────────
layer_unit() {
  # All python suites share one venv so pip never mutates system site-packages (6.140).
  ensure_venv || true
  # Monitoring pytest — bulk is pure logic; the migrations-smoke self-skips w/o DATABASE_URL.
  if have python3; then
    run_step "monitoring pytest" -- bash -c 'cd apps/monitoring && python3 -m pip install -q -r requirements.in pytest pytest-cov && python3 -m pytest -q'
  else skip "monitoring pytest" "python3 not installed"; fi

  # ca-issuer pytest — pure PKI logic. NOT covered by CI today (closes a gap).
  if have python3 && [ -d apps/ca-issuer/tests ]; then
    run_step "ca-issuer pytest" -- bash -c 'cd apps/ca-issuer && { python3 -m pip install -q -r requirements.in pytest 2>/dev/null || python3 -m pip install -q pytest cryptography; }; python3 -m pytest -q'
  else skip "ca-issuer pytest" "python3 missing or no tests"; fi

  # Server pytest — needs a Postgres: testcontainers (docker) or an injected DATABASE_URL.
  if have python3 && { [ -n "${DATABASE_URL:-}" ] || have_docker; }; then
    run_step "server pytest" -- bash -c 'cd apps/server && python3 -m pip install -q -r requirements-dev.txt && python3 -m pytest -q'
  else skip "server pytest" "needs docker (testcontainers) or DATABASE_URL"; fi

  # Go agent — fmt + vet + test + cross-compile (matches CI).
  if have go; then
    run_step "go agent (vet+test+cross)" -- bash -c '
      cd apps/agent &&
      go vet ./... &&
      go test -cover ./... &&
      GOOS=linux   GOARCH=amd64 go build -o /dev/null ./cmd/adminhelper-agent &&
      GOOS=windows GOARCH=amd64 go build -o /dev/null ./cmd/adminhelper-agent'
  else skip "go agent" "go not installed"; fi

  # Rust/Tauri backend — needs tauri system libs + the frpc sidecar (externalBin).
  if have cargo && [ -f "$FRPC_SIDECAR" ]; then
    run_step "cargo test (desktop)" -- bash -c 'cd apps/desktop/src-tauri && cargo fmt --check && cargo clippy -- -D warnings && cargo test'
  else skip "cargo test (desktop)" "cargo or frpc sidecar ($FRPC_SIDECAR) missing"; fi

  # Desktop UI (Svelte) — check + lint + vitest.
  if have_node; then
    run_step "desktop-ui vitest" -- bash -c 'cd apps/desktop/ui && npm_ci_if_stale && npm run check && npm run lint && npm run test'
  else skip "desktop-ui vitest" "node/npm not installed"; fi

  # Desktop E2E specs — lint only. The suite itself needs a display + Docker (heavy
  # tier), but linting the ~600 lines of wdio JS is cheap and catches spec bugs
  # before a costly build (2.89).
  if have_node; then
    run_step "desktop-e2e lint" -- bash -c 'cd apps/desktop/e2e && npm_ci_if_stale && npm run lint'
  else skip "desktop-e2e lint" "node/npm not installed"; fi

  # Web frontend — check + lint + vitest unit.
  if have_node; then
    run_step "web vitest" -- bash -c 'cd apps/web && npm_ci_if_stale && npm run check && npm run lint && npm run test:unit'
  else skip "web vitest" "node/npm not installed"; fi
}

# ── integration (docker) ──────────────────────────────────────────────────────
layer_integration() {
  require_real
  if ! have_docker || ! have_compose; then
    skip "integration suite" "docker + compose v2 required"; return
  fi
  run_step "integration_stack (mTLS gateway)" -- bash scripts/tests/integration_stack_test.sh
  run_step "backup_restore (crown-jewel DR)"  -- bash scripts/tests/backup_restore_test.sh
  run_step "sse_push_e2e (Redis fan-out)"     -- bash scripts/tests/sse_push_e2e.sh
  run_step "agent_monitoring (push pipeline)" -- bash scripts/tests/agent_monitoring_test.sh
  run_step "repo_build (apt/rpm + sign)"      -- bash scripts/tests/repo_build_test.sh
  # Hermetic (no docker) but cheap and valuable to keep green here too.
  run_step "update.sh sandbox"                -- bash scripts/tests/update_test.sh
  run_step "diagnostics.sh redaction"         -- bash scripts/tests/diagnostics_test.sh
}

# ── e2e (docker + display) ─────────────────────────────────────────────────────
layer_e2e() {
  require_real
  if have_node; then
    run_step "web Playwright E2E" -- bash -c 'cd apps/web && npm_ci_if_stale && npx playwright install --with-deps chromium && npx playwright test'
  else skip "web Playwright" "node not installed"; fi

  # Smoke first (cheapest, no backend): tauri-driver->WebKitWebDriver->window+mount.
  # Needs only a display; `npm test` matches the *.e2e.js glob (smoke), not the
  # *.live.js wrappers. Fastest fault localization when all live specs go red (6.141).
  if have_node && have_display; then
    run_step "desktop-e2e smoke" -- bash -c 'cd apps/desktop/e2e && npm_ci_if_stale && npm test'
  else skip "desktop-e2e smoke" "node + display required"; fi

  if ! have_docker || ! have_display; then
    skip "desktop GUI E2E" "docker + xvfb + WebKitWebDriver + tauri-driver required"; return
  fi
  local s
  for s in desktop_e2e_live desktop_e2e_crud desktop_e2e_connect desktop_e2e_connect_tunnel \
           desktop_e2e_tunnel desktop_e2e_monitoring desktop_e2e_sse_push; do
    run_step "$s" -- bash "scripts/tests/$s.sh"
  done
}

echo "AdminHelper test aggregator — layer=$LAYER  root=$ROOT"
echo "docker=$(have_docker && echo yes || echo no) node=$(have_node && echo yes || echo no) go=$(have go && echo yes || echo no) cargo=$(have cargo && echo yes || echo no) display=$(have_display && echo yes || echo no)"

case "$LAYER" in
  lint)        layer_lint ;;
  unit)        layer_unit ;;
  quick)       layer_lint; layer_unit ;;
  integration) layer_integration ;;
  e2e)         layer_e2e ;;
  all)         require_real; layer_lint; layer_unit; layer_integration; layer_e2e ;;
  *) echo "unknown layer: $LAYER (use lint|unit|quick|integration|e2e|all)"; exit 2 ;;
esac

# On failure, collect on-box debug artifacts (container/agent logs, framebuffer
# screenshot) so a crabbox_iter run leaves them locally without a re-run. Opt-in.
if [ "$FAIL" -gt 0 ] && [ "${AH_CAPTURE:-0}" = 1 ]; then
  bash "$ROOT/scripts/tests/crabbox_debug.sh" 2>/dev/null || true
  echo "  auto-debug captured -> $AH_OUT_DIR"
fi

echo ""
echo "──────────────────────────────────────────────"
echo "  run.sh[$LAYER]: $PASS passed, $FAIL failed, $SKIP skipped"
[ "$FAIL" -gt 0 ] && { printf '  failed: %s\n' "${FAILED_STEPS[*]}"; exit 1; }
exit 0
