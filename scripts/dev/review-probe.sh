#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review-probe.sh — would the new test be red without the change? And does a
# mutant of the change get past the tests?
#
#   bash scripts/dev/review-probe.sh <component> [--staged | --commit <rev>] [--base <rev>] [-- <test>]
#   bash scripts/dev/review-probe.sh <component> [--staged | --commit <rev>]
#                                    --mutate <file>:<line> '<replacement>' [-- <test>]
#
#     <component>  server monitoring ca-issuer agent desktop desktop-rs
#                  desktop-ui desktop-e2e web scripts (the keys of verify.sh)
#     --staged     the change is what is staged, on HEAD (the default)
#     --commit     the change is that commit, on <rev>^
#     --base       another base for the test hunks
#     -- <test>    handed to the suite (verify.sh <component> -- <test>)
#     --mutate     one line of a file of the change replaced; the suite is the
#                  quick layer, so the replacement has to be lint-clean
#
# The caller's checkout is never touched. The probe builds a worktree of its own
# (git worktree add --detach, under a mktemp -d in the caller's TMPDIR) and puts
# ONLY the hunks under the component's test paths onto the base: the new test
# without the fix. verify.sh <component> --tree <worktree> --strict then runs with
# an AH_OUT_DIR of its own — verify.sh deletes the last-verify.json of whatever
# directory it writes to, and the builder's is task-close's evidence — and with
# AH_DEVENV on the caller's .devenv.sh, since the worktree has none (gitignored).
# A trap removes the worktree and prunes it.
#
# The answer is the probe block of review-verdict.schema.json, on stdout:
#   applicable true,  red_without_change true    a test fails without the change
#   applicable true,  red_without_change false   green without it: it proves nothing
#   applicable false, reason new-symbol          it cannot even load without the
#                                                change (collection, import or
#                                                build error) — no verdict
#   applicable false, reason toolchain           a required step was skipped
#   applicable false, reason no-test-change | apply-failed | other-failure
# Red is the failure of a TEST: a pytest <failure> in the JUnit file (an <error>
# is a collection or setup error), go `--- FAIL:` without `[build failed]`, a
# failing vitest/cargo test rather than a file that does not compile.
#
# --mutate: the worktree carries the whole change with one line of it replaced
# (a file inside it, nowhere else); {"mutant": "killed"} when a test turns red,
# "survived" when the tests stay green, "unknown" with a reason when the run says
# neither. The suite is the component's quick layer, lint included: a
# replacement that is not lint-clean ends as "unknown", not as a verdict.
#
# Exit: 0 an answer on stdout · 2 usage · 74 the probe could not be set up

set -uo pipefail

usage() { sed -n '/^#   bash scripts\/dev\/review-probe.sh/,/^# The caller/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }
die() { echo "review-probe.sh: $*" >&2; exit 2; }
infra() { echo "review-probe.sh: $*" >&2; exit 74; }

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2

# The paths that hold a component's tests — the same list as review.sh
# component_tests (review_probe_test.sh holds the two to each other).
component_tests() {
  case "$1" in
    scripts)     echo "scripts/tests/ scripts/vm/tests/" ;;
    server)      echo "apps/server/tests/" ;;
    monitoring)  echo "apps/monitoring/tests/" ;;
    ca-issuer)   echo "apps/ca-issuer/tests/" ;;
    agent)       echo "apps/agent/*_test.go" ;;
    desktop|desktop-rs) echo "apps/desktop/src-tauri/tests/" ;;
    desktop-ui)  echo "apps/desktop/ui/tests/ apps/desktop/ui/src/*.test.ts apps/desktop/ui/src/*.spec.ts" ;;
    desktop-e2e) echo "scripts/tests/ apps/desktop/ui/e2e/" ;;
    web)         echo "apps/web/tests/ apps/web/e2e/ apps/web/src/*.test.ts apps/web/src/*.spec.ts" ;;
    *)           echo "" ;;
  esac
}

