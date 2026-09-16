#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# lib_vm_test.sh — hermetic test for scripts/vm/lib.sh.
#
# lib.sh is the part of the VM harness that can be checked without a hypervisor:
# where the lane comes from, how a warm slot is stored and cleared, and how a
# marker is cut out of a box's output. Everything that needs Proxmox lives in
# vm.py and is covered by scripts/vm/tests. No network, no VM, no token — the
# state directory is a temp dir for the whole run.
#
# Run: bash scripts/tests/lib_vm_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
# Claude Code exports the `env` block of .claude/settings.local.json into every
# shell, so the real Proxmox values are already here — and vm_load_env's whole
# contract is that an existing variable wins. Clearing them is what makes the
# file the thing under test.
unset AH_LANE AH_PVE_URL AH_PVE_NODE AH_PVE_TOKEN AH_PVE_CA AH_PVE_STORAGE \
      AH_PVE_BRIDGE AH_PVE_POOL AH_PVE_VMID_RANGE AH_VM_MAX AH_VM_SSH_KEY \
      AH_VM_LINKED AH_VM_REMOTE_DIR

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# The library writes into AH_VM_STATE_DIR; pointing it at a temp dir keeps the
# developer's own .vm/ (and with it a running lane) out of this test.
export AH_VM_STATE_DIR="$WORK/state"
# shellcheck source=/dev/null
. "$REPO_ROOT/scripts/vm/lib.sh"

echo "── the lane ──"
[ "$(vm_lane)" = "main" ] && ok "no lane file, no AH_LANE -> main" || bad "default lane: $(vm_lane)"

mkdir -p "$AH_VM_STATE_DIR"; echo "worktree-a" > "$AH_VM_STATE_DIR/lane"
[ "$(vm_lane)" = "worktree-a" ] && ok ".vm/lane is read" || bad "lane file: $(vm_lane)"

AH_LANE="from-env" ; export AH_LANE
[ "$(vm_lane)" = "from-env" ] && ok "AH_LANE beats the file" || bad "AH_LANE: $(vm_lane)"

AH_LANE="Pilot Two!"
[ "$(vm_lane)" = "pilot-two" ] && ok "a lane is lowercased and cleaned" || bad "cleaning: $(vm_lane)"

AH_LANE="   "
[ "$(vm_lane)" = "main" ] && ok "an empty lane still means main" || bad "empty lane: $(vm_lane)"
unset AH_LANE

