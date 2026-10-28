#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# log-digest.sh — what a reader needs first from a run.sh log, and where the rest is.
#
#   bash scripts/dev/log-digest.sh <log> [<exit>]
#
# Prints:
#   - one line per step (PASS, FAIL, SKIP) in the order the log first names it; a
#     SKIP the caller asked for (--only or `--` arguments, reason AH_ONLY or
#     AH_ARGS) only as a count
#   - per red or self-skipped step: its error lines (at most 60) and the last 20
#     lines of its section, each with its line number in the log
#   - pytest SKIPPED lines: the first 10, then their number
#   - run.sh's closing block: the summary, the strict-failed list, the failed list
#     (the required set only on a red run)
#   - no closing block at the end of the log: every strict-failed line and the last
#     40 lines (the run ended early or broke)
#   - the exit code, when given, and the log path with its length
#
# A step's output can itself look like run.sh output: a red shell test prints the
# run.sh or digest text it captured. So nothing inside the log is trusted to mark
# a boundary. The closing block counts only where run.sh writes it, at the very end
# of the log. A step shows the WORST result any line gives it (FAIL over SKIP over
# PASS over a SKIP asked for), and conflicting lines are named. A red step's excerpt
# runs from the first header of its name to the last result line of its name: on
# doubt it shows more, never less. Step lines and the closing block are never cut;
# only the excerpts are bounded, and they name the range to read on in.
#
# Exit: 0 printed · 2 usage or unreadable log

set -uo pipefail

usage() { sed -n 's/^#   \(bash scripts\/dev\/log-digest.sh.*\)/\1/p' "$0"; }
[ $# -ge 1 ] && [ $# -le 2 ] || { usage >&2; exit 2; }
case "$1" in -h|--help) usage; exit 0 ;; esac
LOG="$1" RC="${2-}"
[ -f "$LOG" ] && [ -r "$LOG" ] || { echo "log-digest: no readable log: $LOG" >&2; exit 2; }
case "$RC" in ''|*[!0-9]*) [ -z "$RC" ] || { echo "log-digest: not an exit code: $RC" >&2; exit 2; } ;; esac

