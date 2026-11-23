#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# queue-wait.sh — wait until a pull request leaves the merge queue of main.
#
#   bash scripts/dev/queue-wait.sh <pr>
#
# Since R-1344 the ruleset of main requires a merge queue, and `gh pr merge`
# only enqueues (or, with checks still pending, turns auto-merge on). The
# session runs this as a background waiter without model calls (CLAUDE.md §5)
# and carries on with /feature-build §4.8 once it ends. Run it inside the
# checkout: the repository comes from the current directory (or GH_REPO).
#
# Every AH_QUEUE_POLL seconds (default 30) it reads the pull request's state,
# merge commit, queue entry and auto-merge request, up to AH_QUEUE_TIMEOUT
# seconds (default 5400: the queue's check timeout is 60 min, plus a waiting
# entry ahead of it).
#
# Exit: 0 merged (prints `merged <sha>`) · 1 closed, or open and neither queued
# nor set to auto-merge on two reads in a row (left the queue; prints the
# reason) · 2 usage, or gh failed three reads in a row · 3 timeout

set -uo pipefail

usage() { sed -n '/^#   bash scripts\/dev\/queue-wait.sh/p' "$0" | sed 's/^# \{0,1\}//'; }
case "${1-}" in -h|--help) usage; exit 0 ;; esac
if [ $# -ne 1 ] || ! [[ "$1" =~ ^[0123456789]+$ ]]; then usage >&2; exit 2; fi
PR=$1
POLL=${AH_QUEUE_POLL:-30}
TIMEOUT=${AH_QUEUE_TIMEOUT:-5400}
[[ "$POLL" =~ ^[0123456789]+$ && "$TIMEOUT" =~ ^[0123456789]+$ ]] \
  || { echo "queue-wait: AH_QUEUE_POLL and AH_QUEUE_TIMEOUT take whole seconds" >&2; exit 2; }

# shellcheck disable=SC2016  # $owner, $name, $pr are GraphQL variables, not shell
QUERY='query($owner:String!,$name:String!,$pr:Int!){repository(owner:$owner,name:$name){pullRequest(number:$pr){
  state mergeCommit{oid} mergeQueueEntry{state} autoMergeRequest{enabledAt}}}}'
JQ='.data.repository.pullRequest | "\(.state) \(.mergeCommit.oid // "-") \(.mergeQueueEntry.state // "-") \(if .autoMergeRequest then "auto" else "-" end)"'

start=$SECONDS gh_fail=0 idle=0
while :; do
  if line=$(gh api graphql -F owner='{owner}' -F name='{repo}' -F pr="$PR" -f query="$QUERY" --jq "$JQ" 2>&1); then
    gh_fail=0
    read -r state sha entry auto <<<"$line"
    case "$state" in
      MERGED) echo "merged $sha"; exit 0 ;;
      CLOSED) echo "closed: #$PR was closed without a merge"; exit 1 ;;
      OPEN)
        if [ "$entry" = - ] && [ "$auto" = - ]; then
          idle=$((idle + 1))
          # One read without an entry can fall between `gh pr merge` and the
          # queue taking the pull request; two in a row mean it is out.
          [ "$idle" -ge 2 ] && { echo "left the queue: #$PR is open, not queued, no auto-merge (a red queue run or a conflict)"; exit 1; }
        else
          idle=0
        fi ;;
      *) echo "queue-wait: unexpected answer: $line" >&2; exit 2 ;;
    esac
  else
    gh_fail=$((gh_fail + 1))
    echo "queue-wait: gh failed ($gh_fail/3): $line" >&2
    [ "$gh_fail" -ge 3 ] && exit 2
  fi
  [ $((SECONDS - start)) -ge "$TIMEOUT" ] && { echo "timeout: #$PR still waiting after ${TIMEOUT}s" >&2; exit 3; }
  sleep "$POLL"
done
