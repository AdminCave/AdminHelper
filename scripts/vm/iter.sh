#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# iter.sh — the fast dev loop. Reuses a warm box (scripts/vm/warm.sh), re-syncs
# only the changed source (target/ + node_modules/ survive the delete-sync →
# cargo/npm rebuild incrementally), and pulls the box's .ah-out back on every
# run. Minutes, not ~40. On failure the box is kept for `vm.py ssh`.
#
#   bash scripts/vm/iter.sh <lint|unit|quick|integration|e2e|all> \
#        [--strict] [--only <keys…>] [--step <name>]
#       run run.sh <layer> on the warm full box, forwarding its flags (AH_ONLY=
#       "server web" is the env form of --only — the per-task fast loop)
#   bash scripts/vm/iter.sh --cmd '<command>'
#       sync + run an arbitrary command on the warm full box (a task's Verify:)
#   bash scripts/vm/iter.sh --desktop [spec ...]
#       drive the Tauri GUI on the warm desktop box against the warm server box
#
# AH_NO_SYNC=1  -> drop --sync (re-run the already-synced tree, e.g. a flaky retry).
# AH_DRY_RUN=1  -> LAYER FORM ONLY: print the remote command and exit, WITHOUT
#                  cloning a box (--cmd and --desktop still warm; --desktop needs
#                  the warm pond for the server IP, so a dry run cannot mean much
#                  there). The argument handling is otherwise only observable by
#                  burning a VM.
# AH_OUT_DIR    -> where the box's .ah-out is pulled to (default .ah-out).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/vm/lib.sh
. "$DIR/lib.sh"
cd "$VM_ROOT" || exit 1
# A dry run never reaches the hypervisor, so it must not demand a token either:
# that is what lets the argument handling be tested off this box — in CI, in a
# fresh clone, anywhere without the gitignored provider env.
if [ "${AH_DRY_RUN:-0}" != "1" ]; then
  vm_load_env || exit 1
fi

OUT_DIR="${AH_OUT_DIR:-.ah-out}"
# The box's own stdout, kept as a file as well as shown: heavy.sh reads the
# summary line out of it when a wrapper died before printing one, and a human
# watching a 40-minute layer should not have to guess whether it is alive.
BOX_LOG="$OUT_DIR/last.out.log"
# --extend renews with the frist the box was WARMED with (warm.sh records it as
# desktop_ttl), not with this script's own default: a box warmed for 20 minutes
# must not turn into an 8-hour box because someone ran a lint on it (R-0049).
# An explicit AH_WARM_TTL still wins; a warm.env from before the key existed
# keeps the old 8h renewal.
TTL="${AH_WARM_TTL:-$(warm_get desktop_ttl)}"; TTL="${TTL:-8h}"

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

mkdir -p "$OUT_DIR"
SYNC=(--sync); [ "${AH_NO_SYNC:-0}" = 1 ] && SYNC=()

# box_run <vmid> <timeout> <command…> — the one place that calls vm.py run.
# Every run extends the warm box's lease, so a loop that is being worked on does
# not expire under the hands of the person working on it, and pulls .ah-out so
# the screenshots and service logs of a failed journey are local afterwards.
# The remote exit code is this function's, unchanged: a red suite stays 1, and
# vm.py's own 74 (no ssh, capacity, timeout) stays 74 so heavy.sh can sort it
# away as infrastructure instead of reporting a test that never ran.
box_run() {
  local vmid="$1" tmo="$2"; shift 2
  vm_py run "$vmid" "${SYNC[@]}" --timeout "$tmo" --out "$OUT_DIR" --extend "$TTL" \
    -- "$@" 2>&1 | tee "$BOX_LOG"
  return "${PIPESTATUS[0]}"
}

report_fail() {
  echo ""
  echo "  ✗ FAILED — auto-debug captured (no re-run needed):"
  echo "    output : $BOX_LOG   (full, untruncated)"
  echo "    pulled : $OUT_DIR/  (screenshots/*.png + service logs)"
  echo "    inspect: python3 scripts/vm/vm.py ssh $1   (box kept)"
}

if [ "${1:-}" = "--desktop" ]; then
  shift
  # warm.sh pond ensures server (stack up + creds) AND desktop are warm; idempotent.
  bash "$DIR/warm.sh" pond >/dev/null || exit 1
  DT="$(warm_get desktop)"; SRV_IP="$(warm_get server_ip)"
  PW="$(warm_get server_admin_pw)"; KEY="$(warm_get server_monitor_key)"
  [ -n "$DT" ] && [ -n "$SRV_IP" ] || { echo "warm pond not ready (run: warm.sh pond)"; exit 1; }
  echo "== desktop GUI on $DT vs https://$SRV_IP (specs: ${*:-default}) =="
  # ONE quoted string, not separate arguments: `vm.py run` joins its command with
  # spaces (verb_run), so an empty $PW would vanish and $KEY would slide into its
  # place — the box would then be handed a monitor key as the admin password.
  # The old wrapper handed argv to exec and kept empty elements; this is the
  # shape that survives the join. The single quotes hold because the values are
  # an IPv4, a hex password and a urlsafe key — none can contain a quote;
  # multibox.sh builds the same stage the same way and says the same thing.
  if box_run "$DT" 3000 \
       "bash scripts/tests/box_desktopbox.sh '$SRV_IP' '$PW' '$KEY' $*"; then
    echo "  ✓ desktop journeys green"
  else rc=$?; report_fail "$DT"; exit "$rc"; fi
