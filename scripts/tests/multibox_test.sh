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
export FAKE_DOCKER_N="$WORK/docker.n"

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
      # The frps stage of --tunnel (R-0411) on the server box; NONE: no marker.
      *"box_serverbox.sh frps-mark"*) echo "${FAKE_FRPS_MARK:-MB_FRPS_MARK=0123456789abcdef:3:101}" ;;
      *"box_serverbox.sh frps-restart "*)
        echo "MB_FRPS_SEEN=events:applied/none/false,pid:101-202-202,starts:1,exits:0"
        [ "${FAKE_FRPS_RESTART:-OK}" = NONE ] || echo "MB_FRPS_RESTART=${FAKE_FRPS_RESTART:-OK}"
        [ "${FAKE_FRPS_BACK:-OK}" = NONE ] || echo "MB_FRPS_TUNNELS=${FAKE_FRPS_BACK:-OK}" ;;
      # frps' way out of frpedge (--tunnel), seen from the server box; NONE: no marker.
      *"box_serverbox.sh frps-egress "*)
        [ "${FAKE_FRPS_EGRESS:-}" = NONE ] || echo "MB_FRPS_EGRESS=${FAKE_FRPS_EGRESS:-frps:blocked,server:open}" ;;
      *box_serverbox.sh*)
        [ "${FAKE_SERVER_RC:-0}" = 0 ] || exit "$FAKE_SERVER_RC"
        echo "MB_SID=s1 MB_PTOK=p1 MB_ADMIN_PW=pw1 MB_MONITOR_KEY=k1"
        echo "MB_REPO_GPG_FP=fp1 MB_CA_FP=ca1 MB_DEB_OLDDPKG_OK=1 MB_FRPS_UP=1"
        echo "MB_AGENT_GO=${FAKE_AGENT_GO-go1.26.9}"
        echo "MB_ENFORCE_CERTLESS_REJECTED=1 MC_OK_STATUS=ok MC_CRIT_STATUS=critical"
        echo "MB_TUN_SID=t1 MB_TUN_PTOK=tp1 MB_CFG=c1 MB_VIS_SID=v1 MB_VIS_PTOK=vp1 MB_VISITOR_B64=dmlz" ;;
      # --enforce: one enrollment token per desktop spec, each on a line of its own.
      *mint-enroll-token*) printf '%s\n' mb-fake-enroll-token-0001 mb-fake-enroll-token-0002 ;;
      *box_desktopbox.sh*) echo "DESKTOP_ALL_OK" ;;
      *box_agentbox_rpm.sh*) echo "RPM_ALL_OK" ;;
      # The admin API on the server box (srv_api); the tunnel name is the last word.
      *"python3 -I - clear "*) echo "${FAKE_API_CLEAR:-MB_API_CLEARED=1}" ;;
      *"python3 -I - frps-config "*) echo "${FAKE_API_FRPS_CONFIG:-MB_API_FRPS_CONFIG=${args##* }}" ;;
      *"python3 -I - add "*)
        name="${args##* }"
        [ "$name" = "${FAKE_API_ADD_FAIL:-}" ] || echo "MB_API_TUNNEL=$name MB_VISITOR_B64=bGF0ZQ==" ;;
      *"box_tunnelbox.sh late "*)
        echo "TUNNEL_FRPC_CONNECTED ${FAKE_TUNNEL_LATE:-TUNNEL_LATE_OK} ${FAKE_TUNNEL_SYNC:-TUNNEL_SYNC_HASH_OK}" ;;
      *"box_tunnelbox.sh mark "*) echo "TUNNEL_SSH_USER=ah TUNNEL_MARK_OK" ;;
      *"box_tunnelbox.sh reload "*) echo "${FAKE_TUNNEL_RELOAD:-TUNNEL_RELOAD_OK}" ;;
      *box_tunnelbox.sh*) echo "TUNNEL_SSHD_OK TUNNEL_PROVISION_OK ${FAKE_TUNNEL_BEFORE:-TUNNEL_BEFORE_OK}" ;;
      # After the frps restart (R-0411) the *_AFTER answers, by default the ones before it.
      *"box_visitorbox.sh hold "*)
        if grep -q 'box_serverbox.sh frps-restart' "$FAKE_LOG"; then echo "${FAKE_VIS_HOLD_AFTER:-${FAKE_VIS_HOLD:-VIS_SESSION_OPEN}}"
        else echo "${FAKE_VIS_HOLD:-VIS_SESSION_OPEN}"; fi ;;
      *"box_visitorbox.sh check"*)
        if grep -q 'box_serverbox.sh frps-restart' "$FAKE_LOG"; then echo "${FAKE_VIS_CHECK_AFTER:-${FAKE_VIS_CHECK:-VIS_SESSION_SURVIVED}}"
        else echo "${FAKE_VIS_CHECK:-VIS_SESSION_SURVIVED}"; fi ;;
      *box_visitorbox.sh*) echo "${FAKE_VIS_SSH:-VIS_TUNNEL_SSH_OK} VIS_SSH_PUB_B64=cHVi" ;;
      *"logs --no-color frps"*)
        for t in ${FAKE_FRPS_TUNNELS:-mb-ssh-late mb-ssh-reload}; do echo "new proxy [mb-tunnel.$t] type [stcp] success"; done ;;
      # --docker: the template and the check state over the admin API, the n-th query
      # answering with the n-th word of FAKE_DOCKER_STATES (NONE: no marker).
      *"python3 -I - docker-assign "*) echo "${FAKE_API_DOCKER_ASSIGN:-MB_API_TEMPLATE=docker-host}" ;;
      *"python3 -I - docker-state "*)
        n=$(cat "$FAKE_DOCKER_N" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$FAKE_DOCKER_N"
        read -ra states <<<"${FAKE_DOCKER_STATES:-DOCKER_OK DOCKER_EXIT_DAMPED DOCKER_EXIT_CRIT DOCKER_UNAVAIL_WARN}"
        s="${states[$((n - 1))]:-NONE}"
        [ "$s" = NONE ] || echo "MB_DOCKER_STATE=$s MB_DOCKER_SEEN=status:fake,query:$n" ;;
      # The docker steps on the agent box; FAKE_DOCKER_STEP_<STEP> is the verdict of one.
      *"box_agentbox.sh docker "*)
        step="${args##* }"; var="FAKE_DOCKER_STEP_${step^^}"; v="${!var:-OK}"
        [ "$step" = start ] && echo "AGENT_DOCKER_ENGINE=29.8.1 AGENT_DOCKER_IMAGE=busybox"
        [ "$v" = NONE ] || echo "AGENT_DOCKER_STEP=$v" ;;
      *box_agentbox.sh*)
        echo "${FAKE_AGENT_PROVISION:-AGENT_PROVISION_OK} ${FAKE_AGENT_RUN:-AGENT_RUN_OK} AGENT_CERT_OK AGENT_REPO_OK AGENT_CAFLIP_OK" ;;
      *box_moncheckbox.sh*start*) echo "MC_MAILHOG_UP=1 MC_CA_B64=Y2E=" ;;
      *box_moncheckbox.sh*assert*) echo "MC_MAIL_COUNT=1 MC_ALERT_RECEIVED=1" ;;
      # Two: the capstone expects a report from the .deb and from the rpm agent.
      *POST\ /agent*) echo "2" ;;
    esac ;;
esac
exit 0
FAKE
chmod +x "$AH_VM_PY"

reset_state() { rm -rf "$AH_VM_STATE_DIR" "$AH_OUT_DIR"; mkdir -p "$AH_VM_STATE_DIR"; : > "$FAKE_LOG"; rm -f "$FAKE_SEQ" "$FAKE_DOCKER_N"; }
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

