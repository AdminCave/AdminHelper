#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review.sh — the checks a diff has to pass before it becomes a commit.
#
#   bash scripts/dev/review.sh diff-scan [--staged] [--task <ledger> <id>]
#                                                       ways to make a suite lie
#   bash scripts/dev/review.sh scope <ledger> <id> [--staged]   paths vs. the task
#   bash scripts/dev/review.sh sec [--staged]           what must never be committed
#   bash scripts/dev/review.sh check-verdict <file> --tree <hash>
#                                                       a reviewer's verdict JSON
#   bash scripts/dev/review.sh risk [--staged | --range <a>..<b>]
#                                                       which reviewer a diff gets
#
# Deterministic, model-free, and called by task-close.sh before it commits. They
# answer three questions a reviewer would otherwise have to ask every time:
#
#   diff-scan  does this diff buy its green by switching a test off? A `|| true`,
#              a `set +e`, a skip, xfail, todo or `.only(` of the test frameworks,
#              a deleted assertion (with the Rust assert_ macros and, in a Go
#              test, the t.Fatal/t.Error calls; only where tests are — a test
#              file or the span of a test, never an import line, R-0130; a
#              helper in `#[cfg(test)] mod tests` without `#[test]` is outside)
#              or a `return` inside a test, bare or with the value a test
#              returns anyway (None, undefined, Ok(())), with code of the test
#              after it and not in a function nested in the test, changes
#              what "passed" means. Other return values and a generic `.fail(`
#              stay out.
#              Two things are deliberately not findings: a
#              line that carries `# review: ok <reason>` (and says why), and a
#              pattern that only appears behind a comment marker, because a
#              comment switches nothing off. With --task, a third: an assertion
#              that goes with its WHOLE test — the test's head deleted in the
#              same block and not added back — when the task declares that test
#              in a `Test-Löschung: <file>::<test> — <reason>` line. Dead code and
#              its test can leave together; an assertion out of a test that
#              stays is still a finding, declared or not.
#   scope      does the diff stay inside the files the task declared? Everything
#              else is either a forgotten `ledger.sh set-files` or a drive-by.
#   sec        is something staged that this public repo must never hold — the
#              private roadmap, a security ledger, a finding's dedup key, or one
#              of the two gitignored files that carry credentials.
#   check-verdict  is a reviewer's verdict usable for this tree? It has to follow
#              scripts/dev/review-verdict.schema.json, be about the tree --tree
#              names, and say approve without a blocker and without a probe
#              that found the new test green without the change. A blocker
#              without evidence counts as a nit. Prints the review line that
#              task-close.sh writes into the ledger.
#   risk       does the diff touch a risk path (scripts/dev/review-risk.txt and
#              the harness paths)? Prints `xhigh` and the paths it hit, or
#              `standard`; both exit 0. The reviewer model follows from it.
#
# --staged looks at the index (what task-close.sh is about to commit); without it
# the working tree is compared against the index. Neither form sees UNTRACKED files —
# git diff does not — so the answer for a brand-new file exists only once it is
# staged, which is the state task-close.sh works on anyway.
#
# Exit: 0 clean · 2 usage (check-verdict: unreadable or outside the schema) ·
# 3 findings (diff-scan, scope; check-verdict: no usable approve) · 4 blocked
# (sec; check-verdict: a verdict for another tree)

set -uo pipefail

CALLER_PWD="$PWD"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2

usage() { sed -n '/^#   bash scripts\/dev\/review.sh diff-scan/,/^# Deterministic/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }
die() { echo "review.sh: $*" >&2; exit 2; }

# The ways a diff can buy a green run. Fixed strings, \x1f-separated, each one
# with the language it comes from: pytest, vitest/jest/Playwright, Rust, Go,
# shell. One line per group, so each can carry the marker that exempts it.
SKIP_PATTERNS='@pytest.mark.skip\x1fpytest.skip(\x1f@pytest.mark.xfail\x1fpytest.xfail(\x1f'        # review: ok this IS the list
SKIP_PATTERNS+='.skipTest(\x1fpytest.importorskip(\x1f'                                             # review: ok this IS the list
SKIP_PATTERNS+='it.skip(\x1ftest.skip(\x1fdescribe.skip(\x1f.skipIf(\x1f.todo(\x1f.fixme(\x1f'      # review: ok this IS the list
SKIP_PATTERNS+='fit(\x1ffdescribe(\x1f.runIf(\x1f.fails(\x1ftest.fail(\x1f'                         # review: ok this IS the list
SKIP_PATTERNS+='xit(\x1fxtest(\x1fxdescribe(\x1fit.only(\x1ftest.only(\x1fdescribe.only(\x1f'       # review: ok this IS the list
SKIP_PATTERNS+='#[ignore\x1ft.Skip(\x1ft.Skipf(\x1ft.SkipNow(\x1f|| true\x1f--no-verify\x1fset +e'  # review: ok this IS the list

# Which test files a component owns. The scope check allows them even when the
# task's Dateien: line forgot to name the test that proves it — a task that may
# not add its own test is a task that ships untested. Globs where a whole source
# tree would otherwise be waved through (`*` crosses `/` in a case pattern):
# allowing all of apps/agent/ would have made this check meaningless for Go.
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

VERB="${1-}"; [ $# -gt 0 ] && shift
STAGED=0
ARGS=()
TASK_LEDGER="" TASK_ID="" TREE_ARG="" RANGE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --staged) STAGED=1 ;;
    --tree)
      [ $# -ge 2 ] || die "--tree needs <hash>"
      TREE_ARG="$2"; shift ;;
    --range)
      [ $# -ge 2 ] || die "--range needs <a>..<b>"
      case "$2" in -*|'') die "not a range: $2" ;; *..*) ;; *) die "not a range (<a>..<b>): $2" ;; esac
      RANGE="$2"; shift ;;
    --task)
      [ $# -ge 3 ] || die "--task needs <ledger> <id>"
      TASK_LEDGER="$2"; TASK_ID="$3"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --*) die "unknown flag: $1" ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done

