#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# check-versions.sh — assert every HAND-MAINTAINED version site carries <X.Y.Z>.
#
#   bash scripts/release/check-versions.sh <X.Y.Z> [--root <dir>]
#
# The agent, the server and the images derive their version from the tag; these
# six sites do not, and a forgotten one is invisible until a user hits it. The
# doc sidebar footers hung three releases long, and release.yml only ever checked
# tauri.conf.json. The list mirrors .claude/rules/release.md — keep both in sync.
#
#   1  apps/desktop/src-tauri/tauri.conf.json   "version"   (the release gate)
#   2  apps/desktop/src-tauri/Cargo.toml        [package] version
#   3  apps/desktop/src-tauri/Cargo.lock        package "adminhelper"
#   4  CHANGELOG.md                             section "## [X.Y.Z]"
#   5  docs/**/*.html                           sidebar footers <span>vX.Y.Z</span>
#   6  docs/index.html + docs/en/index.html     the "what's new" callouts
#
# Prints one `ok`/`MISSING` line per site and exits 1 if any site is off, so the
# output is the checklist rather than a single yes/no.
#
# --root <dir> points the whole check at another tree; the hermetic test
# (scripts/tests/check_versions_test.sh) uses it with a fixture.
#
# The version is compared VERBATIM: a prerelease tag (v0.46.0-beta.1) therefore
# demands that string at all six sites. The old inline step could never pass a
# prerelease at all (it stripped the suffix from the file but not from the tag),
# so this loosens nothing — but whether a beta should bump 38 doc footers is an
# open decision, tracked as T6a in tasks/harness-stufe-3.md.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --root) shift; [ $# -gt 0 ] || { echo "--root needs a directory"; exit 2; }; ROOT="$1" ;;
    --*) echo "unknown flag: $1 (use --root <dir>)"; exit 2 ;;
    *) [ -z "$VER" ] || { echo "unexpected argument: $1 (version is already '$VER')"; exit 2; }
       VER="$1" ;;
  esac
  shift
done
[ -n "$VER" ] || { echo "usage: check-versions.sh <X.Y.Z> [--root <dir>]"; exit 2; }
# Tags are written vX.Y.Z and the sites carry X.Y.Z; accept either spelling
# rather than answering a leading v with six MISSING lines.
VER="${VER#v}"
[ -d "$ROOT" ] || { echo "no such root: $ROOT"; exit 2; }

# The floor exists so a page that LOSES its footer is a finding, not a silently
# smaller "all footers agree". Raise it when docs/ grows a new sidebar.
MIN_FOOTERS=38

# $VER goes into grep/sed patterns, where '.' matches any character — without
# this, "0.45.0" would accept "0X45X0".
VER_RE="$(printf '%s' "$VER" | sed 's/[.[\*^$]/\\&/g')"

OK=0; MISSING=0
ok()      { printf '  ok       %-34s %s\n' "$1" "$2"; OK=$((OK + 1)); }
missing() { printf '  MISSING  %-34s %s\n' "$1" "$2"; MISSING=$((MISSING + 1)); }

TAURI="$ROOT/apps/desktop/src-tauri/tauri.conf.json"
CARGO="$ROOT/apps/desktop/src-tauri/Cargo.toml"
LOCK="$ROOT/apps/desktop/src-tauri/Cargo.lock"
CHANGELOG="$ROOT/CHANGELOG.md"
DOCS="$ROOT/docs"

echo "check-versions: target $VER (root $ROOT)"

# 1 — tauri.conf.json. Same extraction as the inline step it replaces.
if [ ! -f "$TAURI" ]; then missing "tauri.conf.json" "file not found"
else
  v="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$TAURI" | head -1)"
  [ "$v" = "$VER" ] && ok "tauri.conf.json" "$v" || missing "tauri.conf.json" "version is '${v:-none}'"
fi

