#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review.sh — the checks a diff has to pass before it becomes a commit.
#
#   bash scripts/dev/review.sh diff-scan [--staged]     ways to make a suite lie
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
#              comment switches nothing off.
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
for a in "$@"; do
  case "$a" in
    --staged) STAGED=1 ;;
    -h|--help) usage; exit 0 ;;
    --*) die "unknown flag: $a" ;;
    *) ARGS+=("$a") ;;
  esac
done
DIFF_ARGS=()
[ "$STAGED" = 1 ] && DIFF_ARGS+=(--staged)

changed_paths() { git diff "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" --name-only; }

case "$VERB" in
  diff-scan)
    # -U0: only what this diff actually adds or removes. Context lines would
    # convict a `|| true` that has been standing there for two years.
    # The patterns arrive as one \x1f-separated string: an awk -v value cannot
    # carry an array, and each of them is a fixed string, not a regex.
    FOUND="$(git diff "${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}" -U0 | awk -v PAT="$SKIP_PATTERNS" '
      function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
      # Where a comment starts, or 0. Only a marker at the start of the line or
      # after whitespace counts, so the // in an https:// URL is not a comment.
      function comment_at(s,   c, c2) {
        c = 0
        if (match(s, /(^|[ \t])#/))    c = RSTART + RLENGTH - 1
        if (match(s, /(^|[ \t])\/\//)) { c2 = RSTART + RLENGTH - 2; if (!c || c2 < c) c = c2 }
        return c
      }
      /^--- /         { oldfile = substr($0, 5); sub(/^a\//, "", oldfile); next }
      /^\+\+\+ /      {
                        file = substr($0, 5)
                        # A deletion has +++ /dev/null; the path is on the --- side.
                        if (file == "/dev/null") file = oldfile; else sub(/^b\//, "", file)
                        next
                      }
      /^@@/           {
                        split($2, o, ","); split($3, nw, ",")
                        oldno = o[1]; sub(/^-/, "", oldno); oldno += 0
                        newno = nw[1]; sub(/^\+/, "", newno); newno += 0
                        next
                      }
      /^-/ && !/^---/ {
                        line = substr($0, 2)
                        if (line !~ /review: ok/ &&
                            (line ~ /(^|[^A-Za-z_.])assert([^A-Za-z_]|$)/ || line ~ /expect\(/))
                          printf "%s:%d  removed assertion: %s\n", file, oldno, trim(line)
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
    if [ -n "$FOUND" ]; then
      echo "review.sh diff-scan: the diff changes what a green run means" >&2
      printf '%s\n' "$FOUND" >&2
      echo "  (deliberate? append '# review: ok <reason>' to the line)" >&2
      exit 3
    fi
    echo "diff-scan: clean"
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
    ALLOW="$(sed -n 's/.*Dateien:[[:space:]]*//p' <<<"$LINE" \
      | sed 's/([^)]*)//g' | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]].*//' | grep -v '^$')"
    ALLOW="$ALLOW
$(component_tests "$KOMP" | tr ' ' '\n')
docs/
CHANGELOG.md
$LEDGER"

    FOREIGN=()
    while IFS= read -r p; do
      [ -n "$p" ] || continue
      hit=0
      while IFS= read -r a; do
        [ -n "$a" ] || continue
        case "$a" in
          */) case "$p" in "$a"*) hit=1 ;; esac ;;
          *\**)
            # shellcheck disable=SC2254  # an entry with * IS a pattern
            case "$p" in $a) hit=1 ;; esac ;;
          *) [ "$p" = "$a" ] && hit=1 ;;
        esac
        [ "$hit" = 1 ] && break
      done <<< "$ALLOW"
      [ "$hit" = 1 ] || FOREIGN+=("$p")
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
