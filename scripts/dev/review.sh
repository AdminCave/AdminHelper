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
#
# Deterministic, model-free, and called by task-close.sh before it commits. They
# answer three questions a reviewer would otherwise have to ask every time:
#
#   diff-scan  does this diff buy its green by switching a test off? A `|| true`,
#              a `set +e`, a `@pytest.mark.skip` or a deleted assertion changes
#              what "passed" means. Two things are deliberately not findings: a
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
#
# --staged looks at the index (what task-close.sh is about to commit); without it
# the working tree is compared against HEAD. Neither form sees UNTRACKED files —
# git diff does not — so the answer for a brand-new file exists only once it is
# staged, which is the state task-close.sh works on anyway.
#
# Exit: 0 clean · 2 usage · 3 findings (diff-scan, scope) · 4 blocked (sec)

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2

usage() { sed -n '/^#   bash scripts\/dev\/review.sh diff-scan/,/^# Deterministic/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }
die() { echo "review.sh: $*" >&2; exit 2; }

# The ways a diff can buy a green run. Fixed strings, \x1f-separated, each one
# with the language it comes from: pytest, vitest/jest, Rust, Go, shell.
SKIP_PATTERNS="$(printf '%s' \
  '@pytest.mark.skip\x1fpytest.skip(\x1fit.skip(\x1ftest.skip(\x1fxit(\x1f#[ignore]\x1ft.Skip(\x1ft.Skipf(\x1f|| true\x1f--no-verify\x1fset +e')"  # review: ok this IS the list

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
TASK_LEDGER="" TASK_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --staged) STAGED=1 ;;
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

changed_paths() { git diff "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" --name-only; }

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
    RAW="$(git diff "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" -U0 | awk -v PAT="$SKIP_PATTERNS" '
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
      inheader && /^--- / { oldfile = substr($0, 5); sub(/^a\//, "", oldfile); next }
      inheader && /^\+\+\+ / {
                        file = substr($0, 5)
                        # A deletion has +++ /dev/null; the path is on the --- side.
                        if (file == "/dev/null") file = oldfile; else sub(/^b\//, "", file)
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
                        if (line !~ /review: ok/ &&
                            (line ~ /(^|[^A-Za-z_.])assert([^A-Za-z_]|$)/ || line ~ /expect\(/))
                          printf "RA\t%s\t%d\t%s\n", file, oldno, trim(line)
                        oldno++; next
                      }
      /^\+/           {
                        line = substr($0, 2)
                        if (line !~ /review: ok/) {
                          cmt = comment_at(line)
                          cnt = split(PAT, pat, "\x1f")
                          for (i = 1; i <= cnt; i++) {
                            pos = index(line, pat[i])
                            # A word boundary in front, or `xit(` convicts every
                            # `sys.exit(` in the repo. index() rather than a
                            # regex: the patterns are fixed strings full of
                            # regex metacharacters.
                            prev = (pos > 1) ? substr(line, pos - 1, 1) : " "
                            if (pos > 0 && prev !~ /[A-Za-z0-9_]/ && (cmt == 0 || pos <= cmt)) {
                              printf "%s:%d  %s: %s\n", file, newno, pat[i], trim(line)
                              break
                            }
                          }
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
out = [l for l in lines if not l.startswith("RA\t")]

def git(*a):
    r = subprocess.run(("git",) + a, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None

def old_text(path):   # the side the diff removes from
    return git("show", ("HEAD:" if staged else ":") + path) or ""

def new_text(path):   # the side the diff arrives at
    if staged:
        return git("show", ":" + path) or ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""

PY = re.compile(r"^(\s*)(?:async\s+)?def\s+(test\w*)\s*\(")
GO = re.compile(r"^()func\s+(Test\w*)\s*\(")
JS = re.compile(r"^(\s*)(?:it|test)(?:\.only|\.skip)?\s*\(\s*([\x27\x22`])(.*?)\2")
RS = re.compile(r"^(\s*)(?:pub\s+)?(?:async\s+)?fn\s+(\w+)")
RS_ATTR = re.compile(r"^\s*#\[(?:[a-z_]+::)?test\]")

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
            k_ind = len(t) - len(t.lstrip())
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

changed = (git("diff", *(["--staged"] if staged else []), "--name-only") or "").split()

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
        entries[(path, name)] = (old[0][1], old[0][2])

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
    done <<< "$(git diff "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" | awk '
      /^\+\+\+ / { file = substr($0, 5); sub(/^b\//, "", file); next }
      /^@@/       { split($3, nw, ","); newno = nw[1]; sub(/^\+/, "", newno); newno += 0; next }
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

  -h|--help) usage ;;
  "") echo "review.sh needs a verb" >&2; usage >&2; exit 2 ;;
  *)  echo "unknown verb: $VERB" >&2; usage >&2; exit 2 ;;
esac
