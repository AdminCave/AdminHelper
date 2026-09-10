#!/usr/bin/env bash
#
# crabbox_iter.sh — the fast dev loop. Reuses a warm box (crabbox_warm.sh), re-syncs
# only the changed source (target/ + node_modules/ survive the delete-sync → cargo/
# npm rebuild incrementally), and auto-captures debug artifacts on failure. Minutes,
# not ~40. On failure the box is kept (-keep-on-failure) for `crabbox ssh`.
#
#   bash scripts/tests/crabbox_iter.sh <lint|unit|quick|integration|e2e|all> \
#        [--strict] [--only <keys…>] [--step <name>]
#       run run.sh <layer> on the warm full box, forwarding its flags (AH_ONLY=
#       "server web" is the env form of --only — the per-task fast loop)
#   bash scripts/tests/crabbox_iter.sh --cmd '<command>'
#       sync + run an arbitrary command on the warm full box (a task's Verify:)
#   bash scripts/tests/crabbox_iter.sh --desktop [spec ...]
#       drive the Tauri GUI on the warm desktop box against the warm server box
#
# AH_NO_SYNC=1  -> add -no-sync (re-run the already-synced tree, e.g. a flaky retry).
# AH_DRY_RUN=1  -> LAYER FORM ONLY: print the remote command and exit, WITHOUT
#                  leasing a box (--cmd and --desktop still lease; --desktop needs
#                  the warm pond for the server IP, so a dry run cannot mean much
#                  there). The argument handling is otherwise only observable by
#                  burning a VM.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/tests/crabbox_lib.sh
. "$DIR/crabbox_lib.sh"
cd "$CBX_ROOT" || exit 1
# A dry run never reaches the provider, so it must not demand one either: that is
# what lets the argument handling be tested off this box — in CI, in a fresh
# clone, anywhere without crabbox or the gitignored provider env.
if [ "${AH_DRY_RUN:-0}" != "1" ]; then
  command -v crabbox >/dev/null || { echo "crabbox not installed"; exit 1; }
  cbx_load_env || exit 1
fi

# The box has no .git (the sync carries files, not the repository), so it cannot
# compute the evidence fields of last-<layer>.json itself — without these, every
# box returns an artifact with an empty head and tree_hash. Computed here, over
# the tree that is about to be synced.
#
# Nothing is passed under AH_NO_SYNC: the box then keeps an OLDER tree, and
# labelling it with today's hash would be a run claiming a tree it never saw.
# Empty evidence is honest, wrong evidence is not.
evidence_envs() {
  [ "${AH_NO_SYNC:-0}" = 1 ] && return 0
  local head tree
  head="$(git rev-parse HEAD 2>/dev/null)"
  tree="$(bash "$DIR/../dev/tree-hash.sh" 2>/dev/null)"
  # All-or-nothing on purpose: a garbled value discards the good one too, rather
  # than shipping half an identity that looks complete.
  case "$head$tree" in *[!0-9a-f]*) return 0 ;; esac
  [ -n "$head" ] && printf ' AH_HEAD=%s' "$head"
  [ -n "$tree" ] && printf ' AH_TREE_HASH=%s' "$tree"
  return 0
}

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
elif [ "${1:-}" = "--cmd" ]; then
  shift
  CMD="${*:-}"
  [ -n "$CMD" ] || { echo "usage: crabbox_iter.sh --cmd '<command>'"; exit 2; }
  bash "$DIR/crabbox_warm.sh" desktop >/dev/null || exit 1
  BOX="$(warm_get desktop)"
  [ -n "$BOX" ] || { echo "no warm box (run: crabbox_warm.sh desktop)"; exit 1; }
  echo "== cmd on warm box $BOX: $CMD =="
  # run.sh's python suites install into the box venv (AH_VENV, default /tmp/ah-venv)
  # and only run.sh activates it — bridge it here so a task Verify like
  # 'python3 -m pytest …' sees the same deps. The $-expansion happens ON THE BOX.
  VENVPRE='v="${AH_VENV:-/tmp/ah-venv}"; [ -f "$v/bin/activate" ] && . "$v/bin/activate"; '
  # Same reason as the layer form: a Verify: command that writes an artifact needs
  # the evidence fields too, and the box cannot derive them.
  CMDENVS="$(evidence_envs)"; CMDENVS="${CMDENVS# }"
  [ -n "$CMDENVS" ] && VENVPRE="export $CMDENVS; $VENVPRE"
  if CBX_TIMEOUT=3000 cbx run --id "$BOX" "${CAP[@]}" -- "$VENVPRE$CMD"; then
    echo "  ✓ cmd green"
  else report_fail "$BOX"; exit 1; fi
