#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# merge-watch.sh — what lies around after merges through the queue of main.
#
#   bash scripts/dev/merge-watch.sh
#
# Since R-1345 a session enqueues its pull request and waits with queue-wait.sh
# in the background. When that session has ended, nobody sees a pull request
# that fell out of the queue or a red ci.yml run on main. This asks GitHub live
# (two gh calls, no model, no cron) and the SessionStart hook shows the answer,
# so every session sees it at its start (R-1724). It repairs nothing: the
# pull request's own project reacts (/feature-build §4.7, §4.8).
#
# Output: one line `Merge: Queue <n> (#a #b) · main <sha7> <conclusion>`, then
# one line `ACTION: …` per finding:
#   - an open pull request whose last queue event is a removal other than
#     "merged" (out of the queue and not enqueued again), with reason and time
#   - the newest ci.yml push run on main that ran to an end is not green
# Run it inside the checkout: the repository comes from the current directory
# (or GH_REPO).
#
# Exit: 0 nothing to do · 1 at least one ACTION line · 2 usage, or gh failed
# (prints `Merge: ?` and the error on stderr)

set -uo pipefail

usage() { sed -n '/^#   bash scripts\/dev\/merge-watch.sh/p' "$0" | sed 's/^# \{0,1\}//'; }
case "${1-}" in -h|--help) usage; exit 0 ;; esac
[ $# -eq 0 ] || { usage >&2; exit 2; }

# 100 open pull requests: far above what this repository ever has open; one
# beyond would go unseen, not misreported.
# shellcheck disable=SC2016  # $owner and $name are GraphQL variables, not shell
QUERY='query($owner:String!,$name:String!){repository(owner:$owner,name:$name){
  mergeQueue(branch:"main"){entries(first:50){nodes{pullRequest{number}}}}
  pullRequests(states:OPEN,first:100){nodes{number mergeQueueEntry{state}
    timelineItems(last:1,itemTypes:[ADDED_TO_MERGE_QUEUE_EVENT,REMOVED_FROM_MERGE_QUEUE_EVENT]){
      nodes{__typename ... on RemovedFromMergeQueueEvent{createdAt reason}}}}}}}'
# Lines `Q <n>` per queue entry and `OUT <n> <reason> <time>` per pull request
# that left the queue; the reason has its spaces replaced so it stays one field.
# shellcheck disable=SC2016  # $r and $n are jq variables, not shell
JQ='.data.repository as $r
  | ($r.mergeQueue.entries.nodes // [] | .[] | "Q \(.pullRequest.number)"),
    ($r.pullRequests.nodes[]
      | select(.mergeQueueEntry == null)
      | .number as $n | .timelineItems.nodes[0] // empty
      | select(.__typename == "RemovedFromMergeQueueEvent")
      | select((.reason // "" | ascii_downcase) != "merged")
      | "OUT \($n) \(.reason // "unknown" | gsub("[[:space:]]+"; "_")) \(.createdAt)")'

fail() { echo "Merge: ?"; echo "merge-watch: $1" >&2; exit 2; }

gql=$(gh api graphql -F owner='{owner}' -F name='{repo}' -f query="$QUERY" --jq "$JQ" 2>&1) \
  || fail "gh api graphql failed: $gql"
# A cancelled or skipped run says nothing about main (a newer push superseded
# it): the newest of the last ten that ran to an end counts.
run=$(gh run list --workflow ci.yml --branch main --event push --status completed --limit 10 \
  --json headSha,conclusion,databaseId \
  -q '[.[] | select(.conclusion != "cancelled" and .conclusion != "skipped")]
      | if length == 0 then "none" else .[0] | "\(.headSha) \(.conclusion) \(.databaseId)" end' 2>&1) \
  || fail "gh run list failed: $run"

queued=() actions=()
while read -r kind n reason at; do
  case "$kind" in
    Q) queued+=("#$n") ;;
    OUT) actions+=("ACTION: #$n ist aus der Merge Queue gefallen ($reason, $at) und nicht neu eingereiht") ;;
    "") ;;
    *) fail "unexpected answer: $kind $n $reason $at" ;;
  esac
done <<<"$gql"

if [ "$run" = none ]; then
  main="main kein ci.yml-Lauf"
else
  read -r sha concl id <<<"$run"
  [ -n "${id-}" ] || fail "unexpected run answer: $run"
  main="main ${sha:0:7} $concl"
  [ "$concl" = success ] \
    || actions+=("ACTION: main ist rot: ci.yml auf ${sha:0:7} endete mit $concl (gh run view $id --log-failed)")
fi

echo "Merge: Queue ${#queued[@]}${queued[0]:+ (${queued[*]})} · $main"
for a in ${actions+"${actions[@]}"}; do echo "$a"; done
[ ${#actions[@]} -eq 0 ]
