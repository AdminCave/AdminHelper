#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# vm_wrappers_test.sh — hermetic test for scripts/vm/warm.sh and scripts/vm/reap.sh.
#
# Both are thin: they decide WHEN to call vm.py and WITH WHICH arguments, and
# they parse what comes back. That decision is the whole risk — a warm.sh that
# clones instead of reusing burns ten minutes and a VM per iteration, and a
# reap.sh that names the wrong VMIDs destroys a box somebody is working on. So
# vm.py is replaced by a recorder here: no Proxmox, no network, no VM, and the
# assertions are over the argument list the wrappers produced.
#
# Run: bash scripts/tests/vm_wrappers_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
# Claude Code exports the `env` block of .claude/settings.local.json into every
# shell, so the real Proxmox values are already here. AH_PVE_URL is set below to
# a value that goes nowhere — vm_load_env returns early on it, and the recorder
# never opens a socket either way.
unset AH_LANE AH_WARM_TTL

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
WARM="$REPO_ROOT/scripts/vm/warm.sh"
REAP="$REPO_ROOT/scripts/vm/reap.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# The wrappers write into AH_VM_STATE_DIR; a temp dir keeps the developer's own
# .vm/ — and with it a running lane — out of this test.
export AH_VM_STATE_DIR="$WORK/state"
export AH_PVE_URL="https://vm-wrappers-test.invalid"
export FAKE_LOG="$WORK/calls.log"
export FAKE_LANE="$WORK/lane.seen"

# The recorder. It answers each verb with the shape vm.py really prints (`clone`
# a "<vmid> <name>" line, `wait` the address, `list --json` the listing), and
# every answer is scriptable from the test through FAKE_*.
export AH_VM_PY="$WORK/vm.py"
cat > "$AH_VM_PY" <<'FAKE'
#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >> "$FAKE_LOG"
printf '%s\n' "${AH_LANE-<unset>}" > "$FAKE_LANE"
case "${1:-}" in
  clone) echo "${FAKE_NEWID:-3001} ah-fake-main-0001" ;;
  wait)  echo "${FAKE_IP:-10.0.0.9}" ;;
  run)   [ -n "${FAKE_RUN_OUT:-}" ] && printf '%s\n' "$FAKE_RUN_OUT"
         exit "${FAKE_RUN_RC:-0}" ;;
  list)  if [ "${2:-}" = "--json" ]; then printf '%s\n' "${FAKE_LIST_JSON:-{\"vms\": []\}}"
         else echo "0 ours, 0 not ours"; fi ;;
  destroy) shift; echo "destroyed $*" ;;
  reap)  echo "nothing expired" ;;
esac
exit 0
FAKE
chmod +x "$AH_VM_PY"

reset_state() {  # a fresh warm.env + an empty call log for every case
  rm -rf "$AH_VM_STATE_DIR"; mkdir -p "$AH_VM_STATE_DIR"
  : > "$FAKE_LOG"
  unset FAKE_NEWID FAKE_IP FAKE_RUN_OUT FAKE_RUN_RC FAKE_LIST_JSON
}
slot() { grep -E "^$1=" "$AH_VM_STATE_DIR/warm.env" 2>/dev/null | tail -1 | cut -d= -f2-; }
running_json() { printf '{"vms": [{"vmid": %s, "status": "running"}], "untagged": 0}' "$1"; }

