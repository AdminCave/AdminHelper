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
#                                         feature/<slug> (forked from main); copies
#                                         .claude/settings.local.json, links .devenv.sh
#   bash scripts/dev/lane.sh done <slug>  stop the lane's boxes (recorded slugs +
#                                         pond sweep), then remove worktree + branch
#                                         (branch only if merged)
#   bash scripts/dev/lane.sh list         worktrees + their warm boxes
set -euo pipefail

CMD="${1:-}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# Refuse to run from a linked worktree (its .git is a FILE): `done` would remove
# the very worktree the session sits in, leaving the caller in a deleted cwd.
[ -d "$ROOT/.git" ] || { echo "lane.sh must run from the MAIN checkout, not a worktree"; exit 1; }

lane_new() {
  local slug="${1:?usage: lane.sh new <slug>}"
  # The dir name IS the lane id (cbx_lane normalizes lossily: foo_bar and foo.bar
  # would both become lane foo-bar and SHARE a pond) — so only allow the charset
  # that survives normalization unchanged.
  case "$slug" in *[!a-z0-9-]*)
    echo "slug must be lowercase [a-z0-9-] only (the dir name is the lane/pond id)"; exit 2 ;;
  esac
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
  # Per-machine files the lane needs (both gitignored): .devenv.sh is read-only →
  # symlink; settings.local.json is WRITTEN by Claude Code (permission grants), a
  # symlink would make N lane sessions read-modify-write ONE shared file → COPY.
  [ -f .devenv.sh ] && ln -sfn "$ROOT/.devenv.sh" "$wt/.devenv.sh"
  [ -f .claude/settings.local.json ] \
    && cp .claude/settings.local.json "$wt/.claude/settings.local.json"
  echo ""
  echo "── lane $slug ready ──"
  echo "  start:  cd $wt && claude --model opus --permission-mode acceptEdits"
  echo "  then:   /feature-build tasks/$slug.md"
  echo "  (ledger head should say 'Fast-Suite: crabbox' — the lane has no local toolchain artifacts)"
}

lane_done() {
  local slug="${1:?usage: lane.sh done <slug>}"
  local wt="../AdminHelper-$slug" branch="feature/$slug"
  # Reap with the MAIN checkout's (current) scripts: the lane's own copies fork
  # from main and may predate the lane-aware pond split — running them would
  # sweep the shared ah-warm pond (other lanes' boxes). Read the lane's warm.env
  # BEFORE removing the worktree, and abort instead of hiding reap failures — a
  # hidden failure leaks paid boxes with no record left once warm.env is gone.
  # shellcheck source=scripts/tests/crabbox_lib.sh
  . "$ROOT/scripts/tests/crabbox_lib.sh"
  command -v crabbox >/dev/null || { echo "crabbox not installed — NOT removing the worktree (boxes may still run)"; exit 1; }
  cbx_load_env || { echo "crabbox env not loadable — NOT removing the worktree (boxes may still run)"; exit 1; }
  local pond ids s
  pond="$(AH_LANE="$slug" cbx_pond)"
  if [ -f "$wt/.crabbox/warm.env" ]; then
    while IFS='=' read -r role s; do
      case "$role" in desktop|server)
        [ -n "$s" ] && { echo "  stop $role $s"; cbx stop --id "$s" >/dev/null 2>&1 || true; } ;;
      esac
    done < "$wt/.crabbox/warm.env"
  fi
  ids="$(cbx list --pond "$pond" 2>/dev/null | grep -oE 'lease=cbx_[a-z0-9]+' | cut -d= -f2 | sort -u || true)"
  for id in $ids; do
    cbx stop --id "$id" >/dev/null 2>&1 || true; echo "  stopped $id"
  done
  if cbx list --pond "$pond" 2>/dev/null | grep -q 'lease='; then
    echo "  pond $pond still has leases — NOT removing the worktree; inspect: crabbox list --pond $pond"; exit 1
  fi
  if [ -d "$wt" ]; then
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
  # sed, not awk '{print $2}': worktree paths may contain spaces.
  while read -r wt; do
    [ "$wt" = "$ROOT" ] && continue
    [ -f "$wt/.crabbox/warm.env" ] || continue
    echo "  $wt boxes: $(grep -E '^(desktop|server)=' "$wt/.crabbox/warm.env" | tr '\n' ' ')"
  done < <(git worktree list --porcelain | sed -n 's/^worktree //p')
}

case "$CMD" in
  new)  lane_new "${2:-}" ;;
  done) lane_done "${2:-}" ;;
  list) lane_list ;;
  *) echo "usage: lane.sh <new|done> <slug> | lane.sh list"; exit 2 ;;
esac
