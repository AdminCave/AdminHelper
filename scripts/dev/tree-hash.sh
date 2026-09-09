#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# tree-hash.sh — 40 hex chars identifying the CONTENT a test run saw.
#
# Written into the run artifacts (last-<layer>.json, last-verify.json) so a
# "green" can be tied to a tree instead of to a claim. Built in a throwaway
# index, so the real one is untouched and the hash covers untracked files too —
# a new, uncommitted source file changes the result. Ledger edits do not:
# tasks/ and the output dirs are excluded, so ticking a box mid-run does not
# invalidate the evidence of that run.
#
# Run: bash scripts/dev/tree-hash.sh   (prints the hash, or exits non-zero)

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# A 0700 dir, not `mktemp` alone: git refuses a zero-byte file as an index
# ("index file smaller than expected"); the path must simply not exist yet.
tmpd="$(mktemp -d)"
trap 'rm -rf "$tmpd"' EXIT
export GIT_INDEX_FILE="$tmpd/index"

# Add everything, then drop the three excluded trees from the temp index. The
# obvious `:(exclude)…` pathspecs cannot be used: naming a path that .gitignore
# already covers makes `git add` exit 1 ("paths are ignored"), which would turn
# a hash request into a hard error on any box that has .crabbox-out/.
git add -A -- .
git rm -r -q -f --cached --ignore-unmatch -- tasks .ah-out .crabbox-out
git write-tree