# 2 — Cargo.toml, the [package] version only (dependencies carry versions too).
if [ ! -f "$CARGO" ]; then missing "Cargo.toml" "file not found"
else
  v="$(awk '/^\[package\]/{p=1;next} /^\[/{p=0} p && /^version[[:space:]]*=/{sub(/^version[[:space:]]*=[[:space:]]*"/,""); sub(/".*$/,""); print; exit}' "$CARGO")"
  [ "$v" = "$VER" ] && ok "Cargo.toml" "$v" || missing "Cargo.toml" "[package] version is '${v:-none}'"
fi

# 3 — Cargo.lock. Stale here means `cargo build --locked` fails in CI, after the
# tag is already pushed.
if [ ! -f "$LOCK" ]; then missing "Cargo.lock" "file not found"
else
  v="$(awk '/^name = "adminhelper"$/{f=1;next} f && /^version[[:space:]]*=/{sub(/^version[[:space:]]*=[[:space:]]*"/,""); sub(/".*$/,""); print; exit}' "$LOCK")"
  [ "$v" = "$VER" ] && ok "Cargo.lock" "$v" || missing "Cargo.lock" "package adminhelper is '${v:-none}'"
fi

# 4 — CHANGELOG section. Keep a Changelog: "## [X.Y.Z] - YYYY-MM-DD".
if [ ! -f "$CHANGELOG" ]; then missing "CHANGELOG.md" "file not found"
elif grep -q "^## \[$VER_RE\]" "$CHANGELOG"; then ok "CHANGELOG.md" "section ## [$VER]"
else missing "CHANGELOG.md" "no section '## [$VER]'"
fi

# 5 — the sidebar footers, DE + EN. Reported by file: "one of them is old" is
# only actionable with the name.
#
# Matched on the CLASS, not on the one-line markup: the two landing pages write
# the footer across two lines, so a pattern anchored on `<div …><span>v` skipped
# exactly them — and they were the ones that hung three releases (0.43.2 through
# 0.45.0), which is the defect this check exists for.
if [ ! -d "$DOCS" ]; then missing "docs sidebar footers" "no docs/ under root"
else
  found=0; stale_n=0; stale=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    found=$((found + 1))
    v="$(sed -n '/class="sidebar-footer"/,/<\/div>/ s|.*<span>v\([0-9][^<]*\)</span>.*|\1|p' "$f" | head -1)"
    [ "$v" = "$VER" ] && continue
    stale_n=$((stale_n + 1))
    # A forgotten bump leaves all 36 stale; the full list would bury the other
    # five checks. Name enough to start the sed one-liner, count the rest.
    [ "$stale_n" -le 5 ] && stale="$stale ${f#"$ROOT/"}(v${v:-?})"
  done < <(grep -rl 'class="sidebar-footer"' "$DOCS" --include='*.html' 2>/dev/null | sort)
  if [ "$stale_n" -gt 0 ]; then
    [ "$stale_n" -gt 5 ] && stale="$stale … and $((stale_n - 5)) more"
    missing "docs sidebar footers" "$stale_n of $found stale:$stale"
  elif [ "$found" -lt "$MIN_FOOTERS" ]; then
    missing "docs sidebar footers" "only $found of >= $MIN_FOOTERS files carry a footer"
  else ok "docs sidebar footers" "$found files at v$VER"
  fi
fi

# 6 — the two "what's new" callouts on the landing pages.
news_de="$DOCS/index.html"; news_en="$DOCS/en/index.html"
bad=""
grep -q "Was ist neu in $VER_RE" "$news_de" 2>/dev/null || bad="$bad docs/index.html"
grep -q "What's new in $VER_RE" "$news_en" 2>/dev/null || bad="$bad docs/en/index.html"
[ -z "$bad" ] && ok "news callouts (DE+EN)" "both name $VER" \
  || missing "news callouts (DE+EN)" "not naming $VER:$bad"

echo "  check-versions: $OK ok, $MISSING missing (target $VER)"
[ "$MISSING" -eq 0 ]