COMP="${1-}"; [ $# -gt 0 ] && shift
case "$COMP" in -h|--help) usage; exit 0 ;; ""|-*) usage >&2; die "needs a component" ;; esac
TESTPATHS="$(component_tests "$COMP")"
[ -n "$TESTPATHS" ] || die "unknown component: $COMP"
MODE="" REV="" BASE="" MUT_AT="" MUT_TO="" TESTARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --staged) [ -z "$MODE" ] || die "--staged or --commit, not both"; MODE=staged ;;
    --commit)
      [ -z "$MODE" ] || die "--staged or --commit, not both"
      [ $# -ge 2 ] || die "--commit needs <rev>"; MODE=commit; REV="$2"; shift ;;
    --base) [ $# -ge 2 ] || die "--base needs <rev>"; BASE="$2"; shift ;;
    --mutate)
      [ $# -ge 3 ] || die "--mutate needs <file>:<line> '<replacement>'"
      MUT_AT="$2"; MUT_TO="$3"; shift 2 ;;
    --) shift; TESTARGS=("$@"); break ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done
MODE="${MODE:-staged}"
[ -z "$BASE" ] || [ -z "$MUT_AT" ] || die "--base has no meaning with --mutate (the mutant sits on the whole change)"
case "$MUT_AT" in "") ;; *:*[!0-9]*|*:) die "--mutate needs <file>:<line>, got $MUT_AT" ;; *:*) ;; *) die "--mutate needs <file>:<line>, got $MUT_AT" ;; esac

if [ "$MODE" = commit ]; then
  git rev-parse --verify -q "$REV^{commit}" >/dev/null || die "no such commit: $REV"
  BASE="${BASE:-$REV^}"
else
  BASE="${BASE:-HEAD}"
fi
git rev-parse --verify -q "$BASE^{commit}" >/dev/null || die "no such base: $BASE"

answer() { python3 -c 'import json, sys; print(json.dumps(json.loads(sys.argv[1])))' "$1"; exit 0; }

PROBE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ah-probe.XXXXXXXX")" || infra "mktemp failed"
WT="$PROBE_DIR/wt"
cleanup() {
  git worktree remove --force "$WT" >/dev/null 2>&1
  git worktree prune >/dev/null 2>&1
  rm -rf "$PROBE_DIR"
}
trap cleanup EXIT

read -ra PATHSPEC <<< "$TESTPATHS"
if [ -n "$MUT_AT" ]; then
  # The whole change: the commit itself, or HEAD with everything staged on it.
  if [ "$MODE" = commit ]; then START="$REV"; else START=HEAD; fi
  git worktree add -q --detach "$WT" "$START" >/dev/null 2>&1 || infra "git worktree add failed"
  if [ "$MODE" = staged ]; then
    git diff --staged --binary > "$PROBE_DIR/change.patch" || infra "could not read the staged diff"
    if [ -s "$PROBE_DIR/change.patch" ]; then
      git -C "$WT" apply "$PROBE_DIR/change.patch" 2>/dev/null || answer '{"mutant": "unknown", "reason": "apply-failed"}'
    fi
  fi
  MFILE="${MUT_AT%:*}" MLINE="${MUT_AT##*:}"
  python3 - "$WT" "$MFILE" "$MLINE" "$MUT_TO" <<'PY' || die "--mutate: $MFILE is no file of the worktree with a line $MLINE"
import os, sys
wt, rel, n, new = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
path = os.path.realpath(os.path.join(wt, rel))
# Only a file of the worktree: `..` or a tracked symlink must not reach the
# caller's checkout or anything else.
if not path.startswith(os.path.realpath(wt) + os.sep):
    sys.exit(1)
try:
    lines = open(path, encoding="utf-8").read().split("\n")
except (OSError, UnicodeDecodeError):
    sys.exit(1)
# The last element after the final newline is not a line.
if not 1 <= n <= len(lines) - (1 if lines[-1] == "" else 0):
    sys.exit(1)
