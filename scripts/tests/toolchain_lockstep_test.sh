#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# toolchain_lockstep_test.sh — hermetic test for scripts/dev/toolchain-lockstep.sh.
#
# Fixture workflows under --root, a fake `curl` in front of PATH: no network, no
# toolchain, bash + coreutils. The check is a CI gate whose whole value is being
# red for the right reason, so every case asserts the exit code AND the wording
# that names the drift — "it exited 1" would also hold if it failed on a typo.
#
# Run: bash scripts/tests/toolchain_lockstep_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CHECK="$HERE/../dev/toolchain-lockstep.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# A fake curl that answers from the environment instead of the network:
#   FAKE_MOD  what the proxy returns   FAKE_RC  curl's exit code (0 / 22 / 6)
FAKE="$WORK/fakebin"; mkdir -p "$FAKE"
cat > "$FAKE/curl" <<'EOF'
#!/usr/bin/env bash
# Record the whole invocation so a case can assert WHICH url was fetched — the
# fake answers regardless, so a typo in the proxy path would pass every other
# case in this file.
printf '%s\n' "$*" >> "$FAKE_LOG"
[ "${FAKE_RC:-0}" = 0 ] || { echo "curl: (${FAKE_RC}) fake failure" >&2; exit "$FAKE_RC"; }
printf '%s\n' "$FAKE_MOD"
EOF
chmod +x "$FAKE/curl"
FAKE_LOG="$WORK/curl.log"; : > "$FAKE_LOG"; export FAKE_LOG
export PATH="$FAKE:$PATH"

# fixture <dir> <go-version-ci> <go-version-release> <go-version-audit> <pin>
#         [<ruff-ci> <ruff-bootstrap> <ruff-dev>]
# ci.yml carries go-version TWICE, like the real one (agent + agent-windows) —
# the single-file drift a per-file check would miss. The ruff pins default to
# agreeing ones, so the go cases below see a tree that is in lockstep there.
fixture() {
  local d="$1" ci="$2" rel="$3" aud="$4" pin="$5"
  local ruff_ci="${6:-0.15.20}" ruff_boot="${7:-0.15.20}" ruff_dev="${8:-0.15.20}"
  mkdir -p "$d/.github/workflows" "$d/scripts/vm" "$d/apps/server"
  printf 'name: CI\njobs:\n  python-lint:\n    steps:\n      - name: Install ruff\n        run: pip install ruff==%s\n  agent:\n    steps:\n      - uses: actions/setup-go@v6\n        with:\n          go-version: "%s"\n  agent-windows:\n    steps:\n      - uses: actions/setup-go@v6\n        with:\n          go-version: "%s"\n' \
    "$ruff_ci" "$ci" "$ci" > "$d/.github/workflows/ci.yml"
  printf '#!/usr/bin/env bash\nTAURI_CLI_VERSION="${AH_TAURI_CLI_VERSION:-2.11.2}"\nRUFF_VERSION="${AH_RUFF_VERSION:-%s}"\n' \
    "$ruff_boot" > "$d/scripts/vm/bootstrap_linux.sh"
  printf -- '-r requirements.in\n\npytest>=9.0.3\nruff==%s\n' "$ruff_dev" > "$d/apps/server/requirements-dev.txt"
  printf 'name: Release\njobs:\n  agent:\n    steps:\n      - uses: actions/setup-go@v6\n        with:\n          go-version: "%s"\n' \
    "$rel" > "$d/.github/workflows/release.yml"
  printf 'name: Dependency Audit\njobs:\n  go:\n    steps:\n      - uses: actions/setup-go@v6\n        with:\n          go-version: "%s"\n      - name: Install govulncheck\n        run: go install golang.org/x/vuln/cmd/govulncheck@%s\n' \
    "$aud" "$pin" > "$d/.github/workflows/audit.yml"
}

MOD_125='module golang.org/x/vuln

go 1.25.0

require golang.org/x/mod v0.39.0
'
MOD_126='module golang.org/x/vuln

go 1.26.0

require golang.org/x/mod v0.41.0
'

# run_case <name> <expect-rc> <expect-substring> -- <args...>
# FAKE_MOD/FAKE_RC come from the caller's environment.
run_case() {
  local name="$1" want_rc="$2" want="$3"; shift 3; [ "$1" = "--" ] && shift
  local out rc=0
  out=$(bash "$CHECK" "$@" 2>&1) || rc=$?
  if [ "$rc" != "$want_rc" ]; then
    bad "$name: rc=$rc (expected $want_rc)"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  # -- before the pattern: a few expectations start with a dash ("--root needs
  # a directory"), and grep would read those as its own flags.
  if [ -n "$want" ] && ! printf '%s' "$out" | grep -qF -- "$want"; then
    bad "$name: output does not mention '$want'"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  ok "$name"
}

# ── 1: in lockstep ───────────────────────────────────────────────────────────
GOOD="$WORK/good"; fixture "$GOOD" 1.25 1.25 1.25 v1.7.0
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "go 1.25.0 pin on go-version 1.25 -> exit 0" 0 "ok (go 1.25 <= 1.25)" -- --root "$GOOD"
# The directive may also be BELOW the workflows' Go — still fine, and the case
# that proves the comparison is <=, not =.
FAKE_MOD='module golang.org/x/vuln

