#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# worktree-teardown.sh — take down what worktree-setup.sh made (CLAUDE.md §8): the
# lane's VMs first, then the worktree, its test database and venv, and its branch
# when that is merged.
#
#   bash scripts/dev/worktree-teardown.sh <path> <slug>
#
# The VMs go first, and when they cannot go nothing else does: the worktree's
# .vm/warm.env records their VMIDs, and once the worktree is gone a leaked VM has
# no record left to find it by. A worktree removed by hand is swept by its lane tag.
# Repeatable: a second run after a teardown exits 0.
# Exit: 0 done · 1 a step failed (the reason is printed) · 2 wrong call.
set -euo pipefail

usage() { echo "usage: worktree-teardown.sh <path> <slug>" >&2; exit 2; }
fail() { echo "worktree-teardown.sh: $*" >&2; exit 1; }
[ $# -eq 2 ] || usage
SLUG="$2"

# The same rule as worktree-setup.sh: teardown reaps by lane, so a slug setup would
# not take sweeps another lane (-foo is lane foo, - is lane main).
case "$SLUG" in
  "") usage ;;
  main|-*|*-) echo "slug must not be 'main' and must not start or end with '-'" >&2; exit 2 ;;
  *[!abcdefghijklmnopqrstuvwxyz0123456789-]*) echo "slug must be lowercase [a-z0-9-] only (the slug is the lane id)" >&2; exit 2 ;;
esac
[ "${#SLUG}" -le 40 ] || { echo "slug must be at most 40 characters" >&2; exit 2; }

# An inherited GIT_DIR or GIT_WORK_TREE would point git -C at another repository.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
ROOT="$(cd "$(dirname "$0")/../.." && pwd -P)"
# From a linked worktree (its .git is a file) this could remove the very worktree
# the caller sits in, with that worktree's copy of reap.sh.
[ -d "$ROOT/.git" ] || { echo "worktree-teardown.sh runs from the main checkout, not from a worktree" >&2; exit 2; }
WT="$(realpath -m -- "$1")"
[ "$WT" != "$ROOT" ] || { echo "$1 is the main checkout, never taken down" >&2; exit 2; }
registered() {
  local list line
  list="$(git -C "$ROOT" worktree list --porcelain)" || return 1
  while IFS= read -r line; do
    case "$line" in "worktree "*) [ "$(realpath -m -- "${line#worktree }")" != "$1" ] || return 0 ;; esac
  done <<<"$list"
  return 1
}
if [ -d "$WT" ]; then
  registered "$WT" || { echo "$1 is no worktree of $ROOT — nothing taken down" >&2; exit 2; }
  if [ -f "$WT/.vm/lane" ] && [ "$(cat "$WT/.vm/lane")" != "$SLUG" ]; then
    echo "$1 is lane $(cat "$WT/.vm/lane"), not $SLUG — nothing taken down" >&2; exit 2
  fi
else
  # A path that is not there with the slug of a worktree that is — a typo, or a
  # relative path from another directory — would take that worktree's lane,
  # database and venv down and leave the worktree standing.
  other=""
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) other="${line#worktree }" ;;
      *) [ -d "$other" ] && { [ "$line" = "branch refs/heads/feature/$SLUG" ] \
           || [ "$(cat "$other/.vm/lane" 2>/dev/null)" = "$SLUG" ]; } \
           && { echo "$1 does not exist, but $other is lane $SLUG — nothing taken down" >&2; exit 2; } ;;
    esac
  done < <(git -C "$ROOT" worktree list --porcelain)
fi

# The database's server, read before anything goes: a URL that cannot be used must
# not leave a teardown half done. As in worktree-setup.sh.
DB="adminhelper_test_${SLUG//-/_}"
[ -f "$ROOT/.devenv.sh" ] || fail "no .devenv.sh in the main checkout — $DB cannot be dropped, nothing taken down"
URL="$(set +eu; unset AH_TEST_DB; . "$ROOT/.devenv.sh" >/dev/null 2>&1; printf '%s' "${AH_TEST_DB:-}")"
[ -n "$URL" ] || fail "the main checkout's .devenv.sh sets no AH_TEST_DB — $DB cannot be dropped, nothing taken down"
if [[ "$URL" =~ ^postgresql\+[abcdefghijklmnopqrstuvwxyz0123456789]+:// ]]; then URL="postgresql://${URL#*://}"; fi
# shellcheck source=scripts/dev/pg-url.sh
. "$ROOT/scripts/dev/pg-url.sh"
pg_url_split "$URL" "postgresql+<driver>:// counts as one" || fail "$PG_URL_ERR — nothing taken down"
# shellcheck source=scripts/vm/lib.sh
. "$ROOT/scripts/vm/lib.sh"

if [ ! -d "$WT" ]; then
  # No worktree, no warm.env: reap.sh finds no VMIDs, and vm.py reap takes only
  # expired boxes. A live box of the lane would burn until its ttl; the lane is
  # being taken down, so whatever carries its tag goes.
  vm_py destroy --lane "$SLUG" || fail "vm.py destroy --lane $SLUG failed — VMs of the lane may still run"
  # A directory deleted by hand leaves the worktree registered, and git branch -d
  # then refuses even a merged branch ("used by worktree").
  git -C "$ROOT" worktree prune
fi
# The main checkout's reap.sh against the worktree's own state; for a worktree that
# is gone that state does not exist, and reap.sh still sweeps the lane's expired
# boxes and ends on vm.py list, which fails on a leak.
AH_VM_STATE_DIR="$WT/.vm" bash "$ROOT/scripts/vm/reap.sh" --lane "$SLUG" \
  || fail "reap failed — the worktree stays (VMs of lane $SLUG may still run)"
if [ -d "$WT" ]; then
  git -C "$ROOT" worktree remove "$WT" \
    || fail "worktree not clean — inspect it, then: git worktree remove --force $WT, and run this again"
  echo "  worktree $WT removed"
fi

rc=0
( [ -z "$PG_URL_PASS" ] || export PGPASSWORD="$PG_URL_PASS"
  exec dropdb --if-exists --maintenance-db="$PG_URL_OUT" "$DB" ) || rc=$?
[ "$rc" = 0 ] || fail "dropdb $DB failed (exit $rc) — run this again"
echo "  test database $DB dropped"
rm -rf -- "$HOME/.cache/ah-venv-$SLUG"
echo "  venv ~/.cache/ah-venv-$SLUG removed"

BRANCH="feature/$SLUG"
if git -C "$ROOT" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  if git -C "$ROOT" branch -d "$BRANCH" >/dev/null 2>&1; then
    echo "  branch $BRANCH deleted (merged)"
  else
    echo "  note: branch $BRANCH kept, not merged (git branch -D $BRANCH if you mean it)"
  fi
fi
echo "worktree $SLUG taken down"