lines[n - 1] = new
open(path, "w", encoding="utf-8").write("\n".join(lines))
PY
else
  if [ "$MODE" = commit ]; then
    git diff --binary "$REV^" "$REV" -- "${PATHSPEC[@]}" > "$PROBE_DIR/tests.patch" || infra "could not read the diff of $REV"
  else
    git diff --staged --binary -- "${PATHSPEC[@]}" > "$PROBE_DIR/tests.patch" || infra "could not read the staged diff"
  fi
  [ -s "$PROBE_DIR/tests.patch" ] \
    || answer '{"applicable": false, "reason": "no-test-change", "red_without_change": null}'
  git worktree add -q --detach "$WT" "$BASE" >/dev/null 2>&1 || infra "git worktree add failed"
  git -C "$WT" apply "$PROBE_DIR/tests.patch" 2>/dev/null \
    || answer '{"applicable": false, "reason": "apply-failed", "red_without_change": null}'
fi

OUT="$PROBE_DIR/out"; mkdir -p "$OUT"
DEVENV=()
[ -f "$ROOT/.devenv.sh" ] && DEVENV=(AH_DEVENV="$ROOT/.devenv.sh")
CMD=(bash "$ROOT/scripts/dev/verify.sh" "$COMP" --tree "$WT" --strict)
[ "${#TESTARGS[@]}" -eq 0 ] || CMD+=(-- "${TESTARGS[@]}")
env "${DEVENV[@]+"${DEVENV[@]}"}" AH_OUT_DIR="$OUT" "${CMD[@]}" > "$PROBE_DIR/run.log" 2>&1
VRC=$?

python3 - "$VRC" "$OUT" "$PROBE_DIR/run.log" "${MUT_AT:+mutate}" <<'PY'
import glob, json, os, re, sys
import xml.etree.ElementTree as ET

vrc, out, runlog, mutate = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] == "mutate"


def read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def verdict():
    if vrc == 0:
        return "green", ""
    failures = errors = 0
    for x in glob.glob(os.path.join(out, "junit", "*.xml")):
        try:
            root = ET.parse(x).getroot()
        except ET.ParseError:
            continue
        failures += len(root.findall(".//testcase/failure"))
        errors += len(root.findall(".//testcase/error"))
    logs = read(runlog) + "".join(read(p) for p in glob.glob(os.path.join(out, "step-*.log")))
    # pytest says it in its JUnit file and, without one, in its summary lines.
    if failures or re.search(r"^FAILED \S+::\S+", logs, re.M):
        return "red", ""
    # The new test could not even load without the change: a collection error
    # in pytest, a build or import error elsewhere.
    if errors or re.search(r"^ERROR \S+|\[build failed\]|^\S+\.go:\d+:\d+: undefined:|error\[E\d+\]|could not compile"
                           r"|Failed to resolve import|Failed to load url|Transform failed", logs, re.M):
        return "none", "new-symbol"
    # A test that ran and failed, in the words of go, cargo, vitest and the shell
    # suites. run.sh's own step lines (`  FAIL  <step>`, two blanks) are not one.
    if re.search(r"^\s*--- FAIL: |^test result: FAILED|^\s*FAIL\s+\S+ > |^\s*[×✗] \S+ > |^  FAIL \S",
                 logs, re.M):
        return "red", ""
    # Under --strict a skipped required step fails the run: no toolchain for it.
    if re.search(r"^\s+SKIP\s+.*\((?!AH_ONLY\))[^)]*\)\s*$", logs, re.M):
        return "none", "toolchain"
    return "none", "other-failure"


kind, reason = verdict()
# No verdict from a red run: the end of it on stderr says why.
if kind == "none":
    sys.stderr.write("".join(read(runlog).splitlines(True)[-30:]))
if mutate:
    print(json.dumps({"mutant": {"red": "killed", "green": "survived"}.get(kind, "unknown"),
                      "reason": reason}))
else:
    print(json.dumps({"applicable": kind != "none", "reason": reason,
                      "red_without_change": {"red": True, "green": False}.get(kind)}))
PY
