#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# toolchain-lockstep.sh — assert the govulncheck pin still builds on our Go.
# Since R-0046 it also holds the ruff pins together, since R-0411 the oasdiff pin.
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
# Six assertions:
#   1  every `go-version:` in ci.yml, release.yml and audit.yml is the same
#      (the pin is chosen against one Go version — three different ones make
#      "the Go version" meaningless before the third assertion can mean
#      anything)
#   1b every `with:` block that sets `go-version:` also sets `check-latest: true`.
#      setup-go resolves MAJOR.MINOR from the runner image's toolcache first, and
#      the image held 1.26.8 when the stdlib fixes came with 1.26.9: without it,
#      release.yml can ship another stdlib than the one audit.yml scanned.
#      Offline, like 2.
#   1c the default of GO_VERSION in scripts/vm/bootstrap_linux.sh, the Go every
#      heavy-tier box builds the agent with, has that go-version's MAJOR.MINOR.
#      The patch is free (the tarball's SHA-256 pins it). Offline.
#   2  the ruff that ci.yml installs is the default of RUFF_VERSION in
#      scripts/vm/bootstrap_linux.sh and the `ruff==` pin in
#      apps/server/requirements-dev.txt. The first bake of a linux-server
#      template ran an unpinned ruff and went red on rules the dev box and CI
#      never saw; the comments at all three places said "keep in sync", and
#      nothing checked it. requirements-dev.txt pins rather than floors: run.sh
#      installs it into AH_VENV, and a `ruff>=` there left a newer ruff in place
#      that reported 841 findings CI never saw. ruff.toml's `required-version`
#      names the same release: the pins only heal a venv that pip touches, and
#      run.sh takes the first ruff on PATH — with it, any other ruff stops with
#      exit 2 instead of linting by its own rules. Offline, so it runs before
#      the proxy fetch and a drift stays a drift when the proxy is down.
#   2b the oasdiff that ci.yml installs — OASDIFF_VERSION and
#      OASDIFF_SHA256_LINUX_AMD64, every occurrence — is the default of the same
#      two in scripts/vm/bootstrap_linux.sh. run.sh's scripts block needs the real
#      binary (openapi_breaking_test exits 75 without it), so CI and the boxes
#      must measure with the same release. Offline, like 2.
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
    # A comment after the value is allowed: a line the pattern skipped would
    # count for nothing, and a drift on it would pass unseen. YAML reads `#` as a
    # comment only after a blank, so `1.25#x` stays the value and is judged.
    case "$v" in
      *[!0-9.]* | *.*.* | *.) bad_version=1 ;;
      *.*) bad_version=0 ;;
      *) bad_version=1 ;;
    esac
    [ "$bad_version" = 0 ] || {
      echo "::error::cannot compare go-version '$v' in .github/workflows/$f.yml — this check needs a plain MAJOR.MINOR pin, not a range, alias or .x wildcard"
      exit 1; }
    versions="$versions $f=$v"
  done < <(sed -n 's/^[[:space:]]*go-version:[[:space:]]*"\{0,1\}\([^"[:space:]]*\)"\{0,1\}\([[:space:]]\{1,\}#.*\)\{0,1\}[[:space:]]*$/\1/p' "$WF/$f.yml")
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

