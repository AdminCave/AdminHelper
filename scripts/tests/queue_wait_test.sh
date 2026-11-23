#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# queue_wait_test.sh — does queue-wait.sh end exactly when the pull request
# leaves the merge queue, with the right exit? A fake gh plays a scripted
# sequence of answers (one line per read); GitHub is never asked.
#
# Run: bash scripts/tests/queue_wait_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
QW="$REPO_ROOT/scripts/dev/queue-wait.sh"
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
export WORK SEQ="$WORK/seq"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
# The fake answers with the next line of $SEQ (what `--jq` would print); a line
# FAIL makes it fail like a network error. It logs its arguments and counts reads.
cat > "$WORK/bin/gh" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WORK/args"
n=$(( $(cat "$WORK/n" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$WORK/n"
line=$(sed -n "${n}p" "$SEQ")
[ -n "$line" ] || line=$(tail -n 1 "$SEQ")
[ "$line" = FAIL ] && { echo "HTTP 502" >&2; exit 1; }
echo "$line"
FAKE
chmod +x "$WORK/bin/gh"

# q <answers…> -- [args] : run queue-wait.sh against these answers
q() {
  : > "$SEQ"; rm -f "$WORK/n" "$WORK/args"
  while [ $# -gt 0 ] && [ "$1" != -- ]; do echo "$1" >> "$SEQ"; shift; done
  [ "${1-}" = -- ] && shift
  OUT=$(PATH="$WORK/bin:$PATH" AH_QUEUE_POLL=0 AH_QUEUE_TIMEOUT="${TO:-60}" \
        bash "$QW" "${@:-42}" 2>&1); rc=$?
  READS=$(cat "$WORK/n" 2>/dev/null || echo 0)
}

q -- abc; [ $rc -eq 2 ] && [ "$READS" = 0 ] && ok "a non-number -> 2, gh never asked" || bad "usage: rc=$rc reads=$READS"
q -- 1 2; [ $rc -eq 2 ] && ok "two arguments -> 2" || bad "two args: rc=$rc"
OUT=$(AH_QUEUE_POLL=x bash "$QW" 42 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q 'whole seconds' <<<"$OUT" && ok "a poll interval that is no number -> 2" || bad "poll: rc=$rc $OUT"

q "OPEN - AWAITING_CHECKS -" "OPEN - QUEUED -" "MERGED abc123 - -"
[ $rc -eq 0 ] && [ "$OUT" = "merged abc123" ] && [ "$READS" = 3 ] && ok "queued, then merged -> 0 and the merge sha" \
  || bad "merged: rc=$rc reads=$READS [$OUT]"
grep -q -- "-F pr=42" "$WORK/args" && grep -q "mergeQueueEntry" "$WORK/args" && grep -q -- "--jq" "$WORK/args" \
  && ok "it asks for the queue entry of the named pull request" || bad "args: $(cat "$WORK/args")"

q "OPEN - - auto" "OPEN - - auto" "OPEN - - auto" "MERGED def456 - -"
[ $rc -eq 0 ] && [ "$READS" = 4 ] && ok "auto-merge pending counts as waiting, not as out of the queue" \
  || bad "auto: rc=$rc reads=$READS [$OUT]"

q "OPEN - QUEUED -" "OPEN - - -" "OPEN - - -" "MERGED never - -"
[ $rc -eq 1 ] && grep -q 'left the queue' <<<"$OUT" && [ "$READS" = 3 ] && ok "two reads without entry -> 1, left the queue" \
  || bad "ejected: rc=$rc reads=$READS [$OUT]"
# Counter-check: one read without an entry is a gap, not an ejection.
q "OPEN - - -" "OPEN - QUEUED -" "OPEN - - -" "MERGED aaa - -"
[ $rc -eq 0 ] && [ "$OUT" = "merged aaa" ] && ok "a single read without entry is not yet out" || bad "gap: rc=$rc [$OUT]"

q "CLOSED - - -"; [ $rc -eq 1 ] && grep -q 'closed' <<<"$OUT" && ok "closed -> 1" || bad "closed: rc=$rc [$OUT]"
q "WEIRD - - -"; [ $rc -eq 2 ] && grep -q 'unexpected' <<<"$OUT" && ok "an unknown state -> 2" || bad "weird: rc=$rc [$OUT]"

q FAIL FAIL "MERGED bbb - -"
[ $rc -eq 0 ] && grep -qx "merged bbb" <<<"$OUT" && ok "two failed reads are retried" || bad "retry: rc=$rc [$OUT]"
q FAIL FAIL FAIL "MERGED ccc - -"
[ $rc -eq 2 ] && [ "$READS" = 3 ] && grep -q '3/3' <<<"$OUT" && ok "three failed reads in a row -> 2" \
  || bad "gh down: rc=$rc reads=$READS [$OUT]"

TO=0 q "OPEN - QUEUED -"
[ $rc -eq 3 ] && grep -q 'timeout' <<<"$OUT" && [ "$READS" = 1 ] && ok "still queued at the deadline -> 3" \
  || bad "timeout: rc=$rc reads=$READS [$OUT]"

echo "queue_wait_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
