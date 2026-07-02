#!/usr/bin/env bash
#
# crabbox_iter.sh — the fast dev loop. Reuses a warm box (crabbox_warm.sh), re-syncs
# only the changed source (target/ + node_modules/ survive the delete-sync → cargo/
# npm rebuild incrementally), and auto-captures debug artifacts on failure. Minutes,
# not ~40. On failure the box is kept (-keep-on-failure) for `crabbox ssh`.
#
#   bash scripts/tests/crabbox_iter.sh <lint|unit|quick|integration|e2e|all>
#       run run.sh <layer> on the warm full box
#   bash scripts/tests/crabbox_iter.sh --desktop [spec ...]
#       drive the Tauri GUI on the warm desktop box against the warm server box
#
# AH_NO_SYNC=1 -> add -no-sync (re-run the already-synced tree, e.g. a flaky retry).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/tests/crabbox_lib.sh
. "$DIR/crabbox_lib.sh"
cd "$CBX_ROOT" || exit 1
command -v crabbox >/dev/null || { echo "crabbox not installed"; exit 1; }
cbx_load_env || exit 1

mkdir -p .crabbox-out .crabbox/out
NOSYNC=(); [ "${AH_NO_SYNC:-0}" = 1 ] && NOSYNC=(-no-sync)
# Auto-debug flags: keep the box on failure, write full local logs, pull the on-box
# .crabbox-out (screenshots + service logs). -no-hydrate skips Actions re-hydration.
CAP=(-keep-on-failure -no-hydrate "${NOSYNC[@]}"
     -capture-stdout .crabbox/out/last.out.log
     -capture-stderr .crabbox/out/last.err.log
     -artifact-glob ".crabbox-out/**")

report_fail() {
  echo ""
  echo "  ✗ FAILED — auto-debug captured (no re-run needed):"
  echo "    stderr : .crabbox/out/last.err.log   (full, untruncated)"
  echo "    pulled : .crabbox-out/  (screenshots/*.png + service logs)"
  echo "    bundle : newest .crabbox/captures/*.tar.gz"
  echo "    inspect: crabbox ssh --id $1   (box kept via -keep-on-failure)"
}

if [ "${1:-}" = "--desktop" ]; then
  shift
  # crabbox_warm.sh pond ensures server (stack up + creds) AND desktop are warm; idempotent.
  bash "$DIR/crabbox_warm.sh" pond >/dev/null || exit 1
  DT="$(warm_get desktop)"; SRV_IP="$(warm_get server_ip)"
  PW="$(warm_get server_admin_pw)"; KEY="$(warm_get server_monitor_key)"
  [ -n "$DT" ] && [ -n "$SRV_IP" ] || { echo "warm pond not ready (run: crabbox_warm.sh pond)"; exit 1; }
  echo "== desktop GUI on $DT vs https://$SRV_IP (specs: ${*:-default}) =="
  if CBX_TIMEOUT=3000 cbx run --id "$DT" "${CAP[@]}" -- \
        bash scripts/tests/crabbox_desktopbox.sh "$SRV_IP" "$PW" "$KEY" "$@"; then
    echo "  ✓ desktop journeys green"
  else report_fail "$DT"; exit 1; fi
else
  LAYER="${1:-quick}"
  bash "$DIR/crabbox_warm.sh" desktop >/dev/null || exit 1
  BOX="$(warm_get desktop)"
  [ -n "$BOX" ] || { echo "no warm box (run: crabbox_warm.sh desktop)"; exit 1; }
  echo "== run.sh $LAYER on warm box $BOX =="
  if CBX_TIMEOUT=3000 cbx run --id "$BOX" "${CAP[@]}" -- \
        "AH_ALLOW_REAL=1 AH_CAPTURE=1 bash scripts/tests/run.sh $LAYER"; then
    echo "  ✓ run.sh $LAYER green"
  else report_fail "$BOX"; exit 1; fi
fi