echo "── --tunnel: the agent's own sync over its server's route ──"
reset_state
OUT=$(bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q '^  ok   tunnel agent: frpc sync got config-hash' <<<"$OUT" \
  && ok "a sync that gets the applied hash back is an ok of its own" \
  || bad "tunnel sync ok: rc=$rc; $(grep -a 'tunnel agent' <<<"$OUT")"
reset_state
OUT=$(FAKE_TUNNEL_SYNC=TUNNEL_SYNC_FAILED bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL tunnel agent: frpc sync .*: TUNNEL_SYNC_FAILED' <<<"$OUT" \
  && ok "a failed sync fails the run and names its marker" \
  || bad "tunnel sync failed: rc=$rc; $(grep -a 'tunnel agent' <<<"$OUT")"
reset_state
OUT=$(FAKE_TUNNEL_SYNC=NONE bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL tunnel agent: frpc sync .*: no marker' <<<"$OUT" \
  && ok "a tunnel box without a sync marker fails the run" \
  || bad "tunnel sync missing: rc=$rc; $(grep -a 'tunnel agent' <<<"$OUT")"

echo "── --tunnel: a tunnel after the provisioning, a reload under an open session ──"
# The tunnel steps in the order the run asked for them: the API calls on the server box
# and the modes of the two role scripts.
tunnel_steps() {
  local l m
  while IFS= read -r l; do
    case "$l" in
      *"python3 -I - clear "*) printf 'clear ' ;;
      *"python3 -I - add "*) printf 'add:%s ' "${l##* }" ;;
      *"python3 -I - frps-config "*) printf 'frps-config ' ;;
      *"box_serverbox.sh frps-"*) m="${l#*box_serverbox.sh }"; printf '%s ' "${m%% *}" ;;
      *"box_tunnelbox.sh "*) m="${l#*box_tunnelbox.sh }"; printf 'tunnel:%s ' "${m%% *}" ;;
      *"box_visitorbox.sh "*) m="${l#*box_visitorbox.sh }"; printf 'visitor:%s ' "${m%% *}" ;;
    esac
  done < "$FAKE_LOG"
}
reset_state
OUT=$(bash "$MB" --tunnel 2>&1); rc=$?
missing=""
for want in "tunnel agent: provisioned before its tunnel existed" \
            "tunnel agent: one agent run set frpc up for the later tunnel" \
            "frps registered the agent's STCP tunnel mb-ssh-late" \
            "visitor holds an SSH session open through mb-ssh-late" \
            "tunnel agent: frpc took mb-ssh-reload by a reload, no restart" \
            "frps registered the second tunnel mb-ssh-reload" \
            "the visitor's SSH session through mb-ssh-late lived through the reload"; do
  grep -qF "  ok   $want" <<<"$OUT" || missing="$missing [$want]"
done
[ $rc -eq 0 ] && [ -z "$missing" ] \
  && ok "a green --tunnel run has an ok of its own for the late tunnel, the reload and the session" \
  || bad "--tunnel: rc=$rc, missing:$missing"
[ "$(tunnel_steps)" = "frps-egress clear tunnel:10.0.0.1 add:mb-ssh-late tunnel:late visitor:10.0.0.1 tunnel:mark visitor:hold add:mb-ssh-reload tunnel:reload visitor:check frps-mark frps-config frps-restart visitor:hold visitor:check " ] \
  && ok "frps' way out, delete the seeded tunnel, provision, add, agent run, visitor, session, add, reload, check, then mark frps, change its config, watch the restart, a new session, check" \
  || bad "tunnel order: $(tunnel_steps)"
grep -qE '^run 3001 --timeout 300 -- printf %s [[:alnum:]+/=]+ \| base64 -d \| python3 -I - clear pw1 t1$' "$FAKE_LOG" \
  && grep -qE '^run 3001 --timeout 300 -- printf %s [[:alnum:]+/=]+ \| base64 -d \| python3 -I - add pw1 t1 c1 mb-ssh-late$' "$FAKE_LOG" \
  && ok "the API calls run on the server box with the admin password, the host and its FRP config" \
  || bad "api calls: $(grep -o 'python3 -I - .*' "$FAKE_LOG")"
grep -q '^run 3004 --sync --timeout 3000 -- bash scripts/tests/box_visitorbox.sh 10.0.0.1 v1 vp1 bGF0ZQ==$' "$FAKE_LOG" \
  && ok "the visitor gets the visitor.toml from after the late tunnel, not the seeded one" \
  || bad "visitor toml: $(grep 'box_visitorbox.sh 10' "$FAKE_LOG")"
grep -q 'box_tunnelbox.sh mark cHVi$' "$FAKE_LOG" && grep -q 'box_visitorbox.sh hold ah$' "$FAKE_LOG" \
  && ok "the visitor's key goes to the tunnel box, the tunnel box's user to the visitor" \
  || bad "key/user: $(grep -E 'box_(tunnel|visitor)box.sh (mark|hold)' "$FAKE_LOG")"

# expect_fail <what> <FAIL line> <VAR=value…> — a --tunnel run with that fake answer is red
# and names what it saw.
expect_fail() {
  local what="$1" want="$2" out rc; shift 2
  reset_state
  out=$(env "$@" bash "$MB" --tunnel 2>&1); rc=$?
  [ $rc -ne 0 ] && grep -qF "  FAIL $want" <<<"$out" \
    && ok "$what" || bad "$what: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$out")"
}
expect_fail "a seeded tunnel the API did not delete fails the run" \
  "could not delete the seeded tunnel" FAKE_API_CLEAR=NONE
expect_fail "a host provisioned with a tunnel fails the run" \
  "tunnel agent: provisioning without a tunnel" FAKE_TUNNEL_BEFORE=TUNNEL_BEFORE_FAIL
expect_fail "an agent run that did not take the late tunnel fails the run and names its marker" \
  "tunnel agent: the agent run did not take the later tunnel: TUNNEL_LATE_FAIL" FAKE_TUNNEL_LATE=TUNNEL_LATE_FAIL
expect_fail "a tunnel box without a late marker fails the run" \
  "tunnel agent: the agent run did not take the later tunnel: no marker" FAKE_TUNNEL_LATE=NONE
expect_fail "a restart instead of a reload fails the run and names its marker" \
  "tunnel agent: mb-ssh-reload without a clean reload: TUNNEL_RELOAD_RESTARTED" FAKE_TUNNEL_RELOAD=TUNNEL_RELOAD_RESTARTED
expect_fail "a tunnel box without a reload marker fails the run" \
  "tunnel agent: mb-ssh-reload without a clean reload: no marker" FAKE_TUNNEL_RELOAD=NONE
expect_fail "a session lost in the reload fails the run" \
  "the visitor's SSH session through mb-ssh-late did not live through the reload: VIS_SESSION_LOST" FAKE_VIS_CHECK=VIS_SESSION_LOST
expect_fail "a session check without a marker fails the run" \
  "the visitor's SSH session through mb-ssh-late did not live through the reload: no marker" FAKE_VIS_CHECK=NONE
expect_fail "a second tunnel frps never registered fails the run" \
  "frps shows no STCP registration of mb-ssh-reload" FAKE_FRPS_TUNNELS=mb-ssh-late
