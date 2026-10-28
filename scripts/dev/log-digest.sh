#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# log-digest.sh — what a reader needs first from a run.sh log, and where the rest is.
#
#   bash scripts/dev/log-digest.sh <log> [<exit>]
#
# Prints, in log order:
#   - every step line (PASS, FAIL, SKIP); a SKIP the caller asked for (--only or
#     `--` arguments, reason AH_ONLY or AH_ARGS) only as a count
#   - every `strict-failed:` line, the summary line and the `failed:` line
#   - pytest SKIPPED lines: the first 10, then their number
#   - per red or self-skipped step: its error lines (at most 60) and the last 20
#     lines of its section, each with its line number in the log
#   - no summary line at all: the last 40 lines (the run ended early or broke)
#   - the exit code, when given, and the log path with its length
# No step line is ever cut, so no red or skipped step can vanish from the digest;
# only the excerpts are bounded, and they name the line range to read on in.
#
# Exit: 0 printed · 2 usage or unreadable log

set -uo pipefail

usage() { sed -n 's/^#   \(bash scripts\/dev\/log-digest.sh.*\)/\1/p' "$0"; }
[ $# -ge 1 ] && [ $# -le 2 ] || { usage >&2; exit 2; }
case "$1" in -h|--help) usage; exit 0 ;; esac
LOG="$1" RC="${2-}"
[ -f "$LOG" ] && [ -r "$LOG" ] || { echo "log-digest: no readable log: $LOG" >&2; exit 2; }
case "$RC" in ''|*[!0-9]*) [ -z "$RC" ] || { echo "log-digest: not an exit code: $RC" >&2; exit 2; } ;; esac

# Two passes over the same file: the first learns which steps are red and where
# their sections end, the second prints. -a: a NUL byte in a suite output must
# not turn the log into "binary" for anything downstream.
LC_ALL=C awk -v rc="$RC" -v logf="$LOG" '
function clean(s) { gsub(/\033\[[0-9;]*[A-Za-z]/, "", s); sub(/\r$/, "", s); return s }
function errline(s,   t) {
  if (s ~ /^  ok /) return 0
  t = tolower(s)
  return t ~ /(fail|error|traceback|assert|panic|exception|not ok|denied|not found|no such file|timed out|timeout|killed|refus|cannot|could not)/ || s ~ /^E  /
}
# The step a result line reports, without the reason of a SKIP.
function stepname(s) {
  s = substr(s, 9)
  if (s ~ / \(self-skipped\)$/) s = substr(s, 1, length(s) - 15)
  return s
}
function flush_excerpt(name,   i, k, from, hidden) {
  printf "── %s: log lines %d-%d; error lines and the last %d:\n", name, start[name] + 1, stop[name], TAILN
  for (i = 1; i <= nerr; i++) { printf "  %d: %s\n", errno[i], errtxt[i]; shown[errno[i]] = 1 }
  from = (nring > TAILN) ? nring - TAILN + 1 : 1
  # Error lines past the cap that the tail below shows anyway are not hidden.
  hidden = more
  for (k = from; k <= nring; k++) { i = (k - 1) % TAILN; if (!(ringno[i] in shown) && errline(ringtxt[i])) hidden-- }
  if (hidden > 0) printf "  … %d more error lines in that range\n", hidden
  for (k = from; k <= nring; k++) {
    i = (k - 1) % TAILN
    if (!(ringno[i] in shown)) printf "  %d: %s\n", ringno[i], ringtxt[i]
  }
}
BEGIN { TAILN = 20; ERRMAX = 60; ENDN = 40 }
NR == FNR {
  l = clean($0)
  if (l ~ /^### /) start[substr(l, 5)] = FNR
  else if (l ~ /^  FAIL  / || l ~ /^  SKIP  .* \(self-skipped\)$/) { s = stepname(l); red[s] = 1; stop[s] = FNR - 1 }
  else if (l ~ /^  run\.sh\[[^]]*\]: /) summary = 1
  total = FNR
  next
}
{
  l = clean($0)
  lastno[FNR % ENDN] = FNR; lasttxt[FNR % ENDN] = l
  if (l ~ /^### /) {
    sec = substr(l, 5); insec = (sec in red) && (sec in start) && start[sec] == FNR
    nerr = 0; more = 0; nring = 0; delete shown
    next
  }
  if (l ~ /^  (PASS|FAIL|SKIP)  /) {
    if (l ~ /^  SKIP  .*\((AH_ONLY|AH_ARGS)\)$/) { narrowed++; next }
    print l
    if (insec && stepname(l) == sec) flush_excerpt(sec)
    insec = 0
    next
  }
  if (insec) {
    if (errline(l)) { if (nerr < ERRMAX) { nerr++; errno[nerr] = FNR; errtxt[nerr] = l } else more++ }
    ringno[nring % TAILN] = FNR; ringtxt[nring % TAILN] = l; nring++
    next
  }
  if (l ~ /^SKIPPED \[/) { if (++skipped <= 10) print "  " l; next }
  if (l ~ /^  strict-failed: /) { print l; next }
  if (l ~ /^  run\.sh\[[^]]*\]: /) {
    if (skipped > 10) printf "  (%d pytest SKIPPED lines in all)\n", skipped
    if (narrowed) printf "  (%d steps outside --only or the -- arguments: not run)\n", narrowed
    narrowed = 0; skipped = 0
    print l
    next
  }
  if (l ~ /^  failed: / || (rc != "" && rc != 0 && l ~ /^  required \(strict\): /)) print l
}
END {
  if (!summary) {
    if (narrowed) printf "  (%d steps outside --only or the -- arguments: not run)\n", narrowed
    printf "── no summary line: the run ended before run.sh counted; the last lines:\n"
    for (k = (total > ENDN ? total - ENDN + 1 : 1); k <= total; k++) printf "  %d: %s\n", lastno[k % ENDN], lasttxt[k % ENDN]
  }
  printf "  %slog: %s (%d lines)\n", (rc != "" ? "exit " rc " · " : ""), logf, total
}' "$LOG" "$LOG"
