#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# toolchain-lockstep.sh — assert the govulncheck pin still builds on our Go.
# Since R-0046 it also holds the ruff pins together.
#
#   bash scripts/dev/toolchain-lockstep.sh [--root <dir>]
#
# audit.yml installs govulncheck from source under GOTOOLCHAIN=local (setup-go's
# default), so the pin only builds while x/vuln's own `go` directive stays at or
# below the `go-version` the workflows set. That coupling broke once already:
# x/vuln v1.8.0 declares `go 1.26.0`, and `@latest` stopped compiling — a job
# that fails on its INSTALL step reports nothing about our dependencies while
# looking like an ordinary red run. The pin's comment says "raise this together
# with go-version"; this is that sentence as a check.
#
# Three assertions:
#   1  every `go-version:` in ci.yml, release.yml and audit.yml is the same
#      (the pin is chosen against one Go version — three different ones make
#      "the Go version" meaningless before the third assertion can mean
#      anything)
#   2  the ruff that ci.yml installs is the default of RUFF_VERSION in
#      scripts/vm/bootstrap_linux.sh, and the floor in
#      apps/server/requirements-dev.txt does not exceed it. The first bake of a
#      linux-server template ran an unpinned ruff and went red on rules the dev
#      box and CI never saw; the comments at all three places said "keep in
#      sync", and nothing checked it. Offline, so it runs before the proxy fetch
#      and a drift stays a drift when the proxy is down.
#   3  the `go` directive of the pinned x/vuln release is <= that go-version
#
# Exit: 0 in lockstep · 1 drift (with a ::error:: line for the CI annotation) ·
# 2 usage · 75 the module proxy was unreachable, nothing was asserted — run.sh's
# SKIP code, so a CI job stays honest about not having checked instead of going
# green on a fetch that never happened.
#
# --root <dir> points the check at another tree; the hermetic test
# (scripts/tests/toolchain_lockstep_test.sh) uses it with fixture workflows and
# a fake curl.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
while [ $# -gt 0 ]; do
  case "$1" in
    --root) shift; [ $# -gt 0 ] || { echo "--root needs a directory"; exit 2; }; ROOT="$1" ;;
    *) echo "unexpected argument: $1 (use --root <dir>)"; exit 2 ;;
  esac
  shift
done
[ -d "$ROOT" ] || { echo "no such root: $ROOT"; exit 2; }

WF="$ROOT/.github/workflows"
AUDIT="$WF/audit.yml"
# The module behind the `go install` line in audit.yml. Held as a constant
# rather than derived from the pin: the proxy path is the MODULE, and cutting
# `/cmd/govulncheck` off the install path guesses where the module ends.
VULN_MOD="golang.org/x/vuln"

# ── 1: one Go version across the three workflows ─────────────────────────────
# Every occurrence, not one per file: ci.yml sets go-version in two jobs, and a
# bump that updates only the first is exactly the drift this looks for.
versions=""
for f in ci release audit; do
  [ -f "$WF/$f.yml" ] || { echo "::error::missing workflow: .github/workflows/$f.yml"; exit 1; }
  while IFS= read -r v; do
    # Read the value VERBATIM and judge it here. A pattern that only matched
    # digits would answer a legitimate `go-version: "1.25.x"` (setup-go accepts
    # it) with "no go-version found" — red, but pointing at the wrong thing.
    # Exactly MAJOR.MINOR, digits only. `[0-9]*.[0-9]*` would let "1.25.x"
    # through — it matches, and the value then fails later as phantom "drift".
    case "$v" in
      *[!0-9.]* | *.*.* | *.) bad_version=1 ;;
      *.*) bad_version=0 ;;
      *) bad_version=1 ;;
    esac
    [ "$bad_version" = 0 ] || {
      echo "::error::cannot compare go-version '$v' in .github/workflows/$f.yml — this check needs a plain MAJOR.MINOR pin (today \"1.25\"), not a range, alias or .x wildcard"
      exit 1; }
    versions="$versions $f=$v"
  done < <(sed -n 's/^[[:space:]]*go-version:[[:space:]]*"\{0,1\}\([^"[:space:]]*\)"\{0,1\}[[:space:]]*$/\1/p' "$WF/$f.yml")
done
[ -n "$versions" ] || { echo "::error::no go-version: found in ci.yml/release.yml/audit.yml"; exit 1; }

GO_VERSION=""
for pair in $versions; do
  v="${pair#*=}"
  [ -n "$GO_VERSION" ] || GO_VERSION="$v"
  [ "$v" = "$GO_VERSION" ] || {
    echo "::error::go-version drift across the workflows:$versions — the govulncheck pin is chosen against one Go version, so all of them must agree"
    exit 1; }
done
echo "go-version:$versions"

# ── 2: one ruff across CI, the VM bootstrap and the dev floor ────────────────
# Plain dotted digits only: the floor is compared with sort -V, and a "0.15.*"
# or "~=0.15" would sort somewhere without meaning anything.
plain_version() { case "$1" in "" | *[!0-9.]* | .* | *. | *..*) return 1 ;; esac; }
BOOT="$ROOT/scripts/vm/bootstrap_linux.sh"
REQ="$ROOT/apps/server/requirements-dev.txt"
for f in "$BOOT" "$REQ"; do
  [ -f "$f" ] || { echo "::error::missing ${f#"$ROOT"/} — the ruff pin cannot be checked"; exit 1; }
