#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# verify.sh — the one way a task's Verify: line runs a component's fast suite.
#
#   bash scripts/dev/verify.sh <component> [--strict] [--tree <path>] [-- <args>]
#
#     <component>  server monitoring ca-issuer agent desktop desktop-rs
#                  desktop-ui desktop-e2e web scripts — or `all` for every
#                  component. Runs that component's lint AND unit steps.
#     --strict     a SKIP of a required step fails the run (see run.sh)
#     --tree       run against another checkout (a worktree), not this one
#     -- <args>    extra arguments for the suite itself, e.g.
#                  `verify.sh server --strict -- tests/test_auth.py -k lifecycle`
#                  (word-split by the suite's shell — a single argument cannot
#                  contain spaces, so `-k "foo or bar"` arrives as three)
#
# Why this exists rather than a bare run.sh call: a ledger's Verify: line has to
# be matchable by a Bash allow-rule, and a rule never matches across an env
# prefix — `source .devenv.sh && DATABASE_URL=… pytest` cannot be allowlisted.
# So the environment is resolved HERE (devenv, AH_TEST_DB) and the caller writes
# flags only. A run that got far enough leaves $AH_OUT_DIR/last-verify.json: the
# run.sh artifact plus what only this wrapper knows (component, args, tree). A run
# that did not leaves NO file — stale evidence is worse than none.
#
# AH_DEVENV=<path> overrides the devenv file (default <tree>/.devenv.sh).
# Sourcing it means --tree executes a file from the tree it points at; that is the
# same trust level as the checkout's own scripts, and --tree is chosen by the
# caller, not by anything the suite reads.

set -uo pipefail

# Printed by -h and by every argument error. Bounded by the header's blank comment
# line, so extending the usage block above never truncates it mid-sentence again.
usage() { sed -n '/^#   bash scripts\/dev\/verify.sh/,/^# Why this exists/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }

COMPONENT="" STRICT=0 TREE="" ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --strict) STRICT=1; shift ;;
    --tree)
      shift; [ $# -gt 0 ] || { echo "--tree needs a path"; exit 2; }
      TREE="$1"; shift ;;
    --) shift; ARGS=("$@"); break ;;
    -h|--help) usage; exit 0 ;;
    --*) echo "unknown flag: $1"; usage; exit 2 ;;
    *)
      [ -z "$COMPONENT" ] || { echo "unexpected argument: $1 (component is already '$COMPONENT')"; exit 2; }
      COMPONENT="$1"; shift ;;
  esac
done
[ -n "$COMPONENT" ] || { echo "verify.sh needs a component"; usage; exit 2; }

SELF_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TREE="${TREE:-$SELF_ROOT}"
[ -d "$TREE" ] || { echo "no such tree: $TREE"; exit 2; }
TREE="$(cd "$TREE" && pwd)"
RUN="$TREE/scripts/tests/run.sh"
[ -f "$RUN" ] || { echo "not an AdminHelper checkout (no scripts/tests/run.sh): $TREE"; exit 2; }

# The devenv file is gitignored and per-host; it is what makes AH_TEST_DB and the
# go/ruff toolchains reachable. Missing is not an error — a crabbox box has the
# toolchains on PATH and no devenv file at all.
DEVENV="${AH_DEVENV:-$TREE/.devenv.sh}"
if [ -f "$DEVENV" ]; then
  # The trap catches a devenv that calls `exit`: without it, `exit 0` there would
  # end verify.sh green without a single suite having run.
  trap 'echo "verify.sh: $DEVENV aborted the run" >&2; exit 2' EXIT
  # shellcheck disable=SC1090
  . "$DEVENV" || echo "  (warning: $DEVENV could not be sourced)" >&2
  trap - EXIT
  set +e   # a `set -e` in the devenv file must not leak into this wrapper
fi

# The quick layer, not just unit: a component's fast suite is lint AND unit
# (CLAUDE.md's component table — ruff, gofmt, shellcheck live in layer_lint).
# Delegating to `unit` alone would have made `verify.sh server` silently skip
# ruff, and every ledger Verify: line rewritten to this form would have verified
# less than the line it replaced. `all` needs no --only.
if [ "$COMPONENT" = "all" ]; then
  CMD=(bash "$RUN" quick)
else
  CMD=(bash "$RUN" quick --only "$COMPONENT")
fi
[ "$STRICT" = 1 ] && CMD+=(--strict)

cd "$TREE" || exit 2
export AH_ARGS="${ARGS[*]:-}"

# Both artifacts go BEFORE the run, so "the file is there" can only mean "this run
# wrote it". Without this, a run that never reached run.sh's writer (an unknown
# component, a failed cd) would stamp a new component name onto an older run's
# record — exactly what run.sh guards against one task earlier.
OUT_DIR="${AH_OUT_DIR:-$TREE/.crabbox-out}"
LAYER="quick"
SRC="$OUT_DIR/last-$LAYER.json"
DST="$OUT_DIR/last-verify.json"
rm -f "$SRC" "$DST"

"${CMD[@]}"; rc=$?

# last-verify.json = the run's own artifact plus the three things only this
# wrapper knows. Reusing run.sh's file keeps one schema instead of two that
# drift; if the run never got far enough to write a complete one, say so rather
# than inventing a record of a run that did not happen.
# Control characters are stripped for the same reason run.sh strips them: a tab
# in an argument would make the artifact unparseable for its only readers.
json_str() {
  printf '"%s"' "$(printf '%s' "$1" \
    | LC_ALL=C tr '\000-\037' ' ' \
    | sed 's/\\/\\\\/g; s/"/\\"/g')"
}
if [ -s "$SRC" ] && [ "$(tail -n1 "$SRC")" = "}" ]; then
  {
    sed '$d' "$SRC"
    printf ',\n  "component": %s,\n  "args": %s,\n  "tree": %s\n}\n' \
      "$(json_str "$COMPONENT")" "$(json_str "${ARGS[*]:-}")" "$(json_str "$TREE")"
  } > "$DST" && echo "  verify: $DST"
else
  echo "  verify: no complete run artifact at $SRC — last-verify.json not written" >&2
fi

exit "$rc"
