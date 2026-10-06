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
#   bash scripts/dev/review.sh sec [--staged | --range <a>..<b> [--not-on <remote>] | --message <file>]
#                                                       what must never be committed or pushed
#                                                       (names a path or file:line, never a line's
#                                                       content: its output may stand in a public CI log)
#   bash scripts/dev/review.sh check-verdict <file> --tree <hash> [--task <ledger> <id>]
#                                                       a reviewer's verdict JSON
#   bash scripts/dev/review.sh risk [--staged | --range <a>..<b>]
#                                                       which reviewer a diff gets
#   bash scripts/dev/review.sh docs-pairs [--staged]    a docs page in one language
#   bash scripts/dev/review.sh contracts [--staged] [--list]
#                                                       the checks a changed path pulls in
#   bash scripts/dev/review.sh pr-body <ledger> [--verdicts <dir>]
#                                                       the PR text out of the ledger
#   bash scripts/dev/review.sh log [--ledger <ledger>]  the reviewer runs, with a sum
#   bash scripts/dev/review.sh log --append <verdict>
#   bash scripts/dev/review.sh log --failed "<reason>" --task <ledger> <id> --round <n> [--tree <hash>]
#                                                       one run into the log (task-close.sh)
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
#              its test can leave together. And a fourth: an assertion out of a
#              test that STAYS, when the task declares that change in an
#              `Assertion-Änderung: <file>::<test> — <reason>` line, the test is
#              there exactly once before and after, and its new body gains at
#              least as many assertions as it loses (R-0206). Any other assertion
#              out of a test that stays is still a finding.
#   scope      does the diff stay inside the files the task declared? Everything
#              else is either a forgotten `ledger.sh set-files` or a drive-by.
#   sec        is something staged that this public repo must never hold — the
#              private roadmap, a security ledger, a finding's dedup key, one
#              of the two gitignored files that carry credentials, or a line
#              with a token pattern (Proxmox, GitHub, Anthropic). With --message,
#              the message of the commit being made (the commit-msg hook).
#   check-verdict  is a reviewer's verdict usable for this tree? It has to follow
#              scripts/dev/review-verdict.schema.json, be about the tree --tree
#              names, and say approve without a blocker and without a probe
#              that found the new test green without the change; with --task,
#              also be about that task (another one exits 4). A blocker without
#              evidence counts as a nit; a probe that did not apply (no test
#              changed: a refactor) is no obstacle; a surviving mutant is named.
#              Prints the review line that task-close.sh writes into the ledger.
#   risk       does the diff touch a risk path (scripts/dev/review-risk.txt and
#              the harness paths)? Prints `xhigh` and the paths it hit, or
#              `standard`; both exit 0. The reviewer model follows from it.
#              Without a flag it judges everything not committed yet — staged,
#              unstaged and untracked: at the review step nothing is staged.
#   docs-pairs does every changed docs page bring its other language along?
#              The other page is the one the page's lang-switch links to (not
#              a name rule: admin/benutzer.html is en/admin/users.html); pages
#              without a switch and everything that is no html are outside.
#   contracts  the checks scripts/dev/review-contracts.txt ties to the changed
#              paths: a test of a component (through verify.sh, with an
#              AH_OUT_DIR of its own so the builder's last-verify.json stays) or
#              a pair of files that must carry the same value. --list names
#              them without running them. Prints `contracts: <n> ok` or
#              `contracts: none`.
#   pr-body    Markdown for the PR: the ledger head (spec, roadmap ids, heavy
#              line), each task with its box, Evidenz: and Review: lines and —
#              with --verdicts <dir> — the verdict in <dir>/<id>.json; [~] and
#              [?] tasks apart; in <dir> a task's verdict is <id>.json or, from
#              the reviewer process, its last <id>.r<n>.verdict.json, held by
#              check-verdict itself (to its own tree and task): one outside
#              the schema reads "ungültig", one without a usable approve says
#              so. A task without evidence reads "unverifiziert", never
#              approve. Addresses, host names and VMIDs are cut out of every
#              ledger line it copies: this text goes to a public repo.
#
#   log        one JSONL line per reviewer run in .ah-out/review/review-log.jsonl
#              (date, ledger, task, round, model, effort, verdict, blocker,
#              wichtig, nit, probe, mutants set and killed, cost_usd, num_turns,
#              duration_s, tree): --append takes a verdict check-verdict
#              accepts, --failed a run that gave none (verdict "failed", the
#              reason, and cost, turns and duration out of its raw answer when
#              there is one). Without either it prints the runs as a table and
#              a sum line `N runs, A approve, R request_changes, F failed, $X,
#              T turns, S s`, with --ledger only that ledger's.
#
# --staged looks at the index (what task-close.sh is about to commit); without it
# the working tree is compared against the index. Neither form sees UNTRACKED files —
# git diff does not — so the answer for a brand-new file exists only once it is
# staged, which is the state task-close.sh works on anyway.
#
# Exit: 0 clean · 2 usage (check-verdict: unreadable or outside the schema) ·
# 3 findings (diff-scan, scope, docs-pairs, contracts; check-verdict: no usable approve) · 4 blocked
# (sec; check-verdict: a verdict for another tree or another task) · 74 a contract test that
# could not run

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
TASK_LEDGER="" TASK_ID="" TREE_ARG="" RANGE="" NOT_ON="" LIST_ONLY=0 VERDICTS="" APPEND="" FAILED="" FAILED_SET=0 ROUND_ARG="" LOG_LEDGER="" MESSAGE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --staged) STAGED=1 ;;
    --list) LIST_ONLY=1 ;;
    --verdicts)
      [ $# -ge 2 ] || die "--verdicts needs <dir>"
      VERDICTS="$2"; shift ;;
    --append)
      [ $# -ge 2 ] || die "--append needs <verdict>"
      APPEND="$2"; shift ;;
    --failed)
      [ $# -ge 2 ] || die "--failed needs <reason>"
      FAILED="$2"; FAILED_SET=1; shift ;;
    --round)
      [ $# -ge 2 ] || die "--round needs <n>"
      ROUND_ARG="$2"; shift ;;
    --ledger)
      [ $# -ge 2 ] || die "--ledger needs <ledger>"
      LOG_LEDGER="$2"; shift ;;
    --tree)
      [ $# -ge 2 ] || die "--tree needs <hash>"
      TREE_ARG="$2"; shift ;;
    --not-on)
      [ $# -ge 2 ] || die "--not-on needs <remote>"
      case "$2" in -*|'') die "not a remote: $2" ;; esac
      NOT_ON="$2"; shift ;;
    --range)
      [ $# -ge 2 ] || die "--range needs <a>..<b>"
      case "$2" in -*|'') die "not a range: $2" ;; *..*) ;; *) die "not a range (<a>..<b>): $2" ;; esac
      RANGE="$2"; shift ;;
    --message)
      [ $# -ge 2 ] || die "--message needs <file>"
      # An empty name would leave MESSAGE unset and fall through to sec over the
      # worktree, which may well say clean.
      [ -n "$2" ] || die "--message needs a file name, got an empty one"
      MESSAGE="$2"; shift ;;
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
if [ -n "$MESSAGE" ]; then
  [ "$VERB" = sec ] || die "--message is for sec alone"
  # Relative to where the caller stands, as for check-verdict: the hook passes a
  # path git resolved, a call by hand may come from a subdirectory.
  case "$MESSAGE" in /*) ;; *) MESSAGE="$CALLER_PWD/$MESSAGE" ;; esac
  [ "$STAGED" = 0 ] && [ -z "$RANGE" ] || die "--message stands alone, without --staged or --range"
  [ -f "$MESSAGE" ] && [ -r "$MESSAGE" ] || die "--message: no readable file $MESSAGE"
fi
[ -z "$NOT_ON" ] || [ -n "$RANGE" ] || die "--not-on needs --range"
if [ -n "$RANGE" ]; then
  # The other verbs judge what is about to be committed; a range is history.
  case "$VERB" in risk|sec) ;; *) die "--range is for risk and sec alone" ;; esac
  [ -z "$NOT_ON" ] || [ "$VERB" = sec ] || die "--not-on is for sec --range alone"
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
    # The tests the task declares as deleted (Test-Löschung) or as changed
    # (Assertion-Änderung) — read from the COMMITTED ledger
    # (HEAD), never from the working tree: a builder must not be able to grant
    # itself the exception in the same run (Kevin, 2026-09-25). The declaration
    # typically arrives with the plan commit at the gate. Only with --task: a
    # call by hand has no task to speak for it and stays strict.
    DECL=""
    DECL_CHG=""
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
        DECL_CHG="$(task_field "$COMMITTED" "$TASK_ID" "Assertion-Änderung")"
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
      # assert, the Rust macros assert_{eq,ne,matches,…}!, expect( of vitest/jest,
      # and in a Go test file the calls on its testing.T t — outside one, a t is
      # just a name.
      function is_assert(s, f) {
        return s ~ /(^|[^A-Za-z_.])assert(_[a-z]+)?!?([^A-Za-z_]|$)/ || s ~ /expect\(/ ||
               (f ~ /_test\.go$/ && s ~ /(^|[^A-Za-z0-9_.])t\.(Fatal|Fatalf|Error|Errorf|Fail|FailNow)\(/)
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
                        # Whether the line stood where tests are is the judge below.
                        if (line !~ /review: ok/ && is_assert(line, file))
                          printf "RA\t%s\t%d\t%s\n", file, oldno, trim(line)
                        oldno++; next
                      }
      /^\+/           {
                        line = substr($0, 2)
                        sub(/\r$/, "", line)
                        # An added assertion, not a line that only comments: what a
                        # declared change has to bring back, counted below.
                        if (is_assert(line, file) && line !~ /^[ \t]*(#|\/\/|\/\*|\*)/)
                          printf "AA\t%s\t%d\t%s\n", file, newno, trim(line)
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
    # line number lies inside the old span of such a test. A declared change
    # (R-0206) counts only if the name is a test head exactly once in the old AND
    # in the new version, neither span holds another head and the file is not
    # renamed; its removed assertions pass when its new span gains at least as
    # many added ones.
    FOUND="$(printf '%s\n' "$RAW" | DECL="$DECL" DECL_CHG="$DECL_CHG" STAGED="$STAGED" python3 -c '
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
aas = [l.split("\t", 3)[1:] for l in lines if l.startswith("AA\t")]
renamed = dict(l.split("\t", 2)[1:][::-1] for l in lines if l.startswith("RN\t"))   # new -> old
out = [l for l in lines if not l.startswith(("RA\t", "RL\t", "AR\t", "AA\t", "RN\t"))]

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


def declared(decl):
    """(path, name) of each declaration that carries a reason; the others become notes."""
    for part in re.split(r";\s*(?=[^\s;:]+::)", decl):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^([^\s:]+)::(.+?)\s+—\s+\S", part)
        if not m:
            notes.setdefault(part.split("::")[0], []).append("declaration without a reason ignored: " + part)
            continue
        yield m.group(1), m.group(2).strip()


for path, name in declared(os.environ.get("DECL", "")):
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

# Declared changes (R-0206): an assertion may leave a test that STAYS. The test
# is there exactly once before and after (a name that two classes or describe
# blocks share cannot be told apart), neither span holds the head of another
# test (a span guessed too wide by odd indentation), and the file is not renamed
# in this diff. Whether its new body brings back enough assertions is counted
# below, against the removed ones that count.
changes = {}
for path, name in declared(os.environ.get("DECL_CHG", "")):
    what = f"declared change {path}::{name} ignored"
    if path in renamed or path in renamed.values():
        notes.setdefault(path, []).append(f"{what}: the file is renamed in this diff")
        continue
    old_h, new_h = heads(path, old_text(path)), heads(path, new_text(path))
    old = [h for h in old_h if h[0] == name]
    new = [h for h in new_h if h[0] == name]
    if len(old) != 1 or len(new) != 1:
        notes.setdefault(path, []).append(
            f"{what}: {len(old)} tests of that name in the old file and {len(new)} in the new one, it must be one in each")
        continue
    (a, b), (c, d) = old[0][1:3], new[0][1:3]
    inner = [h for h in old_h if a < h[1] <= b] + [h for h in new_h if c < h[1] <= d]
    if inner:
        notes.setdefault(path, []).append(f"{what}: its span holds another test ({inner[0][0]}, line {inner[0][1]})")
        continue
    changes[(path, name)] = (a, b, c, d)

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

# A declared change covers the removed assertions of its old span only when its
# new span gains at least as many (n >= r): changed, not taken away.
covered = {}
for k, (a, b, c, d) in changes.items():
    r = sum(1 for p, o, _ in ras if p == k[0] and a <= int(o) <= b)
    n = sum(1 for p, o, _ in aas if p == k[0] and c <= int(o) <= d)
    if r and n >= r:
        covered[k] = (a, b, r, n)
    elif r:
        notes.setdefault(k[0], []).append(
            f"declared change {k[0]}::{k[1]} ignored: {n} assertion(s) added in its new body, {r} removed")

used, changed = set(), set()
for path, oldno, text in ras:
    n = int(oldno)
    hit = [k for k, (a, b) in entries.items() if k[0] == path and a <= n <= b]
    chg = [k for k, (a, b, _, _) in covered.items() if k[0] == path and a <= n <= b]
    if hit:
        used.add(hit[0])
    elif chg:
        changed.add(chg[0])
    else:
        why = "; ".join(notes.get(path, []))
        out.append(f"{path}:{oldno}  removed assertion: {text}" + (f"  ({why})" if why else ""))
for k in sorted(used):
    out.append(f"DECLARED\t{k[0]}::{k[1]}")
for k in sorted(changed):
    out.append(f"CHANGED\t{k[0]}::{k[1]} ({covered[k][2]} removed, {covered[k][3]} added)")
print("\n".join(out))
')" || die "could not judge the removed assertions"
    GONE="$(printf '%s\n' "$FOUND" | sed -n 's/^DECLARED\t//p' | sort)"
    CHG="$(printf '%s\n' "$FOUND" | sed -n 's/^CHANGED\t//p' | sort)"
    FOUND="$(printf '%s\n' "$FOUND" | grep -v -e '^DECLARED' -e '^CHANGED' | grep -v '^$')"
    if [ -n "$FOUND" ]; then
      echo "review.sh diff-scan: the diff changes what a green run means" >&2
      printf '%s\n' "$FOUND" >&2
      echo "  (deliberate? append '# review: ok <reason>' to the line; a whole test that" >&2
      echo "   goes with dead code: 'Test-Löschung: <file>::<test> — <reason>' in the task;" >&2
      echo "   an assertion changed in a test that stays: 'Assertion-Änderung: <file>::<test>" >&2
      echo "   — <reason>'; either committed before the change — the working-tree ledger does not count)" >&2
      exit 3
    fi
    # Each entry of a change carries a comma of its own, so the lists are joined with "; ".
    DONE=""
    [ -z "$GONE" ] || DONE="$(grep -c . <<<"$GONE") declared test deletion(s): $(paste -sd, - <<<"$GONE" | sed 's/,/, /g')"
    [ -z "$CHG" ] || DONE="${DONE:+$DONE; }$(grep -c . <<<"$CHG") declared assertion change(s): $(awk 'NR > 1 { printf "; " } { printf "%s", $0 }' <<<"$CHG")"
    if [ -n "$DONE" ]; then
      echo "diff-scan: clean ($DONE)"
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
    # and this repo is public (CLAUDE.md §2). The findings name a path or a
    # file:line and never the content of a line, so they may stand in a public
    # CI log.
    BLOCKED=()
    # sec_path <path> <tag> — the files that must never leave.
    sec_path() {
      case "$1" in
        # The private roadmap and the security ledgers — and the two files that
        # actually carry credentials on this box: the Proxmox token lives in
        # .claude/settings.local.json (CLAUDE.md §8) and the database password
        # in .devenv.sh. Both are gitignored, and both would be taken by an
        # `git add -f` or a helpful editor.
        tasks/private/*|tasks/sec-*.md|docs/features/sec-*.md) BLOCKED+=("$1$2") ;;
        .claude/settings.local.json|.devenv.sh|*/.devenv.sh) BLOCKED+=("$1$2 (carries credentials)") ;;
      esac
    }
    # Token shapes (R-0183) as their issuers write them: Proxmox USER@REALM!TOKENID=UUID
    # (Proxmox VE API wiki), the GitHub prefixes ghp_ gho_ ghu_ ghs_ ghr_ github_pat_
    # (docs.github.com, token formats) and sk-ant- (Anthropic keys and the setup-token;
    # in no doc, so not verified, taken from practice). A minimum length lets the
    # placeholders in code, docs and tests pass, and so does a body of at most two
    # different characters (xxxx…, 0000-…). No interval expressions: not every awk
    # knows them, so the length is RLENGTH.
    SEC_TOKEN_AWK='
      function plain(t,   i, c, seen, n) {
        n = 0
        for (i = 1; i <= length(t); i++) {
          c = substr(t, i, 1)
          if (c != "-" && c != "_" && !(c in seen)) { seen[c] = 1; n++ }
        }
        return n <= 2
      }
      function longrun(s, re, n, cut,   t, b) {
        while (match(s, re)) {
          t = substr(s, RSTART, RLENGTH); s = substr(s, RSTART + RLENGTH)
          if (length(t) >= n) { b = t; sub(cut, "", b); if (!plain(b)) return 1 }
        }
        return 0
      }
      function uuidish(u,   g) {
        return length(u) == 36 && split(u, g, "-") == 5 && length(g[1]) == 8 && length(g[5]) == 12 && !plain(u)
      }
      function pvetoken(s,   l, t, u) {
        # USER@REALM!TOKENID=UUID, the PBS form with a colon, and both URL-encoded
        # (%40, %21, %3D, %3A) are one pattern once the escapes are undone.
        l = s; gsub(/%40/, "@", l); gsub(/%21/, "!", l); gsub(/%3[Dd]/, "=", l); gsub(/%3[Aa]/, ":", l)
        while (match(l, /[A-Za-z0-9._-]+@[A-Za-z0-9._-]+![A-Za-z0-9._-]+[=:][0-9A-Fa-f-]+/)) {
          t = substr(l, RSTART, RLENGTH); l = substr(l, RSTART + RLENGTH)
          u = t; sub(/^.*[=:]/, "", u)
          if (uuidish(u)) return 1
        }
        # The secret alone behind a key name (api_token_secret, PVE_TOKEN_SECRET and
        # the like); a bare UUID without such a name is an ordinary id.
        l = tolower(s)
        while (match(l, /token_secret[^0-9a-z]*[:=][^0-9a-z]*[0-9a-f-]+/)) {
          t = substr(l, RSTART, RLENGTH); l = substr(l, RSTART + RLENGTH)
          # The filler may end in a hyphen, as in a shell default (:-UUID).
          u = t; sub(/^.*[^0-9a-f-]/, "", u); sub(/^-+/, "", u)
          if (uuidish(u)) return 1
        }
        return 0
      }
      function token(s) {
        return longrun(s, "(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]+", 34, "^gh._") ||
               longrun(s, "github_pat_[A-Za-z0-9_]+", 41, "^github_pat_") ||
               longrun(s, "sk-ant-[A-Za-z0-9_-]+", 27, "^sk-ant-([a-z]+[0-9]+-)?") || pvetoken(s)
      }
      function finding(a, file, n) {
        if (a ~ /Dedup-Key:[[:space:]]*sec:/) printf "%s:%d\tkey\n", file, n
        else if (token(a)) printf "%s:%d\ttoken\n", file, n
      }'
    # sec_hits <tag> — the lines the awk below printed, as findings: file:line and
    # what it is, never the line itself.
    sec_hits() {
      local hit kind
      while IFS=$'\t' read -r hit kind; do
        [ -n "$hit" ] || continue
        case "$kind" in
          token) BLOCKED+=("$hit$1 (a token pattern)") ;;
          *)     BLOCKED+=("$hit$1 (a security finding's Dedup-Key)") ;;
        esac
      done
    }
    # sec_scan <tag> <git diff args…> — what this diff adds that must never leave.
    sec_scan() {
      local tag="$1" p out
      shift
      # -z: --name-only C-quotes a path with `"` or `\` even with core.quotePath=false,
      # and a quoted `"tasks/private/…` matched no pattern. A git that cannot read the
      # change is no clean change: fail closed.
      out="$("${GIT_DIFF[@]}" "$@" --name-only -z | tr '\0' '\n')" || die "sec: git could not read this change"
      while IFS= read -r p; do sec_path "$p" "$tag"; done <<< "$out"
      # awk, not `grep -q`: grep leaves the pipeline the moment it matches, git
      # diff dies of SIGPIPE, and with `set -o pipefail` the hit turned into a
      # clean bill of health for every diff larger than the pipe buffer. It also
      # names the line, because "somewhere in this diff" is not actionable.
      out="$("${GIT_DIFF[@]}" "$@" | awk "$SEC_TOKEN_AWK"'
        # Headers only before the first @@ of a file: `++ x` added reads `+++ x`.
        /^diff --git /             { inheader = 1; next }
        inheader && /^\+\+\+ / { file = substr($0, 5); sub(/^b\//, "", file); sub(/\t$/, "", file); next }
        /^@@/       { inheader = 0; split($3, nw, ","); newno = nw[1]; sub(/^\+/, "", newno); newno += 0; next }
        inheader    { next }
        # "\ No newline at end of file" belongs to no side and counts no line.
        /^\\/       { next }
        /^\+/       { finding(substr($0, 2), file, newno); newno++; next }
        /^-/        { next }
                    { newno++ }')" || die "sec: git could not read this change"
      sec_hits "$tag" <<< "$out"
    }
    # sec_scan_merge <tag> <merge> — what the merge itself brings: the combined diff
    # shows only what differs from every parent, and a line counts only when it is
    # new against all of them. Against the first parent alone, a merge of main
    # would bring every public line of main along.
    MERGE_DIFF=(git -c core.quotePath=false diff-tree --no-commit-id -r --text --no-ext-diff --no-textconv --no-color)
    sec_scan_merge() {
      local tag="$1" c="$2" p out
      out="$("${MERGE_DIFF[@]}" -c --name-only -z "$c" | tr '\0' '\n')" || die "sec: git could not read merge $c"
      while IFS= read -r p; do sec_path "$p" "$tag"; done <<< "$out"
      out="$("${MERGE_DIFF[@]}" --cc -p "$c" | awk "$SEC_TOKEN_AWK"'
        /^diff --(cc|combined) /    { inheader = 1; next }
        inheader && /^\+\+\+ / { file = substr($0, 5); sub(/^b\//, "", file); sub(/\t$/, "", file); next }
        /^@@@/      { inheader = 0; np = 0; while (substr($0, np + 1, 1) == "@") np++; np--
                      for (i = 2; i <= NF; i++) if ($i ~ /^\+/) { split($i, nw, ","); newno = substr(nw[1], 2) + 0; break }
                      next }
        inheader    { next }
        # git does not print the no-newline marker in a combined diff today; should it
        # ever, the marker counts no line here either.
        /^\\/       { next }
        { pre = substr($0, 1, np); if (index(pre, "-")) next
          rest = pre; gsub(/\+/, "", rest)
          if (rest == "") finding(substr($0, np + 1), file, newno)
          newno++ }')" || die "sec: git could not read merge $c"
      sec_hits "$tag" <<< "$out"
    }
    # sec_scan_message <commit> — its message leaves with a push as well as its diff
    # (R-0183). Only for a span: at pre-commit there is no message yet.
    sec_scan_message() {
      local out
      out="$(git log -1 --format=%B "$1" | awk "$SEC_TOKEN_AWK"'
        { if (token($0)) printf "the commit message:%d\ttoken\n", NR }')" || die "sec: git could not read the message of $1"
      sec_hits " (commit ${1:0:12})" <<< "$out"
    }
    if [ -n "$MESSAGE" ]; then
      # The message of the commit being made (R-0197): before this, only a span
      # (pre-push, CI) read messages, when the commit already lay in the local
      # history. With commit -v git puts the diff below a scissors line, and that is
      # no part of the message. Comment lines are read: without an editor (-m, -F)
      # git keeps them in the commit.
      out="$(awk "$SEC_TOKEN_AWK"'
        /^# -+ >8 -+$/ { exit }
        { if (token($0)) printf "the commit message:%d\ttoken\n", NR }' "$MESSAGE")" \
        || die "sec: could not read the message $MESSAGE"
      sec_hits "" <<< "$out"
    elif [ -n "$RANGE" ]; then
      # A range is history, not a net change: a file added and removed again inside
      # it still leaves with a push. So every commit is read on its own — against its
      # parent (a root against the empty tree), a merge by what it brings itself;
      # `a...b` is the history since the merge base, as `git diff a...b` reads it.
      case "$RANGE" in
        *...*) BASE="$(git merge-base "${RANGE%%...*}" "${RANGE#*...}" 2>/dev/null)" \
                 || die "no merge base for $RANGE"
               SPAN="$BASE..${RANGE#*...}" ;;
        *)     SPAN="$RANGE" ;;
      esac
      EMPTY_TREE="$(git hash-object -t tree /dev/null)"
      # The empty tree on the left means "from the beginning": the whole history of
      # the right side (the pre-push hook for a new ref).
      [ "${SPAN%%..*}" = "$EMPTY_TREE" ] && SPAN="${SPAN#*..}"
      # --not-on <remote>: only what that remote does not have yet — a branch that
      # merged main brings main's commits into the span, and they are public already.
      NOT_ARGS=()
      [ -n "$NOT_ON" ] && NOT_ARGS=(--not --remotes="$NOT_ON")
      COMMITS="$(git rev-list --reverse "$SPAN" "${NOT_ARGS[@]+"${NOT_ARGS[@]}"}" 2>/dev/null)" \
        || die "not a range git knows: $RANGE"
      # "clean" is a verdict on commits read; a span without any has none. Exit 0
      # all the same: a push that brings no new commit is no refusal (pre-push).
      if [ -z "$COMMITS" ]; then
        echo "sec: empty span ($RANGE) — nothing read"
        exit 0
      fi
      while IFS= read -r c; do
        [ -n "$c" ] || continue
        if git rev-parse -q --verify "$c^2" >/dev/null 2>&1; then
          sec_scan_merge " (merge ${c:0:12})" "$c"
        else
          parent="$(git rev-parse -q --verify "$c^1" 2>/dev/null)" || parent="$EMPTY_TREE"
          sec_scan " (commit ${c:0:12})" "$parent" "$c"
        fi
        sec_scan_message "$c"
      done <<< "$COMMITS"
    else
      sec_scan "" "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}"
    fi
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
    python3 - "$FILE" "$SCHEMA" "$TREE_ARG" "$TASK_LEDGER" "$TASK_ID" <<'PY'
import json, os, re, sys

# The keywords the schema uses, checked with python3 alone: the runner has no
# jsonschema package, and a verdict is too small to need one.
TYPES = {"object": dict, "array": list, "string": str, "integer": int,
         "number": (int, float), "boolean": bool, "null": type(None)}


def is_type(v, t):
    # bool is an int to python, not to JSON.
    if t in ("integer", "number") and isinstance(v, bool):
        return False
    return isinstance(v, TYPES[t])


def same(a, b):
    # The same for enum and const: true is not 1, false is not 0.
    return a == b and isinstance(a, bool) == isinstance(b, bool)


def check(v, s, where, errs):
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(is_type(v, t) for t in ts):
            errs.append("%s: not %s" % (where, " or ".join(ts)))
            return
    if "enum" in s and not any(same(v, e) for e in s["enum"]):
        errs.append("%s: %r is none of %s" % (where, v, ", ".join(map(str, s["enum"]))))
    if "const" in s and not same(v, s["const"]):
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
    # Conditional parts: version 2 asks for more, a probe that did not apply
    # for its reason.
    for sub in s.get("allOf", []):
        check(v, sub, where, errs)
    if "if" in s:
        probe = []
        check(v, s["if"], where, probe)
        if not probe and "then" in s:
            check(v, s["then"], where, errs)


path, schema_path, tree, task_ledger, task_id = sys.argv[1:6]
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
# A verdict about another task says nothing about this one, even for the same
# tree (tree-hash.sh leaves tasks/ out).
if (task_ledger or task_id) and (os.path.normpath(d["task"]["ledger"]) != os.path.normpath(task_ledger)
                or d["task"]["id"] != task_id):
    print("check-verdict: the verdict is for %s %s, not for %s %s"
          % (d["task"]["ledger"], d["task"]["id"], task_ledger, task_id), file=sys.stderr)
    sys.exit(4)
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
noted = ["%d %s" % (n, k) for k, n in counts.items() if n]
noted += ["mutant survived: %s:%s" % (m["file"], m["line"]) for m in d.get("mutants", []) if m["result"] == "survived"]
# A probe that could not run proves nothing: the approve stands, but says so.
if probe and not probe.get("applicable") and probe.get("reason") not in ("no-test-change", "only-test-change"):
    noted.append("probe not run: %s" % probe.get("reason"))
print("approve (%s/%s%s)" % (d["reviewer"]["model"], d["reviewer"]["effort"], "; " + ", ".join(noted) if noted else ""))
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
    if [ "$STAGED" = 1 ] || [ -n "$RANGE" ]; then
      CHANGED="$("${GIT_DIFF[@]}" "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" --name-only --no-renames -z | tr '\0' '\n'; exit "${PIPESTATUS[0]}")" \
        || die "could not read the diff"
    else
      # Everything not committed yet: the review step comes before anything is
      # staged, and a new file (a migration, a script) is a path before git
      # knows it. An untracked scratch file read as xhigh is the safe side.
      CHANGED="$("${GIT_DIFF[@]}" HEAD --name-only --no-renames -z | tr '\0' '\n'; exit "${PIPESTATUS[0]}")" \
        || die "could not read the diff"
      CHANGED+=$'\n'"$(git ls-files --others --exclude-standard -z | tr '\0' '\n'; exit "${PIPESTATUS[0]}")" \
        || die "could not list the untracked files"
    fi
    HITS=()
    while IFS= read -r p; do
      [ -n "$p" ] || continue
      while IFS= read -r pat; do
        # An entry ending in / is a directory, as in scope's lists.
        case "$pat" in */) pat="$pat*" ;; esac
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

  docs-pairs)
    [ "${#ARGS[@]}" -eq 0 ] || die "docs-pairs takes no operand (only --staged)"
    CHANGED="$("${GIT_DIFF[@]}" "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" --name-only --no-renames -z | tr '\0' '\n'; exit "${PIPESTATUS[0]}")" \
      || die "could not read the diff"
    PAGES=()
    while IFS= read -r p; do
      case "$p" in docs/*.html) PAGES+=("$p") ;; esac
    done <<< "$CHANGED"
    [ "${#PAGES[@]}" -gt 0 ] || { echo "docs-pairs: clean"; exit 0; }
    command -v python3 >/dev/null 2>&1 || die "docs-pairs needs python3"
    MISSING="$(python3 - "$STAGED" "${PAGES[@]}" <<'PY'
import os, re, subprocess, sys

staged = sys.argv[1] == "1"
pages = sys.argv[2:]
SWITCH = re.compile(r'<div class="lang-switch"[^>]*>(.*?)</div>', re.S)
LINK = re.compile(r"<a\b([^>]*)>")


def content(path):
    # The side the diff arrives at; for a deleted page the side it leaves.
    for src in ([] if staged else [None]) + [":" + path, "HEAD:" + path]:
        if src is None:
            try:
                return open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
        r = subprocess.run(["git", "show", src], capture_output=True)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace")
    return ""


for page in pages:
    m = SWITCH.search(content(page))
    if not m:
        continue
    for attrs in LINK.findall(m.group(1)):
        href = re.search(r'href="([^"#?]*)', attrs)
        # The page itself (the active link) is no other page; a misplaced
        # is-active must not hide the real other language.
        if not href or not href.group(1) or "://" in href.group(1):
            continue
        other = os.path.normpath(os.path.join(os.path.dirname(page), href.group(1)))
        if other != page and other not in pages:
            print("%s -> %s" % (page, other))
PY
)" || die "docs-pairs could not read the pages"
    if [ -n "$MISSING" ]; then
      echo "review.sh docs-pairs: a docs page changes without its other language (.claude/rules/docs.md):" >&2
      sed 's/^/  /' <<<"$MISSING" >&2
      exit 3
    fi
    echo "docs-pairs: clean"
    ;;

  contracts)
    [ "${#ARGS[@]}" -eq 0 ] || die "contracts takes no operand (only --staged and --list)"
    F=scripts/dev/review-contracts.txt
    # As HEAD, the index and the worktree have the list (see risk): a diff that
    # strikes its own contract is still held to it.
    CLIST="$(git show "HEAD:$F" 2>/dev/null; git show ":$F" 2>/dev/null; cat "$ROOT/$F" 2>/dev/null)"
    [ -n "$CLIST" ] || die "no $F in HEAD, the index or the worktree"
    CHANGED="$("${GIT_DIFF[@]}" "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" --name-only --no-renames -z | tr '\0' '\n'; exit "${PIPESTATUS[0]}")" \
      || die "could not read the diff"
    CHECKS=()
    while read -r glob kind rest; do
      case "$glob" in ''|'#'*) continue ;; esac
      case "$kind" in test|pair) ;; *) die "unknown contract kind in $F: $kind" ;; esac
      case "$glob" in */) glob="$glob*" ;; esac
      while IFS= read -r p; do
        [ -n "$p" ] || continue
        # shellcheck disable=SC2254  # the list IS patterns
        case "$p" in $glob) CHECKS+=("$kind $rest"); break ;; esac
      done <<< "$CHANGED"
    done <<< "$CLIST"
    # Each check once: a pair stands in the list for both of its files.
    mapfile -t CHECKS < <(printf '%s\n' "${CHECKS[@]+"${CHECKS[@]}"}" | awk 'NF && !seen[$0]++')
    [ "${#CHECKS[@]}" -gt 0 ] || { echo "contracts: none"; exit 0; }
    if [ "$LIST_ONLY" = 1 ]; then printf '%s\n' "${CHECKS[@]}"; exit 0; fi
    OK=0 RED=() UNRUN=()
    for c in "${CHECKS[@]}"; do
      read -r kind a1 a2 a3 <<< "$c"
      case "$kind" in
        test)
          D="$(mktemp -d "${TMPDIR:-/tmp}/ah-contract.XXXXXXXX")" || die "mktemp failed"
          AH_OUT_DIR="$D" bash "$ROOT/scripts/dev/verify.sh" "$a1" --strict -- "$a2" > "$D/run.log" 2>&1
          vrc=$?
          case "$vrc" in
            0) OK=$((OK + 1)) ;;
            # A run that never got going (a broken list line, an unknown
            # component) is no verdict on the code — but never a green one.
            2|74) UNRUN+=("$c (verify.sh exit $vrc)"); tail -n 15 "$D/run.log" >&2 ;;
            *) RED+=("$c (verify.sh exit $vrc)"); tail -n 15 "$D/run.log" >&2 ;;
          esac
          rm -rf "$D" ;;
        pair)
          if why="$(python3 - "$STAGED" "$a1" "$a2" "$a3" <<'PY'