elif [ "${1:-}" = "--cmd" ]; then
  shift
  CMD="${*:-}"
  [ -n "$CMD" ] || { echo "usage: iter.sh --cmd '<command>'"; exit 2; }
  bash "$DIR/warm.sh" desktop >/dev/null || exit 1
  BOX="$(warm_get desktop)"
  [ -n "$BOX" ] || { echo "no warm box (run: warm.sh desktop)"; exit 1; }
  echo "== cmd on warm box $BOX: $CMD =="
  # run.sh's python suites install into the box venv (AH_VENV, default /tmp/ah-venv)
  # and only run.sh activates it — bridge it here so a task Verify like
  # 'python3 -m pytest …' sees the same deps. The $-expansion happens ON THE BOX.
  VENVPRE='v="${AH_VENV:-/tmp/ah-venv}"; [ -f "$v/bin/activate" ] && . "$v/bin/activate"; '
  # Same reason as the layer form: a Verify: command that writes an artifact needs
  # the evidence fields too, and the box cannot derive them.
  CMDENVS="$(evidence_envs)"; CMDENVS="${CMDENVS# }"
  [ -n "$CMDENVS" ] && VENVPRE="export $CMDENVS; $VENVPRE"
  if box_run "$BOX" 3000 "$VENVPRE$CMD"; then
    echo "  ✓ cmd green"
  else rc=$?; report_fail "$BOX"; exit "$rc"; fi
else
  LAYER="${1:-quick}"
  [ $# -gt 0 ] && shift
  # Forward run.sh's flags (--strict, --only, --step) instead of dropping them:
  # `iter.sh quick --strict` used to run the box suite WITHOUT the strict mode
  # and still report green — the failure mode stage 1 exists to remove.
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
  # layer (`iter.sh --strict`) used to become LAYER="--strict", slip past the flag
  # check above and clone a VM just to fail on the box. Charset, not a layer list:
  # run.sh stays the single authority on which layers exist.
  case "$LAYER" in ''|-*|*[!a-z0-9-]*)
    echo "invalid layer '$LAYER' (lint|unit|quick|integration|e2e|all)"; exit 2 ;;
  esac
  # Validate AH_ONLY BEFORE warming — a rejected value must not clone a box.
  # The value is embedded in the remote command string → reject anything beyond
  # the key charset so a stray quote can't break/inject the box shell; run.sh
  # validates the keys themselves.
  case "${AH_ONLY:-}" in *[!a-z0-9\ -]*)
    echo "invalid AH_ONLY '${AH_ONLY:-}' (lowercase keys, space-separated)"; exit 2 ;;
  esac
  # AH_REQUIRED rides along the same way — same charset rule, same reason.
  case "${AH_REQUIRED:-}" in *[!a-z0-9_\ -]*)
    echo "invalid AH_REQUIRED '${AH_REQUIRED:-}' (step ids, space-separated)"; exit 2 ;;
  esac
  # Forward AH_ONLY so a lane's per-task iteration only runs the touched
  # component's lint/unit steps (run.sh skips the rest). Forward AH_REQUIRED so
  # a caller can name the box's required set; when it is unset, run.sh derives
  # the heavy layers' set itself (heavy.sh relies on that and unsets it).
  ENVS="AH_ALLOW_REAL=1 AH_CAPTURE=1$(evidence_envs)"
  [ -n "${AH_ONLY:-}" ] && ENVS="$ENVS AH_ONLY='$AH_ONLY'"
  [ -n "${AH_REQUIRED:-}" ] && ENVS="$ENVS AH_REQUIRED='$AH_REQUIRED'"
  if [ "${AH_DRY_RUN:-0}" = "1" ]; then
    echo "$ENVS bash scripts/tests/run.sh $LAYER$FLAGS"; exit 0
  fi
  bash "$DIR/warm.sh" desktop >/dev/null || exit 1
  BOX="$(warm_get desktop)"
  [ -n "$BOX" ] || { echo "no warm box (run: warm.sh desktop)"; exit 1; }
  echo "== run.sh $LAYER$FLAGS_SHOWN on warm box $BOX${AH_ONLY:+ (AH_ONLY=$AH_ONLY)} =="
  # 'all' = integration + GUI-e2e + unit + lint in one go: ~42 min on a warm box
  # and well past 50 min on a cold one (the Tauri release build alone is ~20).
  # The flat 3000s bound killed it mid-suite, which reads exactly like a test
  # failure (no summary line, box kept) — give the long layer its own headroom.
  case "$LAYER" in all) LAYER_TMO=6000 ;; *) LAYER_TMO=3000 ;; esac
  if box_run "$BOX" "$LAYER_TMO" "$ENVS bash scripts/tests/run.sh $LAYER$FLAGS"; then
    echo "  ✓ run.sh $LAYER$FLAGS_SHOWN green"
  else rc=$?; report_fail "$BOX"; exit "$rc"; fi
fi