reset_state
OUT=$(FAKE_API_ADD_FAIL=mb-ssh-late bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL could not create tunnel mb-ssh-late' <<<"$OUT" \
  && ! grep -q 'box_visitorbox.sh' "$FAKE_LOG" \
  && ok "without the late tunnel the visitor does not run on the stale seeded visitor.toml" \
  || bad "late tunnel missing: rc=$rc; $(grep -aE '^  FAIL' <<<"$OUT"); $(grep box_visitorbox "$FAKE_LOG")"
reset_state
OUT=$(FAKE_VIS_HOLD=VIS_SESSION_NOT_OPEN bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL visitor could not open an SSH session through mb-ssh-late: VIS_SESSION_NOT_OPEN' <<<"$OUT" \
  && grep -q '^  SKIP the SSH session through the reload' <<<"$OUT" && ! grep -q 'box_visitorbox.sh check' "$FAKE_LOG" \
  && ok "a session that never opened fails the run, and its survival is named unverified" \
  || bad "no session: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT")"

echo "── --tunnel: a config change restarts frps once, the agent and a visitor come back (R-0411) ──"
reset_state
OUT=$(bash "$MB" --tunnel 2>&1); rc=$?
missing=""
for want in "frps up on the server box, run by its supervisor from the seeded config" \
            "max_ports_per_client of the FRP config set to 32 over the API" \
            "frps restarted exactly once for the change: one event, applied, one start and no exit in its log, a new frps process (events:applied/none/false,pid:101-202-202,starts:1,exits:0)" \
            "the agent's frpc logged in again by itself: frps registered mb-ssh-late mb-ssh-reload anew after the restart" \
            "a new visitor connection after the restart: an SSH session through mb-ssh-late carries data" \
            "the new SSH session through mb-ssh-late still carries data seconds later"; do
  grep -qF "  ok   $want" <<<"$OUT" || missing="$missing [$want]"
done
[ $rc -eq 0 ] && [ -z "$missing" ] \
  && ok "a green --tunnel run has an ok of its own for the change, the one restart, the agent and the new visitor" \
  || bad "R-0411: rc=$rc, missing:$missing"
grep -q '^run 3001 --timeout 300 -- bash scripts/tests/box_serverbox.sh frps-mark$' "$FAKE_LOG" \
  && grep -qE '^run 3001 --timeout 300 -- printf %s [[:alnum:]+/=]+ \| base64 -d \| python3 -I - frps-config pw1 c1 32$' "$FAKE_LOG" \
  && grep -q '^run 3001 --timeout 900 -- bash scripts/tests/box_serverbox.sh frps-restart 0123456789abcdef:3:101 mb-ssh-late mb-ssh-reload$' "$FAKE_LOG" \
  && ok "mark, change and watch run on the server box: the tunnels' FRP config, the mark, both tunnels" \
  || bad "frps calls: $(grep -E 'frps-' "$FAKE_LOG")"
[ "$(grep -c '^run 3004 --timeout 300 -- bash scripts/tests/box_visitorbox.sh hold ah$' "$FAKE_LOG")" = 2 ] \
  && ok "the new visitor connection is a second session from the visitor box, as the tunnel box's user" \
  || bad "holds: $(grep 'box_visitorbox.sh hold' "$FAKE_LOG")"
# heavy.sh capstone_scan files a FAIL by the role of the section header it falls under.
grep -q '^== tunnel (R-0411): ' <<<"$OUT" \
  && ok "the stage runs under a tunnel header, so the capstone files its failures under the tunnel role" \
  || bad "no tunnel header for the stage: $(grep -a '^== ' <<<"$OUT")"

expect_fail "a restart the supervisor did not report once fails the run and names its verdict" \
  "frps did not restart exactly once for the change: EVENTS (events:applied/none/false,pid:101-202-202,starts:1,exits:0)" FAKE_FRPS_RESTART=EVENTS
expect_fail "a restart watch without a verdict fails the run" \
  "frps did not restart exactly once for the change: no marker" FAKE_FRPS_RESTART=NONE
expect_fail "a login watch without a verdict fails the run" \
  "the agent's frpc did not log in again after the restart: no marker" FAKE_FRPS_BACK=NONE
expect_fail "a new session that broke off fails the run" \
  "the new SSH session through mb-ssh-late broke off: VIS_SESSION_LOST" FAKE_VIS_CHECK_AFTER=VIS_SESSION_LOST
# frps_calls — the steps of the frps stage the run made, in order.
frps_calls() { tunnel_steps | grep -oE 'frps-(mark|config|restart)|visitor:(hold|check)' | paste -sd' ' -; }
reset_state
OUT=$(FAKE_FRPS_MARK=NONE bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL frps: no supervisor mark before the config change' <<<"$OUT" \
  && grep -q '^  SKIP the frps restart for a config change (no mark)' <<<"$OUT" \
  && [ "$(frps_calls)" = "visitor:hold visitor:check frps-mark" ] \
  && ok "without a mark the config is not changed, and the restart is named unverified" \
  || bad "no mark: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT"); $(frps_calls)"
reset_state
OUT=$(FAKE_API_FRPS_CONFIG=NONE bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL could not set max_ports_per_client of the FRP config' <<<"$OUT" \
  && grep -q '^  SKIP the frps restart for a config change (the config did not change)' <<<"$OUT" \
  && [ "$(frps_calls)" = "visitor:hold visitor:check frps-mark frps-config" ] \
  && ok "a config the API did not change is not watched for a restart, which is named unverified" \
  || bad "no change: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT"); $(frps_calls)"
reset_state
OUT=$(FAKE_FRPS_BACK=MISSING:mb-ssh-reload bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q "^  FAIL the agent's frpc did not log in again after the restart: MISSING:mb-ssh-reload" <<<"$OUT" \
  && grep -q '^  SKIP a new visitor connection after the restart (the agent.s tunnels are not back)' <<<"$OUT" \
  && [ "$(frps_calls)" = "visitor:hold visitor:check frps-mark frps-config frps-restart" ] \
  && ok "a tunnel frps did not register anew fails the run, and no visitor tries it" \
  || bad "agent not back: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT"); $(frps_calls)"
reset_state
OUT=$(FAKE_VIS_HOLD_AFTER=VIS_SESSION_NOT_OPEN bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL no new visitor connection through mb-ssh-late after the restart: VIS_SESSION_NOT_OPEN' <<<"$OUT" \
  && [ "$(frps_calls)" = "visitor:hold visitor:check frps-mark frps-config frps-restart visitor:hold" ] \
  && ok "a visitor that does not get through after the restart fails the run" \
  || bad "no new visitor: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT"); $(frps_calls)"
reset_state
OUT=$(FAKE_VIS_SSH=VIS_TUNNEL_SSH_FAIL bash "$MB" --tunnel 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  SKIP the frps restart for a config change (the visitor never got through before it)' <<<"$OUT" \
  && ! grep -qE 'frps-(mark|config|restart)' "$FAKE_LOG" \
  && ok "without a visitor that got through, frps is not touched, and the restart is named unverified" \
  || bad "no first visitor: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT"); $(grep frps- "$FAKE_LOG")"

echo "── --tunnel: frps reaches no second host from frpedge ──"
reset_state
OUT=$(bash "$MB" --tunnel 2>&1); rc=$?
# The tunnel box is the third clone: 3003 at 10.0.0.3.
[ $rc -eq 0 ] && grep -qF '  ok   frps reaches no second host from frpedge, the server container does (10.0.0.3:22)' <<<"$OUT" \
  && grep -q '^run 3001 --timeout 300 -- bash scripts/tests/box_serverbox.sh frps-egress 10.0.0.3 22$' "$FAKE_LOG" \
  && ok "the check runs on the server box against the tunnel box's sshd, an ok of its own" \
  || bad "egress: rc=$rc; $(grep -aE 'frps egress|frps reaches' <<<"$OUT"); $(grep frps-egress "$FAKE_LOG")"
expect_fail "frps reaching the tunnel box fails the run and names both results" \
  "frps egress to 10.0.0.3:22: frps:open,server:open (want frps:blocked,server:open)" FAKE_FRPS_EGRESS=frps:open,server:open
expect_fail "a target the server container cannot reach either fails the run" \
  "frps egress to 10.0.0.3:22: frps:blocked,server:closed" FAKE_FRPS_EGRESS=frps:blocked,server:closed
expect_fail "an nc that could not run in the frps container fails the run" \
  "frps egress to 10.0.0.3:22: frps:error,server:open" FAKE_FRPS_EGRESS=frps:error,server:open
expect_fail "a check without a marker fails the run" \
  "frps egress to 10.0.0.3:22: no marker" FAKE_FRPS_EGRESS=NONE
reset_state
bash "$MB" --agents 1 >/dev/null 2>&1
! grep -q 'frps-egress' "$FAKE_LOG" \
  && ok "without --tunnel there is no egress check" || bad "egress without the flag: $(grep frps-egress "$FAKE_LOG")"

echo "── the API program on the server box ──"
# srv_api ships it base64-encoded. Taken from a recorded call and run against a fake
# urlopen: a broken program fails here, not an hour into a VM run.
reset_state
bash "$MB" --tunnel >/dev/null 2>&1
PROG="$WORK/srv_api.py"
call="$(grep -m1 -F 'python3 -I - clear ' "$FAKE_LOG")"
b64="${call#* printf %s }"; b64="${b64%% *}"
base64 -d <<<"$b64" > "$PROG"
HARNESS="$WORK/api_harness.py"
cat > "$HARNESS" <<'PY'
import json, os, sys, urllib.request

prog, argv = sys.argv[1], sys.argv[2:]
tunnels = [{"id": "x1", "name": "mb-ssh"}]
keep = os.environ.get("HARNESS_KEEP") == "1"
templates = json.loads(os.environ.get("HARNESS_TEMPLATES") or json.dumps(
    [{"id": "z1", "name": "ZFS Storage", "builtinSlug": "zfs-storage"},
     {"id": "d1", "name": "Docker Host", "builtinSlug": "docker-host"}]))
checks = json.loads(os.environ.get("HARNESS_CHECKS") or "[]")


class Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body


def urlopen(req, context=None, timeout=None):
    method, path = req.get_method(), req.full_url.replace("https://localhost", "")
    body = json.loads(req.data) if req.data else None
    print("CALL %s %s %s" % (method, path, json.dumps(body, sort_keys=True) if body else ""), file=sys.stderr)
    if path == "/api/auth/login":
        return Resp(json.dumps({"access_token": "tok"}).encode())
    if req.get_header("Authorization") != "Bearer tok":
        raise AssertionError("no token on " + path)
    if method == "GET" and path.startswith("/api/frp/tunnels?server_id="):
        return Resp(json.dumps(tunnels).encode())
    if method == "DELETE" and path.startswith("/api/frp/tunnels/"):
        if not keep:
            tunnels[:] = [t for t in tunnels if path != "/api/frp/tunnels/" + t["id"]]
        return Resp(b"")
    if method == "POST" and path == "/api/frp/tunnels":
        return Resp(b"{}")
    if method == "PUT" and path == "/api/frp/server-config/c1":
        kept = os.environ.get("HARNESS_PUT_KEEP") == "1"
        return Resp(json.dumps({"id": "c1", "maxPortsPerClient": None if kept else body["max_ports_per_client"]}).encode())
    if method == "GET" and path == "/api/frp/generate/visitor-toml":
        return Resp(b"visitor")
    if method == "GET" and path == "/api/monitoring/templates":
        return Resp(json.dumps(templates).encode())
    if method == "GET" and path == "/api/servers/s1":
        return Resp(json.dumps({"id": "s1", "name": "mb-agent", "hostname": "mb-agent.local"}).encode())
    if method == "POST" and path == "/api/monitoring/templates/d1/assign":
        created = os.environ.get("HARNESS_CREATED", "c2").split()
        return Resp(json.dumps({"checksCreated": created, "alertsCreated": []}).encode())
    if method == "GET" and path == "/api/monitoring/checks?server_id=s1":
        return Resp(json.dumps(checks).encode())
    raise AssertionError("unexpected call " + method + " " + path)


urllib.request.urlopen = urlopen
sys.argv = ["-"] + argv
exec(compile(open(prog).read(), prog, "exec"), {"__name__": "__main__"})
PY
OUT=$(python3 -I "$HARNESS" "$PROG" clear pw1 t1 2>&1); rc=$?
[ $rc -eq 0 ] && grep -qx 'MB_API_CLEARED=1' <<<"$OUT" \
  && grep -qxF 'CALL POST /api/auth/login {"password": "pw1", "username": "admin"}' <<<"$OUT" \
  && grep -qxF 'CALL DELETE /api/frp/tunnels/x1 ' <<<"$OUT" \
  && ok "clear logs in as admin, deletes the tunnels of the host and says how many" || bad "clear: rc=$rc $OUT"
OUT=$(HARNESS_KEEP=1 python3 -I "$HARNESS" "$PROG" clear pw1 t1 2>&1); rc=$?
[ $rc -ne 0 ] && ! grep -q 'MB_API_CLEARED' <<<"$OUT" \
  && ok "a tunnel still there after the delete is an error, not a marker" || bad "clear kept: rc=$rc $OUT"
OUT=$(python3 -I "$HARNESS" "$PROG" add pw1 t1 c1 mb-ssh-late 2>&1); rc=$?
[ $rc -eq 0 ] \
  && grep -qxF 'CALL POST /api/frp/tunnels {"frp_config_id": "c1", "local_port": 22, "name": "mb-ssh-late", "protocol": "ssh", "server_id": "t1", "tunnel_type": "stcp"}' <<<"$OUT" \
  && grep -qx 'MB_API_TUNNEL=mb-ssh-late' <<<"$OUT" && grep -qx "MB_VISITOR_B64=$(printf visitor | base64)" <<<"$OUT" \
  && ok "add creates an STCP tunnel to the sshd and hands on the visitor.toml that has it" || bad "add: rc=$rc $OUT"
OUT=$(python3 -I "$HARNESS" "$PROG" frps-config pw1 c1 32 2>&1); rc=$?
[ $rc -eq 0 ] && grep -qxF 'CALL PUT /api/frp/server-config/c1 {"max_ports_per_client": 32}' <<<"$OUT" \
  && grep -qx 'MB_API_FRPS_CONFIG=32' <<<"$OUT" \
  && ok "frps-config sets max_ports_per_client of the FRP config and says to what" || bad "frps-config: rc=$rc $OUT"
OUT=$(HARNESS_PUT_KEEP=1 python3 -I "$HARNESS" "$PROG" frps-config pw1 c1 32 2>&1); rc=$?
[ $rc -ne 0 ] && ! grep -q 'MB_API_FRPS_CONFIG' <<<"$OUT" \
  && ok "a config that does not show the new value after the PUT is an error, not a marker" || bad "frps-config kept: rc=$rc $OUT"
OUT=$(python3 -I "$HARNESS" "$PROG" docker-assign pw1 s1 2>&1); rc=$?
[ $rc -eq 0 ] \
  && grep -qxF 'CALL POST /api/monitoring/templates/d1/assign {"hostname": "mb-agent.local", "server_id": "s1", "server_name": "mb-agent"}' <<<"$OUT" \
  && grep -qx 'MB_API_TEMPLATE=docker-host' <<<"$OUT" \
  && ok "docker-assign gives the host the standard template docker-host, with the name and hostname of its record" \
  || bad "docker-assign: rc=$rc $OUT"
OUT=$(HARNESS_TEMPLATES='[{"id": "d1", "name": "Docker Host", "builtinSlug": null}]' python3 -I "$HARNESS" "$PROG" docker-assign pw1 s1 2>&1); rc=$?
[ $rc -ne 0 ] && ! grep -q 'MB_API_TEMPLATE' <<<"$OUT" && ! grep -q 'CALL POST /api/monitoring' <<<"$OUT" \
  && ok "a template only named Docker Host is not the standard one: no assignment, no marker" || bad "docker-assign by name: rc=$rc $OUT"
OUT=$(HARNESS_CREATED='' python3 -I "$HARNESS" "$PROG" docker-assign pw1 s1 2>&1); rc=$?
[ $rc -ne 0 ] && ! grep -q 'MB_API_TEMPLATE' <<<"$OUT" \
  && ok "an assignment that created no check is an error, not a marker" || bad "docker-assign without a check: rc=$rc $OUT"

# dcheck <status> <failCount> <details> — the checks of host s1 as GET /checks lists them: a
# check of another type first, which docker-state must pass over.
dcheck() {
  printf '[{"id": "c1", "checkType": "agent_resources", "consecutiveFails": 3, "state": {"status": "critical", "failCount": 3}},'
  printf ' {"id": "c2", "checkType": "docker_health", "consecutiveFails": 2, "state": {"status": "%s", "failCount": %s, "details": %s}}]' "$1" "$2" "$3"
}
RUN_OK='{"name": "mb-dock-run", "category": "ok", "reason": null}'
EXIT_CRIT='{"name": "mb-dock-exit", "category": "critical", "reason": "exit:1"}'
EXIT_STOPPED='{"name": "mb-dock-exit", "category": "stopped", "reason": "stopped"}'
declare -A DET=(
  [UP]="{\"available\": true, \"error\": null, \"containers\": [$RUN_OK]}"
  [UP_EXIT]="{\"available\": true, \"error\": null, \"containers\": [$RUN_OK, $EXIT_CRIT]}"
  [UP_STOPPED]="{\"available\": true, \"error\": null, \"containers\": [$RUN_OK, $EXIT_STOPPED]}"
  [DOWN]='{"available": false, "error": "daemon_unreachable", "containers": []}'
  [DOWN_TIMEOUT]='{"available": false, "error": "timeout", "containers": []}'
  [NO_DETAILS]=null
)
wrong=""
while read -r want st fc det; do
  out="$(HARNESS_CHECKS="$(dcheck "$st" "$fc" "${DET[$det]}")" python3 -I "$HARNESS" "$PROG" docker-state pw1 s1 2>&1)"
  got="$(sed -n 's/^MB_DOCKER_STATE=//p' <<<"$out")"
  [ "$got" = "$want" ] || wrong="$wrong [$st $fc $det: ${got:-no marker}, want $want; $out]"
done <<'CASES'
DOCKER_OK ok 0 UP
DOCKER_STATE_OTHER ok 1 UP
DOCKER_STATE_OTHER pending 0 NO_DETAILS
DOCKER_EXIT_DAMPED ok 1 UP_EXIT
DOCKER_STATE_OTHER ok 0 UP_EXIT
DOCKER_EXIT_CRIT critical 2 UP_EXIT
DOCKER_STATE_OTHER critical 1 UP_EXIT
DOCKER_STATE_OTHER critical 2 UP_STOPPED
DOCKER_STATE_OTHER critical 2 UP
DOCKER_UNAVAIL_WARN warning 3 DOWN
DOCKER_STATE_OTHER unknown 3 DOWN
DOCKER_STATE_OTHER warning 3 DOWN_TIMEOUT
CASES
[ -z "$wrong" ] \
  && ok "docker-state names ok, the damped and the counted exit 1 and the stopped daemon, and nothing else" \
  || bad "docker-state:$wrong"
OUT=$(HARNESS_CHECKS="$(dcheck critical 2 "${DET[UP_EXIT]}")" python3 -I "$HARNESS" "$PROG" docker-state pw1 s1 2>&1)
grep -qxF 'MB_DOCKER_SEEN=status:critical,fails:2/2,available:True,error:None,mb-dock-run:ok/-,mb-dock-exit:critical/exit:1' <<<"$OUT" \
  && ok "docker-state says what it saw in one word" || bad "docker-state seen: $OUT"
two="$(dcheck ok 0 "${DET[UP]}" | sed 's/}}]$/}}, {"id": "c3", "checkType": "docker_health", "state": {"status": "ok"}}]/')"
OUT=$(HARNESS_CHECKS="$two" python3 -I "$HARNESS" "$PROG" docker-state pw1 s1 2>&1); rc=$?
[ $rc -ne 0 ] && ! grep -q 'MB_DOCKER_STATE' <<<"$OUT" \
  && ok "two Docker Health checks on the host are an error, not a state" || bad "two checks: rc=$rc $OUT"

echo "── the frps stage on the server box (box_serverbox.sh frps-mark, frps-restart) ──"
# The role script itself against a fake mb-dc: the supervisor's status file as its n-th read
# sees it (a new heartbeat each read, as from a poll, unless SV_FROZEN), the pid of frps as
# its n-th query sees it, and frps' log; sleep returns at once, so a wait runs out in its
# number of tries, not in minutes. A copy outside the checkout: a mode it does not know falls
# into a missing bootstrap, not into the real one.
SB_ROOT="$WORK/sb"
mkdir -p "$SB_ROOT/scripts/tests" "$SB_ROOT/bin"
cp "$HERE/box_serverbox.sh" "$SB_ROOT/scripts/tests/"
export SV_LOG="$WORK/sv.log" SV_READS="$WORK/sv.n" SV_PIDN="$WORK/sv-pid.n"
cat > "$SB_ROOT/bin/mb-dc" <<'FAKE'
#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >> "$SV_LOG"
case "$*" in
  "exec -T server cat /app/frps-state/status.json")
    n=$(( $(cat "$SV_READS" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$SV_READS"
    hb=$n; [ "${SV_FROZEN:-0}" = 1 ] && hb=1
    seq=3
    events='{"seq":3,"event":"started","at":"2026-10-17T10:00:00Z","reason":"none","tokenChanged":false}'
    # SV_EVENTS: <read>:<event>,… — each event is in the file from that read on.
    for spec in ${SV_EVENTS//,/ }; do
      [ "$n" -ge "${spec%%:*}" ] || continue
      seq=$((seq + 1))
      events="$events,{\"seq\":$seq,\"event\":\"${spec#*:}\",\"at\":\"2026-10-17T10:00:30Z\",\"reason\":\"none\",\"tokenChanged\":false}"
    done
    printf '{"v":1,"boot":"%s","heartbeat":"2026-10-17T11:%02d:%02dZ","state":"%s","reason":"none","since":"2026-10-17T10:00:00Z","appliedHash":null,"rejectedHash":null,"events":[%s]}\n' \
      "${SV_BOOT:-0123456789abcdef}" $((hb / 60 % 60)) $((hb % 60)) "${SV_STATE:-running}" "$events" ;;
  # frps-egress: the container's sh runs here with the nc of $SB_ROOT/bin, the server's python
  # with python3; EG_EXEC=frps|server: that exec fails.
  "exec -T frps sh -c "*"nc -z"*)
    [ "${EG_EXEC:-}" = frps ] && exit 1
    shift 3; exec "$@" ;;
  "exec -T server python -c "*)
    [ "${EG_EXEC:-}" = server ] && exit 1
    shift 4; exec python3 -I "$@" ;;
  # SV_PID: <pid>,… — the n-th query gets the n-th, the last one repeats; "-": no frps.
  "exec -T frps sh -c "*)
    k=$(( $(cat "$SV_PIDN" 2>/dev/null || echo 0) + 1 )); echo "$k" > "$SV_PIDN"
    read -ra pids <<<"${SV_PID//,/ }"
    [ "$k" -le "${#pids[@]}" ] || k=${#pids[@]}
    p="${pids[$((k - 1))]}"
    if [ "$p" != - ]; then echo "rc=0 $p"; else echo "rc=1 "; fi ;;
  # SV_SUP: start|exit,… — the supervisor's lines about frps since the event; SV_TUNNELS: the
  # tunnels frps registered since.
  "logs --no-color --since "*" frps")
    for l in ${SV_SUP//,/ }; do
      case $l in
        start) echo "frps-1  | [frps-supervisor] frps started from /var/lib/frps-active/current (pid 202)" ;;
        exit) echo "frps-1  | [frps-supervisor] frps exited (1), restarting it in 2s" ;;
      esac
    done
    for t in ${SV_TUNNELS//,/ }; do
      echo "frps-1  | 2026-10-17 10:00:31.000 [I] [server/control.go:1] [0a1b2c3d] new proxy [mb-tunnel.$t] type [stcp] success"
    done ;;
esac
exit 0
FAKE
printf '#!/bin/sh\nexit 0\n' > "$SB_ROOT/bin/sleep"
# The nc of the frps image (OpenBSD, probed): -z without -v says nothing on a failed connect,
# "succeeded!" on stderr for an open one, its usage on bad flags. EG_NC picks the answer.
export EG_NC_LOG="$WORK/nc.log"
cat > "$SB_ROOT/bin/nc" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$EG_NC_LOG"
case "${EG_NC:-blocked}" in
  open) echo "Connection to $3 $4 port [tcp/*] succeeded!" >&2 ;;
  blocked) exit 1 ;;
  usage) echo "usage: nc [-46CDdFhklNnrStUuvZz] [-I length] [-i interval] [-M ttl]" >&2; exit 1 ;;
  missing) echo "sh: nc: not found" >&2; exit 127 ;;
esac
FAKE
chmod +x "$SB_ROOT/bin/mb-dc" "$SB_ROOT/bin/sleep" "$SB_ROOT/bin/nc"
# sb <events> <pids> <supervisor lines> <tunnels> <mode> <args…> — one mode of the copy, as
# multibox.sh calls it, the reads and queries counted from 1; "-" for none.
sb() {
  local ev="$1" pid="$2" sup="$3" tun="$4"; shift 4
  rm -f "$SV_READS" "$SV_PIDN"; : > "$SV_LOG"
  SV_EVENTS="${ev#-}" SV_PID="$pid" SV_SUP="${sup#-}" SV_TUNNELS="${tun#-}" PATH="$SB_ROOT/bin:$PATH" \
    bash "$SB_ROOT/scripts/tests/box_serverbox.sh" "$@" 2>&1
}
OUT=$(sb - 101 - - frps-mark)
grep -qx 'MB_FRPS_MARK=0123456789abcdef:3:101' <<<"$OUT" \
  && ok "frps-mark: the boot of the supervisor, its last event and the pid of frps" || bad "frps-mark: $OUT"
wrong=""
# Each case: the status the supervisor writes, then the pid of frps.
for c in "SV_STATE=waiting 101" "SV_STATE=running -" "SV_BOOT=0123456789abcdeg 101" "SV_BOOT=0123456789abcde 101"; do
  out="$(export "${c% *}"; sb - "${c#* }" - - frps-mark)"
  grep -qx 'MB_FRPS_MARK_FAIL' <<<"$out" && ! grep -q 'MB_FRPS_MARK=' <<<"$out" || wrong="$wrong [$c: $out]"
done
[ -z "$wrong" ] \
  && ok "frps-mark: no mark while the supervisor waits, without a frps process, or with a boot that is not 16 hex" \
  || bad "frps-mark without a mark:$wrong"

ALL=mb-ssh-late,mb-ssh-reload
OUT=$(sb 2:applied 202 start "$ALL" frps-restart 0123456789abcdef:3:101 mb-ssh-late mb-ssh-reload)
grep -qx 'MB_FRPS_RESTART=OK' <<<"$OUT" && grep -qx 'MB_FRPS_TUNNELS=OK' <<<"$OUT" \
  && grep -qx 'MB_FRPS_SEEN=events:applied/none/false,pid:101-202-202,starts:1,exits:0' <<<"$OUT" \
  && ok "frps-restart: one applied event, one start and no exit in the log, a new frps pid, both tunnels back" \
  || bad "frps-restart: $OUT"
grep -qx 'logs --no-color --since 2026-10-17T10:00:29Z frps' "$SV_LOG" \
  && ok "frps-restart: frps' log is read since a second before the event, not before" \
  || bad "log since: $(grep '^logs' "$SV_LOG" | sort -u)"
# Each case: the verdicts, then events, pids, the supervisor's lines and the tunnels frps
# registered since the event.
wrong=""
while read -r want ev pid sup tun; do
  out="$(sb "$ev" "$pid" "$sup" "$tun" frps-restart 0123456789abcdef:3:101 mb-ssh-late mb-ssh-reload)"
  got="$(sed -n 's/^MB_FRPS_RESTART=//p' <<<"$out")/$(sed -n 's/^MB_FRPS_TUNNELS=//p' <<<"$out")"
  [ "$got" = "$want" ] || wrong="$wrong [$ev $pid $sup $tun: $got, want $want]"
done <<CASES
OK/OK 2:applied 202 start $ALL
EVENTS/OK 2:applied,4:applied 202 start $ALL
EVENTS/OK 2:applied,6:applied 202 start $ALL
EVENTS/OK 2:rejected 202 start $ALL
EVENTS/OK 2:applied,2:crashed 202 start $ALL
CRASHED/OK 2:applied 202 start,exit,start $ALL
CRASHED/OK 2:applied 202 start,exit $ALL
CRASHED/OK 2:applied 202,303 start $ALL
NO_START_LOG/OK 2:applied 202 - $ALL
SAME_PID/OK 2:applied 101 start $ALL
NO_FRPS/OK 2:applied 202,- start $ALL
OK/MISSING:mb-ssh-reload 2:applied 202 start mb-ssh-late
OK/MISSING:mb-ssh-late+mb-ssh-reload 2:applied 202 start -
CASES
[ -z "$wrong" ] \
  && ok "frps-restart: no ok without one applied event, one start of frps, the pid of the event, every tunnel back" \
  || bad "frps-restart:$wrong"
# The events are read only after two more polls: a second event that comes with the second
# poll after the first one is seen (EVENTS above), and a supervisor that stops polling is a
# verdict of its own, not an ok on a file that no longer changes.
OUT=$(SV_FROZEN=1 sb 2:applied 202 start "$ALL" frps-restart 0123456789abcdef:3:101 mb-ssh-late mb-ssh-reload)
grep -qx 'MB_FRPS_RESTART=NO_POLL' <<<"$OUT" && grep -qx 'MB_FRPS_TUNNELS=OK' <<<"$OUT" \
  && ok "frps-restart: a heartbeat that stands still is NO_POLL" || bad "frozen heartbeat: $(grep '^MB_FRPS' <<<"$OUT")"
OUT=$(sb - 202 start "$ALL" frps-restart 0123456789abcdef:3:101 mb-ssh-late mb-ssh-reload)
grep -qx 'MB_FRPS_RESTART=NO_EVENT' <<<"$OUT" && grep -qx 'MB_FRPS_TUNNELS=NO_RESTART' <<<"$OUT" \
  && [ "$(cat "$SV_READS")" -ge 60 ] && ! grep -q '^logs --no-color --since' "$SV_LOG" \
  && ok "frps-restart: without an event it asks the supervisor 60 times, gives up, and reads no log" \
  || bad "no event: $(grep '^MB_FRPS' <<<"$OUT"); $(cat "$SV_READS") reads; $(grep '^logs' "$SV_LOG" | head -3)"
wrong=""
for mark in not-a-mark 0123456789abcdeg:3:101 0123456789abcdef:x:101; do
  out="$(sb 2:applied 202 start "$ALL" frps-restart "$mark" mb-ssh-late)"
  grep -qx 'MB_FRPS_RESTART=NO_MARK' <<<"$out" && grep -qx 'MB_FRPS_TUNNELS=NO_RESTART' <<<"$out" \
    || wrong="$wrong [$mark: $(grep '^MB_FRPS' <<<"$out")]"
done
[ -z "$wrong" ] && ok "frps-restart: a broken mark is a verdict of its own" || bad "bad mark:$wrong"

echo "── frps without a way out (box_serverbox.sh frps-egress) ──"
# The server's python connects for real: to a port that listens, and to one bound without a
# listener (refused). Detached from this script's output, so that no reader waits on it.
python3 -I -c '
import socket, time
lis = socket.create_server(("127.0.0.1", 0))
shut = socket.socket()
shut.bind(("127.0.0.1", 0))
print(lis.getsockname()[1], shut.getsockname()[1], flush=True)
time.sleep(60)' </dev/null >"$WORK/eg.ports" 2>/dev/null &
EG_PID=$!
for _ in $(seq 1 50); do [ -s "$WORK/eg.ports" ] && break; sleep 0.1; done
read -r OPEN SHUT < "$WORK/eg.ports" || true
[ -n "${OPEN:-}" ] && [ -n "${SHUT:-}" ] && ok "frps-egress: a listening and a refusing port for the server's side" \
  || bad "frps-egress: no ports from the listener: $(cat "$WORK/eg.ports")"
# eg <ip> <port> — the mode as multibox.sh calls it; EG_NC and EG_EXEC from the caller.
eg() { : > "$EG_NC_LOG"; sb - - - - frps-egress "$@"; }
OUT=$(eg 127.0.0.1 "${OPEN:-0}"); rc=$?
[ $rc -eq 0 ] && [ "$OUT" = "MB_FRPS_EGRESS=frps:blocked,server:open" ] \
  && [ "$(cat "$EG_NC_LOG")" = "-z -w3 127.0.0.1 ${OPEN:-0}" ] \
  && ok "frps-egress: nc -z from frps fails without a word, the server connects: one line, exit 0" \
  || bad "frps-egress: rc=$rc out=[$OUT] nc=[$(cat "$EG_NC_LOG")]"
# Each case: the line it must print, then nc's answer, the exec that fails and the port.
wrong=""
while read -r want nc fails port; do
  out="$(EG_NC="$nc" EG_EXEC="${fails#-}" eg 127.0.0.1 "$port")"; rc=$?
  [ $rc -ne 0 ] && [ "$out" = "MB_FRPS_EGRESS=$want" ] || wrong="$wrong [$nc $fails $port: rc=$rc $out, want $want]"
done <<CASES
frps:open,server:open open - ${OPEN:-0}
frps:error,server:open usage - ${OPEN:-0}
frps:error,server:open missing - ${OPEN:-0}
frps:error,server:open blocked frps ${OPEN:-0}
frps:blocked,server:closed blocked - ${SHUT:-0}
frps:blocked,server:error blocked server ${OPEN:-0}
CASES
[ -z "$wrong" ] \
  && ok "frps-egress: exit 1 for an open frps, a closed target, and for an nc or a python that could not run" \
  || bad "frps-egress:$wrong"
kill "$EG_PID" 2>/dev/null; wait "$EG_PID" 2>/dev/null

echo "── the agent run on a host without a tunnel ──"
reset_state
OUT=$(bash "$MB" --agents 1 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q '^  ok   agent 3002: run --once green without a tunnel' <<<"$OUT" \
  && ok "a green agent run is an ok of its own" || bad "agent run ok: rc=$rc; $(grep -a 'agent 3002' <<<"$OUT")"
reset_state
OUT=$(FAKE_AGENT_RUN=AGENT_RUN_FAIL bash "$MB" --agents 1 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL agent 3002: run --once failed' <<<"$OUT" \
  && ok "a failed agent run fails the run" || bad "agent run failed: rc=$rc; $(grep -a 'agent 3002' <<<"$OUT")"

echo "── --docker: real Docker on the agent box, three states of the Docker Host check ──"
# The docker steps in the order the run asked for them: the API calls on the server box and
# the steps on the agent box.
docker_steps() {
  local l
  while IFS= read -r l; do
    case "$l" in
      *"python3 -I - docker-assign "*) printf 'assign ' ;;
      *"python3 -I - docker-state "*) printf 'state ' ;;
      *"box_agentbox.sh docker "*) printf '%s ' "${l##* }" ;;
    esac
  done < "$FAKE_LOG"
}
reset_state
OUT=$(bash "$MB" --docker 2>&1); rc=$?
missing=""
for want in "the Docker Host template is assigned to the host of agent 3002 over the API" \
            "docker agent box: the agent timer is stopped, a container keeps running, one agent run (Docker 29.8.1, image busybox)" \
            "docker: a running container -> ok (DOCKER_OK; status:fake,query:1)" \
            "docker agent box: a second container ended with exit 1, no restart policy, one agent run" \
            "docker: the first report of the exit 1 -> critical exit:1 in the details, the status damped (DOCKER_EXIT_DAMPED;" \
            "docker agent box: one more agent run" \
            "docker: the second report -> critical, reason exit:1 (DOCKER_EXIT_CRIT;" \
            "docker agent box: Docker daemon and socket stopped, one agent run" \
            "docker: the stopped daemon -> warning, error daemon_unreachable (DOCKER_UNAVAIL_WARN;"; do
  grep -qF "  ok   $want" <<<"$OUT" || missing="$missing [$want]"
done
[ $rc -eq 0 ] && [ -z "$missing" ] \
  && ok "a green --docker run has an ok of its own for each step and each of the three states" \
  || bad "--docker: rc=$rc, missing:$missing"
[ "$(docker_steps)" = "assign start state exit state rerun state down state " ] \
  && ok "assign the template, then per step: change Docker, one agent run, the state on the server" \
  || bad "docker order: $(docker_steps)"
grep -q '^run 3002 --timeout 900 -- bash scripts/tests/box_agentbox.sh docker start$' "$FAKE_LOG" \
  && grep -qE '^run 3001 --timeout 300 -- printf %s [[:alnum:]+/=]+ \| base64 -d \| python3 -I - docker-assign pw1 s1$' "$FAKE_LOG" \
  && grep -qE '^run 3001 --timeout 300 -- printf %s [[:alnum:]+/=]+ \| base64 -d \| python3 -I - docker-state pw1 s1$' "$FAKE_LOG" \
  && ok "the docker steps run on the provisioned agent box, the API calls on the server box for its host" \
  || bad "docker calls: $(grep -E 'docker-|box_agentbox.sh docker' "$FAKE_LOG")"
grep -q '^doctor --roles server,agent$' "$FAKE_LOG" \
  && ok "--docker asks for no box of its own" || bad "docker roles: $(grep '^doctor' "$FAKE_LOG")"

# expect_docker_fail <what> <FAIL line> <VAR=value…> — a --docker run with that fake answer
# is red and names what it saw.
expect_docker_fail() {
  local what="$1" want="$2" out rc; shift 2
  reset_state
  out=$(env "$@" bash "$MB" --docker 2>&1); rc=$?
  [ $rc -ne 0 ] && grep -qF "  FAIL $want" <<<"$out" \
    && ok "$what" || bad "$what: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$out")"
}
expect_docker_fail "a first state other than ok fails the run and names it" \
  "docker: a running container -> ok: DOCKER_STATE_OTHER (expected DOCKER_OK" \
  FAKE_DOCKER_STATES="DOCKER_STATE_OTHER DOCKER_EXIT_DAMPED DOCKER_EXIT_CRIT DOCKER_UNAVAIL_WARN"
expect_docker_fail "an exit 1 counted on its first report fails the run (consecutive_fails 2 damps it)" \
  "docker: the first report of the exit 1 -> critical exit:1 in the details, the status damped: DOCKER_EXIT_CRIT (expected DOCKER_EXIT_DAMPED" \
  FAKE_DOCKER_STATES="DOCKER_OK DOCKER_EXIT_CRIT DOCKER_EXIT_CRIT DOCKER_UNAVAIL_WARN"
expect_docker_fail "an exit 1 still damped on its second report fails the run" \
  "docker: the second report -> critical, reason exit:1: DOCKER_EXIT_DAMPED (expected DOCKER_EXIT_CRIT" \
  FAKE_DOCKER_STATES="DOCKER_OK DOCKER_EXIT_DAMPED DOCKER_EXIT_DAMPED DOCKER_UNAVAIL_WARN"
expect_docker_fail "a state query without a marker fails the run" \
  "docker: the stopped daemon -> warning, error daemon_unreachable: no marker (expected DOCKER_UNAVAIL_WARN" \
  FAKE_DOCKER_STATES="DOCKER_OK DOCKER_EXIT_DAMPED DOCKER_EXIT_CRIT"
expect_docker_fail "a daemon still up after the stop fails the run and names the verdict" \
  "docker agent box: Docker daemon and socket stopped, one agent run: STILL_UP" FAKE_DOCKER_STEP_DOWN=STILL_UP
expect_docker_fail "a docker step without a verdict fails the run" \
  "docker agent box: a second container ended with exit 1, no restart policy, one agent run: no marker" FAKE_DOCKER_STEP_EXIT=NONE
reset_state
OUT=$(FAKE_API_DOCKER_ASSIGN=NONE bash "$MB" --docker 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL could not assign the Docker Host template' <<<"$OUT" \
  && grep -q '^  SKIP the three Docker states (no Docker Host check)' <<<"$OUT" \
  && ! grep -q 'box_agentbox.sh docker' "$FAKE_LOG" \
  && ok "without the template no docker step runs, and the three states are named unverified" \
  || bad "no template: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT"); $(grep 'box_agentbox.sh docker' "$FAKE_LOG")"
reset_state
OUT=$(FAKE_AGENT_PROVISION=AGENT_PROVISION_FAIL bash "$MB" --docker 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  SKIP the Docker stage (no provisioned agent box)' <<<"$OUT" \
  && ! grep -qE 'docker-assign|box_agentbox.sh docker' "$FAKE_LOG" \
  && ok "an agent box that never provisioned gets no docker step, and the stage is named unverified" \
  || bad "no provisioned box: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT")"
reset_state
OUT=$(bash "$MB" --agents 1 2>&1)
! grep -qE 'docker-assign|docker-state|box_agentbox.sh docker' "$FAKE_LOG" && ! grep -q 'Docker' <<<"$OUT" \
  && ok "without --docker there is no docker step" || bad "docker without the flag: $(grep -E 'docker' "$FAKE_LOG")"

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

echo "── --capstone --strict: the Docker stage belongs to the release gate ──"
reset_state
OUT=$(bash "$MB" --capstone --strict 2>&1); rc=$?
missing=""
for want in "the Docker Host template is assigned to the host of agent 3002 over the API" \
            "docker: a running container -> ok (DOCKER_OK;" \
            "docker: the second report -> critical, reason exit:1 (DOCKER_EXIT_CRIT;" \
            "docker: the stopped daemon -> warning, error daemon_unreachable (DOCKER_UNAVAIL_WARN;"; do
  grep -qF "  ok   $want" <<<"$OUT" || missing="$missing [$want]"
done
[ $rc -eq 0 ] && grep -qE '^ +multibox: [0-9]+ ok, 0 failed, 0 skipped  \(' <<<"$OUT" && [ -z "$missing" ] \
  && ok "--capstone runs the Docker stage, and a strict capstone with it is green with nothing skipped" \
  || bad "capstone docker: rc=$rc, missing:$missing; $(grep -aE '^  (FAIL|SKIP)|multibox:' <<<"$OUT")"
on_agent="$(grep -c '^run 3002 --timeout 900 -- bash scripts/tests/box_agentbox.sh docker ' "$FAKE_LOG")"
[ "$(docker_steps)" = "assign start state exit state rerun state down state " ] && [ "$on_agent" = 4 ] \
  && ok "the capstone runs every Docker step on the .deb agent box" \
  || bad "capstone docker steps: $(docker_steps); $(grep 'box_agentbox.sh docker' "$FAKE_LOG")"
grep -qF "  ok   frps restarted exactly once for the change" <<<"$OUT" \
  && grep -qF "  ok   a new visitor connection after the restart" <<<"$OUT" \
  && ok "the capstone runs the frps restart stage of --tunnel" || bad "capstone frps: $(grep -a 'frps' <<<"$OUT")"
reset_state
OUT=$(FAKE_FRPS_MARK=NONE bash "$MB" --capstone --strict 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL strict: the frps restart for a config change (no mark)' <<<"$OUT" \
  && ok "a strict capstone whose frps restart stage was skipped is red and names the stage" \
  || bad "capstone, frps skipped: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT")"
reset_state
OUT=$(FAKE_API_DOCKER_ASSIGN=NONE bash "$MB" --capstone --strict 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL strict: the three Docker states (no Docker Host check)' <<<"$OUT" \
  && ok "a strict capstone whose Docker stage was skipped is red and names the stage" \
  || bad "capstone, docker skipped: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT")"
reset_state
OUT=$(FAKE_DOCKER_STATES=NONE bash "$MB" --capstone --strict 2>&1); rc=$?
[ $rc -ne 0 ] && grep -qF '  FAIL docker: a running container -> ok: no marker (expected DOCKER_OK' <<<"$OUT" \
  && ok "a strict capstone without a Docker result is red" \
  || bad "capstone, no docker result: rc=$rc; $(grep -aE '^  (FAIL|SKIP)' <<<"$OUT")"

echo "── an unknown flag ──"
reset_state
OUT=$(bash "$MB" --bogus 2>&1); rc=$?
[ $rc -eq 2 ] && [ ! -s "$FAKE_LOG" ] \
  && ok "an unknown flag is a usage error before any VM is touched" || bad "unknown flag: rc=$rc"

echo "── the Go that built the agent .deb ──"
reset_state
OUT=$(bash "$MB" --agents 1 2>&1); rc=$?
[ $rc -eq 0 ] && grep -qxF '  go version (agent .deb, server box): go1.26.9' <<<"$OUT" \
  && ok "the run names the Go the server box built the agent with" || bad "go line: rc=$rc $(grep -a 'go version' <<<"$OUT")"
reset_state
OUT=$(FAKE_AGENT_GO='' bash "$MB" --agents 1 2>&1); rc=$?
[ $rc -eq 0 ] && grep -qxF '  go version (agent .deb, server box): unknown (no MB_AGENT_GO marker)' <<<"$OUT" \
  && ok "no version from the box reads unknown and fails nothing" || bad "go line without the marker: rc=$rc $(grep -a 'go version' <<<"$OUT")"

echo ""
echo "multibox_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
