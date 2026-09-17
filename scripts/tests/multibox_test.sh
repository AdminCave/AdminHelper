#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# multibox_test.sh — hermetic test for scripts/tests/multibox.sh.
#
# multibox orchestrates up to seven VMs for an hour. Everything that can go
# wrong cheaply is in the orchestration itself: the order the boxes are asked
# for, whether the capacity check really runs BEFORE the first clone, whether a
# failure halfway through still tears the scenario down, and whether the summary
# line heavy.sh copies verbatim still has the shape heavy.sh greps for. vm.py is
# replaced by a recorder here — no Proxmox, no network, no VM, seconds instead
# of an hour.
#
# Run: bash scripts/tests/multibox_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
unset AH_LANE AH_STRICT AH_DESKTOP_VM AH_DESKTOP_ID

HERE=$(cd "$(dirname "$0")" && pwd)
MB="$HERE/multibox.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export AH_VM_STATE_DIR="$WORK/state"
export AH_OUT_DIR="$WORK/out"
export AH_PVE_URL="https://multibox-test.invalid"
export FAKE_LOG="$WORK/calls.log"
export FAKE_SEQ="$WORK/vmid.n"

# The recorder. Answers each verb in vm.py's real shape and hands every role
# script the markers multibox greps for, so a green run is green for the same
# reason the real one is.
export AH_VM_PY="$WORK/vm.py"
cat > "$AH_VM_PY" <<'FAKE'
#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >> "$FAKE_LOG"
args="$*"
case "${1:-}" in
  doctor) exit "${FAKE_DOCTOR_RC:-0}" ;;
  clone)
    n=$(cat "$FAKE_SEQ" 2>/dev/null || echo 3000); n=$((n + 1)); echo "$n" > "$FAKE_SEQ"
    echo "$n ah-fake-main-000$n" ;;
  wait) echo "10.0.0.$(( ${2:-3000} - 3000 ))" ;;
  run)
    case "$args" in
      *box_serverbox.sh*)
        [ "${FAKE_SERVER_RC:-0}" = 0 ] || exit "$FAKE_SERVER_RC"
        echo "MB_SID=s1 MB_PTOK=p1 MB_ADMIN_PW=pw1 MB_MONITOR_KEY=k1"
        echo "MB_REPO_GPG_FP=fp1 MB_CA_FP=ca1 MB_DEB_OLDDPKG_OK=1 MB_FRPS_UP=1" ;;
      *box_agentbox.sh*)
        echo "AGENT_PROVISION_OK AGENT_CERT_OK AGENT_REPO_OK AGENT_CAFLIP_OK" ;;
      *box_moncheckbox.sh*start*) echo "MC_MAILHOG_UP=1 MC_CA_B64=Y2E=" ;;
      *box_moncheckbox.sh*assert*) echo "MC_MAIL_COUNT=1 MC_ALERT_RECEIVED=1" ;;
      *POST\ /agent*) echo "1" ;;
    esac ;;
esac
exit 0
FAKE
chmod +x "$AH_VM_PY"

reset_state() { rm -rf "$AH_VM_STATE_DIR" "$AH_OUT_DIR"; mkdir -p "$AH_VM_STATE_DIR"; : > "$FAKE_LOG"; rm -f "$FAKE_SEQ"; }
verbs() { cut -d' ' -f1 "$FAKE_LOG" | paste -sd, -; }

echo "── a plain run ──"
reset_state
OUT=$(bash "$MB" --agents 1 2>&1); rc=$?
[ $rc -eq 0 ] || bad "plain run: rc=$rc out=$OUT"
# The shape heavy.sh's capture_summary greps for. Its own summary line is the
# only thing the weekly report quotes from this script.
grep -qE '^ +multibox: [0-9]+ ok, 0 failed, [0-9]+ skipped  \(server=10\.0\.0\.[0-9]+, agents=3[0-9]+\)$' <<<"$OUT" \
  && ok "the summary line keeps its shape" || bad "summary: $(grep -a multibox: <<<"$OUT")"
# doctor BEFORE the first clone is the whole point of the check: a scenario that
# does not fit must cost nothing, not four booted boxes.
[ "$(head -1 "$FAKE_LOG" | cut -d' ' -f1)" = "doctor" ] \
  && ok "doctor runs before anything is cloned" || bad "first call: $(head -1 "$FAKE_LOG")"