go 1.24.0
' FAKE_RC=0 run_case "an older directive is fine too" 0 "ok (go 1.24 <= 1.25)" -- --root "$GOOD"

# ── 2: go-version drift between the workflows ────────────────────────────────
DRIFT="$WORK/drift"; fixture "$DRIFT" 1.26 1.25 1.25 v1.7.0
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "release.yml left behind -> exit 1" 1 "go-version drift" -- --root "$DRIFT"
# Only the SECOND go-version in ci.yml bumped: the drift a one-grep-per-file
# check reports as green.
HALF="$WORK/half"; fixture "$HALF" 1.25 1.25 1.25 v1.7.0
sed -i '0,/go-version: "1.25"/! s/go-version: "1.25"/go-version: "1.26"/' "$HALF/.github/workflows/ci.yml"
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "one of ci.yml's two jobs bumped -> exit 1" 1 "go-version drift" -- --root "$HALF"

# ── 3: the pin outruns the toolchain (the real v1.8.0 case) ──────────────────
FAKE_MOD="$MOD_126" FAKE_RC=0 run_case "pin declares go 1.26 on go-version 1.25 -> exit 1" 1 "needs Go 1.26" -- --root "$GOOD"
FAKE_MOD="$MOD_126" FAKE_RC=0 run_case "  …and says so as a CI annotation" 1 "::error::" -- --root "$GOOD"

# ── 4: the proxy is unreachable -> SKIP, never a green ───────────────────────
FAKE_MOD="" FAKE_RC=6 run_case "no network -> exit 75, nothing asserted" 75 "the pin was NOT checked" -- --root "$GOOD"
# An HTTP error is the proxy ANSWERING that the version does not exist — a
# finding about the pin, not about the network, so it must not become a SKIP.
FAKE_MOD="" FAKE_RC=22 run_case "proxy has no such version -> exit 1, not 75" 1 "has no golang.org/x/vuln@v1.7.0" -- --root "$GOOD"

# ── 5: a pin that isn't one ──────────────────────────────────────────────────
LATEST="$WORK/latest"; fixture "$LATEST" 1.25 1.25 1.25 latest
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "@latest instead of a version -> exit 1" 1 "unpinned @latest" -- --root "$LATEST"
NODIR="$WORK/nodirective"; fixture "$NODIR" 1.25 1.25 1.25 v1.7.0
FAKE_MOD='module golang.org/x/vuln

require golang.org/x/mod v0.39.0
' FAKE_RC=0 run_case ".mod without a go directive -> exit 1" 1 "no 'go' directive" -- --root "$NODIR"

# ── 5b: what the check actually asks the proxy ───────────────────────────────
# Every case above is green no matter which URL the script builds. This one
# pins the URL and the timeout, so a wrong module path or a dropped --max-time
# is a failure here instead of a hang in CI.
: > "$FAKE_LOG"
FAKE_MOD="$MOD_125" FAKE_RC=0 bash "$CHECK" --root "$GOOD" >/dev/null 2>&1
if grep -qF -- 'https://proxy.golang.org/golang.org/x/vuln/@v/v1.7.0.mod' "$FAKE_LOG" \
   && grep -qF -- '--max-time 10' "$FAKE_LOG"; then
  ok "fetches the pinned .mod from the module proxy, with a timeout"
else
  bad "curl was called as: $(cat "$FAKE_LOG")"
fi

# ── 5c: a go-version this check cannot compare ───────────────────────────────
# setup-go accepts "1.25.x" and "^1.25"; this check does not, and must say so
# instead of answering "no go-version found" and sending the reader hunting.
# All three the same, so the drift check cannot mask the real message.
WILD="$WORK/wildcard"; fixture "$WILD" 1.25.x 1.25.x 1.25.x v1.7.0
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "go-version 1.25.x -> exit 1, named" 1 "cannot compare go-version '1.25.x'" -- --root "$WILD"
RANGE="$WORK/range"; fixture "$RANGE" '^1.25' '^1.25' '^1.25' v1.7.0
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "go-version ^1.25 -> exit 1, named" 1 "cannot compare go-version '^1.25'" -- --root "$RANGE"
# And the plain pin must still pass this gate — a validator that rejects
# everything would make every case above green for the wrong reason.
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "a plain 1.25 passes the validator" 0 "ok (go 1.25 <= 1.25)" -- --root "$GOOD"

