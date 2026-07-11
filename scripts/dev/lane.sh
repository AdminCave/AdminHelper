#!/usr/bin/env bash
# SPDX-FileCopyrightText: Kevin Stenzel
# SPDX-License-Identifier: GPL-3.0-or-later
#
# lane.sh — manage parallel build lanes (git worktree + crabbox wiring).
# A lane = its own worktree + feature branch + warm crabbox box in its own pond
# (derived from the checkout dir name — see cbx_lane in scripts/tests/crabbox_lib.sh).
# Full workflow: AUTONOMOUS.md ("Parallel-Betrieb").
#
#   bash scripts/dev/lane.sh new <slug>   worktree ../AdminHelper-<slug> on
#                                         feature/<slug> (forked from main) + links
#                                         to the gitignored per-machine files
#                                         (.devenv.sh, .claude/settings.local.json)
#   bash scripts/dev/lane.sh done <slug>  reap the lane's boxes, remove worktree +
#                                         branch (branch only if merged)
#   bash scripts/dev/lane.sh list         worktrees + their warm boxes
set -euo pipefail

CMD="${1:-}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

lane_new() {
  local slug="${1:?usage: lane.sh new <slug>}"
  local wt="../AdminHelper-$slug" branch="feature/$slug"
  [ -e "$wt" ] && { echo "lane dir $wt already exists"; exit 1; }
  # A worktree only sees COMMITTED state — an uncommitted plan (spec + ledger)
  # from /feature-plan would be invisible to the lane.
  if ! git cat-file -e "main:tasks/$slug.md" 2>/dev/null; then
    echo "  WARN: tasks/$slug.md is not committed on main — commit the plan first"
    echo "        (chore(plan): add spec + ledger for $slug), or the lane won't see it."
  fi
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    git worktree add "$wt" "$branch"
  else
    git worktree add -b "$branch" "$wt" main
  fi
  # The lane needs the gitignored per-machine files: toolchain env + the crabbox
  # provider secret (cbx_load_env reads .claude/settings.local.json).
  [ -f .devenv.sh ] && ln -sfn "$ROOT/.devenv.sh" "$wt/.devenv.sh"
  [ -f .claude/settings.local.json ] \
    && ln -sfn "$ROOT/.claude/settings.local.json" "$wt/.claude/settings.local.json"
  echo ""
  echo "── lane $slug ready ──"
  echo "  start:  cd $wt && claude --model opus --permission-mode acceptEdits"
  echo "  then:   /feature-build tasks/$slug.md"
  echo "  (ledger head should say 'Fast-Suite: crabbox' — the lane has no local toolchain artifacts)"
}

lane_done() {
  local slug="${1:?usage: lane.sh done <slug>}"
  local wt="../AdminHelper-$slug" branch="feature/$slug"
  if [ -d "$wt" ]; then
    # Reap via the LANE's scripts so CBX_ROOT (and thus pond + warm.env) is the lane's.
    ( cd "$wt" && bash scripts/tests/crabbox_reap.sh ) || true
    git worktree remove "$wt" \
      || { echo "worktree not clean — inspect it, then: git worktree remove --force $wt"; exit 1; }
  fi
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    git branch -d "$branch" 2>/dev/null && echo "  branch $branch deleted (was merged)" \
      || echo "  branch $branch kept (not merged — git branch -D $branch if you mean it)"
  fi
}

lane_list() {
  git worktree list
  local wt
  while read -r wt; do
    [ "$wt" = "$ROOT" ] && continue
    [ -f "$wt/.crabbox/warm.env" ] || continue
    echo "  $wt boxes: $(grep -E '^(desktop|server)=' "$wt/.crabbox/warm.env" | tr '\n' ' ')"
  done < <(git worktree list --porcelain | awk '/^worktree /{print $2}')
}

case "$CMD" in
  new)  lane_new "${2:-}" ;;
  done) lane_done "${2:-}" ;;
  list) lane_list ;;
  *) echo "usage: lane.sh <new|done> <slug> | lane.sh list"; exit 2 ;;
esac
