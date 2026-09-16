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

echo "oasdiff breaking $BASE:$REL -> working tree"
oasdiff breaking "$BASE_FILE" "$REL" --fail-on ERR --format text
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
