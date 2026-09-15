#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# sync_check_test.sh — hermetic test for `sync-from-web.sh --check`.
#
# Fixture checkouts under a temp dir: the script derives its repo root from
# BASH_SOURCE, so a copy of it next to a fixture apps/web + apps/desktop/ui is
# all it takes. No node, no network — bash, awk and coreutils.
#
# What is worth testing here is not "does it run" but the two ways this guard can
# go quietly weaker: a shared symbol disappearing from one side, and the block
# parser reading too little on BOTH sides (which compares equal and passes).
#
# Run: bash scripts/tests/sync_check_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SCRIPT="$HERE/../../apps/desktop/ui/scripts/sync-from-web.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

[ -f "$SCRIPT" ] || { echo "sync-from-web.sh not found — skipping (75)"; exit 75; }

WORK=$(mktemp -d) || { echo "cannot create a temp dir" >&2; exit 2; }
trap 'rm -rf "$WORK"' EXIT

# fixture <dir> <web-types-body> <desktop-types-body>
# The shared set the script pins is FrpConfig/FrpStatus/FrpStatusProxy/Server, so
# every fixture has to carry those four unless the case is about one going away.
fixture() {
  local d="$1"
  mkdir -p "$d/apps/web/src/lib/api" "$d/apps/desktop/ui/scripts" "$d/apps/desktop/ui/src/lib/api"
  cp "$SCRIPT" "$d/apps/desktop/ui/scripts/sync-from-web.sh"
  printf '%s\n' "$2" > "$d/apps/web/src/lib/api/types.ts"
  printf '%s\n' "$3" > "$d/apps/desktop/ui/src/lib/api/types.ts"
}

WEB_BASE='export interface FrpConfig {
  id: string;
  name: string;
}

export interface FrpStatus {
  online: boolean;
}

export interface FrpStatusProxy {
  name: string;
}

export interface Server {
  id: string;
  hostname: string;
}

export interface WebOnly {
  x: number;
}'

DESKTOP_BASE='export interface FrpConfig {
  id: string;
  name: string;
}

export interface FrpStatus {
  online: boolean;
}

export interface FrpStatusProxy {
  name: string;
}

export interface Server {
  id: string;
  hostname: string;
  connections?: Connection[];
}

export interface DesktopOnly {
  y: number;
}'

# run_case <name> <expect-rc> <expect-substring> <dir>
run_case() {
  local name="$1" want_rc="$2" want="$3" dir="$4"
  local out rc=0
  out=$(bash "$dir/apps/desktop/ui/scripts/sync-from-web.sh" --check 2>&1) || rc=$?
  if [ "$rc" != "$want_rc" ]; then
    bad "$name: rc=$rc (expected $want_rc)"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  if [ -n "$want" ] && ! printf '%s' "$out" | grep -qF -- "$want"; then
    bad "$name: output does not mention '$want'"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  ok "$name"
}

# ── the real shape: desktop carries more, and that is correct ────────────────
D="$WORK/ok"; fixture "$D" "$WEB_BASE" "$DESKTOP_BASE"
run_case "desktop superset -> exit 0" 0 "keine Abweichung" "$D"

# ── the web gains a field the desktop lacks ─────────────────────────────────
D="$WORK/added"; fixture "$D" "${WEB_BASE/  hostname: string;/  hostname: string;
  region: string;}" "$DESKTOP_BASE"
run_case "web-only new field -> exit 1" 1 "region: string;" "$D"

# ── a rename on the web side ────────────────────────────────────────────────
D="$WORK/renamed"; fixture "$D" "${WEB_BASE/  hostname: string;/  host_name: string;}" "$DESKTOP_BASE"
run_case "field renamed on the web side -> exit 1" 1 "host_name" "$D"

# ── a shared symbol disappears from the desktop ─────────────────────────────
# The realistic failure: ONE refactor, not all four at once. A mere count floor
# would still read three of four as "no drift".
D="$WORK/gone"; fixture "$D" "$WEB_BASE" "${DESKTOP_BASE/export interface Server {/export interface ServerRow {}"
run_case "one shared symbol renamed away -> exit 1" 1 "erwartete gemeinsame Symbole fehlen" "$D"

# ── a type alias with an object body must be read whole ─────────────────────
# Read to the first ';' the block would stop after its first field — on BOTH
# sides, so the halves compare equal and the drift below passes unseen.
OBJ_WEB="$WEB_BASE
export type Limits = {
  soft: number;
  hard: number;
};"
OBJ_DESKTOP="$DESKTOP_BASE
export type Limits = {
  soft: number;
  hard: string;
};"
D="$WORK/objalias"; fixture "$D" "$OBJ_WEB" "$OBJ_DESKTOP"
run_case "object-bodied type alias is read whole -> exit 1" 1 "hard: number;" "$D"

# ── a missing target file names itself, once ────────────────────────────────
D="$WORK/nodst"; fixture "$D" "$WEB_BASE" "$DESKTOP_BASE"
rm -f "$D/apps/desktop/ui/src/lib/api/types.ts"
run_case "missing target file -> exit 1" 1 "Ziel-Datei fehlt" "$D"

# ── an unknown flag is refused ──────────────────────────────────────────────
D="$WORK/flag"; fixture "$D" "$WEB_BASE" "$DESKTOP_BASE"
out=$(bash "$D/apps/desktop/ui/scripts/sync-from-web.sh" --nope 2>&1); rc=$?
if [ "$rc" = 2 ]; then ok "unknown flag -> exit 2"; else bad "unknown flag -> exit $rc (want 2)"; fi

echo "sync_check_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