echo "── warm.sh: reuse ──"
reset_state
echo "desktop=3001" > "$AH_VM_STATE_DIR/warm.env"
# The prefix goes INSIDE the substitution: `FOO=1 OUT=$(...)` is an assignment
# list, so FOO would be set in this shell and never reach the child.
OUT=$(FAKE_LIST_JSON="$(running_json 3001)" bash "$WARM" desktop 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "reuse desktop box 3001" <<<"$OUT" \
  && ok "a running recorded box is reused" || bad "reuse: rc=$rc out=$OUT"
grep -q '^clone' "$FAKE_LOG" && bad "reuse still cloned: $(cat "$FAKE_LOG")" \
  || ok "reuse clones nothing"
grep -q '^run' "$FAKE_LOG" && bad "reuse still bootstrapped" || ok "reuse bootstraps nothing"

echo "── warm.sh: the one-time clone ──"
reset_state
OUT=$(bash "$WARM" desktop 2>&1); rc=$?
[ $rc -eq 0 ] || bad "first warm failed: rc=$rc out=$OUT"
grep -q '^clone --profile linux-full --role desktop --ttl 8h$' "$FAKE_LOG" \
  && ok "clone asks for the full profile, the desktop role and the default ttl" \
  || bad "clone args: $(grep '^clone' "$FAKE_LOG")"
grep -q '^wait 3001$' "$FAKE_LOG" && ok "the clone is waited for by VMID" \
  || bad "wait args: $(grep '^wait' "$FAKE_LOG")"
grep -q "^run 3001 --sync --timeout 2700 -- AH_BOOTSTRAP_PROFILE=full bash scripts/vm/bootstrap_linux.sh$" "$FAKE_LOG" \
  && ok "the bootstrap runs on the synced checkout, bounded" \
  || bad "bootstrap args: $(grep '^run' "$FAKE_LOG")"
[ "$(slot desktop)" = "3001" ] && ok "the VMID lands in warm.env" || bad "slot: $(slot desktop)"

echo "── warm.sh: the ttl comes from AH_WARM_TTL ──"
reset_state
AH_WARM_TTL=20m bash "$WARM" desktop >/dev/null 2>&1
grep -q -- '--ttl 20m$' "$FAKE_LOG" && ok "AH_WARM_TTL reaches the clone" \
  || bad "ttl: $(grep '^clone' "$FAKE_LOG")"

echo "── warm.sh: a recorded box that is gone ──"
reset_state
echo "desktop=3999" > "$AH_VM_STATE_DIR/warm.env"
OUT=$(bash "$WARM" desktop 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "recorded desktop VM 3999 is gone" <<<"$OUT" \
  && ok "a vanished slot is re-warmed, not trusted" || bad "stale slot: rc=$rc out=$OUT"
[ "$(slot desktop)" = "3001" ] && ok "the slot now holds the new VMID" || bad "slot: $(slot desktop)"

echo "── warm.sh: a box that is listed but stopped ──"
reset_state
echo "desktop=3001" > "$AH_VM_STATE_DIR/warm.env"
FAKE_LIST_JSON='{"vms": [{"vmid": 3001, "status": "stopped"}]}' bash "$WARM" desktop >/dev/null 2>&1
grep -q '^clone' "$FAKE_LOG" && ok "a stopped box is not mistaken for a warm one" \
  || bad "stopped box reused: $(cat "$FAKE_LOG")"

echo "── warm.sh: a failed bootstrap claims no slot ──"
reset_state
OUT=$(FAKE_RUN_RC=1 bash "$WARM" desktop 2>&1); rc=$?
[ $rc -eq 1 ] && ok "a failed bootstrap fails the wrapper" || bad "bootstrap rc: $rc"
[ -z "$(slot desktop)" ] && ok "a half-hydrated box does not become the warm slot" \
  || bad "slot after failure: $(slot desktop)"
grep -q "vm.py ssh 3001" <<<"$OUT" && ok "the kept box is named with the way in" \
  || bad "no inspect hint: $OUT"

echo "── warm.sh: the server role ──"
reset_state
MARKERS="MB_SID=sid-7 MB_PTOK=ptok-7 MB_ADMIN_PW=pw-7 MB_MONITOR_KEY=key7=="
OUT=$(FAKE_NEWID=3002 FAKE_IP=10.0.0.42 FAKE_RUN_OUT="$MARKERS" bash "$WARM" server 2>&1); rc=$?
[ $rc -eq 0 ] || bad "server warm failed: rc=$rc out=$OUT"
grep -q '^clone --profile linux-server --role server --ttl 8h$' "$FAKE_LOG" \
  && ok "the server box comes off the server profile" || bad "server clone: $(grep '^clone' "$FAKE_LOG")"
grep -q "^run 3002 --sync --timeout 2700 -- bash scripts/tests/box_serverbox.sh 10.0.0.42$" "$FAKE_LOG" \
  && ok "the role script gets the box's own address" || bad "serverbox args: $(grep '^run' "$FAKE_LOG")"
[ "$(slot server)" = "3002" ] && [ "$(slot server_ip)" = "10.0.0.42" ] \
  && ok "VMID and address are stashed" || bad "server slots: $(slot server) / $(slot server_ip)"
[ "$(slot server_sid)" = "sid-7" ] && [ "$(slot server_ptok)" = "ptok-7" ] \
  && [ "$(slot server_admin_pw)" = "pw-7" ] \
  && ok "the session, token and password markers are cut out" \
  || bad "markers: sid=$(slot server_sid) ptok=$(slot server_ptok) pw=$(slot server_admin_pw)"
# The padding is the point: a monitor key is base64 and ends in '=', and a marker
# parser that cuts at the first '=' hands the box a key it cannot decode.
[ "$(slot server_monitor_key)" = "key7==" ] && ok "a base64 marker keeps its padding" \
  || bad "monitor key: $(slot server_monitor_key)"
# The creds are in the file but must not be printed — the terminal scrolls into
# a paste buffer, warm.env is gitignored.
grep -q "pw-7" <<<"$OUT" && bad "the admin password was printed" || ok "no credential on stdout"

echo "── warm.sh: a stack that never came up ──"
reset_state
OUT=$(FAKE_RUN_OUT="docker: no such image" bash "$WARM" server 2>&1); rc=$?
[ $rc -eq 1 ] && [ -z "$(slot server)" ] \
  && ok "no markers means no server slot" || bad "missing markers: rc=$rc slot=$(slot server)"

echo "── warm.sh: pond is server then desktop ──"
reset_state
FAKE_RUN_OUT="MB_SID=s MB_PTOK=p MB_ADMIN_PW=w MB_MONITOR_KEY=k" bash "$WARM" pond >/dev/null 2>&1
[ "$(grep -c '^clone' "$FAKE_LOG")" = "2" ] \
  && [ "$(grep '^clone' "$FAKE_LOG" | head -1 | grep -c linux-server)" = "1" ] \
  && ok "pond warms the server first, then the desktop" || bad "pond: $(grep '^clone' "$FAKE_LOG")"

echo "── warm.sh: an unknown role ──"
reset_state
OUT=$(bash "$WARM" bogus 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q "usage: warm.sh" <<<"$OUT" \
  && ok "an unknown role is a usage error, not a clone" || bad "usage: rc=$rc out=$OUT"
[ -s "$FAKE_LOG" ] && bad "an unknown role still called vm.py" || ok "an unknown role calls nothing"

echo "── reap.sh ──"
reset_state
printf 'desktop=3001\nserver=3002\nserver_ip=10.0.0.42\nserver_ptok=p\n' > "$AH_VM_STATE_DIR/warm.env"
OUT=$(bash "$REAP" 2>&1); rc=$?
[ $rc -eq 0 ] || bad "reap failed: rc=$rc out=$OUT"
grep -q '^destroy 3001 3002$' "$FAKE_LOG" \
  && ok "both warm slots are destroyed in ONE call" || bad "destroy args: $(grep '^destroy' "$FAKE_LOG")"
grep -q '^reap$' "$FAKE_LOG" && ok "the expiry sweep follows" || bad "no plain reap: $(cat "$FAKE_LOG")"
[ -z "$(slot server_ip)" ] && [ -z "$(slot desktop)" ] \
  && ok "warm.env is emptied, credentials included" || bad "warm.env left: $(cat "$AH_VM_STATE_DIR/warm.env")"
[ "$(tail -1 "$FAKE_LOG")" = "list" ] \
  && ok "the sweep ends by listing what is left" || bad "last call: $(tail -1 "$FAKE_LOG")"

echo "── reap.sh --all ──"
reset_state
bash "$REAP" --all >/dev/null 2>&1
grep -q '^reap --all$' "$FAKE_LOG" && ok "--all widens the expiry sweep" \
  || bad "--all: $(grep '^reap' "$FAKE_LOG")"

echo "── reap.sh --lane ──"
reset_state
OUT=$(bash "$REAP" --lane pilot-two 2>&1)
grep -q "lane pilot-two" <<<"$OUT" && ok "--lane names the lane it acts on" || bad "lane header: $OUT"
# vm.py derives the lane from AH_LANE — the wrapper has to hand it over, or the
# sweep runs against `main` while the header claims another lane.
[ "$(cat "$FAKE_LANE")" = "pilot-two" ] && ok "the lane reaches vm.py as AH_LANE" \
  || bad "AH_LANE seen by vm.py: $(cat "$FAKE_LANE")"

reset_state
OUT=$(bash "$REAP" --bogus 2>&1); rc=$?
[ $rc -eq 2 ] && ok "an unknown flag is rejected" || bad "unknown flag: rc=$rc out=$OUT"

# ══ iter.sh renews with the box's own frist (R-0049) ══════════════════════════
# A box warmed for 20 minutes must not become an 8-hour box because a lint ran
# on it. warm.sh records the frist as desktop_ttl; iter.sh renews with that,
# AH_WARM_TTL still wins, and a warm.env from before the key keeps 8h.
ITER="$REPO_ROOT/scripts/vm/iter.sh"
RUNNING='{"vms": [{"vmid": 3001, "status": "running"}]}'
echo "── iter.sh: --extend uses the frist the box was warmed with ──"
reset_state
AH_WARM_TTL=20m bash "$WARM" desktop >/dev/null 2>&1
[ "$(slot desktop_ttl)" = "20m" ] && ok "warm.sh records the frist as desktop_ttl" || bad "desktop_ttl: $(slot desktop_ttl)"
: > "$FAKE_LOG"
FAKE_LIST_JSON="$RUNNING" AH_OUT_DIR="$WORK/out" bash "$ITER" lint >/dev/null 2>&1 || true
grep -q -- '--extend 20m ' "$FAKE_LOG" && ok "iter.sh renews with the recorded 20m, not its default" \
  || bad "extend args: $(grep '^run' "$FAKE_LOG")"
: > "$FAKE_LOG"
FAKE_LIST_JSON="$RUNNING" AH_OUT_DIR="$WORK/out" AH_WARM_TTL=8h bash "$ITER" lint >/dev/null 2>&1 || true
grep -q -- '--extend 8h ' "$FAKE_LOG" && ok "an explicit AH_WARM_TTL still wins" \
  || bad "extend args: $(grep '^run' "$FAKE_LOG")"
reset_state
echo "desktop=3001" > "$AH_VM_STATE_DIR/warm.env"
FAKE_LIST_JSON="$RUNNING" AH_OUT_DIR="$WORK/out" bash "$ITER" lint >/dev/null 2>&1 || true
grep -q -- '--extend 8h ' "$FAKE_LOG" && ok "a warm.env without desktop_ttl keeps the 8h renewal" \
  || bad "extend args: $(grep '^run' "$FAKE_LOG")"

echo ""
echo "vm_wrappers_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
