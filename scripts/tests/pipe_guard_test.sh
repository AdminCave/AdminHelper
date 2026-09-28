#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# pipe_guard_test.sh — a git command that writes many records must not feed a
# reader that stops early. git flushes a pipe after every record (GIT_FLUSH in
# `man git`), so in `git log | grep -q x` grep exits on a middle line, git's next
# write gets SIGPIPE (141), and under `set -o pipefail` the match turns into a
# red. heavy_test 4i-d fell that way in about 3 % of its runs (R-0103).
# The rule for scripts/tests/*_test.sh: the output of git log, rev-list, reflog,
# shortlog, check-attr or check-ignore goes into a variable first, or is cut to
# one record (-1, -n 1, --max-count=1), before grep -q/-m/-l, head or sed …q
# reads it.
#
# A line scan, not a parser: continuation lines are joined, comments dropped, and
# a pipe inside quotes is no pipe — which also hides one inside a quoted "$(…)",
# whose status is rarely looked at.
#
# Run: bash scripts/tests/pipe_guard_test.sh            self-test, then every *_test.sh
#      bash scripts/tests/pipe_guard_test.sh <file…>    scan only these files
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

# scan <file…> — one `<file>:<line>: <text>` per risky pipe. Plain POSIX awk: the
# boxes run this block too, and not every one of them has gawk.
scan() {
  awk '
  # Blank out what reads as shell syntax inside quotes (| ; & ( )) and drop a
  # comment. Length-preserving, so a position in the masked line is the same
  # position in the real one.
  function mask(s,   out, i, n, c, q) {
    out = ""; q = ""; n = length(s)
    for (i = 1; i <= n; i++) {
      c = substr(s, i, 1)
      if (c == "\\" && q != "\047") {
        c = substr(s, i + 1, 1); i++
        out = out "_" (c ~ /[|;&()]/ ? "_" : c); continue
      }
      if (q == "") {
        if (c == "#" && (i == 1 || substr(s, i - 1, 1) ~ /[ \t]/)) break
        if (c == "\047" || c == "\"") q = c
      } else if (c == q) q = ""
      else if (c ~ /[|;&()]/) c = "_"
      out = out c
    }
    # 2>&1, <&0 and &> redirect; they end nothing.
    gsub(/>&/, ">_", out); gsub(/<&/, "<_", out); gsub(/&>/, "_>", out)
    return out
  }
  # The git command a pipe starts from: many records, not cut to one?
  function many(s,   t, n, i, k) {
    n = split(s, t, /[ \t]+/)
    for (i = 1; i <= n; i++) {
      if (t[i] !~ /(^|[(`])git$/) continue
      for (k = i + 1; k <= n; k++) {
        if (t[k] == "-C" || t[k] == "-c") { k++; continue }
        if (t[k] !~ /^-/) break
      }
      if (k > n || t[k] !~ /^(log|rev-list|reflog|shortlog|check-attr|check-ignore)$/) continue
      for (k++; k <= n; k++) {
        if (t[k] == "-1" || t[k] == "-n1" || t[k] == "--max-count=1") return 0
        if ((t[k] == "-n" || t[k] == "--max-count") && t[k + 1] == "1") return 0
      }
      return 1
    }
    return 0
  }
  # Does this command stop reading before its input ends?
  function early(s,   t, n, k) {
    n = split(s, t, /[ \t]+/)
    for (k = 1; k <= n && (t[k] == "" || t[k] ~ /^[A-Za-z_][A-Za-z0-9_]*=/); k++) ;
    if (t[k] == "head") return 1
    if (t[k] == "sed") return (s ~ /(^|[0-9\/;{}$\047"[:space:]])[qQ][0-9]*([;}\047"[:space:]]|$)/)
    if (t[k] !~ /^[ef]?grep$/) return 0
    for (k++; k <= n && t[k] != "--"; k++) {
      if (t[k] ~ /^--(quiet|silent|max-count|files-with-matches)/) return 1
      if (t[k] ~ /^-[^-]/ && t[k] ~ /[qml]/) return 1
    }
    return 0
  }
  function check(s, lnum,   m, n, i, k, cnt, seg, orig, p, stop) {
    m = mask(s); n = length(m); cnt = 0; k = 1
    for (i = 1; i <= n; i++)
      if (substr(m, i, 1) == "|" && substr(m, i + 1, 1) != "|" && substr(m, i - 1, 1) != "|") {
        cnt++; seg[cnt] = substr(m, k, i - k); orig[cnt] = substr(s, k, i - k); k = i + 1
      }
    cnt++; seg[cnt] = substr(m, k); orig[cnt] = substr(s, k)
    for (i = 1; i < cnt; i++) {
      # Only the last command before the pipe writes into it.
      p = seg[i]
      while (match(p, /[;&)]|\|\|/)) p = substr(p, RSTART + RLENGTH)
      if (!many(p)) continue
      for (k = i + 1; k <= cnt; k++) {
        stop = match(seg[k], /[;&)]|\|\|/)
        if (early(stop ? substr(orig[k], 1, RSTART - 1) : orig[k])) {
          sub(/^[ \t]+/, "", s); printf "%s:%d: %s\n", FILENAME, lnum, s; return
        }
        if (stop) break
      }
    }
  }
  FNR == 1 { buf = "" }
  buf == "" && /^[ \t]*#/ { next }
  {
    if (buf == "") start = FNR
    if ($0 ~ /\\$/) { buf = buf substr($0, 1, length($0) - 1) " "; next }
    line = buf $0; buf = ""
    if (line ~ /git/) check(line, start)
  }' "$@"
}

# expect <hit|clean> <description> <line…> — the scanner against lines whose
# verdict is known. Fed through process substitution, so the fixtures sit in
# quotes here and the scan of this very file stays clean.
expect() {
  local want="$1" desc="$2" found rc; shift 2
  found=$(scan <(printf '%s\n' "$@")); rc=$?
  [ "$rc" = 0 ] || { bad "$desc: the scan failed (awk exit $rc)"; return; }
  case "$want" in
    hit)   [ -n "$found" ] && ok "reported: $desc" || bad "not reported: $desc" ;;
    clean) [ -z "$found" ] && ok "not reported: $desc" || bad "false alarm ($desc): $found" ;;
  esac
}

if [ $# -gt 0 ]; then
  files=("$@")
else
  echo "── self-test"
  expect hit "4i-d before R-0103" \
    "git -C \"\$AH_PRIVATE_DIR\" log --format=%s | grep -qx 'roadmap: add R-0018' \\" \
    '  && ok "private repo: roadmap.py committed the row" || bad "log: $(git -C "$AH_PRIVATE_DIR" log --format=%s)"'
  expect hit "case 10 before R-0103" \
    "git -C \"\$AH_PRIVATE_DIR\" log --oneline 2>/dev/null | grep -q 'weekly ' \\" \
    '  && ok "history.csv committed in the private repo" || bad "no weekly commit in the private repo"'
  expect hit "the pipe on the continuation line" 'git log --oneline \' '  | grep -q x'
  expect hit "rev-list into head" 'git rev-list HEAD | head -n 2'
  expect hit "a sed that quits" "git log --format=%H | sed -n '2{p;q}'"
  expect hit "grep -m" 'git reflog | grep -m1 x'
  expect hit "grep -l" 'git shortlog -s | grep -l x'
  expect hit "an early reader later in the pipeline" 'git log --format=%s 2>&1 | sort | grep -q x'
  expect clean "git log -1 into grep -q" 'git log -1 --format=%s | grep -q x'
  expect clean "-n 1 and --max-count=1" 'git log -n 1 | grep -q x' 'git log --max-count=1 | head -1'
  expect clean "the log in a variable first" 'x=$(git log --format=%s)' 'grep -q y <<<"$x"'
  expect clean "readers that read everything" 'git log | grep -c x' 'git log | wc -l'
  expect clean "a comment" '# git log | grep -q x' 'true  # git log | grep -q x'
  expect clean "a pipe inside quotes" "echo 'git log | grep -q x'" 'echo "git log | grep -q x"'
  expect clean "a git command outside the list" 'git status --porcelain | grep -q x'
  expect clean "|| is no pipe" 'git log || grep -q x f'
  expect clean "the pipeline ended before the pipe" 'git log > f; cat f | grep -q x'
  # Registered, or the scripts block never runs it.
  grep -qw pipe_guard_test <<<"$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$HERE/run.sh")" \
    && ok "pipe_guard_test is registered in AH_SCRIPT_TESTS_DEFAULT" \
    || bad "pipe_guard_test missing from AH_SCRIPT_TESTS_DEFAULT"
  echo "── scan"
  files=("$HERE"/*_test.sh)
fi

n=0
for f in "${files[@]}"; do
  if [ -r "$f" ]; then n=$((n + 1)); else bad "cannot read $f"; fi
done
[ "$n" -gt 0 ] && ok "$n script(s) scanned" || bad "no test script found — the guard scans nothing"
found=$(scan "${files[@]}"); rc=$?
if [ "$rc" != 0 ]; then
  bad "the scan itself failed (awk exit $rc)"
elif [ -z "$found" ]; then
  ok "no git producer of many records feeds an early reader"
else
  while IFS= read -r line; do bad "SIGPIPE under pipefail (R-0103): $line"; done <<<"$found"
fi

echo ""
echo "pipe_guard_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
