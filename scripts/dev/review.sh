#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review.sh — the checks a diff has to pass on its way into this public repo.
#
#   bash scripts/dev/review.sh sec [--staged | --range <a>..<b> [--not-on <remote>] | --message <file> [--editor]]
#                                                       what must never be committed or pushed
#                                                       (names a path or file:line, never a line's
#                                                       content: its output may stand in a public CI log)
#   bash scripts/dev/review.sh risk [--staged | --range <a>..<b>]
#                                                       does a diff need the security reviewer
#   bash scripts/dev/review.sh pr-body <ledger>         the PR text out of the ledger
#   bash scripts/dev/review.sh final <ledger>           is the branch closable: the reviewer's branch
#                                                       verdict, current, approve for code and tests;
#                                                       prints its PR section
#
# Deterministic and model-free. The git hooks in scripts/dev/hooks and
# task-close.sh run sec; the CI job "Public repo guard (review.sh sec)" runs it
# over every commit a push or a pull request brings.
#
#   sec        is something staged that this public repo must never hold — the
#              private roadmap, a security ledger, a finding's dedup key, one
#              of the two gitignored files that carry credentials, or a line
#              with a token pattern (Proxmox, GitHub, Anthropic). With --message,
#              the message of the commit being made (the commit-msg hook), all of
#              it; with --editor too (git brought up an editor), the diff that
#              commit -v puts below the scissors line does not count.
#   risk       does the diff touch a risk path (scripts/dev/review-risk.txt)?
#              Prints `xhigh` and the paths it hit, or `standard`; both exit 0.
#              A risk path adds the `security` sub-agent (CLAUDE.md §6).
#              Without a flag it judges everything not committed yet — staged,
#              unstaged and untracked: at the review step nothing is staged.
#   pr-body    Markdown for the PR: the ledger head (spec, roadmap ids, heavy
#              line), each task with its box, Evidenz: and Review: lines; [~] and
#              [?] tasks apart. A task without evidence reads "unverifiziert".
#              Addresses, host names and VMIDs are cut out of every ledger line
#              it copies: this text goes to a public repo.
#   final      the closing check of a branch: no task of the ledger is still [ ]
#              or [?], and <wt>/.ah-out/review/<slug>/branch.verdict.json, the
#              reviewer's verdict in mode branch, says approve overall, for the
#              code and for the tests, with evidence for both, a coverage list,
#              at most three probes (red | green | not-runnable) and no blocker,
#              given on a commit after which the branch's own line brought only
#              commits to the ledger alone and merges without changes of their
#              own (CHANGELOG.md aside). <wt> is the checkout the
#              ledger lies in. Prints the PR section (cleaned like pr-body); exit
#              3 with every reason the branch is not closable.
#
# --staged looks at the index (what task-close.sh is about to commit); without it
# the working tree is compared against the index. Neither form sees UNTRACKED files —
# git diff does not — so the answer for a brand-new file exists only once it is
# staged, which is the state task-close.sh works on anyway.
#
# Exit: 0 clean · 2 usage · 3 not closable (final) · 4 blocked (sec)

set -uo pipefail

CALLER_PWD="$PWD"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2

usage() { sed -n '/^#   bash scripts\/dev\/review.sh sec/,/^# Deterministic/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }
die() { echo "review.sh: $*" >&2; exit 2; }

VERB="${1-}"; [ $# -gt 0 ] && shift
STAGED=0
ARGS=()
RANGE="" NOT_ON="" MESSAGE="" FROM_EDITOR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --staged) STAGED=1 ;;
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
    --editor) FROM_EDITOR=1 ;;
    -h|--help) usage; exit 0 ;;
    --*) die "unknown flag: $1" ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done

