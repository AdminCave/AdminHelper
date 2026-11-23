#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# merge_watch_test.sh — does merge-watch.sh report exactly the pull requests that
# fell out of the merge queue and a red main, and nothing else? A fake gh answers
# with raw GitHub JSON and runs the script's own jq program over it with the real
# jq, so the filter itself is under test; GitHub is never asked.
#
# Run: bash scripts/tests/merge_watch_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

command -v jq >/dev/null || { echo "merge_watch_test: jq missing"; exit 75; }

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
MW="$REPO_ROOT/scripts/dev/merge-watch.sh"
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
export WORK
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
# `gh api …` answers with $WORK/gql.json, `gh run …` with $WORK/runs.json, each
# filtered through the program after --jq/-q. A file holding FAIL fails like a
# network error. Every call's arguments go to $WORK/args.
cat > "$WORK/bin/gh" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WORK/args"
case "$1" in api) f="$WORK/gql.json" ;; run) f="$WORK/runs.json" ;; *) exit 9 ;; esac
[ "$(cat "$f")" = FAIL ] && { echo "HTTP 502" >&2; exit 1; }
prog=""
while [ $# -gt 0 ]; do
  case "$1" in --jq|-q) prog=$2; shift ;; esac
  shift
done
jq -r "$prog" "$f"
FAKE
chmod +x "$WORK/bin/gh"

# pr <n> <entry: - or QUEUED> <last event: - | added | removed:<reason>>
pr() {
  local entry=null ev='[]'
  [ "$2" = - ] || entry="{\"state\":\"$2\"}"
  case "$3" in
    added) ev='[{"__typename":"AddedToMergeQueueEvent"}]' ;;
    removed:*) ev="[{\"__typename\":\"RemovedFromMergeQueueEvent\",\"createdAt\":\"2026-11-23T10:00:00Z\",\"reason\":\"${3#removed:}\"}]" ;;
  esac
  echo "{\"number\":$1,\"mergeQueueEntry\":$entry,\"timelineItems\":{\"nodes\":$ev}}"
}
# gql <queue numbers, comma-separated or "null"> <pr json…>
gql() {
  local queue=$1 q nodes
  shift
  if [ "$queue" = null ]; then q=null; else
    q="{\"entries\":{\"nodes\":[$(for n in ${queue//,/ }; do printf '{"pullRequest":{"number":%s}},' "$n"; done | sed 's/,$//')]}}"
  fi
  nodes=$(IFS=,; echo "$*")
  echo "{\"data\":{\"repository\":{\"mergeQueue\":$q,\"pullRequests\":{\"nodes\":[$nodes]}}}}" > "$WORK/gql.json"
}
# runs <conclusion:sha:id …>, newest first
runs() {
  local out="" r c s i
  for r in "$@"; do IFS=: read -r c s i <<<"$r"; out+="{\"conclusion\":\"$c\",\"headSha\":\"$s\",\"databaseId\":$i},"; done
  echo "[${out%,}]" > "$WORK/runs.json"
}
mw() { rm -f "$WORK/args"; OUT=$(PATH="$WORK/bin:$PATH" bash "$MW" "$@" 2>&1); rc=$?; }
GREEN=success:aaaaaaa1111111:11

gql 638 "$(pr 638 QUEUED added)"; runs "$GREEN"
mw extra; [ $rc -eq 2 ] && [ ! -e "$WORK/args" ] && ok "an argument -> 2, gh never asked" || bad "usage: rc=$rc"

mw
[ $rc -eq 0 ] && [ "$OUT" = "Merge: Queue 1 (#638) · main aaaaaaa success" ] \
  && ok "one queued, main green -> 0 and one line" || bad "clean: rc=$rc [$OUT]"
grep -q 'mergeQueue(branch:"main")' "$WORK/args" && grep -q REMOVED_FROM_MERGE_QUEUE_EVENT "$WORK/args" \
  && ok "it asks for the queue of main and the queue events" || bad "gql args: $(head -1 "$WORK/args")"
grep -q -- '^run list --workflow ci.yml --branch main --event push --status completed' "$WORK/args" \
  && ok "it asks for completed ci.yml push runs on main" || bad "run args: $(grep '^run' "$WORK/args")"

gql null "$(pr 641 - removed:FAILED_CHECKS)" "$(pr 642 - added)" "$(pr 643 - -)" \
  "$(pr 644 - removed:MERGED)" "$(pr 645 QUEUED removed:FAILED_CHECKS)"
mw
[ $rc -eq 1 ] && grep -q '^Merge: Queue 0 · main aaaaaaa success$' <<<"$OUT" \
  && grep -q '^ACTION: #641 ist aus der Merge Queue gefallen (FAILED_CHECKS, 2026-11-23T10:00:00Z)' <<<"$OUT" \
  && ok "a pull request out of the queue -> 1, an ACTION line with reason and time" || bad "out: rc=$rc [$OUT]"
[ "$(grep -c '^ACTION' <<<"$OUT")" = 1 ] \
  && ok "only #641: enqueued, never queued, removed as merged, queued again are no finding" \
  || bad "false findings: [$OUT]"

gql null "$(pr 646 - 'removed:failed checks')"; mw
grep -q '(failed_checks, ' <<<"$OUT" && ok "a reason with a space stays one field" || bad "space: [$OUT]"

gql 638 "$(pr 638 QUEUED added)"; runs cancelled:ccccccc:30 failure:bbbbbbb2222222:22 "$GREEN"
mw
[ $rc -eq 1 ] && grep -q '^Merge: Queue 1 (#638) · main bbbbbbb failure$' <<<"$OUT" \
  && grep -q '^ACTION: main ist rot: ci.yml auf bbbbbbb endete mit failure (gh run view 22 --log-failed)$' <<<"$OUT" \
  && ok "red main behind a cancelled run -> 1 and the failed run" || bad "red: rc=$rc [$OUT]"
runs cancelled:ccccccc:30 skipped:ddddddd:31 "$GREEN"; mw
[ $rc -eq 0 ] && grep -q 'main aaaaaaa success$' <<<"$OUT" \
  && ok "cancelled and skipped runs do not count" || bad "cancelled: rc=$rc [$OUT]"
runs; mw
[ $rc -eq 0 ] && [ "$OUT" = "Merge: Queue 1 (#638) · main kein ci.yml-Lauf" ] \
  && ok "no run at all -> 0, said so" || bad "none: rc=$rc [$OUT]"

echo FAIL > "$WORK/gql.json"; runs "$GREEN"; mw
[ $rc -eq 2 ] && grep -qx 'Merge: ?' <<<"$OUT" && grep -q 'HTTP 502' <<<"$OUT" \
  && ok "graphql failing -> 2 and 'Merge: ?'" || bad "gql fail: rc=$rc [$OUT]"
gql 638 "$(pr 638 QUEUED added)"; echo FAIL > "$WORK/runs.json"; mw
[ $rc -eq 2 ] && grep -qx 'Merge: ?' <<<"$OUT" && ok "run list failing -> 2 and 'Merge: ?'" || bad "run fail: rc=$rc [$OUT]"

echo "merge_watch_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
