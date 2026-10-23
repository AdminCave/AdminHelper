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

echo "── the lane is not read from tracked state ──"
# A checkout of its own, lib.sh and reap.sh copied in, its .vm/lane naming lane-a.
# git stops at WORK: a repository around the temp dir cannot answer for it.
CO="$WORK/checkout"
mkdir -p "$CO/scripts/vm" "$CO/.vm"
cp "$REPO_ROOT/scripts/vm/lib.sh" "$REPO_ROOT/scripts/vm/reap.sh" "$CO/scripts/vm/"
echo "lane-a" > "$CO/.vm/lane"
printf 'desktop=3001\n' > "$CO/.vm/warm.env"; cp "$CO/.vm/warm.env" "$WORK/co-warm.mark"
export GIT_CEILING_DIRECTORIES="$WORK"
# The fixtures are repositories of their own: an inherited GIT_DIR would make every
# git -C below act on somebody else's index.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
# shellcheck source=/dev/null
co_lane() { (unset AH_LANE; export AH_VM_STATE_DIR="$CO/.vm"; . "$CO/scripts/vm/lib.sh"; vm_lane) 2>&1; }
out=$(co_lane); rc=$?
[ "$rc" = 2 ] && grep -q 'tracks paths under .vm' <<<"$out" && ! grep -q 'lane-a' <<<"$out" \
  && ok "a checkout git cannot read: vm_lane refuses with exit 2 and names no value" || bad "no git: rc=$rc out=$out"
git -C "$CO" init -q
out=$(co_lane); rc=$?
[ "$rc" = 0 ] && [ "$out" = "lane-a" ] && ok "an untracked .vm/lane is read as before" || bad "untracked: rc=$rc out=$out"
git -C "$CO" add -f .vm/lane
out=$(co_lane); rc=$?
[ "$rc" = 2 ] && grep -q 'tracks paths under .vm' <<<"$out" && ! grep -q 'lane-a' <<<"$out" \
  && ok "a tracked .vm/lane: vm_lane refuses with exit 2 and names no value" || bad "tracked: rc=$rc out=$out"
