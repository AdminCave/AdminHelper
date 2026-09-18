#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# bake.sh — build a fresh template so cold starts skip the ~18 min toolchain
# bootstrap. A thin front for `vm.py bake`: the work (clone from the base image,
# bootstrap, warm the caches, clean, shut down, convert, tag) is vm.py's, this
# adds the wall clock and the one result line a bake is read by.
#
#   bash scripts/vm/bake.sh <linux-full|linux-server>
#     linux-full    the fat template: toolchains, docker, caches — what the
#                   heavy tiers run on
#     linux-server  server/agent roles: no desktop, no display, no browser
#
# PROVISIONS a VM and runs ~45 min. Run it deliberately — it is not part of the
# fast loop, and CLAUDE.md keeps `bake` off the list of things that happen by
# themselves. The old template is NOT touched: `clone` takes the newest one with
# the profile's tag, and deleting the previous one is Kevin's call (`vm.py
# doctor` lists them).
set -uo pipefail
PROFILE="${1:-}"
case "$PROFILE" in
  linux-full|linux-server) ;;
  *) echo "usage: bake.sh <linux-full|linux-server>"; exit 2 ;;
esac
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/vm/lib.sh
. "$DIR/lib.sh"
cd "$VM_ROOT" || exit 1
vm_load_env || exit 1

mkdir -p "$AH_VM_STATE_DIR"
LOG="$AH_VM_STATE_DIR/bake-$PROFILE.log"

echo "== bake $PROFILE — PROVISIONS a VM, ~45 min =="
START=$SECONDS
vm_py bake --profile "$PROFILE" 2>&1 | tee "$LOG"
rc="${PIPESTATUS[0]}"
SECS=$((SECONDS - START))
if [ "$rc" != 0 ]; then
  echo "bake $PROFILE FAILED after $((SECS / 60))m$((SECS % 60))s (exit $rc)"
  exit "$rc"
fi
# vm.py's last line is "<vmid> <name> <tag>;built-<yyyymmdd>" — repeat it as one
# result line so a bake can be read from the scrollback without the step log.
RESULT="$(tail -1 "$LOG")"
echo ""
echo "baked $PROFILE: $RESULT  ($((SECS / 60))m$((SECS % 60))s)"
echo "  the next clone of $PROFILE takes it; the previous template stays until you drop it"
echo "  templates:  python3 scripts/vm/vm.py doctor"
