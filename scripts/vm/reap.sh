#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# reap.sh — drop the warm boxes so they don't linger (cost). Warm boxes carry a
# ttl and vm.py's reaper takes them when it runs out; this is the manual sweep
# for branch-switch / EOD. Destroys the VMs recorded in .vm/warm.env, then lets
# vm.py reap whatever else on THIS LANE has expired, then clears warm.env.
#
#   bash scripts/vm/reap.sh [--lane <lane>] [--all]
#     --lane <lane>  act as that lane (default: .vm/lane, else main)
#     --all          extend the expiry sweep to EVERY lane. A live box on
#                    another lane is not touched even then — its ttl is its
#                    own; take it by id with `vm.py destroy <vmid>`.
#
# Only this lane's warm slots are destroyed outright: another lane's warm.env is
# in another worktree, and guessing at its VMs by tag is how one lane kills the
# box another is iterating on. The slots go to vm.py with the lane, the slot's
# role and --no-scenario, and vm.py refuses a slot whose VM carries another lane
# or role, or any scenario: free_vmid hands a freed VMID to the next clone, and a
# scenario leases its server first.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/vm/lib.sh
. "$DIR/lib.sh"
cd "$VM_ROOT" || exit 1
vm_load_env || exit 1

ALL=0
while [ $# -gt 0 ]; do case "$1" in
  --lane) AH_LANE="${2:?--lane needs a value}"; export AH_LANE; shift ;;
  --all) ALL=1 ;;
  *) echo "unknown arg: $1 (use --lane <lane> | --all)"; exit 2 ;;
esac; shift; done
LANE="$(vm_lane)" || exit 2
# vm.py derives the lane the same way (AH_LANE, then .vm/lane) — export the
# resolved name so both sides agree even when neither was set.
export AH_LANE="$LANE"

echo "== reap warm boxes (lane $LANE) =="
ROLES=() IDS=()
for role in desktop server; do
  v="$(warm_get "$role")"
  [ -n "$v" ] || continue
  # A VMID and nothing else: a value starting with - would reach vm.py's argparse
  # as an option (--role=desktop would select every desktop VM of the lane).
  case "$v" in
    *[!0123456789]*) echo "  slot $role holds no VMID — skipped"; continue ;;
  esac
  echo "  destroy $role $v"; ROLES+=("$role"); IDS+=("$v")
done
# One call per slot: vm.py checks every VM it is named before it destroys the
# first and refuses the whole call for one it will not take. A slot whose VM is
# already gone (the normal case after a ttl expired, not in the listing any more)
# or whose VMID carries another lane, role or a scenario by now must cost only its
# own call, not the live slot next to it.
if [ ${#IDS[@]} -gt 0 ]; then
  for i in "${!IDS[@]}"; do
    vm_py destroy --lane "$LANE" --role "${ROLES[$i]}" --no-scenario "${IDS[$i]}" 2>&1 | sed 's/^/  /' || true  # review: ok the sweep goes on; the closing list exits 74 on a leak
  done
else
  echo "  no warm slots recorded"
fi

echo "== reap expired =="
if [ "$ALL" = 1 ]; then vm_py reap --all | sed 's/^/  /'
else vm_py reap | sed 's/^/  /'; fi

# Clear every key, not just the role slots: the server credentials belong to the
# box that just went away, and a stale one would let iter drive at nothing.
# Read the key list ONCE up front: warm_clear rewrites the very file a loop over
# it would be reading.
for key in $(cut -d= -f1 "$(vm_warm_file)" 2>/dev/null); do warm_clear "$key"; done

# `list` exits 74 when it finds a VM of this lane that nothing claims any more,
# and that exit code is this script's: a sweep that left something behind has not
# done its job, and a leaked VM is a failure, not a footnote.
echo "== remaining VMs (should be empty on this lane) =="
vm_py list 2>&1 | sed 's/^/  /'