# Three passes over the same file: 1 finds the closing block, 2 the steps and their
# ranges, 3 collects the excerpts and prints.
LC_ALL=C awk -v rc="$RC" -v logf="$LOG" '
function clean(s) { gsub(/\033\[[0-9;]*[A-Za-z]/, "", s); sub(/\r$/, "", s); return s }
function errline(s,   t) {
  if (s ~ /^  ok /) return 0
  t = tolower(s)
  return t ~ /(fail|error|traceback|assert|panic|exception|not ok|denied|not found|no such file|timed out|timeout|killed|refus|cannot|could not)/ || s ~ /^E  /
}
function isresult(s) { return s ~ /^  (PASS|FAIL|SKIP)  ./ }
# The step a result line reports; a SKIP line ends in its reason, in parentheses.
function stepname(s,   skip) {
  skip = (s ~ /^  SKIP  /); s = substr(s, 9)
  if (skip && match(s, / \([^()]*\)$/)) s = substr(s, 1, RSTART - 1)
  return s
}
function reason(s) { return (match(s, / \([^()]*\)$/)) ? substr(s, RSTART + 2, RLENGTH - 3) : "" }
# FAIL 3 · SKIP with a reason of its own 2 · PASS 1 · SKIP asked for (AH_ONLY, AH_ARGS) 0
function rank(s,   r) {
  if (s ~ /^  FAIL  /) return 3
  if (s ~ /^  PASS  /) return 1
  r = reason(s)
  return (r == "AH_ONLY" || r == "AH_ARGS") ? 0 : 2
}
# The error lines and the tail, merged in log order; a line in both once.
function excerpt(nm,   i, k, j, from, hidden, n, tn, tt) {
  printf "── %s: log lines %d-%d; error lines and the last %d:\n", nm, first[nm] + 1, last[nm] - 1, TAILN
  n = nerr[nm]; from = (nring[nm] > TAILN) ? nring[nm] - TAILN + 1 : 1
  # Error lines past the cap that the tail shows anyway are not hidden.
  hidden = more[nm]
  for (k = from; k <= nring[nm]; k++) { j = (k - 1) % TAILN; if (errline(ringtxt[nm, j]) && (n < ERRMAX || ringno[nm, j] > errno[nm, n])) hidden-- }
  if (hidden > 0) printf "  … %d more error lines in that range\n", hidden
  i = 1; k = from
  while (i <= n || k <= nring[nm]) {
    if (k <= nring[nm]) { j = (k - 1) % TAILN; tn = ringno[nm, j]; tt = ringtxt[nm, j] } else tn = ""
    if (i <= n && (tn == "" || errno[nm, i] < tn)) { printf "  %d: %s\n", errno[nm, i], errtxt[nm, i]; i++ }
    else { printf "  %d: %s\n", tn, tt; if (i <= n && errno[nm, i] == tn) i++; k++ }
  }
}
BEGIN { TAILN = 20; ERRMAX = 60; ENDN = 40; pass = 0 }
FNR == 1 { pass++ }
pass == 1 {
  l = clean($0); total = FNR
  if (l ~ /^  run\.sh\[[^]]*\]: /) { lastsum = FNR; after = 0; foreign = 0 }
  else if (l ~ /[^ \t]/) { after++; if (l !~ /^  (required \(strict\)|strict-failed|artifact|failed): /) foreign++ }
  next
}
# After its summary run.sh writes only the required set, the strict-failed list,
# the artifact line and the failed list. A summary followed by anything else is
# captured output, and the run ended without its own.
pass == 2 && FNR == 1 { top = (lastsum && after <= 6 && !foreign) ? lastsum : total + 1 }
pass == 2 {
  if (FNR >= top) next
  l = clean($0)
  if (l ~ /^### /) { nm = substr(l, 5); if (!(nm in first)) first[nm] = FNR; next }
  if (isresult(l)) {
    nm = stepname(l); r = rank(l)
    if (!(nm in worst)) { order[++nsteps] = nm; worst[nm] = r; line[nm] = l }
    else {
      if (r != worst[nm] || l != line[nm]) conflict[nm] = 1
      if (r > worst[nm]) { worst[nm] = r; line[nm] = l }
    }
    last[nm] = FNR
    next
  }
  if (l ~ /^  strict-failed: /) bodystrict[++nbs] = l
  next
}
pass == 3 && FNR == 1 {
  for (i = 1; i <= nsteps; i++) {
    nm = order[i]
    red[nm] = (worst[nm] == 3 || (worst[nm] == 2 && reason(line[nm]) == "self-skipped")) && (nm in first) && first[nm] < last[nm]
  }
}
pass == 3 {
  l = clean($0)
  lastno[FNR % ENDN] = FNR; lasttxt[FNR % ENDN] = l
  if (FNR >= top) {
    if (l ~ /^  run\.sh\[[^]]*\]: / || l ~ /^  strict-failed: / || l ~ /^  failed: / \
        || (rc != "" && rc != 0 && l ~ /^  required \(strict\): /)) closing[++ncl] = l
    next
  }
  if (l ~ /^SKIPPED \[/) { if (++skipped <= 10) skipline[skipped] = "  " l }
  for (i = 1; i <= nsteps; i++) {
    nm = order[i]
    if (!red[nm] || FNR <= first[nm] || FNR >= last[nm]) continue
    if (errline(l)) { if (nerr[nm] < ERRMAX) { nerr[nm]++; errno[nm, nerr[nm]] = FNR; errtxt[nm, nerr[nm]] = l } else more[nm]++ }
    ringno[nm, nring[nm] % TAILN] = FNR; ringtxt[nm, nring[nm] % TAILN] = l; nring[nm]++
  }
}
END {
  if (top == "") top = total + 1   # an empty log: no pass ever started
  for (i = 1; i <= nsteps; i++) {
    nm = order[i]
    if (worst[nm] == 0) { narrowed++; continue }
    print line[nm]
    if (red[nm]) excerpt(nm)
  }
  for (i = 1; i <= nsteps; i++) if (order[i] in conflict) cl = cl (cl ? "; " : "") order[i]
  if (cl) printf "  (result lines disagree for: %s — the log holds nested run.sh output; the worst one is shown)\n", cl
  if (narrowed) printf "  (%d steps outside --only or the -- arguments: not run)\n", narrowed
  for (i = 1; i <= skipped && i <= 10; i++) print skipline[i]
  if (skipped > 10) printf "  (%d pytest SKIPPED lines in all)\n", skipped
  if (top <= total) for (i = 1; i <= ncl; i++) print closing[i]
  else {
    for (i = 1; i <= nbs; i++) print bodystrict[i]
    printf "── no closing summary at the end of the log: the run ended before run.sh counted; the last lines:\n"
    for (k = (total > ENDN ? total - ENDN + 1 : 1); k <= total; k++) printf "  %d: %s\n", lastno[k % ENDN], lasttxt[k % ENDN]
  }
  printf "  %slog: %s (%d lines)\n", (rc != "" ? "exit " rc " · " : ""), logf, total
}' "$LOG" "$LOG" "$LOG"