DIFF_ARGS=()
[ "$STAGED" = 1 ] && DIFF_ARGS+=(--staged)
if [ -n "$MESSAGE" ]; then
  [ "$VERB" = sec ] || die "--message is for sec alone"
  # Relative to where the caller stands: the hook passes a path git resolved, a
  # call by hand may come from a subdirectory.
  case "$MESSAGE" in /*) ;; *) MESSAGE="$CALLER_PWD/$MESSAGE" ;; esac
  [ "$STAGED" = 0 ] && [ -z "$RANGE" ] || die "--message stands alone, without --staged or --range"
  [ -f "$MESSAGE" ] && [ -r "$MESSAGE" ] || die "--message: no readable file $MESSAGE"
fi
[ "$FROM_EDITOR" = 0 ] || [ -n "$MESSAGE" ] || die "--editor goes with --message"
[ -z "$NOT_ON" ] || [ -n "$RANGE" ] || die "--not-on needs --range"
if [ -n "$RANGE" ]; then
  # pr-body reads a ledger; a range is history.
  case "$VERB" in risk|sec) ;; *) die "--range is for risk and sec alone" ;; esac
  [ -z "$NOT_ON" ] || [ "$VERB" = sec ] || die "--not-on is for sec --range alone"
  [ "$STAGED" = 0 ] || die "--staged or --range, not both"
  DIFF_ARGS+=("$RANGE")
fi
# Every verb reads the diff through this, never through a bare `git diff`: a
# committed `.gitattributes` with `-diff` turned a test file into "Binary files
# differ" and the checks went blind (adversarial review, 2026-09-25); a
# textconv or external diff driver, color.diff=always, other prefixes and
# octal-quoted paths change the text the checks parse just as well.
GIT_DIFF=(git -c core.quotePath=false diff --text --no-ext-diff --no-textconv --no-color --src-prefix=a/ --dst-prefix=b/)

case "$VERB" in
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
      # history. Comment lines are read: without an editor (-m, -F) git keeps them
      # in the commit. git truncates at its scissors line only with commit -v or
      # with an editor and cleanup=scissors; a scissors line typed into -m, -F or
      # an editor without -v stays in the commit with all that follows (R-0213).
      # So only with --editor, and only from the first diff header below the exact
      # line on: that is the diff commit -v puts there, no part of the message.
      out="$(awk -v ED="$FROM_EDITOR" "$SEC_TOKEN_AWK"'
        ED && $0 == "# ------------------------ >8 ------------------------" { cut = 1 }
        cut && /^diff --git / { exit }
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

  risk)
    [ "${#ARGS[@]}" -eq 0 ] || die "risk takes no operand (only --staged or --range <a>..<b>)"
    # The list as HEAD, the index and the worktree have it, all together — and
    # for a range as its start has it: a diff that strikes a line must not judge
    # itself by the version it brings along.
    f=scripts/dev/review-risk.txt
    PATTERNS="$(git show "HEAD:$f" 2>/dev/null; git show ":$f" 2>/dev/null; cat "$ROOT/$f" 2>/dev/null
                [ -z "$RANGE" ] || git show "${RANGE%%..*}:$f" 2>/dev/null)"
    [ -n "$PATTERNS" ] || die "no $f in HEAD, the index or the worktree"
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
        # An entry ending in / is a directory.
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

  pr-body|final)
    LEDGER="${ARGS[0]-}"
    [ -n "$LEDGER" ] && [ "${#ARGS[@]}" -eq 1 ] || die "$VERB needs <ledger>"
    case "$LEDGER" in /*) ;; *) LEDGER="$CALLER_PWD/$LEDGER" ;; esac
    [ -f "$LEDGER" ] || die "no such ledger: $LEDGER"
    command -v python3 >/dev/null 2>&1 || die "$VERB needs python3"
    rc=0
    python3 - "$VERB" "$LEDGER" <<'PY' || rc=$?
import ipaddress, json, os, re, subprocess, sys

mode, ledger = sys.argv[1], sys.argv[2]
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

def final():
    """review.sh final: is the branch closable? Reasons to stderr, exit 3."""
    wt = os.path.dirname(os.path.dirname(os.path.abspath(ledger)))
    slug = os.path.basename(ledger)[:-3] if ledger.endswith(".md") else os.path.basename(ledger)
    rel = os.path.join(".ah-out", "review", slug, "branch.verdict.json")
    why = []
    for t in tasks:
        if t["box"] in " ?!":
            why.append("task %s is %s" % (t["id"], {" ": "still open [ ]", "?": "a question [?]",
                                                    "!": "unreadable (heading without a box)"}[t["box"]]))
    try:
        v = json.load(open(os.path.join(wt, rel), encoding="utf-8"))
    except FileNotFoundError:
        v = None
        why.append("no branch verdict at %s — the reviewer has not judged the branch" % rel)
    except (OSError, ValueError) as e:
        v = None
        why.append("%s is unreadable (%s)" % (rel, type(e).__name__))
    if v is not None and not isinstance(v, dict):
        why.append("%s is not a JSON object" % rel)
        v = None

    def git(*a):
        return subprocess.run(["git", "-C", wt] + list(a), capture_output=True, text=True)

    head = now = ""
    if v is not None:
        if v.get("verdict") != "approve":
            why.append("the verdict is %r, not approve" % v.get("verdict"))
        sec = {}
        for name in ("code", "tests"):
            s = v.get(name)
            if not isinstance(s, dict):
                why.append("no %s part in the verdict" % name)
                continue
            sec[name] = s
            if s.get("verdict") != "approve":
                why.append("%s: the verdict is %r, not approve" % (name, s.get("verdict")))
            ev = s.get("evidence")
            if not isinstance(ev, list) or not [e for e in ev if isinstance(e, str) and e.strip()]:
                why.append("%s: no evidence (a list of what was run or read)" % name)
            fs = s.get("findings", [])
            if not isinstance(fs, list) or not all(isinstance(f, dict) for f in fs):
                why.append("%s: findings is not a list of objects" % name)
            elif s.get("verdict") == "approve" and [f for f in fs if f.get("severity") == "blocker"]:
                why.append("%s: approve beside a blocker finding" % name)
        t = sec.get("tests", {})
        if "tests" in sec:
            if not isinstance(t.get("coverage"), list):
                why.append("tests: no coverage list (changed product file -> its tests)")
            probes = t.get("probes")
            if not isinstance(probes, list):
                why.append("tests: no probes list (empty when nothing could be reverted)")
            elif len(probes) > 3:
                why.append("tests: %d probes, at most three" % len(probes))
            elif not all(isinstance(p, dict) and isinstance(p.get("test"), str) and p.get("test")
                         and p.get("result") in ("red", "green", "not-runnable") for p in probes):
                why.append("tests: a probe without test, or a result other than red | green | not-runnable")
        head = v.get("head") if isinstance(v.get("head"), str) else ""
        if not re.fullmatch(r"[0-9a-f]{7,40}", head):
            why.append("the verdict names no head commit (\"head\": the HEAD it judged)")
        elif git("merge-base", "--is-ancestor", head, "HEAD").returncode != 0:
            why.append("the verdict head %s is not in the history of HEAD" % head[:12])
        else:
            # The branch's own line only: a merge of main brings main's commits
            # along, and they are judged where they were merged.
            r = git("log", "--first-parent", "--no-merges", "--format=%h %s", head + "..HEAD",
                    "--", ".", ":(exclude)tasks/%s.md" % slug)
            if r.returncode != 0:
                why.append("git could not read %s..HEAD" % head[:12])
            elif r.stdout.strip():
                why.append("commits after the verdict head that change more than the ledger"
                           " — the reviewer has not seen them: " + "; ".join(r.stdout.split("\n")[:5]).strip("; "))
            # A merge that brings changes of its own (a resolved conflict) is new
            # code too: --cc keeps exactly the hunks no parent had. CHANGELOG.md is
            # merged by union and checked by hand (/feature-build §4.6).
            own = []
            for m in git("rev-list", "--first-parent", "--merges", head + "..HEAD").stdout.split():
                d = git("-c", "core.quotePath=false", "diff-tree", "--cc", "-p", "--no-commit-id", "--text",
                        "--no-ext-diff", "--no-textconv", "--no-color", m)
                path = ""
                for dl in d.stdout.split("\n"):
                    if dl.startswith("diff --cc "):
                        path = dl[len("diff --cc "):]
                    elif dl.startswith("@@@") and path not in ("tasks/%s.md" % slug, "CHANGELOG.md"):
                        own.append("%s %s" % (m[:8], path))
                        path = ""
            if own:
                why.append("merges after the verdict head that change files beyond both parents (a resolved"
                           " conflict) — the reviewer has not seen them: " + "; ".join(own[:5]))
        now = git("rev-parse", "--short=8", "HEAD").stdout.strip()
    if why:
        print("review.sh final: %s is not closable:" % ledger, file=sys.stderr)
        for w in why:
            print("  - " + w, file=sys.stderr)
        sys.exit(3)

    def items(xs):
        return "; ".join(clean(x) for x in xs if isinstance(x, str) and x.strip())

    code, tests = v["code"], v["tests"]
    res = {"red": "rot ohne den Fix", "green": "grün ohne den Fix", "not-runnable": "nicht lauffähig"}
    out = ["### Abschlussprüfung (reviewer, Branch)", "",
           "- **Urteil:** approve, geprüft auf `%s` (HEAD `%s`)" % (head[:8], now)]
    checked = code.get("checked") if isinstance(code.get("checked"), list) else []
    out.append("- **Code:** approve%s — Evidenz: %s" % (
        " (Kriterien %s)" % ", ".join(str(c) for c in checked) if checked else "", items(code["evidence"])))
    out.append("- **Tests:** approve — Abdeckung: %d Dateien — Evidenz: %s" % (
        len(tests["coverage"]), items(tests["evidence"])))
    for p in tests["probes"]:
        out.append("  - Gegenprobe `%s`: %s%s" % (clean(p["test"]), res[p["result"]],
                                                   " — " + clean(p["evidence"]) if isinstance(p.get("evidence"), str) and p["evidence"].strip() else ""))
    if not tests["probes"]:
        out.append("  - keine Gegenprobe")
    fs = [(n, f) for n in ("code", "tests") for f in v[n].get("findings", [])]
    if fs:
        out += ["- **Funde (nicht blockierend):**"]
        for n, f in fs:
            loc = "%s:%s" % (f.get("file", "?"), f.get("line", 0)) if f.get("file") else "—"
            out.append("  - [%s] %s `%s` — %s" % (n, clean(str(f.get("severity", "?"))), clean(loc), clean(str(f.get("what", "")))))
    print("\n".join(out))


if mode == "final":
    final()
    sys.exit(0)

out = ["## " + clean(title), ""]
for key in ("Spec", "Roadmap", "Heavy"):
    if key in head:
        out.append("- **%s:** %s" % (key, clean(head[key])))
out += ["", "### Tasks", ""]


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
for box, heading in (("~", "Übersprungen"), ("?", "Offene Fragen")):
    some = [t for t in tasks if t["box"] == box]
    if some:
        out += ["", "### " + heading, ""]
        out += ["- [%s] **%s — %s** — %s" % (box, t["id"], clean(t["title"]), clean(t["note"]) or "siehe Ledger")
                for t in some]
print("\n".join(out))
PY
    case "$rc" in 0) ;; 3) exit 3 ;; *) die "could not read $LEDGER" ;; esac
    ;;

  -h|--help) usage ;;
  "") echo "review.sh needs a verb" >&2; usage >&2; exit 2 ;;
  *)  echo "unknown verb: $VERB" >&2; usage >&2; exit 2 ;;
esac
