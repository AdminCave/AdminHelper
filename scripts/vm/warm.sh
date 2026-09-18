#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# warm.sh — clone and hydrate a VM ONCE and remember its VMID, so the fast loop
# (scripts/vm/iter.sh) reuses it instead of re-cloning + re-bootstrapping +
# rebuilding on every run. Idempotent: if the recorded VM is still running,
# reuse it; if it was reaped, transparently re-warm.
#
#   bash scripts/vm/warm.sh <desktop|server|pond>
#     desktop  full bootstrap profile (Tauri + xvfb) — GUI fast loop (no server)
#     server   server profile — brings the docker stack UP and leaves it up,
#              stashing the server IP + admin/monitor creds for iter
#     pond     server (stack up) + desktop — the distributed desktop fast loop
#
# Warm boxes carry `--ttl ${AH_WARM_TTL:-8h}` and the lane's tag (see vm_lane in
# lib.sh), so parallel worktree-lanes never sweep each other's boxes; iter.sh
# extends the lease on every run and vm.py's reaper takes what expired. Sweep by
# hand with scripts/vm/reap.sh. State is in .vm/warm.env (gitignored).
set -uo pipefail
ROLE="${1:-}"
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/vm/lib.sh
. "$DIR/lib.sh"
cd "$VM_ROOT" || exit 1
vm_load_env || exit 1
LANE="$(vm_lane)"
TTL="${AH_WARM_TTL:-8h}"
# The bound the old wrapper carried, unchanged: a full bootstrap measured 10–20
# min on the fat template, and an unbounded ssh would sit there for a night if
# the guest hangs.
HYDRATE_TIMEOUT=2700

# box_running <vmid> -> 0 while vm.py still lists that VM as running.
# The exit code of `list` is ignored on purpose: it is 74 when the listing finds
# a leaked VM, and the JSON we care about is on stdout long before that.
box_running() {
  vm_py list --json 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(1)
want = sys.argv[1]
sys.exit(0 if any(str(v.get("vmid")) == want and v.get("status") == "running"
                  for v in data.get("vms", [])) else 1)' "$1"
}

kept() {  # kept <vmid> <what failed> — a box we leave standing, and how to get at it
  echo "  $2 on $1 — box kept for inspection:" >&2
  echo "    inspect: python3 scripts/vm/vm.py ssh $1" >&2
  echo "    drop it: python3 scripts/vm/vm.py destroy $1" >&2
}

# clone_box <role> <profile> -> stdout: "<vmid> <ip>"; stderr: progress
clone_box() {
  local role="$1" profile="$2" vmid ip
  vmid="$(vm_py clone --profile "$profile" --role "$role" --ttl "$TTL" | awk 'NR==1{print $1}')" \
    || { echo "  clone failed" >&2; return 1; }
  [ -n "$vmid" ] || { echo "  clone printed no VMID" >&2; return 1; }
  # `wait` prints the address on its last line; anything before it is progress.
  ip="$(vm_py wait "$vmid" | tail -1)" || { kept "$vmid" "never came up"; return 1; }
  echo "$vmid $ip"
}

# warm_role <role> <profile> <bootstrap-profile> -> stdout: vmid ; stderr: progress
warm_role() {
  local role="$1" profile="$2" boot="$3" vmid ip
  vmid="$(warm_get "$role")"
  if [ -n "$vmid" ] && box_running "$vmid"; then
    echo "  reuse $role box $vmid (already warm)" >&2; echo "$vmid"; return 0
  fi
  [ -n "$vmid" ] && { echo "  recorded $role VM $vmid is gone — re-warming" >&2; warm_clear "$role"; }
  echo "  clone + hydrate $role box (profile=$profile) — one-time bootstrap" >&2
  read -r vmid ip < <(clone_box "$role" "$profile") || return 1
  echo "  $role box $vmid @ ${ip:-?} — hydrating" >&2
  # The slot is claimed only by a box that finished its bootstrap. A half-baked
  # one stays for inspection and shows up as a leak in `vm.py list` — which is
  # the truth: it is a VM nothing is using, and the reaper takes it at the ttl.
  vm_py run "$vmid" --sync --timeout "$HYDRATE_TIMEOUT" -- \
    "AH_BOOTSTRAP_PROFILE=$boot bash scripts/vm/bootstrap_linux.sh" >&2 \
    || { kept "$vmid" "bootstrap failed"; return 1; }
  # The frist the box was warmed with, so iter.sh can renew with THAT instead of
  # its own default (R-0049).
  warm_set "$role" "$vmid"; warm_set "${role}_ttl" "$TTL"; echo "$vmid"
}

# warm_server: warm a server box AND bring the stack up (leaving it up), stashing
# the IP + provision token + admin/monitor creds so iter can drive against it.
# box_serverbox.sh does its OWN bootstrap (server profile) + stack up, so clone
# and run it directly — do NOT warm_role first (that would bootstrap twice).
warm_server() {
  local vmid ip out sid ptok pw key
  vmid="$(warm_get server)"
  if [ -n "$vmid" ] && box_running "$vmid" && [ -n "$(warm_get server_ip)" ]; then
    echo "  reuse server box $vmid (stack up @ $(warm_get server_ip))" >&2; return 0
  fi
  [ -n "$vmid" ] && { echo "  recorded server VM $vmid is gone — re-warming" >&2; warm_clear server; }
  echo "  clone server box + hydrate + bring up the stack (one-time)" >&2
  read -r vmid ip < <(clone_box server linux-server) || return 1
  echo "  server box $vmid @ ${ip:-?} — box_serverbox.sh (bootstrap + stack up)" >&2
  out="$(vm_py run "$vmid" --sync --timeout "$HYDRATE_TIMEOUT" -- \
         bash scripts/tests/box_serverbox.sh "$ip" 2>&1)"
  sid="$(vm_marker MB_SID "$out")"
  ptok="$(vm_marker MB_PTOK "$out")"
  pw="$(vm_marker MB_ADMIN_PW "$out")"
  key="$(vm_marker MB_MONITOR_KEY "$out")"
  [ -n "$sid" ] && [ -n "$ptok" ] || {
    echo "  server stack bring-up failed:" >&2; printf '%s\n' "$out" | tail -20 >&2
    kept "$vmid" "stack bring-up failed"; return 1; }
  warm_set server "$vmid"; warm_set server_ip "$ip"; warm_set server_admin_pw "$pw"
  warm_set server_monitor_key "$key"; warm_set server_sid "$sid"; warm_set server_ptok "$ptok"
  echo "  server stack up @ $ip (sid=$sid)" >&2
}

case "$ROLE" in
  desktop) warm_role desktop linux-full full >/dev/null || exit 1 ;;
  server)  warm_server || exit 1 ;;
  pond)    warm_server || exit 1; warm_role desktop linux-full full >/dev/null || exit 1 ;;
  *) echo "usage: warm.sh <desktop|server|pond>"; exit 2 ;;
esac

echo ""
echo "── warm boxes ready (.vm/warm.env · lane $LANE) ──"
grep -vE '_admin_pw=|_monitor_key=|_ptok=' "$(vm_warm_file)" 2>/dev/null | sed 's/^/  /'
echo "  (server creds stashed in warm.env — gitignored, not printed)"
echo "  iterate:  bash scripts/vm/iter.sh [--desktop] <quick|integration|e2e>"
echo "  reap:     bash scripts/vm/reap.sh"
