#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# scratch.sh — scratch directories for the worker's build session (stage 7a, R-0108).
#
#   bash scripts/dev/scratch.sh new [<name>]   create one, print its path
#   bash scripts/dev/scratch.sh rm <path>      remove one this script created
#
# Under dontAsk the runner's build session may not run mktemp or rm: they are no
# read-only commands and no allow rule names them. An allow rule that pins an
# argument by its text is fragile — `rm -rf <dir>/../repo` matches `<dir>/*` —
# so the narrow way is this script, whose check is code. The directories live in
# <checkout>/.ah-out/scratch (gitignored), each with a marker file. rm removes only
# a direct child of that directory that carries the marker, judged after realpath:
# no glob, no symlink, no traversal, not the directory itself, nothing elsewhere.
#
# Exit: 0 done · 2 refused or usage

set -uo pipefail

usage() { sed -n '/^#   bash scripts\/dev\/scratch.sh new/,/^# Under dontAsk/p' "$0" | sed '$d; s/^# \{0,1\}//'; }
die() { echo "scratch.sh: $*" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
BASE="$ROOT/.ah-out/scratch"
MARKER=".ah-scratch"

# The base itself must be a real directory of this checkout, never a link out of it.
base() {
  [ ! -L "$ROOT/.ah-out" ] && [ ! -L "$BASE" ] || die "$BASE (or .ah-out) is a symlink — refused"
  mkdir -p "$BASE" || die "cannot create $BASE"
}

case "${1-}" in
  new)
    [ $# -le 2 ] || die "new takes at most a name"
    NAME="${2:-scratch}"
    [[ "$NAME" =~ ^[A-Za-z0-9._][A-Za-z0-9._-]{0,39}$ ]] && [ "$NAME" != . ] && [ "$NAME" != .. ] \
      || die "a name is 1-40 of A-Z a-z 0-9 . _ - and does not start with -, got '$NAME'"
    base
    D="$(mktemp -d -p "$BASE" "$NAME.XXXXXX")" || die "mktemp failed in $BASE"
    printf 'made by scripts/dev/scratch.sh\n' > "$D/$MARKER" || die "cannot write the marker in $D"
    printf '%s\n' "$D"
    ;;
  rm)
    [ $# -eq 2 ] && [ -n "$2" ] || die "rm takes exactly one path"
    P="$2"
    case "$P" in *[\*\?\[]*) die "no glob: $P" ;; esac
    # A link is refused as it is spelled — lexically normalized, so link//, link/.
    # name the link too — before anything follows it.
    LEX="$(realpath -m -s -- "$P")" || die "cannot read the path $P"
    [ ! -L "$LEX" ] || die "a symlink is no scratch directory: $P"
    [ -d "$P" ] || die "no such directory: $P"
    base
    REAL="$(realpath -e -- "$P")" || die "cannot resolve $P"
    RBASE="$(realpath -e -- "$BASE")" || die "cannot resolve $BASE"
    [ "$REAL" != "$RBASE" ] || die "the scratch directory itself is not removed: $P"
    [ "$(dirname -- "$REAL")" = "$RBASE" ] || die "not a direct child of $BASE: $P"
    [ -f "$REAL/$MARKER" ] && [ ! -L "$REAL/$MARKER" ] || die "no marker of scratch.sh in $P — not one of its directories"
    rm -rf -- "$REAL" || die "could not remove $REAL"
    ;;
  -h|--help) usage ;;
  *) usage >&2; die "needs new or rm" ;;
esac