# task_field <ledger> <id> <field> — the value of the task's `<field>:` line.
task_field() {
  L_ID="$2" L_FIELD="$3" awk '
    BEGIN { id = ENVIRON["L_ID"]; f = ENVIRON["L_FIELD"] ":" }
    $0 ~ "^###[ \t]+" id "([ \t]|$)" { insec = 1; next }
    insec && (/^###[ \t]/ || /^## /) { exit }
    insec && index($0, f) == 1 { print substr($0, length(f) + 1); exit }' "$1"
}
DIFF_ARGS=()
[ "$STAGED" = 1 ] && DIFF_ARGS+=(--staged)
if [ -n "$RANGE" ]; then
  # The other verbs judge what is about to be committed; a range is history.
  [ "$VERB" = risk ] || die "--range is for risk alone"
  [ "$STAGED" = 0 ] || die "--staged or --range, not both"
  DIFF_ARGS+=("$RANGE")
fi
# Every verb reads the diff through this, never through a bare `git diff`: a
# committed `.gitattributes` with `-diff` turned a test file into "Binary files
# differ" and all three checks went blind (adversarial review, 2026-09-25); a
# textconv or external diff driver, color.diff=always, other prefixes and
# octal-quoted paths change the text the checks parse just as well.
GIT_DIFF=(git -c core.quotePath=false diff --text --no-ext-diff --no-textconv --no-color --src-prefix=a/ --dst-prefix=b/)

changed_paths() { "${GIT_DIFF[@]}" "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" --name-only; }

case "$VERB" in
  diff-scan)
    # The tests the task declares as deleted — read from the COMMITTED ledger
    # (HEAD), never from the working tree: a builder must not be able to grant
    # itself the exception in the same run (Kevin, 2026-09-25). The declaration
    # typically arrives with the plan commit at the gate. Only with --task: a
    # call by hand has no task to speak for it and stays strict.
    DECL=""
    if [ -n "$TASK_LEDGER" ]; then
      case "$TASK_ID" in ""|*[!A-Za-z0-9._-]*) die "not a task id: $TASK_ID" ;; esac
      case "$TASK_LEDGER" in */*) ;; *) TASK_LEDGER="tasks/$TASK_LEDGER" ;; esac
      case "$TASK_LEDGER" in *.md) ;; *) TASK_LEDGER="$TASK_LEDGER.md" ;; esac
      [ -f "$TASK_LEDGER" ] || die "no such ledger: $TASK_LEDGER"
      grep -qE "^###[[:space:]]+$TASK_ID([[:space:]]|\$)" "$TASK_LEDGER" \
        || die "no task $TASK_ID in $TASK_LEDGER"
      COMMITTED="$(mktemp)" || die "mktemp failed"
      if git show "HEAD:$TASK_LEDGER" > "$COMMITTED" 2>/dev/null; then
        DECL="$(task_field "$COMMITTED" "$TASK_ID" "Test-Löschung")"
      fi
      rm -f "$COMMITTED"
    fi
    # -U0: only what this diff actually adds or removes. Context lines would
    # convict a `|| true` that has been standing there for two years.
    # The patterns arrive as one \x1f-separated string: an awk -v value cannot
    # carry an array, and each of them is a fixed string, not a regex.
    # `---`/`+++` are file headers only between `diff --git` and the first `@@`
    # of that file: inside a hunk the same characters are content (`++ x` added
    # reads `+++ x`), and taking them for a header let a later line switch files.
    # A removed assertion is not judged here: it leaves as an RA record, and the
    # check below decides against the file CONTENTS whether a declared test
    # covers it.
    RAW="$("${GIT_DIFF[@]}" "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" -U0 | awk -v PAT="$SKIP_PATTERNS" '
      function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
      # Where a comment starts, or 0. Only a marker at the start of the line or
      # after whitespace counts, so the // in an https:// URL is not a comment.
      function comment_at(s,   c, c2) {
        c = 0
        if (match(s, /(^|[ \t])#/))    c = RSTART + RLENGTH - 1
        if (match(s, /(^|[ \t])\/\//)) { c2 = RSTART + RLENGTH - 2; if (!c || c2 < c) c = c2 }
        return c
      }
      /^diff --git /  { inheader = 1; next }
      # git ends a path that holds a space with a tab.
      inheader && /^--- / { oldfile = substr($0, 5); sub(/^a\//, "", oldfile); sub(/\t$/, "", oldfile); next }
      inheader && /^\+\+\+ / {
                        file = substr($0, 5)
                        # A deletion has +++ /dev/null; the path is on the --- side.
                        if (file == "/dev/null") file = oldfile; else sub(/^b\//, "", file)
                        sub(/\t$/, "", file)
                        # A rename: the old span of a test lives under the OLD path.
                        if (oldfile != file && oldfile != "/dev/null")
                          printf "RN\t%s\t%s\n", oldfile, file
                        next
                      }
      /^@@/           {
                        inheader = 0
                        split($2, o, ","); split($3, nw, ",")
                        oldno = o[1]; sub(/^-/, "", oldno); oldno += 0
                        newno = nw[1]; sub(/^\+/, "", newno); newno += 0
                        next
                      }
      inheader        { next }
      /^-/            {
                        line = substr($0, 2)
                        printf "RL\t%s\t%d\n", file, oldno
                        # assert, the Rust macros assert_{eq,ne,matches,…}!, expect(
                        # of vitest/jest, and in a Go test file the calls on its
                        # testing.T t — outside one, a t is just a name. Whether
                        # the line stood where tests are is the judge below.
                        if (line !~ /review: ok/ &&
                            (line ~ /(^|[^A-Za-z_.])assert(_[a-z]+)?!?([^A-Za-z_]|$)/ || line ~ /expect\(/ ||
                             (file ~ /_test\.go$/ &&
                              line ~ /(^|[^A-Za-z0-9_.])t\.(Fatal|Fatalf|Error|Errorf|Fail|FailNow)\(/)))
                          printf "RA\t%s\t%d\t%s\n", file, oldno, trim(line)
                        oldno++; next
                      }
      /^\+/           {
                        line = substr($0, 2)
                        sub(/\r$/, "", line)
                        if (line !~ /review: ok/) {
                          cmt = comment_at(line)
                          cnt = split(PAT, pat, "\x1f")
                          for (i = 1; i <= cnt; i++) {
                            pos = index(line, pat[i])
                            # A word boundary in front, or `xit(` convicts every
                            # `sys.exit(` in the repo. index() rather than a
                            # regex: the patterns are fixed strings full of
                            # regex metacharacters.
                            # A pattern that starts with no word character (`.todo(`,
                            # `@pytest…`, `|| true`) needs no boundary in front.
                            prev = (pos > 1) ? substr(line, pos - 1, 1) : " "
                            if (substr(pat[i], 1, 1) !~ /[A-Za-z0-9_]/) prev = " "
                            if (pos > 0 && prev !~ /[A-Za-z0-9_]/ && (cmt == 0 || pos <= cmt)) {
                              printf "%s:%d  %s: %s\n", file, newno, pat[i], trim(line)
                              break
                            }
                          }
                          # A line that is only a return, bare or with the value a
                          # test returns anyway: inside a test it ends the test
                          # before its checks. Whether it is inside one is decided
                          # below, against the new file.
                          if (line ~ /^[ \t]*return( None| undefined| Ok\(\(\)\))?;?[ \t]*((#|\/\/).*)?$/)
                            printf "AR\t%s\t%d\t%s\n", file, newno, trim(line)
                        }
                        newno++; next
                      }
                      { oldno++; newno++ }
    ')" || die "could not read the diff"
    # The removed assertions, judged against contents. A declared test counts
    # only if (1) the entry carries a reason, (2) its name is a test head exactly
    # ONCE in the old version of its file — two tests of the same name (two
    # describe blocks) cannot be told apart, and git may align the kept head
    # with the dead one —, (3) no head of that name is left in the new version of
    # the file, and (4) no file of the diff gains a head of that name (a test
    # that moves is not a test that goes). An assertion passes only when its OLD
    # line number lies inside the old span of such a test.
    FOUND="$(printf '%s\n' "$RAW" | DECL="$DECL" STAGED="$STAGED" python3 -c '
import os, re, subprocess, sys

staged = os.environ.get("STAGED") == "1"
lines = [l for l in sys.stdin.read().split("\n") if l]
ras = [l.split("\t", 3)[1:] for l in lines if l.startswith("RA\t")]
removed = {}
for l in lines:
    if l.startswith("RL\t"):
        _, f, n = l.split("\t", 2)
        removed.setdefault(f, set()).add(int(n))
ars = [l.split("\t", 3)[1:] for l in lines if l.startswith("AR\t")]
renamed = dict(l.split("\t", 2)[1:][::-1] for l in lines if l.startswith("RN\t"))   # new -> old
out = [l for l in lines if not l.startswith(("RA\t", "RL\t", "AR\t", "RN\t"))]

def git(*a):
    r = subprocess.run(("git", "-c", "core.quotePath=false") + a, capture_output=True)
    return r.stdout if r.returncode == 0 else None

# Bytes, split on \n only: that is how git numbers lines. Text mode turned a
# lone \r into a line break and shifted every span below it.
def text(b):
    return (b or b"").decode("utf-8", errors="replace")

def old_text(path):   # the side the diff removes from
    return text(git("show", ("HEAD:" if staged else ":") + path))

def new_text(path):   # the side the diff arrives at
    if staged:
        return text(git("show", ":" + path))
    try:
        with open(path, "rb") as fh:
            return text(fh.read())
    except OSError:
        return ""

PY = re.compile(r"^(\s*)(?:async\s+)?def\s+(test\w*)\s*\(")
GO = re.compile(r"^()func\s+(Test\w*)\s*\(")
JS = re.compile(r"^(\s*)(?:it|test)(?:\.only|\.skip)?\s*\(\s*([\x27\x22`])(.*?)\2")
RS = re.compile(r"^(\s*)(?:pub\s+)?(?:async\s+)?fn\s+(\w+)")
RS_ATTR = re.compile(r"^\s*#\[(?:[a-z_]+::)?test[\]()]")   # also #[tokio::test(flavor = …)]

def heads(path, text):
    """[(name, first_line, last_line, indent)] of the test heads in text, 1-based."""
    src = text.split("\n")
    found = []
    for i, s in enumerate(src):
        name = ind = None
        if path.endswith(".py"):
            m = PY.match(s)
            if m: ind, name = len(m.group(1)), m.group(2)
        elif path.endswith(".go"):
            m = GO.match(s)
            if m: ind, name = 0, m.group(2)
        elif re.search(r"\.(t|j)sx?$|\.mjs$|\.cjs$", path):
            m = JS.match(s)
            if m: ind, name = len(m.group(1)), m.group(3)
        elif path.endswith(".rs"):
            m = RS.match(s)
            if m:
                j = i - 1
                attr = False
                while j >= 0 and src[j].strip().startswith("#["):
                    if RS_ATTR.match(src[j]): attr = True
                    j -= 1
                if attr: ind, name = len(m.group(1)), m.group(2)
        if name is None:
            continue
        end = len(src)
        for k in range(i + 1, len(src)):
            t = src[k]
            if not t.strip():
                continue
            # spaces and tabs only: Python resets the column at a \f
            k_ind = len(t) - len(t.lstrip(" \t"))
            if k_ind <= ind:
                # the ) of a multi-line signature, or the closing brace of the
                # test, still belongs to it; anything else at its depth ends it
                if t.lstrip().startswith((")", "}")):
                    if t.lstrip().startswith(")") and path.endswith(".py"):
                        continue
                    end = k + 1
                else:
                    end = k
                break
        found.append((name, i + 1, end, ind))
    return found

changed = [p for p in text(git("diff", *(["--staged"] if staged else []), "--name-only", "-z")).split("\0") if p]

entries, notes = {}, {}
decl = os.environ.get("DECL", "")
for part in re.split(r";\s*(?=[^\s;:]+::)", decl):
    part = part.strip()
    if not part:
        continue
    m = re.match(r"^([^\s:]+)::(.+?)\s+—\s+\S", part)
    if not m:
        notes.setdefault(part.split("::")[0], []).append("declaration without a reason ignored: " + part)
        continue
    path, name = m.group(1), m.group(2).strip()
    old = [h for h in heads(path, old_text(path)) if h[0] == name]
    new = [h for h in heads(path, new_text(path)) if h[0] == name]
    moved = [f for f in changed if f != path and
             len([h for h in heads(f, new_text(f)) if h[0] == name]) >
             len([h for h in heads(f, old_text(f)) if h[0] == name])]
    if len(old) != 1:
        notes.setdefault(path, []).append(f"declared {path}::{name} ignored: {len(old)} tests of that name in the old file")
    elif new:
        notes.setdefault(path, []).append(f"declared {path}::{name} ignored: its head is still there — the diff adds its head again or never removed it")
    elif moved:
        notes.setdefault(path, []).append(f"declared {path}::{name} ignored: a test of that name appears in {moved[0]}")
    else:
        a, b = old[0][1], old[0][2]
        src = old_text(path).split("\n")
        # One test, not two: a span that holds the head of another test was
        # guessed too wide (odd indentation), and deleting it would take a test
        # nobody declared (adversarial review, 2026-09-25).
        inner = [h for h in heads(path, old_text(path)) if a < h[1] <= b]
        if inner:
            notes.setdefault(path, []).append(
                f"declared {path}::{name} ignored: its old span holds another test ({inner[0][0]}, line {inner[0][1]})")
            continue
        kept = [n for n in range(a, b + 1)
                if n - 1 < len(src) and src[n - 1].strip() and n not in removed.get(path, set())]
        # The whole test goes: every line of its old body is a deleted line. A
        # span that was guessed too wide (a head in a comment or a string, a \r
        # or \f that fooled the count) keeps lines of the next test and fails here.
        if kept:
            notes.setdefault(path, []).append(
                f"declared {path}::{name} ignored: line {kept[0]} of its old body is not deleted — the whole test does not go")
        else:
            entries[(path, name)] = (a, b)

# A return that ends a test early (bare, or with None, undefined, Ok(()))
# counts inside the span of a test in the NEW file only; a helper next to the
# tests may return early. So may a function nested in the test (a stub, a
# callback): its return ends that function, not the test. A Go subtest (t.Run)
# is no such function, a return there ends the subtest. And a return with no
# code of the test after it ends nothing.
# Per language: a string "function", a vi.fn( or a Rust match arm `=> {` is no
# function of its own.
NESTED = {
    "py": re.compile(r"^\s*(async\s+)?def\s"),
    "js": re.compile(r"\bfunction\s*\*?\s*[\w$]*\s*\(|=>\s*\{\s*$"),
    "rs": re.compile(r"\bfn\s+\w|\|[^|]*\|\s*(->\s*[^{]*)?\{\s*$"),
    "go": re.compile(r"\bfunc\b"),
}
SUBTEST = re.compile(r"\bt\.Run\(")


def lang(path):
    if path.endswith(".py"):
        return "py"
    if path.endswith(".go"):
        return "go"
    if path.endswith(".rs"):
        return "rs"
    return "js" if re.search(r"\.(t|j)sx?$|\.mjs$|\.cjs$", path) else None


def code(s):
    t = s.strip()
    return bool(t) and not t.startswith(("#", "//")) and bool(t.strip(")]};,"))


def depth(s):
    return len(s) - len(s.lstrip(" \t"))


def ends_test_early(src, a, b, n, nested):
    # Walk the openers above the return, each one less indented than the last,
    # up to the head of the test; a closer line (`) -> None:`, `} else {`)
    # opens nothing of its own.
    cur = depth(src[n - 1])
    for k in range(n - 1, a, -1):
        s = src[k - 1]
        if not code(s) or s.lstrip().startswith((")", "]", "}")):
            continue
        if depth(s) < cur:
            if nested and nested.search(s) and not SUBTEST.search(s):
                return False
            cur = depth(s)
    return any(code(src[k - 1]) for k in range(n + 1, b + 1))


spans = {}
for path, newno, ln in ars:
    if path not in spans:
        src = new_text(path)
        spans[path] = (src.split("\n"), heads(path, src))
    lines, found = spans[path]
    n = int(newno)
    if any(a < n <= b and ends_test_early(lines, a, b, n, NESTED.get(lang(path))) for _, a, b, _ in found):
        out.append(f"{path}:{newno}  early return in a test: {ln}")

# R-0130: a removed assertion counts where tests are — in a test file, or in
# the span of a test in the OLD file (Rust keeps tests inline under src/) —
# and an import line never is one (`use pretty_assertions::assert_eq;`).
# Production code may lose an assert or an .expect( without silencing a test.
TEST_PATH = re.compile(r"(^|/)(tests|e2e)/|(^|/)test_[^/]*[.]py$|_test[.](py|go|sh)$|[.](test|spec)[.][^/]+$")
IMPORT = re.compile(r"^(use|import)[ \t]|^from[ \t]+[^ \t]+[ \t]+import[ \t]")
old_spans = {}

def where_tests_are(path, n):
    old = renamed.get(path, path)
    if TEST_PATH.search(path) or TEST_PATH.search(old):
        return True
    if old not in old_spans:
        old_spans[old] = heads(old, old_text(old))
    return any(a <= n <= b for _, a, b, _ in old_spans[old])

ras = [r for r in ras if not IMPORT.match(r[2]) and where_tests_are(r[0], int(r[1]))]

used = set()
for path, oldno, text in ras:
    n = int(oldno)
    hit = [k for k, (a, b) in entries.items() if k[0] == path and a <= n <= b]
    if hit:
        used.add(hit[0])
    else:
        why = "; ".join(notes.get(path, []))
        out.append(f"{path}:{oldno}  removed assertion: {text}" + (f"  ({why})" if why else ""))
for k in sorted(used):
    out.append(f"DECLARED\t{k[0]}::{k[1]}")
print("\n".join(out))
')" || die "could not judge the removed assertions"
    GONE="$(printf '%s\n' "$FOUND" | sed -n 's/^DECLARED\t//p' | sort)"
    FOUND="$(printf '%s\n' "$FOUND" | grep -v '^DECLARED' | grep -v '^$')"
    if [ -n "$FOUND" ]; then
      echo "review.sh diff-scan: the diff changes what a green run means" >&2
      printf '%s\n' "$FOUND" >&2
      echo "  (deliberate? append '# review: ok <reason>' to the line; a whole test that" >&2
      echo "   goes with dead code: 'Test-Löschung: <file>::<test> — <reason>' in the task," >&2
      echo "   committed before the deletion — the working-tree ledger does not count)" >&2
      exit 3
    fi
    if [ -n "$GONE" ]; then
      echo "diff-scan: clean ($(grep -c . <<<"$GONE") declared test deletion(s): $(paste -sd, - <<<"$GONE" | sed 's/,/, /g'))"
    else
      echo "diff-scan: clean"
    fi
    ;;

  scope)
    LEDGER="${ARGS[0]-}"; ID="${ARGS[1]-}"
    [ -n "$LEDGER" ] && [ -n "$ID" ] || die "scope needs <ledger> <id>"
    case "$ID" in *[!A-Za-z0-9._-]*) die "not a task id: $ID" ;; esac
    case "$LEDGER" in */*) ;; *) LEDGER="tasks/$LEDGER" ;; esac
    case "$LEDGER" in *.md) ;; *) LEDGER="$LEDGER.md" ;; esac
    [ -f "$LEDGER" ] || die "no such ledger: $LEDGER"
    LINE="$(L_ID="$ID" awk '
      BEGIN { id = ENVIRON["L_ID"] }
      $0 ~ "^###[ \t]+" id "([ \t]|$)" { insec = 1; next }
      insec && /^Komponente:/ { print; exit }
      insec && (/^###[ \t]/ || /^## /) { exit }' "$LEDGER")"
    [ -n "$LINE" ] || die "no task $ID in $LEDGER (or it has no Komponente: line)"
    KOMP="$(sed -n 's/^Komponente:[[:space:]]*\([^·]*\).*/\1/p' <<<"$LINE" | tr -d ' ')"
    # "scripts/dev/x.sh (neu, SPDX), scripts/tests/y.sh" -> the bare paths. The
    # notes in parentheses go FIRST: they carry commas of their own.
    DECLARED="$(sed -n 's/.*Dateien:[[:space:]]*//p' <<<"$LINE" \
      | sed 's/([^)]*)//g' | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]].*//' | grep -v '^$')"
    # What a task may touch without saying so. Kept apart from DECLARED on
    # purpose: a harness path passes only through the declared list, never
    # through this one — `scripts/tests/` as "the component's tests" used to
    # wave through run.sh and the gates' own test files.
    IMPLICIT="$(component_tests "$KOMP" | tr ' ' '\n')
docs/
CHANGELOG.md
$LEDGER"
    ALLOW="$DECLARED
$IMPLICIT"

    # The harness list, if it is there: these paths change the RULES a run obeys,
    # so they need naming, not a category. A checkout without the file (another
    # repo, an old worktree) falls back to the plain scope check rather than
    # refusing everything — the same fail-open the guard hook uses for it.
    HARNESS=""
    [ -f "$ROOT/scripts/dev/harness-paths.txt" ] \
      && HARNESS="$(grep -v '^[[:space:]]*#' "$ROOT/scripts/dev/harness-paths.txt" | grep -v '^[[:space:]]*$')"
    matches_any() {  # matches_any <path> <newline-separated patterns>
      local p="$1" a
      while IFS= read -r a; do
        [ -n "$a" ] || continue
        case "$a" in
          */) case "$p" in "$a"*) return 0 ;; esac ;;
          *\**)
            # shellcheck disable=SC2254  # an entry with * IS a pattern
            case "$p" in $a) return 0 ;; esac ;;
          *) [ "$p" = "$a" ] && return 0 ;;
        esac
      done <<< "$2"
      return 1
    }

    FOREIGN=()
    while IFS= read -r p; do
      [ -n "$p" ] || continue
      # A harness path is in scope only when the task declares it by name.
      if [ -n "$HARNESS" ] && matches_any "$p" "$HARNESS" && ! matches_any "$p" "$DECLARED"; then
        FOREIGN+=("$p (harness path — name it in Dateien:)")
      elif ! matches_any "$p" "$ALLOW"; then
        FOREIGN+=("$p")
      fi
    done <<< "$(changed_paths)"

    if [ "${#FOREIGN[@]}" -gt 0 ]; then
      echo "review.sh scope: paths outside task $ID of $LEDGER:" >&2
      printf '  %s\n' "${FOREIGN[@]}" >&2
      echo "  (belongs to the task? bash scripts/dev/ledger.sh set-files $LEDGER $ID <path…>)" >&2
      exit 3
    fi
    echo "scope: clean ($ID, component ${KOMP:-?})"
    ;;

  sec)
    # Fail closed. tasks/private/ is gitignored, but `git add -f` would take it,
    # and this repo is public (CLAUDE.md §2).
    BLOCKED=()
    while IFS= read -r p; do
      case "$p" in
        # The private roadmap and the security ledgers — and the two files that
        # actually carry credentials on this box: the Proxmox token lives in
        # .claude/settings.local.json (CLAUDE.md §8) and the database password
        # in .devenv.sh. Both are gitignored, and both would be taken by an
        # `git add -f` or a helpful editor.
        tasks/private/*|tasks/sec-*.md|docs/features/sec-*.md) BLOCKED+=("$p") ;;
        .claude/settings.local.json|.devenv.sh|*/.devenv.sh) BLOCKED+=("$p (carries credentials)") ;;
      esac
    done <<< "$(changed_paths)"
    # awk, not `grep -q`: grep leaves the pipeline the moment it matches, git
    # diff dies of SIGPIPE, and with `set -o pipefail` the hit turned into a
    # clean bill of health for every diff larger than the pipe buffer. It also
    # names the line, because "somewhere in this diff" is not actionable.
    while IFS= read -r hit; do
      [ -n "$hit" ] && BLOCKED+=("$hit (a security finding's Dedup-Key)")
    done <<< "$("${GIT_DIFF[@]}" "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" | awk '
      # Headers only before the first @@ of a file: `++ x` added reads `+++ x`.
      /^diff --git /             { inheader = 1; next }
      inheader && /^\+\+\+ / { file = substr($0, 5); sub(/^b\//, "", file); sub(/\t$/, "", file); next }
      /^@@/       { inheader = 0; split($3, nw, ","); newno = nw[1]; sub(/^\+/, "", newno); newno += 0; next }
      inheader    { next }
      /^\+/       { if ($0 ~ /Dedup-Key:[[:space:]]*sec:/) printf "%s:%d\n", file, newno; newno++; next }
      /^-/        { next }
                  { newno++ }')"
    if [ "${#BLOCKED[@]}" -gt 0 ]; then
      echo "review.sh sec: this repo is public — refusing:" >&2
      printf '  %s\n' "${BLOCKED[@]}" >&2
      exit 4
    fi
    echo "sec: clean"
    ;;

  check-verdict)
    FILE="${ARGS[0]-}"
    [ -n "$FILE" ] && [ -n "$TREE_ARG" ] || die "check-verdict needs <file> --tree <hash>"
    case "$FILE" in /*) ;; *) FILE="$CALLER_PWD/$FILE" ;; esac
    [ -f "$FILE" ] || die "no such verdict file: $FILE"
    SCHEMA="$ROOT/scripts/dev/review-verdict.schema.json"
    [ -f "$SCHEMA" ] || die "no verdict schema: $SCHEMA"
    command -v python3 >/dev/null 2>&1 || die "check-verdict needs python3"
    python3 - "$FILE" "$SCHEMA" "$TREE_ARG" <<'PY'
import json, re, sys

# The keywords the schema uses, checked with python3 alone: the runner has no
# jsonschema package, and a verdict is too small to need one.
TYPES = {"object": dict, "array": list, "string": str, "integer": int,
         "number": (int, float), "boolean": bool, "null": type(None)}


def is_type(v, t):
    # bool is an int to python, not to JSON.
    if t in ("integer", "number") and isinstance(v, bool):
        return False
    return isinstance(v, TYPES[t])


def check(v, s, where, errs):
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(is_type(v, t) for t in ts):
            errs.append("%s: not %s" % (where, " or ".join(ts)))
            return
    if "enum" in s and v not in s["enum"]:
        errs.append("%s: %r is none of %s" % (where, v, ", ".join(s["enum"])))
    if "const" in s and v != s["const"]:
        errs.append("%s: %r, not %r" % (where, v, s["const"]))
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0):
            errs.append("%s: empty" % where)
        # ECMA `$` ends the string; python lets it match before a final newline.
        if "pattern" in s and (not re.search(s["pattern"], v)
                               or s["pattern"].endswith("$") and v.endswith("\n")):
            errs.append("%s: %r does not match %s" % (where, v, s["pattern"]))
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v < s.get("minimum", v):
        errs.append("%s: below %s" % (where, s["minimum"]))
    if isinstance(v, dict):
        props = s.get("properties", {})
        for k in s.get("required", []):
            if k not in v:
                errs.append("%s.%s: missing" % (where, k))
        for k, x in v.items():
            if k in props:
                check(x, props[k], "%s.%s" % (where, k), errs)
            elif s.get("additionalProperties") is False:
                errs.append("%s.%s: not in the schema" % (where, k))
    if isinstance(v, list) and "items" in s:
        for i, x in enumerate(v):
            check(x, s["items"], "%s[%d]" % (where, i), errs)


path, schema_path, tree = sys.argv[1:4]
try:
    d = json.load(open(path))
except Exception as e:
    print("check-verdict: unreadable verdict: %s" % e, file=sys.stderr)
    sys.exit(2)
try:
    schema = json.load(open(schema_path))
except Exception as e:
    print("check-verdict: unreadable schema %s: %s" % (schema_path, e), file=sys.stderr)
    sys.exit(2)
errs = []
check(d, schema, "verdict", errs)
if errs:
    print("check-verdict: outside review-verdict.schema.json:", file=sys.stderr)
    for e in errs:
        print("  " + e, file=sys.stderr)
    sys.exit(2)
# A verdict about another tree says nothing about this one.
if d["tree_hash"] != tree:
    print("check-verdict: the verdict is for tree %s, the staged tree is %s" % (d["tree_hash"], tree),
          file=sys.stderr)
    sys.exit(4)
counts = {"blocker": 0, "wichtig": 0, "nit": 0}
for f in d["findings"]:
    sev = f["severity"]
    if sev == "blocker" and not f.get("evidence", "").strip():
        print("check-verdict: a blocker without evidence counted as nit: %s:%s %s"
              % (f["file"], f.get("line") or "", f["claim"]), file=sys.stderr)
        sev = "nit"
    counts[sev] += 1
if d["verdict"] != "approve":
    print("check-verdict: the verdict is %s, not approve" % d["verdict"], file=sys.stderr)
    sys.exit(3)
if counts["blocker"]:
    print("check-verdict: an approve with %d blocker(s) is no approve" % counts["blocker"], file=sys.stderr)
    sys.exit(3)
probe = d.get("probe") or {}
if probe.get("applicable") and probe.get("red_without_change") is not True:
    print("check-verdict: an approve although the probe found the new test green without the change",
          file=sys.stderr)
    sys.exit(3)
noted = ", ".join("%d %s" % (n, k) for k, n in counts.items() if n)
print("approve (%s/%s%s)" % (d["reviewer"]["model"], d["reviewer"]["effort"], "; " + noted if noted else ""))
PY
    ;;

  risk)
    [ "${#ARGS[@]}" -eq 0 ] || die "risk takes no operand (only --staged or --range <a>..<b>)"
    # Both lists as HEAD, the index and the worktree have them, all together —
    # and for a range as its start has them: a diff that strikes a line (or the
    # whole harness list) must not judge itself by the version it brings along.
    PATTERNS=""
    for f in scripts/dev/review-risk.txt scripts/dev/harness-paths.txt; do
      LIST="$(git show "HEAD:$f" 2>/dev/null; git show ":$f" 2>/dev/null; cat "$ROOT/$f" 2>/dev/null
              [ -z "$RANGE" ] || git show "${RANGE%%..*}:$f" 2>/dev/null)"
      [ -n "$LIST" ] || die "no $f in HEAD, the index or the worktree"
      PATTERNS+="$LIST"$'\n'
    done
    PATTERNS="$(grep -v '^[[:space:]]*#' <<<"$PATTERNS" | grep -v '^[[:space:]]*$' | sort -u)"
    # --no-renames: a moved file counts by where it came from as well, or a
    # refactor that carries auth code out of its directory reads as standard.
    # -z: a name git would quote (`"`, `\`, a control character) stays a name.
    CHANGED="$("${GIT_DIFF[@]}" "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" --name-only --no-renames -z | tr '\0' '\n'; exit "${PIPESTATUS[0]}")" \
      || die "could not read the diff"
    HITS=()
    while IFS= read -r p; do
      [ -n "$p" ] || continue
      while IFS= read -r pat; do
        # shellcheck disable=SC2254  # the list IS patterns
        case "$p" in $pat) HITS+=("$p"); break ;; esac
      done <<< "$PATTERNS"
    done <<< "$CHANGED"
    if [ "${#HITS[@]}" -gt 0 ]; then
      echo xhigh
      printf '  %s\n' "${HITS[@]}"
    else
      echo standard
    fi
    ;;

  -h|--help) usage ;;
  "") echo "review.sh needs a verb" >&2; usage >&2; exit 2 ;;
  *)  echo "unknown verb: $VERB" >&2; usage >&2; exit 2 ;;
esac