import re, subprocess, sys

staged, rx, files = sys.argv[1] == "1", sys.argv[2], sys.argv[3:5]
vals = []
for f in files:
    # What is about to be committed, with --staged; else the worktree.
    if staged:
        r = subprocess.run(["git", "show", ":" + f], capture_output=True)
        text = r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
    else:
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            text = None
    if text is None:
        print("%s is missing" % f)
        sys.exit(1)
    try:
        m = re.search(rx, text, re.M)
    except re.error as e:
        print("bad regex: %s" % e)
        sys.exit(1)
    vals.append(m.group(1) if m else None)
if None in vals or vals[0] != vals[1]:
    print(" vs ".join("%s=%s" % (f, "(no match)" if v is None else v) for f, v in zip(files, vals)))
    sys.exit(1)
PY
)"; then OK=$((OK + 1)); else RED+=("$c: $why"); fi ;;
      esac
    done
    if [ "${#UNRUN[@]}" -gt 0 ]; then
      echo "review.sh contracts: could not run:" >&2
      printf '  %s\n' "${UNRUN[@]}" >&2
    fi
    if [ "${#RED[@]}" -gt 0 ]; then
      echo "review.sh contracts: red (scripts/dev/review-contracts.txt):" >&2
      printf '  %s\n' "${RED[@]}" >&2
      exit 3
    fi
    [ "${#UNRUN[@]}" -eq 0 ] || exit 74
    echo "contracts: $OK ok"
    ;;

  log)
    [ "${#ARGS[@]}" -eq 0 ] || die "log takes no operand"
    command -v python3 >/dev/null 2>&1 || die "log needs python3"
    LOG="$ROOT/.ah-out/review/review-log.jsonl"
    if [ -n "$APPEND" ] || [ "$FAILED_SET" = 1 ]; then
      [ -z "$APPEND" ] || [ "$FAILED_SET" = 0 ] || die "--append or --failed, not both"
      if [ -n "$APPEND" ]; then
        case "$APPEND" in /*) ;; *) APPEND="$CALLER_PWD/$APPEND" ;; esac
        [ -f "$APPEND" ] || die "no such verdict: $APPEND"
        # Only a verdict check-verdict reads (to its own tree and task): 0 or 3.
        VTREE="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("tree_hash", ""))' "$APPEND" 2>/dev/null)"
        VTASK="$(python3 -c 'import json, sys; t = json.load(open(sys.argv[1])).get("task") or {}; print(t.get("ledger", ""), t.get("id", ""))' "$APPEND" 2>/dev/null)"
        read -r VL VI <<< "$VTASK"
        bash "$ROOT/scripts/dev/review.sh" check-verdict "$APPEND" --tree "${VTREE:-none}" --task "${VL:-none}" "${VI:-none}" >/dev/null 2>&1
        case $? in 0|3) ;; *) die "not a verdict check-verdict reads: $APPEND" ;; esac
      else
        [ -n "$FAILED" ] || die "--failed needs a reason"
        [ -n "$TASK_LEDGER" ] && [ -n "$TASK_ID" ] || die "--failed needs --task <ledger> <id>"
        case "$ROUND_ARG" in 1|2) ;; *) die "--failed needs --round 1 or 2" ;; esac
      fi
      mkdir -p "$(dirname "$LOG")" || die "cannot create $(dirname "$LOG")"
      python3 - "$LOG" "$APPEND" "$FAILED" "$TASK_LEDGER" "$TASK_ID" "$ROUND_ARG" "$TREE_ARG" "$ROOT" <<'PY' || die "could not write $LOG"
import datetime, json, os, sys

log, verdict, failed, ledger, tid, rnd, tree, root = sys.argv[1:9]
now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
if verdict:
    d = json.load(open(verdict))
    counts = {k: sum(1 for f in d["findings"] if f["severity"] == k) for k in ("blocker", "wichtig", "nit")}
    p = d.get("probe") or {}
    if not p:
        probe = "none"
    elif p.get("applicable"):
        probe = "red" if p.get("red_without_change") is True else "green"
    else:
        probe = "n/a: %s" % p.get("reason", "")
    mutants = d.get("mutants", [])
    row = {"date": now, "ledger": d["task"]["ledger"], "task": d["task"]["id"], "round": d.get("round"),
           "model": d["reviewer"]["model"], "effort": d["reviewer"]["effort"], "verdict": d["verdict"],
           **counts, "probe": probe, "mutants_set": len(mutants),
           "mutants_killed": sum(1 for m in mutants if m["result"] == "killed"),
           "cost_usd": d.get("cost_usd"), "num_turns": d.get("num_turns"), "duration_s": d.get("duration_s"),
           "tree": d["tree_hash"]}
else:
    # A failed run: what it cost stands in its raw answer, when there is one.
    raw = os.path.join(os.path.dirname(log), os.path.basename(ledger)[:-3] if ledger.endswith(".md")
                       else os.path.basename(ledger), "%s.r%s.raw.json" % (tid, rnd))
    try:
        r = json.load(open(raw))
        r = r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        r = {}
    ms = r.get("duration_ms")
    row = {"date": now, "ledger": ledger, "task": tid, "round": int(rnd), "model": None, "effort": None,
           "verdict": "failed", "reason": " ".join(failed.split()), "blocker": 0, "wichtig": 0, "nit": 0,
           "probe": None, "mutants_set": 0, "mutants_killed": 0, "cost_usd": r.get("total_cost_usd"),
           "num_turns": r.get("num_turns"),
           "duration_s": round(ms / 1000, 1) if type(ms) in (int, float) else None, "tree": tree or None}
# One spelling per ledger, whatever path the close was called with: --ledger
# filters on it.
if os.path.isabs(row["ledger"]):
    row["ledger"] = os.path.relpath(row["ledger"], root)
with open(log, "a", encoding="utf-8") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
PY
      exit 0
    fi
    if [ -n "$LOG_LEDGER" ]; then
      case "$LOG_LEDGER" in */*) ;; *) LOG_LEDGER="tasks/$LOG_LEDGER" ;; esac
      case "$LOG_LEDGER" in *.md) ;; *) LOG_LEDGER="$LOG_LEDGER.md" ;; esac
    fi
    python3 - "$LOG" "$LOG_LEDGER" <<'PY'
