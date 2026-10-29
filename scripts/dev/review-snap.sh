#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review-snap.sh — the id of a git tree that holds a worktree's state as a
# reviewer judged it: HEAD plus the working-tree content of the given paths,
# tracked and new files alike (without paths: the whole working tree, minus what
# .gitignore drops). A follow-up round reads only what changed since:
#   git -C WT diff <tree of the last round> <tree now>
# A task's changes are not committed yet, so HEAD cannot mark the judged state;
# a second full diff per round was the reviewers' biggest token cost
# (2026-10-29: up to seven full reads of one diff in one review).
#
# Neither the worktree's files nor its index change: a temporary index in the
# worktree's own git dir, removed on exit. The blobs land in the object store
# like after `git add` — unreferenced, so git gc drops them later.
#
# Run: bash scripts/dev/review-snap.sh <worktree> [<path>...]
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: review-snap.sh <worktree> [<path>...]" >&2; exit 2; }
WT=$1; shift
GITDIR=$(git -C "$WT" rev-parse --absolute-git-dir)
TMP=$(mktemp -d -p "$GITDIR" review-snap.XXXXXX)
trap 'rm -f "$TMP/index" "$TMP/index.lock"; rmdir "$TMP"' EXIT
export GIT_INDEX_FILE="$TMP/index"

git -C "$WT" read-tree HEAD
# --ignore-missing is not needed: -A records a deleted path as deleted.
git -C "$WT" add -A -- "${@:-.}"
git -C "$WT" write-tree