grep -q '^doctor --roles server,agent$' "$FAKE_LOG" \
  && ok "doctor is told exactly the roles this run will ask for" || bad "roles: $(grep '^doctor' "$FAKE_LOG")"
grep -q '^clone --profile linux-server --role server --scenario mb-[0-9]* --ttl 90m$' "$FAKE_LOG" \
  && ok "the server box is cloned off the server profile, tagged and time-boxed" \
  || bad "server clone: $(grep '^clone' "$FAKE_LOG" | head -1)"
grep -q '^run 3001 --sync --timeout 2700 -- bash scripts/tests/box_serverbox.sh 10.0.0.1$' "$FAKE_LOG" \
  && ok "the server role script gets the box's own address" || bad "serverbox: $(grep box_serverbox "$FAKE_LOG")"
# The SERVER's address, not the agent's own: the whole point of this tier is
# that the agent enrols over a network hop against SAN=<server IP>.
grep -q '^run 3002 --sync --timeout 3000 -- bash scripts/tests/box_agentbox.sh 10.0.0.1 s1 p1 fp1 ca1$' "$FAKE_LOG" \
  && ok "the agent is pointed at the server and given its seed markers" \
  || bad "agentbox: $(grep box_agentbox "$FAKE_LOG")"
[ "$(verbs)" = "doctor,clone,wait,clone,wait,run,run,run,destroy" ] \
  && ok "the call order is doctor, clones, role scripts, teardown" || bad "order: $(verbs)"

echo "── the teardown ──"
reset_state
OUT=$(FAKE_SERVER_RC=1 bash "$MB" --agents 1 2>&1); rc=$?
[ $rc -ne 0 ] && ok "a failed server bring-up fails the run" || bad "server failure: rc=$rc"
# The one thing a half-finished run must still do: an aborted scenario that
# leaves boxes standing costs money every hour until somebody notices.
grep -qE '^destroy --scenario mb-[0-9]+$' "$FAKE_LOG" \
  && ok "a run that died mid-way still tears its scenario down" || bad "no teardown: $(verbs)"
[ "$(tail -1 "$FAKE_LOG" | cut -d' ' -f1)" = "destroy" ] \
  && ok "the teardown is the last thing that happens" || bad "last call: $(tail -1 "$FAKE_LOG")"

echo "── --keep ──"
reset_state
bash "$MB" --agents 1 --keep >/dev/null 2>&1
grep -q '^destroy' "$FAKE_LOG" && bad "--keep still destroyed: $(verbs)" \
  || ok "--keep leaves the scenario standing"

echo "── a hypervisor that cannot fit the run ──"
reset_state
OUT=$(FAKE_DOCTOR_RC=74 bash "$MB" --capstone 2>&1); rc=$?
[ $rc -eq 74 ] && ok "a refused capacity check is infrastructure (74), not a failed test" \
  || bad "doctor refusal: rc=$rc"
grep -q '^clone' "$FAKE_LOG" && bad "cloned anyway: $(verbs)" || ok "and nothing was cloned"
grep -q 'server,agent,moncheck,rpm,tunnel,visitor,desktop' "$FAKE_LOG" \
  && ok "the capstone asks for all seven roles at once" || bad "capstone roles: $(grep '^doctor' "$FAKE_LOG")"

echo "── a warm desktop box is reused ──"
reset_state
OUT=$(AH_DESKTOP_VM=3999 FAKE_DOCTOR_RC=74 bash "$MB" --capstone 2>&1)
grep -q 'doctor --roles server,agent,moncheck,rpm,tunnel,visitor$' "$FAKE_LOG" \
  && ok "AH_DESKTOP_VM takes the desktop role out of the capacity sum" \
  || bad "reuse roles: $(grep '^doctor' "$FAKE_LOG")"
reset_state
OUT=$(AH_DESKTOP_ID=3999 FAKE_DOCTOR_RC=74 bash "$MB" --capstone 2>&1)
grep -q "AH_DESKTOP_ID is the old name" <<<"$OUT" \
  && ok "the old env name still works and says so" || bad "alias: $OUT"

echo "── an unknown flag ──"
reset_state
OUT=$(bash "$MB" --bogus 2>&1); rc=$?
[ $rc -eq 2 ] && [ ! -s "$FAKE_LOG" ] \
  && ok "an unknown flag is a usage error before any VM is touched" || bad "unknown flag: rc=$rc"

echo ""
echo "multibox_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
