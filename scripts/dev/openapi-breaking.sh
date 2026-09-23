#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# openapi-breaking.sh — is this branch's OpenAPI schema a breaking change?
#
#   bash scripts/dev/openapi-breaking.sh <server|monitoring> [--base <ref>] [--root <dir>]
#
#     <component>  server | monitoring — which service's snapshot to compare
#     --base <ref> git ref holding the baseline snapshot (default origin/main)
#     --root <dir> operate on another checkout (used by the hermetic test)
#
# The snapshot committed under apps/<component>/tests/openapi.snapshot.json is the
# contract (see the matching test_openapi_snapshot.py). This compares the base
# ref's snapshot against the working tree's with `oasdiff breaking`, which exits
# non-zero only on ERR-level changes — a removed path, a removed response field,
# a newly required request field. Additions stay green.
#
# Exit codes: 0 compatible (or nothing to compare against) · 1 breaking ·
# 75 oasdiff not installed (SKIP; a required step, so red under run.sh --strict) ·
# 2 usage / missing working-tree snapshot.
#
# Why a snapshot and not a live server: the gate has to run in a plain CI job
# with no database and no container, and the snapshot is already the thing review
# looks at.

set -uo pipefail

usage() { sed -n '/^#   bash scripts\/dev\/openapi-breaking.sh/,/^# Exit codes:/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }

COMPONENT="" BASE="origin/main" ROOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --base) shift; [ $# -gt 0 ] || { echo "--base needs a ref" >&2; exit 2; }; BASE="$1"; shift ;;
    --root) shift; [ $# -gt 0 ] || { echo "--root needs a path" >&2; exit 2; }; ROOT="$1"; shift ;;
    -h|--help) usage; exit 0 ;;
    --*) echo "unknown flag: $1" >&2; usage >&2; exit 2 ;;
    *)
      [ -z "$COMPONENT" ] || { echo "unexpected argument: $1" >&2; exit 2; }
      COMPONENT="$1"; shift ;;
  esac
done

case "$COMPONENT" in
  server|monitoring) ;;
  "") echo "openapi-breaking.sh needs a component" >&2; usage >&2; exit 2 ;;
  *)  echo "unknown component: $COMPONENT (expected server or monitoring)" >&2; exit 2 ;;
esac

ROOT="${ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT" || { echo "no such tree: $ROOT" >&2; exit 2; }

REL="apps/$COMPONENT/tests/openapi.snapshot.json"
[ -f "$REL" ] || {
  echo "no snapshot at $REL — record it with" >&2
  echo "  cd apps/$COMPONENT && pytest tests/test_openapi_snapshot.py --update-openapi-snapshot" >&2
  exit 2
}

# The binary check comes before the git work so a box without oasdiff reports the
# one thing that is actually wrong, not a confusing baseline error first.
command -v oasdiff >/dev/null 2>&1 || {
  echo "oasdiff not installed — skipping the $COMPONENT breaking-change check (75)" >&2
  exit 75
}

TMP=$(mktemp -d) || { echo "cannot create a temp dir" >&2; exit 2; }
trap 'rm -rf "$TMP"' EXIT
BASE_FILE="$TMP/base.json"

# A ref that does not resolve is a setup error, not "nothing to compare": a
# shallow CI clone without the base branch would otherwise make this gate pass
# silently on every PR — the one failure mode a compatibility gate must not have.
git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null || {
  echo "::error::base ref '$BASE' does not resolve in this checkout — fetch it (CI: actions/checkout with fetch-depth: 0)" >&2
  exit 2
}

# A snapshot that does not exist ON a resolvable base ref is the normal state the
# first time this runs (and for a branch that adds the service): there is no
# contract to break yet, so that is a pass, not a failure.
if ! git show "$BASE:$REL" > "$BASE_FILE" 2>/dev/null; then
  echo "no snapshot at $BASE:$REL — nothing to compare against yet (new)"
  exit 0
fi

# An unparsable or empty base file makes oasdiff report "no breaking changes"
# and exit 0 — measured with 1.32.0 — even when the revision removed a path. A
# gate that goes green on a broken baseline is worse than no gate.
grep -q '"openapi"' "$BASE_FILE" || {
  echo "::error::base snapshot at $BASE:$REL is not an OpenAPI document" >&2
  exit 2
}

# A newly set `minimum`/`maximum` on an input is ERR for oasdiff: it narrows the
# accepted set, and narrowing is a breaking change in the general case. Here it is
# the opposite of one — the values that become invalid answer with HTTP 500 today
# (autonomy roadmap R-0052), so no client lives off them: one that sends valid
# values notices nothing, one that sends invalid values gets a validation error
# instead of a server error. oasdiff cannot tell those two cases apart, so the
# twelve rules that mean exactly "a bound was added" run as WARN.
#
# Everything else stays ERR — removed endpoints, removed or renamed response
# fields, new required request fields, tightened types, changed status codes. That
# is why this is a named list and not `--fail-on WARN`.
#
# The file carries no reasons of its own: oasdiff's parser wants exactly two fields
# per line and rejects comments and blank lines (checker/level.go:42 @v1.32.0).
# If it is missing, the gate stays strict rather than quietly loosening.
SEVERITY="$(dirname "$0")/oasdiff-severity.levels"
SEV_ARGS=()
if [ -r "$SEVERITY" ]; then
  SEV_ARGS=(--severity-levels "$SEVERITY")
else
  echo "note: $SEVERITY is missing — running without the narrowing exception" >&2
fi

echo "oasdiff breaking $BASE:$REL -> working tree"
oasdiff breaking "$BASE_FILE" "$REL" --fail-on ERR --format text ${SEV_ARGS[@]+"${SEV_ARGS[@]}"}
rc=$?
case "$rc" in
  0) echo "$COMPONENT: no breaking changes against $BASE" ;;
  1) echo "::error::$COMPONENT OpenAPI has breaking changes against $BASE (see above)" >&2 ;;
  # Anything else is oasdiff itself failing (102 = cannot load a spec). Reporting
  # that as a breaking change would be a lie, and passing 75 through would claim
  # the SKIP semantics run.sh reserves for "not verified".
  *) echo "::error::oasdiff failed with exit $rc — the check did not run" >&2; rc=1 ;;
esac
exit "$rc"