done
RUFF_BOOT="$(sed -n 's/^RUFF_VERSION="\${AH_RUFF_VERSION:-\([^}]*\)}".*/\1/p' "$BOOT" | head -1)"
plain_version "$RUFF_BOOT" || {
  echo "::error::no plain RUFF_VERSION=\"\${AH_RUFF_VERSION:-X.Y.Z}\" default in scripts/vm/bootstrap_linux.sh (found '$RUFF_BOOT')"
  exit 1; }
# Every ruff pin in ci.yml, like every go-version above: a second install line
# that lags behind is the same drift.
ruff_ci=""
while IFS= read -r v; do
  [ "$v" = "$RUFF_BOOT" ] || {
    echo "::error::ruff pin drift: .github/workflows/ci.yml installs ruff==$v, scripts/vm/bootstrap_linux.sh defaults to $RUFF_BOOT — raise both together (and the floor in apps/server/requirements-dev.txt)"
    exit 1; }
  ruff_ci="$v"
done < <(sed -n 's/.*pip install ruff==\([^[:space:]"]*\).*/\1/p' "$WF/ci.yml")
[ -n "$ruff_ci" ] || {
  echo "::error::no pinned 'pip install ruff==X.Y.Z' in .github/workflows/ci.yml — an unpinned ruff is the drift this check exists to prevent"
  exit 1; }
RUFF_FLOOR="$(sed -n 's/^ruff>=\([^[:space:]#,;]*\).*/\1/p' "$REQ" | head -1)"
plain_version "$RUFF_FLOOR" || {
  echo "::error::no plain 'ruff>=X.Y' floor in apps/server/requirements-dev.txt (found '$RUFF_FLOOR')"
  exit 1; }
if [ "$(printf '%s\n%s\n' "$RUFF_FLOOR" "$RUFF_BOOT" | sort -V | tail -1)" != "$RUFF_BOOT" ]; then
  echo "::error::ruff floor $RUFF_FLOOR in apps/server/requirements-dev.txt is above the pinned ruff $RUFF_BOOT (ci.yml, bootstrap_linux.sh) — a dev install would pull a ruff the gates never ran"
  exit 1
fi
echo "ruff: ci.yml=$ruff_ci bootstrap=$RUFF_BOOT floor>=$RUFF_FLOOR"

# ── 3: the pinned x/vuln release must build on that Go ───────────────────────
PIN="$(sed -n "s|.*go install $VULN_MOD/cmd/govulncheck@\(v[0-9][0-9A-Za-z.-]*\).*|\1|p" "$AUDIT" | head -1)"
[ -n "$PIN" ] || {
  echo "::error::no pinned 'go install $VULN_MOD/cmd/govulncheck@vX.Y.Z' in .github/workflows/audit.yml — an unpinned @latest is the drift this check exists to prevent"
  exit 1; }
echo "govulncheck pin: $PIN"

MOD_URL="https://proxy.golang.org/$VULN_MOD/@v/$PIN.mod"
rc=0
# stderr stays on stderr: on a failure curl's own reason belongs in the job log,
# and merging it would otherwise end up parsed as the .mod on a partial success.
mod="$(curl -fsS --max-time 10 "$MOD_URL")" || rc=$?
if [ "$rc" = 22 ]; then
  # An HTTP error is the proxy answering: this version does not exist. That is a
  # finding about the pin, not about the network.
  echo "::error::the module proxy has no $VULN_MOD@$PIN ($MOD_URL) — check the pin in audit.yml"
  exit 1
elif [ "$rc" != 0 ]; then
  echo "  $MOD_URL: curl exit $rc"
  echo "toolchain-lockstep: SKIP — module proxy unreachable, the pin was NOT checked"
  exit 75
fi

DIRECTIVE="$(printf '%s\n' "$mod" | sed -n 's/^go[[:space:]]\{1,\}\([0-9][0-9.]*\).*/\1/p' | head -1)"
[ -n "$DIRECTIVE" ] || {
  echo "::error::no 'go' directive in $MOD_URL — cannot tell which toolchain $VULN_MOD@$PIN needs"
  exit 1; }

# Compare on major.minor only: the directive carries a patch (`go 1.25.0`) that
# setup-go's "1.25" does not, and 1.25.0 > 1.25 in a plain string sort.
mm() { printf '%s.%s' "$(printf '%s' "$1" | cut -d. -f1)" "$(printf '%s' "$1" | cut -d. -f2)"; }
need="$(mm "$DIRECTIVE")"; have="$(mm "$GO_VERSION")"
# 10#: bash reads a leading-zero minor as octal and dies on `09`.
need_n=$(( 10#${need%%.*} * 1000 + 10#${need#*.} ))
have_n=$(( 10#${have%%.*} * 1000 + 10#${have#*.} ))

echo "$VULN_MOD@$PIN declares go $DIRECTIVE; workflows run Go $GO_VERSION"
if [ "$need_n" -gt "$have_n" ]; then
  echo "::error::$VULN_MOD@$PIN needs Go $need but the workflows pin go-version $have — under GOTOOLCHAIN=local the audit job cannot build govulncheck and fails before it scans anything. Raise go-version and the pin together, or pin govulncheck back to a release that builds on $have."
  exit 1
fi
echo "toolchain-lockstep: ok (go $need <= $have)"
