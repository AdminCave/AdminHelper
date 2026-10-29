#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# overlap.sh — which open feature branches change these files?
#
#   bash scripts/dev/overlap.sh [--base <ref>] [--except <branch>] <path>...
#
# Two sessions build in parallel (CLAUDE.md §2). Before one plans a train it
# asks which of its files an open branch of the other already changes: those
# rows wait for the next train, or the other branch takes them along. A path
# ending in / stands for everything under it.
#
# Open = a local or origin feature/* branch that is not merged into the base
# (default origin/main); its files are `git diff --name-only <base>...<branch>`.
# The caller fetches; this script never does.
#
# Exit: 0 no overlap · 1 overlap (one line per branch: `<branch>: <files>`) · 2 usage

set -uo pipefail

usage() { sed -n '/^#   bash scripts\/dev\/overlap.sh/p' "$0" | sed 's/^# \{0,1\}//'; }
BASE=origin/main EXCEPT=""
PATHS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --base)    shift; BASE="${1-}" ;;
    --except)  shift; EXCEPT="${1-}" ;;
    -h|--help) usage; exit 0 ;;
    --*)       echo "overlap: unknown flag: $1" >&2; exit 2 ;;
    *)         PATHS+=("$1") ;;
  esac
  shift
done
[ "${#PATHS[@]}" -gt 0 ] || { usage >&2; exit 2; }
git rev-parse -q --verify "$BASE^{commit}" >/dev/null || { echo "overlap: no base $BASE" >&2; exit 2; }

hits=0
declare -A seen=()
while read -r ref; do
  name="${ref#refs/heads/}"; name="${name#refs/remotes/origin/}"
  [ "$name" = "$EXCEPT" ] && continue
  git merge-base --is-ancestor "$ref" "$BASE" && continue   # merged: nothing open
  mapfile -t changed < <(git diff --name-only "$BASE...$ref")
  found=()
  for f in "${changed[@]}"; do
    for p in "${PATHS[@]}"; do
      if [ "$f" = "$p" ] || { [ "${p%/}" != "$p" ] && [ "${f#"$p"}" != "$f" ]; }; then
        found+=("$f"); break
      fi
    done
  done
  [ "${#found[@]}" -gt 0 ] || continue
  # A branch both local and on origin is reported once, under its name.
  [ -n "${seen[$name]:-}" ] && continue
  seen[$name]=1
  echo "$name: ${found[*]}"
  hits=1
done < <(git for-each-ref --format='%(refname)' refs/heads/feature refs/remotes/origin/feature)
exit "$hits"