else
  LAYER="${1:-quick}"
  [ $# -gt 0 ] && shift
  # Forward run.sh's flags (--strict, --only, --step) instead of dropping them:
  # `crabbox_iter.sh quick --strict` used to run the box suite WITHOUT the strict
  # mode and still report green — the failure mode this stage exists to remove.
  # Each argument is shell-quoted because the result is embedded in the remote
  # command string; an unknown flag is rejected rather than forwarded blind.
  FLAGS="" FLAGS_SHOWN=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --strict|--only|--step) ;;
      --*) echo "unsupported flag for the box run: $1 (use --strict, --only, --step)"; exit 2 ;;
    esac
    FLAGS="$FLAGS $(printf '%q' "$1")"; FLAGS_SHOWN="$FLAGS_SHOWN $1"; shift
  done
  # Same rule as AH_ONLY below, for the same reason: reject BEFORE warming, and
  # reject anything that could break out of the remote command string. A forgotten
  # layer (`crabbox_iter.sh --strict`) used to become LAYER="--strict", slip past
  # the flag check above and lease a VM just to fail on the box. Charset, not a
  # layer list: run.sh stays the single authority on which layers exist.
  case "$LAYER" in ''|-*|*[!a-z0-9-]*)
    echo "invalid layer '$LAYER' (lint|unit|quick|integration|e2e|all)"; exit 2 ;;
  esac
  # Validate AH_ONLY BEFORE warming — a rejected value must not lease a box.
  # The value is embedded in the remote command string → reject anything beyond
  # the key charset so a stray quote can't break/inject the box shell; run.sh
  # validates the keys themselves.
  case "${AH_ONLY:-}" in *[!a-z0-9\ -]*)
    echo "invalid AH_ONLY '${AH_ONLY:-}' (lowercase keys, space-separated)"; exit 2 ;;
  esac
  # Forward AH_ONLY so a lane's per-task iteration only runs the touched
  # component's lint/unit steps (run.sh skips the rest).
  ENVS="AH_ALLOW_REAL=1 AH_CAPTURE=1$(evidence_envs)"
  [ -n "${AH_ONLY:-}" ] && ENVS="$ENVS AH_ONLY='$AH_ONLY'"
  if [ "${AH_DRY_RUN:-0}" = "1" ]; then
    echo "$ENVS bash scripts/tests/run.sh $LAYER$FLAGS"; exit 0
  fi
  bash "$DIR/crabbox_warm.sh" desktop >/dev/null || exit 1
  BOX="$(warm_get desktop)"
  [ -n "$BOX" ] || { echo "no warm box (run: crabbox_warm.sh desktop)"; exit 1; }
  echo "== run.sh $LAYER$FLAGS_SHOWN on warm box $BOX${AH_ONLY:+ (AH_ONLY=$AH_ONLY)} =="
  # 'all' = integration + GUI-e2e + unit + lint in one go: ~42 min on a warm box
  # and well past 50 min on a cold one (the Tauri release build alone is ~20).
  # The flat 3000s bound killed it mid-suite, which reads exactly like a test
  # failure (no summary line, box kept) — give the long layer its own headroom.
  case "$LAYER" in all) LAYER_TMO=6000 ;; *) LAYER_TMO=3000 ;; esac
  if CBX_TIMEOUT=$LAYER_TMO cbx run --id "$BOX" "${CAP[@]}" -- \
        "$ENVS bash scripts/tests/run.sh $LAYER$FLAGS"; then
    echo "  ✓ run.sh $LAYER$FLAGS_SHOWN green"
  else report_fail "$BOX"; exit 1; fi
fi