import json, os, sys

log, only = sys.argv[1], sys.argv[2]
rows = []
try:
    lines = open(log, encoding="utf-8").read().splitlines()
except OSError:
    lines = []
for n, l in enumerate(lines, 1):
    try:
        d = json.loads(l)
        if not isinstance(d, dict):
            raise ValueError
    except ValueError:
        print("review.sh log: line %d of %s is no JSON object, left out" % (n, log), file=sys.stderr)
        continue
    if only and os.path.normpath(str(d.get("ledger"))) != os.path.normpath(only):
        continue
    rows.append(d)
num = lambda v: v if type(v) in (int, float) else 0
fmt = "%-16s %-22s %-5s %2s %-14s %-15s %-6s %-22s %-5s %7s %5s %6s"
if rows:
    print(fmt % ("date", "ledger", "task", "rd", "model/effort", "verdict", "b/w/n", "probe", "mut", "$", "turns", "s"))
for d in rows:
    me = "%s/%s" % (d.get("model"), d.get("effort")) if d.get("model") else "-"
    print(fmt % (str(d.get("date", ""))[:16].replace("T", " "), os.path.basename(str(d.get("ledger")))[:22],
                 d.get("task"), d.get("round"), me, d.get("verdict"),
                 "%s/%s/%s" % (d.get("blocker", 0), d.get("wichtig", 0), d.get("nit", 0)), str(d.get("probe") or "-")[:22],
                 "%s/%s" % (d.get("mutants_killed", 0), d.get("mutants_set", 0)), "%.2f" % num(d.get("cost_usd")),
                 num(d.get("num_turns")), "%.0f" % num(d.get("duration_s"))))
    if d.get("verdict") == "failed" and d.get("reason"):
        print("    failed: %s" % d["reason"])