# An inherited GIT_DIR and an empty GIT_INDEX_FILE of somebody else's repository
# must not let git answer for this checkout.
git init -q "$WORK/foreign"
# shellcheck source=/dev/null
out=$( (unset AH_LANE; export AH_VM_STATE_DIR="$CO/.vm" GIT_DIR="$WORK/foreign/.git" GIT_INDEX_FILE="$WORK/empty.index"
        . "$CO/scripts/vm/lib.sh"; vm_lane) 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q 'tracks paths under .vm' <<<"$out" \
  && ok "with a foreign GIT_DIR and an empty index exported, the tracked .vm/lane is still refused" \
  || bad "foreign GIT_DIR: rc=$rc out=$out"
# shellcheck source=/dev/null
out=$( (export AH_LANE=from-env AH_VM_STATE_DIR="$CO/.vm"; . "$CO/scripts/vm/lib.sh"; vm_lane) 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q 'tracks paths under .vm' <<<"$out" && ! grep -q 'lane-a' <<<"$out" \
  && ok "with AH_LANE set, tracked state is refused too" || bad "AH_LANE: rc=$rc out=$out"
# reap.sh stops before it calls vm.py or touches warm.env.
: > "$WORK/co-vm.log"
printf '#!/bin/sh\necho "$*" >> "%s"\n' "$WORK/co-vm.log" > "$WORK/co-vm.py"; chmod +x "$WORK/co-vm.py"
out=$( (unset AH_LANE; export AH_VM_STATE_DIR="$CO/.vm" AH_VM_PY="$WORK/co-vm.py" AH_PVE_URL="https://lib-vm-test.invalid"
        bash "$CO/scripts/vm/reap.sh") 2>&1); rc=$?
[ "$rc" = 2 ] && [ ! -s "$WORK/co-vm.log" ] && cmp -s "$CO/.vm/warm.env" "$WORK/co-warm.mark" \
  && ok "reap.sh in that checkout: exit 2, no call to vm.py, warm.env as it was" \
  || bad "reap.sh: rc=$rc vm=[$(cat "$WORK/co-vm.log")] out=$out"
# .vm itself tracked, as a link to a directory with state and no lane file:
# reap.sh, warm.sh and iter.sh stop before they call vm.py, with a lane given or not.
CL="$WORK/checkout-link"
mkdir -p "$CL/scripts/vm" "$WORK/elsewhere"
cp "$REPO_ROOT/scripts/vm/lib.sh" "$REPO_ROOT/scripts/vm/reap.sh" "$REPO_ROOT/scripts/vm/warm.sh" \
   "$REPO_ROOT/scripts/vm/iter.sh" "$CL/scripts/vm/"
printf 'desktop=3001\n' > "$WORK/elsewhere/warm.env"; cp "$WORK/elsewhere/warm.env" "$WORK/cl-warm.mark"
ln -s "$WORK/elsewhere" "$CL/.vm"
git -C "$CL" init -q && git -C "$CL" add .vm
for spec in "|reap.sh" "|warm.sh desktop" "|iter.sh quick" \
            "|reap.sh --lane pilot" "pilot|warm.sh desktop" "pilot|iter.sh quick"; do
  lane="${spec%%|*}" spec="${spec#*|}"
  : > "$WORK/co-vm.log"
  # shellcheck disable=SC2086
  out=$( (unset AH_LANE AH_VM_STATE_DIR; [ -z "$lane" ] || export AH_LANE="$lane"
          export AH_VM_PY="$WORK/co-vm.py" AH_PVE_URL="https://lib-vm-test.invalid"
          bash "$CL/scripts/vm/"$spec) 2>&1); rc=$?
  [ "$rc" = 2 ] && [ ! -s "$WORK/co-vm.log" ] && cmp -s "$WORK/elsewhere/warm.env" "$WORK/cl-warm.mark" \
    && grep -q 'tracks paths under .vm' <<<"$out" \
    && ok "$spec${lane:+ (AH_LANE=$lane)} with .vm tracked as a link: exit 2, no call to vm.py" \
    || bad "$spec${lane:+ (AH_LANE=$lane)} (tracked .vm link): rc=$rc vm=[$(cat "$WORK/co-vm.log")] out=$out"
done
# The checkout's own .vm untracked, no lane file: main, as before.
CU="$WORK/checkout-plain"
mkdir -p "$CU/scripts/vm" "$CU/.vm"; cp "$REPO_ROOT/scripts/vm/lib.sh" "$CU/scripts/vm/"; git -C "$CU" init -q
# shellcheck source=/dev/null
out=$( (unset AH_LANE AH_VM_STATE_DIR; . "$CU/scripts/vm/lib.sh"; vm_lane) 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$out" = "main" ] && ok "an own untracked .vm without a lane file is main" || bad "own plain: rc=$rc out=$out"
# A worktree that `git worktree add` made, its own .vm and no lane: refused, and
# vm.py refuses alike. AH_LANE=main or a lane file let it run; the main checkout
# stays on main.
CM="$WORK/checkout-main"; CW="$WORK/checkout-wt"
mkdir -p "$CM/scripts/vm"
cp "$REPO_ROOT/scripts/vm/lib.sh" "$REPO_ROOT/scripts/vm/vm.py" "$REPO_ROOT/scripts/vm/profiles.json" "$CM/scripts/vm/"
git -C "$CM" init -q && git -C "$CM" add scripts \
  && git -C "$CM" -c user.email=t@example.com -c user.name=t -c commit.gpgsign=false commit -qm fixture
git -C "$CM" worktree add -q --detach "$CW"
mkdir -p "$CM/.vm" "$CW/.vm"
# shellcheck source=/dev/null
out=$( (unset AH_LANE AH_VM_STATE_DIR; . "$CW/scripts/vm/lib.sh"; vm_lane) 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q 'this worktree has no .vm/lane — set AH_LANE=<lane>' <<<"$out" \
  && ok "a linked worktree without a lane: vm_lane refuses with exit 2" || bad "linked, no lane: rc=$rc out=$out"
out=$( (cd "$CW" && unset AH_LANE AH_VM_STATE_DIR && python3 -c '
import sys
sys.path.insert(0, "scripts/vm")
import vm
try:
    print(vm.current_lane())
except vm.Usage as exc:
    print("refused:", exc)
') 2>&1)
grep -q '^refused: this worktree has no .vm/lane' <<<"$out" \
  && ok "... and vm.py refuses the same worktree" || bad "vm.py, linked, no lane: $out"
# shellcheck source=/dev/null
out=$( (unset AH_VM_STATE_DIR; export AH_LANE=main; . "$CW/scripts/vm/lib.sh"; vm_lane) 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$out" = "main" ] && ok "with AH_LANE=main the linked worktree runs on main" || bad "linked, AH_LANE=main: rc=$rc out=$out"
echo "lane-c" > "$CW/.vm/lane"
# shellcheck source=/dev/null
out=$( (unset AH_LANE AH_VM_STATE_DIR; . "$CW/scripts/vm/lib.sh"; vm_lane) 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$out" = "lane-c" ] && ok "with a lane file the linked worktree runs on it" || bad "linked, lane file: rc=$rc out=$out"
# shellcheck source=/dev/null
out=$( (unset AH_LANE AH_VM_STATE_DIR; . "$CM/scripts/vm/lib.sh"; vm_lane) 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$out" = "main" ] && ok "the main checkout without a lane stays on main" || bad "main checkout: rc=$rc out=$out"
# The rule is about the checkout's own .vm: with its state elsewhere, the linked
# worktree without a lane is main as before.
rm -f "$CW/.vm/lane"; mkdir -p "$WORK/linked-elsewhere"
# shellcheck source=/dev/null
out=$( (unset AH_LANE; export AH_VM_STATE_DIR="$WORK/linked-elsewhere"; . "$CW/scripts/vm/lib.sh"; vm_lane) 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$out" = "main" ] && ok "a linked worktree with its state elsewhere and no lane is main" \
  || bad "linked, state elsewhere: rc=$rc out=$out"
# A tree git cannot read, its state in a directory of its own (a box synced from a
# worktree): the lane is read and git is not asked.
CB="$WORK/checkout-box"
mkdir -p "$CB/scripts/vm" "$WORK/box-state"; cp "$REPO_ROOT/scripts/vm/lib.sh" "$CB/scripts/vm/"
echo "gitdir: /nonexistent/worktrees/x" > "$CB/.git"; echo "lane-b" > "$WORK/box-state/lane"
# shellcheck source=/dev/null
out=$( (unset AH_LANE; export AH_VM_STATE_DIR="$WORK/box-state"; . "$CB/scripts/vm/lib.sh"; vm_lane) 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$out" = "lane-b" ] && ok "a state dir elsewhere is read without asking git" || bad "box: rc=$rc out=$out"
unset GIT_CEILING_DIRECTORIES

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

echo "── warm.env is written under a lock ──"
# The two parts of a heavy run write warm.env from two wrappers at once.
WF="$(vm_warm_file)"
if command -v flock >/dev/null 2>&1; then
  # A holder that keeps warm.env.lock for 2 s: the subshell BECOMES sleep, so the
  # lock goes when it ends.
  ( exec 9>"$WF.lock"; flock 9; exec sleep 2 ) & holder=$!
  for _ in $(seq 1 50); do flock -n "$WF.lock" true 2>/dev/null || break; sleep 0.1; done
  t0=$(date +%s%N); warm_set held 3010; rc=$?; t1=$(date +%s%N)
  wait "$holder" 2>/dev/null
  ms=$(( (t1 - t0) / 1000000 ))
  [ "$rc" = 0 ] && [ "$ms" -ge 1000 ] && [ "$(warm_get held)" = 3010 ] \
    && ok "warm_set waits for a held lock (${ms} ms), then writes" \
    || bad "held lock: rc=$rc after ${ms} ms, held=$(warm_get held)"

  pids=()
  for i in $(seq 1 20); do warm_set "par$i" "$((4000 + i))" & pids+=("$!"); done
  failed=0; for p in "${pids[@]}"; do wait "$p" || failed=$((failed + 1)); done
  missing=""
  for i in $(seq 1 20); do [ "$(warm_get "par$i")" = "$((4000 + i))" ] || missing="$missing par$i"; done
  [ "$failed" = 0 ] && [ -z "$missing" ] && ok "20 parallel warm_set of different keys: all 20 stand in warm.env" \
    || bad "parallel warm_set: $failed failed, missing:$missing — $(cat "$WF")"
  left="$(compgen -G "$WF.tmp*" || true)"
  [ -z "$left" ] && ok "... and no warm.env.tmp* is left behind" || bad "temp files left: $left"

  for i in $(seq 1 10); do warm_set "gone$i" "$((5000 + i))"; done
  pids=()
  for i in $(seq 1 10); do warm_clear "gone$i" & pids+=("$!"); warm_set "stay$i" "$((6000 + i))" & pids+=("$!"); done
  wait "${pids[@]}"
  wrong=""
  for i in $(seq 1 10); do
    [ "$(warm_get "stay$i")" = "$((6000 + i))" ] || wrong="$wrong stay$i-missing"
    [ -z "$(warm_get "gone$i")" ] || wrong="$wrong gone$i-left"
  done
  [ -z "$wrong" ] && ok "warm_clear next to a parallel warm_set of another key leaves that key standing" \
    || bad "clear next to set:$wrong — $(cat "$WF")"

  # A lock that never comes free: a flock that gives up at once stands in for the
  # 30 s, and records how it was asked.
  BUSY="$WORK/flock-busy"; mkdir -p "$BUSY"
  printf '#!/bin/sh\necho "$*" >> "%s"\nexit 1\n' "$WORK/flock-busy.args" > "$BUSY/flock"; chmod +x "$BUSY/flock"
  cp "$WF" "$WORK/warm-before-busy"
  out=$( (PATH="$BUSY:$PATH"; warm_set busy 3030; echo "set=$?"; warm_clear par1; echo "clear=$?") 2>&1 )
  [ "$(sort -u "$WORK/flock-busy.args")" = "-w 30 9" ] && grep -q '^set=1$' <<<"$out" && grep -q '^clear=1$' <<<"$out" \
    && grep -q 'still held after 30s — busy not written' <<<"$out" && grep -q 'still held after 30s — par1 not written' <<<"$out" \
    && cmp -s "$WF" "$WORK/warm-before-busy" && [ -z "$(compgen -G "$WF.tmp*" || true)" ] \
    && ok "a lock not free within 30 s: warm_set and warm_clear return 1, say so on stderr, write nothing" \
    || bad "busy lock: args=$(cat "$WORK/flock-busy.args" 2>/dev/null) out=$out"

  # Without flock (a PATH with only what the rewrite needs): written as before, and
  # said once, not once per key.
  NOFL="$WORK/no-flock"; mkdir -p "$NOFL"
  for t in dirname mkdir touch grep mv tail cut; do ln -s "$(command -v "$t")" "$NOFL/$t"; done
  out=$( (PATH="$NOFL"; warm_set nolock1 3040; warm_set nolock2 3041; warm_clear par1
          echo "got=$(warm_get nolock1),$(warm_get nolock2),$(warm_get par1)") 2>&1 )
  [ "$(grep -c 'flock not installed' <<<"$out")" = 1 ] && grep -q '^got=3040,3041,$' <<<"$out" \
    && ok "without flock warm_set and warm_clear write unlocked as before and say so once" || bad "no flock: $out"
else
  bad "flock not installed — the lock cases cannot run"
fi

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
cp "$REPO_ROOT/scripts/vm/vm.py" "$FAKE/scripts/vm/vm.py"
# vm_load_env reads ~/.config/adminhelper/pve.env too (R-0229): HOME points at a
# fixture, or these cases would read the developer's real file.
export HOME="$WORK/home"; PVE="$HOME/.config/adminhelper/pve.env"
mkdir -p "$HOME/.config/adminhelper"; chmod 700 "$HOME/.config/adminhelper"
echo '{"env": {"AH_PVE_URL": "https://pve.example:8006", "AH_VM_MAX": "8", "OTHER": "x"}}' \
  > "$FAKE/.claude/settings.local.json"
ENVOUT=$(cd "$FAKE" && bash -c '. scripts/vm/lib.sh; vm_load_env && echo "$AH_PVE_URL|$AH_VM_MAX|${OTHER-<unset>}"')
[ "$ENVOUT" = "https://pve.example:8006|8|<unset>" ] \
  && ok "AH_* are exported, everything else is left alone" || bad "load_env: $ENVOUT"

ENVOUT=$(cd "$FAKE" && AH_VM_MAX=99 bash -c '. scripts/vm/lib.sh; vm_load_env && echo "$AH_VM_MAX"')
[ "$ENVOUT" = "99" ] && ok "the environment wins over the file" || bad "precedence: $ENVOUT"

# A value carrying a quote must arrive verbatim: with Python's %r the shell
# would have expanded what is inside it.
printf '%s\n' '{"env": {"AH_PVE_URL": "https://pve.example:8006", "AH_VM_REMOTE_DIR": "/srv/it'"'"'s $HOME `id`"}}' \
  > "$FAKE/.claude/settings.local.json"
ENVOUT=$(cd "$FAKE" && bash -c '. scripts/vm/lib.sh; vm_load_env && printf "%s" "$AH_VM_REMOTE_DIR"')
[ "$ENVOUT" = '/srv/it'"'"'s $HOME `id`' ] \
  && ok "a value with a quote is not expanded by the shell" || bad "quoting: $ENVOUT"

echo '{"env": {}}' > "$FAKE/.claude/settings.local.json"
(cd "$FAKE" && bash -c '. scripts/vm/lib.sh; vm_load_env' 2>/dev/null) \
  && bad "an empty config was accepted" || ok "an empty config fails loudly"

# pve.env, with placeholders only: the same source and precedence as vm.py.
echo '{"env": {"AH_PVE_URL": "https://from-settings:8006", "AH_PVE_NODE": "settings-node"}}' \
  > "$FAKE/.claude/settings.local.json"
printf 'AH_PVE_URL=https://from-pve-env:8006\nAH_PVE_TOKEN=placeholder-token\nAH_VM_MAX=3\n' > "$PVE"
chmod 600 "$PVE"
ENVOUT=$(cd "$FAKE" && bash -c '. scripts/vm/lib.sh; vm_load_env && echo "$AH_PVE_URL|$AH_PVE_NODE|$AH_PVE_TOKEN"')
[ "$ENVOUT" = "https://from-pve-env:8006|settings-node|placeholder-token" ] \
  && ok "pve.env is read and wins over settings.local.json, which stays the fallback" || bad "pve.env: $ENVOUT"
ENVOUT=$(cd "$FAKE" && AH_VM_MAX=99 bash -c '. scripts/vm/lib.sh; vm_load_env && echo "$AH_VM_MAX"')
[ "$ENVOUT" = "99" ] && ok "the environment wins over pve.env" || bad "pve.env precedence: $ENVOUT"
# A token file others can read is a finding, not a fallback: settings.local.json
# would have the URL, and still nothing is exported.
chmod 644 "$PVE"
ERR=$(cd "$FAKE" && bash -c '. scripts/vm/lib.sh; vm_load_env && echo "loaded:$AH_PVE_URL"' 2>&1); rc=$?
[ "$rc" -ne 0 ] && grep -q 'chmod 600' <<<"$ERR" && ! grep -q 'loaded:' <<<"$ERR" && ! grep -q 'placeholder-token' <<<"$ERR" \
  && ok "a pve.env others can read stops the load with the fix, nothing exported" || bad "loose pve.env: rc=$rc $ERR"
rm -f -- "$PVE"

echo "lib_vm_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
