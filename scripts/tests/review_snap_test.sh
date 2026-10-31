#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review_snap_test.sh — hermetic test for scripts/dev/review-snap.sh: the tree
# holds the judged state (changed, new and deleted files), the delta between two
# snapshots shows only what changed in between, and the worktree and its index
# stay as they were — a reviewer must not change WT.
#
# Run: bash scripts/tests/review_snap_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SNAP="$HERE/../dev/review-snap.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
R="$WORK/repo"
g() { git -C "$R" -c user.name=t -c user.email=t@example.invalid "$@"; }

mkdir -p "$R/src" && git init -q "$R"
printf 'a\n' > "$R/src/a.txt"; printf 'b\n' > "$R/src/b.txt"; printf 'keep\n' > "$R/other.txt"
printf 'ignored.log\n' > "$R/.gitignore"
g add -A && g commit -qm init

# The state under review: a changed, a new, a deleted file, one outside the paths,
# one ignored, and something already staged in the real index.
printf 'a2\n' > "$R/src/a.txt"
printf 'new\n' > "$R/src/new.txt"
rm "$R/src/b.txt"
printf 'outside\n' > "$R/other.txt"
printf 'noise\n' > "$R/ignored.log"
printf 'staged\n' > "$R/staged.txt" && g add staged.txt
before_status=$(g status --porcelain=v1 --untracked-files=all)
before_index=$(g ls-files -s | sha256sum)

rc=0; T1=$(bash "$SNAP" "$R" src) || rc=$?
[ "$rc" = 0 ] && [[ "$T1" =~ ^[0-9a-f]{40}$ ]] && ok "prints a tree id" || bad "rc=$rc out=$T1"
[ "$(g cat-file -t "$T1" 2>/dev/null)" = tree ] && ok "the id is a tree" || bad "not a tree: $T1"
[ "$(g show "$T1:src/a.txt")" = a2 ] && ok "changed file: working-tree content" || bad "a.txt in tree: $(g show "$T1:src/a.txt")"
[ "$(g show "$T1:src/new.txt" 2>/dev/null)" = new ] && ok "new file is in the tree" || bad "new.txt missing"
g cat-file -e "$T1:src/b.txt" 2>/dev/null && bad "deleted file still in the tree" || ok "deleted file is gone"
[ "$(g show "$T1:other.txt")" = keep ] && ok "a path outside the given ones stays at HEAD" || bad "other.txt: $(g show "$T1:other.txt")"
g cat-file -e "$T1:staged.txt" 2>/dev/null && bad "the real index leaked into the tree" || ok "the real index does not leak in"

[ "$(g status --porcelain=v1 --untracked-files=all)" = "$before_status" ] && ok "worktree status unchanged" || bad "status changed"
[ "$(g ls-files -s | sha256sum)" = "$before_index" ] && ok "real index unchanged" || bad "index changed"
left=$(find "$(g rev-parse --absolute-git-dir)" -maxdepth 1 -name 'review-snap.*')
[ -z "$left" ] && ok "no temp dir left in the git dir" || bad "left: $left"

# Same state, same tree; a further change shows up alone in the delta.
[ "$(bash "$SNAP" "$R" src)" = "$T1" ] && ok "unchanged state gives the same tree" || bad "tree differs without a change"
printf 'a3\n' > "$R/src/a.txt"
T2=$(bash "$SNAP" "$R" src)
delta=$(g diff --name-only "$T1" "$T2")
[ "$delta" = src/a.txt ] && ok "delta names only the file changed since" || bad "delta: $delta"
full=$(g diff --name-only HEAD "$T2" | sort | tr '\n' ' ')
[ "$full" = "src/a.txt src/b.txt src/new.txt " ] && ok "against HEAD the full change is there" || bad "full: $full"

# Without paths: the whole working tree, .gitignore respected.
T3=$(bash "$SNAP" "$R")
[ "$(g show "$T3:other.txt")" = outside ] && ok "no paths: whole working tree" || bad "other.txt: $(g show "$T3:other.txt")"
g cat-file -e "$T3:ignored.log" 2>/dev/null && bad "ignored file in the tree" || ok "ignored file stays out"

rc=0; bash "$SNAP" 2>/dev/null || rc=$?
[ "$rc" = 2 ] && ok "no worktree: usage, exit 2" || bad "rc=$rc"
rc=0; bash "$SNAP" "$WORK/nope" 2>/dev/null || rc=$?
[ "$rc" != 0 ] && ok "not a repository: non-zero exit" || bad "rc=0 for a missing repo"

echo ""
echo "review_snap_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