# ── 1b: check-latest beside every go-version ─────────────────────────────────
# Per `with:` block, in any order: a block is the go-version line's siblings —
# every line around it at its indent or deeper, comments and blank lines
# included. A check-latest in another job's block does not count. The scan ends
# with a line "end": without it awk did not run to the end, and a check that
# cannot fail checks nothing. True is what setup-go's core.getBooleanInput takes:
# true, True or TRUE, quoted or not; the single quote comes in as q.
for f in ci release audit; do
  scan="$(awk -v q="'" '
    function ind(s) { return match(s, /[^ ]/) - 1 }
    function inblock(s, d) { return s ~ /^[ ]*(#.*)?$/ || ind(s) >= d }
    function latest(s, d) { return ind(s) == d && s ~ ("^[ ]*check-latest:[ ]*[" q "\"]?(true|True|TRUE)[" q "\"]?[ ]*(#.*)?$") }
    { line[NR] = $0 }
    END {
      for (i = 1; i <= NR; i++) {
        if (line[i] !~ /^[ ]*go-version:/) continue
        d = ind(line[i]); found = 0
        for (j = i - 1; j >= 1 && inblock(line[j], d); j--) if (latest(line[j], d)) found = 1
        for (j = i + 1; j <= NR && inblock(line[j], d); j++) if (latest(line[j], d)) found = 1
        if (!found) print i
      }
      print "end"
    }' "$WF/$f.yml")"
  [ "$(tail -n 1 <<<"$scan")" = end ] || {
    echo "::error::the check-latest scan of .github/workflows/$f.yml did not run to its end — nothing was checked"
    exit 1; }
  n="$(head -n 1 <<<"$scan")"
  [ "$n" = end ] || {
    echo "::error::.github/workflows/$f.yml:$n sets go-version without check-latest: true in the same with: block — setup-go then takes the newest patch in the runner's toolcache, and the release can ship another stdlib than the audit checks"
    exit 1; }
done
echo "check-latest: true beside every go-version"

# ── 1c: the test boxes' Go on the workflows' minor ───────────────────────────
# Without it a minor bump of the workflows leaves the boxes on the old Go, and
# the heavy tier tests a toolchain CI no longer ships.
BOOT="$ROOT/scripts/vm/bootstrap_linux.sh"
[ -f "$BOOT" ] || { echo "::error::missing scripts/vm/bootstrap_linux.sh — the test boxes' Go cannot be checked"; exit 1; }
GO_BOOT="$(sed -n 's/^GO_VERSION="\${AH_GO_VERSION:-\([^}]*\)}".*/\1/p' "$BOOT" | head -1)"
case "$GO_BOOT" in
  "" | *[!0-9.]* | .* | *. | *..* | *.*.*.*) go_boot_ok=0 ;;
  *.*.*) go_boot_ok=1 ;;
  *) go_boot_ok=0 ;;
esac
[ "$go_boot_ok" = 1 ] || {
  echo "::error::no plain GO_VERSION=\"\${AH_GO_VERSION:-X.Y.Z}\" default in scripts/vm/bootstrap_linux.sh (found '$GO_BOOT')"
  exit 1; }
[ "${GO_BOOT%.*}" = "$GO_VERSION" ] || {
  echo "::error::scripts/vm/bootstrap_linux.sh installs Go $GO_BOOT on the test boxes, the workflows run go-version $GO_VERSION — raise GO_VERSION and its SHA-256 together with go-version"
  exit 1; }
echo "bootstrap: GO_VERSION=$GO_BOOT on go-version $GO_VERSION"

# ── 2: one ruff at all four places ───────────────────────────────────────────
# Plain dotted digits only: `ruff==0.15.*` is a valid pip specifier that matches
# more than one ruff, and a pin that is not one release is the drift itself.
plain_version() { case "$1" in "" | *[!0-9.]* | .* | *. | *..*) return 1 ;; esac; }
REQ="$ROOT/apps/server/requirements-dev.txt"
TOML="$ROOT/ruff.toml"
RUFF_PLACES="ci.yml, bootstrap_linux.sh, requirements-dev.txt and ruff.toml"
for f in "$BOOT" "$REQ" "$TOML"; do
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
    echo "::error::ruff pin drift: .github/workflows/ci.yml installs ruff==$v, scripts/vm/bootstrap_linux.sh defaults to $RUFF_BOOT — $RUFF_PLACES move together"
    exit 1; }
  ruff_ci="$v"
done < <(sed -n 's/.*pip install ruff==\([^[:space:]"]*\).*/\1/p' "$WF/ci.yml")
[ -n "$ruff_ci" ] || {
  echo "::error::no pinned 'pip install ruff==X.Y.Z' in .github/workflows/ci.yml — an unpinned ruff is the drift this check exists to prevent"
  exit 1; }
RUFF_DEV="$(sed -n 's/^ruff==\([^[:space:]#,;]*\).*/\1/p' "$REQ" | head -1)"
plain_version "$RUFF_DEV" || {
  echo "::error::no pinned 'ruff==X.Y.Z' in apps/server/requirements-dev.txt (found '$RUFF_DEV') — anything but an exact pin leaves whatever ruff a venv already has"
  exit 1; }
[ "$RUFF_DEV" = "$RUFF_BOOT" ] || {
  echo "::error::ruff pin drift: apps/server/requirements-dev.txt pins ruff==$RUFF_DEV, scripts/vm/bootstrap_linux.sh defaults to $RUFF_BOOT — $RUFF_PLACES move together"
  exit 1; }
