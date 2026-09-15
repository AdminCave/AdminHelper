#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# toolchain-lockstep.sh — assert the govulncheck pin still builds on our Go.
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
# Two assertions:
#   1  every `go-version:` in ci.yml, release.yml and audit.yml is the same
#      (the pin is chosen against one Go version — three different ones make
#      "the Go version" meaningless before the second assertion can mean
#      anything)
#   2  the `go` directive of the pinned x/vuln release is <= that go-version
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

# ── 2: the pinned x/vuln release must build on that Go ───────────────────────
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