# ── 5d: the ruff pins (CI, VM bootstrap, requirements-dev) ──────────────────
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "agreeing ruff pins are named in the output" 0 "ruff: ci.yml=0.15.20 bootstrap=0.15.20 dev=0.15.20" -- --root "$GOOD"
RDRIFT="$WORK/ruffdrift"; fixture "$RDRIFT" 1.25 1.25 1.25 v1.7.0 0.15.21 0.15.20 0.15.20
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "ci.yml ruff ahead of bootstrap -> exit 1" 1 "ruff pin drift: .github/workflows/ci.yml installs ruff==0.15.21, scripts/vm/bootstrap_linux.sh defaults to 0.15.20" -- --root "$RDRIFT"
# Offline: the drift is a finding even when the proxy is down, never a SKIP.
FAKE_MOD="" FAKE_RC=6 run_case "  …also with the proxy unreachable (1, not 75)" 1 "ruff pin drift" -- --root "$RDRIFT"
RBOOT="$WORK/ruffboot"; fixture "$RBOOT" 1.25 1.25 1.25 v1.7.0 0.15.20 0.16.0 0.15.20
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "bootstrap ruff bumped alone -> exit 1" 1 "ruff pin drift: .github/workflows/ci.yml installs ruff==0.15.20, scripts/vm/bootstrap_linux.sh defaults to 0.16.0" -- --root "$RBOOT"
RDEVHI="$WORK/ruffdevhi"; fixture "$RDEVHI" 1.25 1.25 1.25 v1.7.0 0.15.20 0.15.20 0.16.0
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "requirements-dev pins a newer ruff -> exit 1" 1 "ruff pin drift: apps/server/requirements-dev.txt pins ruff==0.16.0, scripts/vm/bootstrap_linux.sh defaults to 0.15.20" -- --root "$RDEVHI"
# Equality, not a floor: an older pin is the same drift. run.sh installs
# requirements-dev.txt into AH_VENV, and a floor there left a newer ruff in place.
RDEVLO="$WORK/ruffdevlo"; fixture "$RDEVLO" 1.25 1.25 1.25 v1.7.0 0.15.20 0.15.20 0.15.19
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "requirements-dev pins 0.15.19 under 0.15.20 -> exit 1" 1 "ruff pin drift: apps/server/requirements-dev.txt pins ruff==0.15.19, scripts/vm/bootstrap_linux.sh defaults to 0.15.20" -- --root "$RDEVLO"
RRANGE="$WORK/ruffrange"; fixture "$RRANGE" 1.25 1.25 1.25 v1.7.0
sed -i 's/^ruff==.*/ruff>=0.15/' "$RRANGE/apps/server/requirements-dev.txt"
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "requirements-dev with a ruff>= range -> exit 1" 1 "no pinned 'ruff==X.Y.Z' in apps/server/requirements-dev.txt" -- --root "$RRANGE"
RNOPIN="$WORK/ruffnopin"; fixture "$RNOPIN" 1.25 1.25 1.25 v1.7.0
sed -i 's/pip install ruff==0.15.20/pip install ruff/' "$RNOPIN/.github/workflows/ci.yml"
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "ci.yml installs an unpinned ruff -> exit 1" 1 "no pinned 'pip install ruff==X.Y.Z'" -- --root "$RNOPIN"
RNOBOOT="$WORK/ruffnoboot"; fixture "$RNOBOOT" 1.25 1.25 1.25 v1.7.0
sed -i '/^RUFF_VERSION=/d' "$RNOBOOT/scripts/vm/bootstrap_linux.sh"
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "bootstrap without a RUFF_VERSION default -> exit 1" 1 "no plain RUFF_VERSION" -- --root "$RNOBOOT"
RNODEV="$WORK/ruffnodev"; fixture "$RNODEV" 1.25 1.25 1.25 v1.7.0
sed -i 's/^ruff==.*/ruff/' "$RNODEV/apps/server/requirements-dev.txt"
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "requirements-dev without a ruff pin -> exit 1" 1 "no pinned 'ruff==X.Y.Z' in apps/server/requirements-dev.txt" -- --root "$RNODEV"
RNOREQ="$WORK/ruffnoreq"; fixture "$RNOREQ" 1.25 1.25 1.25 v1.7.0
rm -f "$RNOREQ/apps/server/requirements-dev.txt"
FAKE_MOD="$MOD_125" FAKE_RC=0 run_case "requirements-dev missing -> exit 1" 1 "missing apps/server/requirements-dev.txt" -- --root "$RNOREQ"
# The one case that reads the real tree instead of a fixture, with a proxy
# answer every Go satisfies: only the offline assertions decide (go-version,
# ruff), so a pin raised at one place is red here in run.sh quick, not first in CI.
REAL_ROOT="$(cd "$HERE/../.." && pwd)"
FAKE_MOD='module golang.org/x/vuln

go 1.0
' FAKE_RC=0 run_case "the repository's own pins pass the offline assertions" 0 "toolchain-lockstep: ok" -- --root "$REAL_ROOT"

# ── 6: argument handling ─────────────────────────────────────────────────────
run_case "unknown argument -> exit 2" 2 "unexpected argument" -- --root "$GOOD" --nope
run_case "--root without a value -> exit 2" 2 "--root needs a directory" -- --root
run_case "--root at a non-directory -> exit 2" 2 "no such root" -- --root "$WORK/does-not-exist"
EMPTY="$WORK/empty"; mkdir -p "$EMPTY/.github/workflows"
run_case "a tree without the workflows -> exit 1" 1 "missing workflow" -- --root "$EMPTY"

echo ""
echo "toolchain_lockstep_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