RUFF_TOML_RAW="$(sed -n 's/^required-version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$TOML" | head -1)"
case "$RUFF_TOML_RAW" in "=="*) RUFF_TOML="${RUFF_TOML_RAW#==}" ;; *) RUFF_TOML="" ;; esac
plain_version "$RUFF_TOML" || {
  echo "::error::ruff.toml required-version is not an exact \"==X.Y.Z\" (found '$RUFF_TOML_RAW') — without it any ruff on PATH lints this tree by its own rules"
  exit 1; }
[ "$RUFF_TOML" = "$RUFF_BOOT" ] || {
  echo "::error::ruff.toml required-version ==$RUFF_TOML, scripts/vm/bootstrap_linux.sh defaults to $RUFF_BOOT — $RUFF_PLACES move together"
  exit 1; }
echo "ruff: ci.yml=$ruff_ci bootstrap=$RUFF_BOOT dev=$RUFF_DEV ruff.toml=$RUFF_TOML"

# ── 2b: one oasdiff in CI and on the boxes ───────────────────────────────────
# ci.yml holds the pair once (an anchored step that ops-scripts aliases), but
# every occurrence is read, like the ruff pins: copies instead of the anchor
# must not hide a lagging one. A value is read quoted or bare, up to a blank.
sha256_hex() { [ "${#1}" -eq 64 ] && case "$1" in *[!0123456789abcdef]*) return 1 ;; esac; }
OAS_BOOT="$(sed -n 's/^OASDIFF_VERSION="\${AH_OASDIFF_VERSION:-\([^}]*\)}".*/\1/p' "$BOOT" | head -1)"
plain_version "$OAS_BOOT" || {
  echo "::error::no plain OASDIFF_VERSION=\"\${AH_OASDIFF_VERSION:-X.Y.Z}\" default in scripts/vm/bootstrap_linux.sh (found '$OAS_BOOT')"
  exit 1; }
OAS_SHA_BOOT="$(sed -n 's/^OASDIFF_SHA256_LINUX_AMD64="\${AH_OASDIFF_SHA256:-\([^}]*\)}".*/\1/p' "$BOOT" | head -1)"
sha256_hex "$OAS_SHA_BOOT" || {
  echo "::error::no plain OASDIFF_SHA256_LINUX_AMD64=\"\${AH_OASDIFF_SHA256:-<64 hex>}\" default in scripts/vm/bootstrap_linux.sh (found '$OAS_SHA_BOOT')"
  exit 1; }
oas_ci=""
while IFS= read -r v; do
  [ "$v" = "$OAS_BOOT" ] || {
    echo "::error::oasdiff pin drift: .github/workflows/ci.yml installs oasdiff $v, scripts/vm/bootstrap_linux.sh defaults to $OAS_BOOT — ci.yml and bootstrap_linux.sh move together"
    exit 1; }
  oas_ci="$v"
done < <(sed -n 's/^[[:space:]]*OASDIFF_VERSION:[[:space:]]*"\{0,1\}\([^"[:space:]]*\)"\{0,1\}.*/\1/p' "$WF/ci.yml")
[ -n "$oas_ci" ] || {
  echo "::error::no OASDIFF_VERSION in .github/workflows/ci.yml — the oasdiff run.sh's scripts block needs cannot be held to the boxes' one"
  exit 1; }
oas_sha_ci=""
while IFS= read -r s; do
  [ "$s" = "$OAS_SHA_BOOT" ] || {
    echo "::error::oasdiff SHA-256 drift: .github/workflows/ci.yml pins $s, scripts/vm/bootstrap_linux.sh defaults to $OAS_SHA_BOOT — ci.yml and bootstrap_linux.sh move together"
    exit 1; }
  oas_sha_ci="$s"
done < <(sed -n 's/^[[:space:]]*OASDIFF_SHA256_LINUX_AMD64:[[:space:]]*"\{0,1\}\([^"[:space:]]*\)"\{0,1\}.*/\1/p' "$WF/ci.yml")
[ -n "$oas_sha_ci" ] || {
  echo "::error::no OASDIFF_SHA256_LINUX_AMD64 in .github/workflows/ci.yml — an unpinned oasdiff tarball is the drift this check exists to prevent"
  exit 1; }
echo "oasdiff: ci.yml=$oas_ci bootstrap=$OAS_BOOT sha256=${OAS_SHA_BOOT:0:12}"

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