# The lane decides which VMs a sweep may take, so the two implementations have
# to agree on every spelling — a disagreement would let one side reap what the
# other believes is still leased.
if command -v python3 >/dev/null 2>&1; then
  # The doubled separators are the ones that matter: `a-b` and `a--b` must
  # stay two different lanes on both sides, or a sweep takes the wrong VMs.
  for raw in "worktree-a" "Pilot Two!" "" "   " "--x--" "a..b" "vm--core" \
             "lane  two" "a__b" "-lead" "trail-" "---"; do
    AH_LANE="$raw"
    py=$(cd "$REPO_ROOT" && AH_LANE="$raw" AH_VM_STATE_DIR="$AH_VM_STATE_DIR" python3 -c '
import sys; sys.path.insert(0, "scripts/vm")
import vm; print(vm.current_lane())')
    sh=$(vm_lane)
    [ "$sh" = "$py" ] && ok "lane %$raw% agrees with vm.py ($sh)" || bad "lane %$raw%: shell=$sh vm.py=$py"
  done
  unset AH_LANE
else
  # SKIP is not green (CLAUDE.md §6): the cross-check IS this test's reason to
  # exist, and lib.sh needs python3 for vm_load_env anyway.
  echo "SKIP: python3 not available — the vm.py cross-check cannot run"; exit 75
fi

echo "── warm slots ──"
[ -z "$(warm_get desktop)" ] && ok "an unset slot reads empty" || bad "unset slot: $(warm_get desktop)"

warm_set desktop 3001
[ "$(warm_get desktop)" = "3001" ] && ok "a slot round-trips" || bad "round-trip: $(warm_get desktop)"

warm_set server 3002
warm_set desktop 3003
[ "$(warm_get desktop)" = "3003" ] && [ "$(warm_get server)" = "3002" ] \
  && ok "a slot is replaced, its neighbours are not" || bad "replace: $(cat "$(vm_warm_file)")"
[ "$(grep -c '^desktop=' "$(vm_warm_file)")" = "1" ] \
  && ok "no duplicate line is left behind" || bad "duplicates: $(cat "$(vm_warm_file)")"

# The server role parks credentials next to the VMIDs; '=' inside them must
# survive, or a base64 value arrives truncated on the receiving box.
warm_set server_admin_pw 'p=ss=w0rd=='
[ "$(warm_get server_admin_pw)" = 'p=ss=w0rd==' ] \
  && ok "a value with '=' survives" || bad "equals: $(warm_get server_admin_pw)"

warm_clear desktop
[ -z "$(warm_get desktop)" ] && [ "$(warm_get server)" = "3002" ] \
  && ok "clearing takes one slot only" || bad "clear: $(cat "$(vm_warm_file)")"

rm -f "$(vm_warm_file)"
warm_clear desktop && ok "clearing a missing file is not an error" || bad "clear without a file"

echo "── markers ──"
OUT='noise MB_SID=abc123 more noise'
[ "$(vm_marker MB_SID "$OUT")" = "abc123" ] && ok "a marker is cut out" || bad "marker: $(vm_marker MB_SID "$OUT")"

# base64 payloads end in '=' padding; cut -f2 once dropped it and the receiving
# box died with "base64: invalid input".
OUT='MC_CA_B64=aGVsbG8gd29ybGQ= trailing'
[ "$(vm_marker MC_CA_B64 "$OUT")" = "aGVsbG8gd29ybGQ=" ] \
  && ok "base64 padding survives" || bad "padding: $(vm_marker MC_CA_B64 "$OUT")"

OUT=$'MB_SID=first\nMB_SID=second'
[ "$(vm_marker MB_SID "$OUT")" = "second" ] && ok "the last marker wins" || bad "last: $(vm_marker MB_SID "$OUT")"

[ -z "$(vm_marker MB_NOPE "$OUT")" ] && ok "a missing marker reads empty" || bad "missing marker"

echo "── the environment ──"
# A file with no AH_PVE_URL must fail loudly rather than let a caller run
# against whatever happens to be in the environment.
FAKE="$WORK/repo"; mkdir -p "$FAKE/.claude" "$FAKE/scripts/vm"
cp "$REPO_ROOT/scripts/vm/lib.sh" "$FAKE/scripts/vm/lib.sh"
echo '{"env": {"AH_PVE_URL": "https://pve.example:8006", "AH_VM_MAX": "8", "OTHER": "x"}}' \
  > "$FAKE/.claude/settings.local.json"
ENVOUT=$(cd "$FAKE" && bash -c '. scripts/vm/lib.sh; vm_load_env && echo "$AH_PVE_URL|$AH_VM_MAX|${OTHER-<unset>}"')
[ "$ENVOUT" = "https://pve.example:8006|8|<unset>" ] \
  && ok "AH_* are exported, everything else is left alone" || bad "load_env: $ENVOUT"

ENVOUT=$(cd "$FAKE" && AH_VM_MAX=99 bash -c '. scripts/vm/lib.sh; vm_load_env && echo "$AH_VM_MAX"')
[ "$ENVOUT" = "99" ] && ok "the environment wins over the file" || bad "precedence: $ENVOUT"

echo '{"env": {}}' > "$FAKE/.claude/settings.local.json"
(cd "$FAKE" && bash -c '. scripts/vm/lib.sh; vm_load_env' 2>/dev/null) \
  && bad "an empty config was accepted" || ok "an empty config fails loudly"

echo "lib_vm_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
