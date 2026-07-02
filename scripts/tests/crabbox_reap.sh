#!/usr/bin/env bash
#
# crabbox_reap.sh — stop warm crabbox boxes so they don't linger (cost). Warm boxes
# self-reap via -idle-timeout/-ttl; this is the manual sweep for branch-switch / EOD.
# Stops the boxes recorded in .crabbox/warm.env + everything in the ah-warm pond,
# then clears warm.env. --all also sweeps leases OUTSIDE the pond (catch strays,
# e.g. boxes a read-only workflow agent leaked).
#
#   bash scripts/tests/crabbox_reap.sh [--pond <name>] [--all]
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/tests/crabbox_lib.sh
. "$DIR/crabbox_lib.sh"
cd "$CBX_ROOT" || exit 1
command -v crabbox >/dev/null || { echo "crabbox not installed"; exit 1; }
cbx_load_env || exit 1

POND="ah-warm"; ALL=0
while [ $# -gt 0 ]; do case "$1" in
  --pond) POND="${2:?}"; shift ;; --all) ALL=1 ;;
  *) echo "unknown arg: $1 (use --pond <name> | --all)"; exit 2 ;;
esac; shift; done

echo "== reap warm boxes =="
for role in desktop server; do
  s="$(warm_get "$role")"; [ -n "$s" ] || continue
  echo "  stop $role $s"; cbx stop --id "$s" >/dev/null 2>&1 || true
done
if [ "$ALL" = 1 ]; then
  echo "  --all: sweeping ALL leases"; LIST="$(cbx list 2>/dev/null)"
else
  LIST="$(cbx list --pond "$POND" 2>/dev/null)"
fi
printf '%s\n' "$LIST" | grep -oE 'lease=cbx_[a-z0-9]+' | cut -d= -f2 | sort -u | while read -r id; do
  [ -n "$id" ] && { cbx stop --id "$id" >/dev/null 2>&1 || true; echo "  stopped $id"; }
done
: > "$(cbx_warm_file)" 2>/dev/null || true

echo "== remaining leases (should be empty) =="
cbx list 2>/dev/null | sed 's/^/  /'; echo "  <<empty = clean>>"