by = lambda v: sum(1 for d in rows if d.get("verdict") == v)
print("%d runs, %d approve, %d request_changes, %d failed, $%.2f, %d turns, %.0f s"
      % (len(rows), by("approve"), by("request_changes"), by("failed"), sum(num(d.get("cost_usd")) for d in rows),
         sum(num(d.get("num_turns")) for d in rows), sum(num(d.get("duration_s")) for d in rows)))
PY
    ;;

  pr-body)
    LEDGER="${ARGS[0]-}"
    [ -n "$LEDGER" ] && [ "${#ARGS[@]}" -eq 1 ] || die "pr-body needs <ledger> (and at most --verdicts <dir>)"
    case "$LEDGER" in /*) ;; *) LEDGER="$CALLER_PWD/$LEDGER" ;; esac
    [ -f "$LEDGER" ] || die "no such ledger: $LEDGER"
    case "$VERDICTS" in ""|/*) ;; *) VERDICTS="$CALLER_PWD/$VERDICTS" ;; esac
    [ -z "$VERDICTS" ] || [ -d "$VERDICTS" ] || die "no such verdict directory: $VERDICTS"
    command -v python3 >/dev/null 2>&1 || die "pr-body needs python3"
    python3 - "$LEDGER" "$VERDICTS" "$ROOT" <<'PY' || die "could not read $LEDGER"
import glob, ipaddress, json, os, re, subprocess, sys

ledger, vdir, root = sys.argv[1], sys.argv[2], sys.argv[3]
# This text goes to a public repo (CLAUDE.md: no homelab names): addresses, host
# names of a private network and VM ids come out of every line it copies.
# Loopback stays, a file name like settings.local.json stays. A bare host name
# without a private suffix cannot be told from a word — that is a limit.
# A VM id after its keyword, and the ids of a list after it ("3901 und 3902").
VM = re.compile(r"\b(?:vm-?ids?|vms?|templates?|tpl|destroy|clone)[\s=:#*-]*\d{3,5}\b"
                r"(?:\s*(?:,|/|und|and|bis|to|–|-)\s*\d{3,5}\b)*", re.I)
HOST = re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*"
                  r"\.(?:lan|local|home\.arpa|home|internal|intra|corp|localdomain|fritz\.box)\b"
                  r"(?![\w-]|\.\w)", re.I)
# A private network with a wildcard in it: 192.168.1.x, 10.0.0.*.
PARTIAL = re.compile(r"(?<![\w.])(?:10(?:\.(?:\d{1,3}|[xX*])){3}|172\.(?:1[6-9]|2\d|3[01])(?:\.(?:\d{1,3}|[xX*])){2}"
                     r"|192\.168(?:\.(?:\d{1,3}|[xX*])){2})(?!\w|\.\w)")
ADDR = re.compile(r"\[?[0-9A-Fa-f:.]*[:.][0-9A-Fa-f:.]*[0-9A-Fa-f](?:%\w+)?\]?(?::\d+)?")


def addr(m):
    text, start = m.group(0), 0
    while True:
        cand = text[start:]
        core = re.sub(r"^\[|\](?::\d+)?$", "", cand)
        if "]" not in cand and core.count(".") == 3:
            core = re.sub(r":\d+$", "", core)   # 10.0.0.1:22
        try:
            ip = ipaddress.ip_address(core.split("%")[0])
            return text if ip.is_loopback else text[:start] + "<addr>"
        except ValueError:
            pass
        # A word and a colon in front (`IP:10.0.0.1`, `dns:2001:db8::1`) are no
        # part of the address: try again behind the first single colon.
        k = re.search(r"(?<!:):(?!:)", cand)
        if not k:
            return text
        start += k.end()


def clean(text):
    text = PARTIAL.sub(lambda m: "<addr>" if re.search(r"[xX*]", m.group(0)) else m.group(0), text)
    text = ADDR.sub(addr, text)
    text = HOST.sub("<host>", text)
    return VM.sub("<vm>", text).strip()


lines = open(ledger, encoding="utf-8").read().split("\n")
title = next((l[2:] for l in lines if l.startswith("# ")), os.path.basename(ledger))
title = re.sub(r"\s+—\s+Task-Ledger\s*$", "", title)
head, tasks, cur = {}, [], None
# A task heading carries its id, a dash, the title and a box; whatever follows
# the box is the note (ledger.sh writes "(…)", hands wrote more).
TASK = re.compile(r"^###\s+([A-Z]+\d+[a-z]?)\s+—\s+(.*)$")
BOX = re.compile(r"\s+\[([ x~?])\]\s*(.*)$")
for l in lines:
    if l.startswith("## ") or re.match(r"^###\s", l):
        # Every heading ends the task above it, as for ledger.sh lint: an
        # Evidenz: line under "### Ergebnis" belongs to no task.
        cur = None
        m = TASK.match(l)
        if m:
            b = BOX.search(m.group(2))
            cur = {"id": m.group(1), "title": m.group(2)[:b.start()] if b else m.group(2),
                   "box": b.group(1) if b else "!", "note": b.group(2).strip() if b else ""}
            if cur["note"].startswith("(") and cur["note"].endswith(")"):
                cur["note"] = cur["note"][1:-1]
            tasks.append(cur)
        continue
    key = l.split(":", 1)[0]
    if cur is None and not tasks and key in ("Spec", "Roadmap", "Heavy") and key not in head:
        head[key] = l.split(":", 1)[1]
    elif cur is not None and key in ("Evidenz", "Review") and key not in cur:
        cur[key] = l.split(":", 1)[1]

out = ["## " + clean(title), ""]
for key in ("Spec", "Roadmap", "Heavy"):
    if key in head:
        out.append("- **%s:** %s" % (key, clean(head[key])))
out += ["", "### Tasks", ""]


def verdict(tid):
    if not vdir:
        return None
    # The reviewer process writes one file per round; the last round counts.
    rounds = sorted(glob.glob(os.path.join(glob.escape(vdir), glob.escape(tid) + ".r[0-9].verdict.json")))
    path = rounds[-1] if rounds else os.path.join(vdir, tid + ".json")
    if not os.path.isfile(path):
        return None
    try:
        d = json.load(open(path))
        r = d.get("reviewer") or {}
        if (d.get("task") or {}).get("id") != tid:
            return "fremd (die Datei gehört zu einer anderen Task)"
    except Exception:
        return "unlesbar"
    # The same check as task-close.sh (R-0151.6), held to the verdict's own tree
    # and task: a file outside the schema is no verdict, whatever it says.
    task = d.get("task") or {}
    cv = subprocess.run(["bash", os.path.join(root, "scripts/dev/review.sh"), "check-verdict", path,
                         "--tree", str(d.get("tree_hash") or "none"), "--task", str(task.get("ledger") or "none"), tid],
                        capture_output=True, text=True, cwd=root)
    err = [l.strip() for l in cv.stderr.strip().splitlines()] or [""]
    # Exit 2: a head line that ends in a colon has its first detail below it.
    # Exit 3: the reason is the last line; a blocker counted as nit warns first.
    why = err[-1] if cv.returncode == 3 else err[0] + (" " + err[1] if err[0].endswith(":") and len(err) > 1 else "")
    why = why.replace("check-verdict: ", "")
    if cv.returncode == 2:
        return clean("ungültig (%s)" % why)
    if cv.returncode == 0:
        text = cv.stdout.strip()
    elif cv.returncode == 3:
        text = "%s (%s/%s) — kein brauchbares approve: %s" % (d.get("verdict"), r.get("model", "?"), r.get("effort", "?"), why)
    else:
        return clean("fremd (%s)" % why)
    if d.get("round"):
        text += " · Runde %s" % d["round"]
    m = d.get("mutants") or []
    if m:
        text += " · Mutanten %d gesetzt, %d gekillt" % (len(m), sum(1 for x in m if x.get("result") == "killed"))
    return clean(text)


for t in tasks:
    if t["box"] in "~?":
        continue
    if t["box"] == "!":
        out.append("- **%s — %s** — **unlesbar** (Kopfzeile ohne Haken)" % (t["id"], clean(t["title"])))
        continue
    line = "- [%s] **%s — %s**" % ("x" if t["box"] == "x" else " ", t["id"], clean(t["title"]))
    if "Evidenz" not in t:
        # No evidence, no claim: whatever a review or a verdict file says.
        out.append(line + " — **unverifiziert** (keine Evidenz)")
        continue
    out.append(line)
    out.append("  - Evidenz: " + clean(t["Evidenz"]))
    if "Review" in t:
        out.append("  - Review: " + clean(t["Review"]))
    v = verdict(t["id"])
    if v:
        out.append("  - Verdict: " + v)
for box, heading in (("~", "Übersprungen"), ("?", "Offene Fragen")):
    some = [t for t in tasks if t["box"] == box]
    if some:
        out += ["", "### " + heading, ""]
        out += ["- [%s] **%s — %s** — %s" % (box, t["id"], clean(t["title"]), clean(t["note"]) or "siehe Ledger")
                for t in some]
print("\n".join(out))
PY
    ;;

  -h|--help) usage ;;
  "") echo "review.sh needs a verb" >&2; usage >&2; exit 2 ;;
  *)  echo "unknown verb: $VERB" >&2; usage >&2; exit 2 ;;
esac
