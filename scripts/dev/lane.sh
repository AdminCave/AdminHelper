#!/usr/bin/env bash
# SPDX-FileCopyrightText: Kevin Stenzel
# SPDX-License-Identifier: GPL-3.0-or-later
#
# lane.sh — manage parallel build lanes (git worktree + VM wiring).
# A lane = its own worktree + feature branch + warm VM, tagged with the lane name
# so no lane can sweep another's boxes (see vm_lane in scripts/vm/lib.sh).
# Full workflow: AUTONOMOUS.md ("Parallel-Betrieb").
#
#   bash scripts/dev/lane.sh new <slug>   worktree ../AdminHelper-<slug> on
#                                         feature/<slug> (forked from main); writes
#                                         .vm/lane, copies .claude/settings.local.json,
#                                         links .devenv.sh
#   bash scripts/dev/lane.sh done <slug>  destroy the lane's VMs, then remove
#                                         worktree + branch (branch only if merged)
#   bash scripts/dev/lane.sh list         worktrees + their warm boxes
set -euo pipefail

CMD="${1:-}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/vm/lib.sh
. "$ROOT/scripts/vm/lib.sh"
# Refuse to run from a linked worktree (its .git is a FILE): `done` would remove
# the very worktree the session sits in, leaving the caller in a deleted cwd.
[ -d "$ROOT/.git" ] || { echo "lane.sh must run from the MAIN checkout, not a worktree"; exit 1; }

lane_new() {
  local slug="${1:?usage: lane.sh new <slug>}"
  # The slug IS the lane id, written to .vm/lane below (vm_lane normalizes
  # lossily: foo_bar and foo.bar would both become lane foo-bar and SHARE their
  # VMs) — so only allow the charset that survives normalization unchanged.
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
  # The lane identity, explicitly: vm.py and lib.sh both read .vm/lane, so every
  # VM this worktree clones carries `lane-<slug>` and no other lane's reap can
  # take it. Deriving the id from the directory name is gone — a file cannot be
  # guessed wrong by one side and right by the other.
  mkdir -p "$wt/.vm" && printf '%s\n' "$slug" > "$wt/.vm/lane"
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
  echo "  (ledger head should say 'Fast-Suite: vm' — the lane has no local toolchain artifacts)"
}

lane_done() {
  local slug="${1:?usage: lane.sh done <slug>}"
  local wt="../AdminHelper-$slug" branch="feature/$slug"
  # Reap with the MAIN checkout's (current) scripts, but against the LANE's own
  # state: the lane's copies fork from main and may predate a change here, while
  # the VMIDs that have to go are recorded in the lane's .vm/warm.env. Abort
  # instead of hiding a reap failure — once the worktree is gone, a leaked VM has
  # no record left to find it by.
  # The state dir is the LANE's when the worktree is still there, and a path that
  # cannot exist when it is not: the warm.env step is then a no-op, but `vm.py
  # reap` and the closing `vm.py list` still run against `lane-$slug`. A worktree
  # somebody removed by hand is exactly the case that leaks, so it must not be
  # the case that silently skips the sweep. Never the MAIN checkout's .vm — that
  # would destroy this session's own warm box.
  local state
  if [ -d "$wt" ]; then
    state="$(cd "$wt" && pwd)/.vm"
  else
    # No worktree, no warm.env — so `reap.sh` would find no VMIDs to destroy and
    # `vm.py reap` only takes what has already expired. A LIVE box of this lane
    # would then burn until its ttl while the closing listing correctly calls it
    # a leak and aborts the removal. Destroy the lane outright: the lane is
    # being dismantled, and nothing else may carry its tag.
    state="$ROOT/.vm/absent-$slug"
    vm_py destroy --lane "$slug" 2>&1 | sed 's/^/  /' \
      || { echo "  destroy failed — VMs of lane $slug may still run"; exit 1; }
    # A hand-deleted directory leaves the worktree REGISTERED and prunable, and
    # git then refuses `branch -d` — even for a fully merged branch — with "is
    # used by worktree". Without this the run would end on the wrong reason
    # ("not merged"), and `-D` would fail the same way.
    git -C "$ROOT" worktree prune >/dev/null 2>&1 || true
  fi
  AH_VM_STATE_DIR="$state" bash "$ROOT/scripts/vm/reap.sh" --lane "$slug" \
    || { echo "  reap failed — NOT removing the worktree (VMs may still run)"; exit 1; }
  # `reap.sh` ends with a listing that exits non-zero on a leak, so reaching here
  # means this lane is clear. The main checkout's own boxes are never touched:
  # every verb above is scoped to `lane-$slug`.
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
    [ -f "$wt/.vm/warm.env" ] || continue
    echo "  $wt boxes: $(grep -E '^(desktop|server)=' "$wt/.vm/warm.env" | tr '\n' ' ')"
  done < <(git worktree list --porcelain | sed -n 's/^worktree //p')
}

# Both verbs, one guard: `done` reaps by lane, so a slug it accepts but `new`
# would have rejected sweeps the wrong lane. `main` and the dash-edge forms are
# the dangerous ones — vm_lane strips leading and trailing dashes, so `-foo`
# becomes lane `foo` and `-` becomes lane `main`, the shared checkout's own lane.
check_slug() {
  case "${1:-}" in
    "") echo "usage: lane.sh <new|done> <slug>"; exit 2 ;;
    main|-*|*-) echo "slug must not be 'main' and must not start or end with '-'"; exit 2 ;;
    *[!a-z0-9-]*) echo "slug must be lowercase [a-z0-9-] only (the slug is the lane id)"; exit 2 ;;
  esac
}

case "$CMD" in
  new)  check_slug "${2:-}"; lane_new "${2:-}" ;;
  done) check_slug "${2:-}"; lane_done "${2:-}" ;;
  list) lane_list ;;
  *) echo "usage: lane.sh <new|done> <slug> | lane.sh list"; exit 2 ;;
esac
