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
        echo "MB_REPO_GPG_FP=fp1 MB_CA_FP=ca1 MB_DEB_OLDDPKG_OK=1 MB_FRPS_UP=1"
        echo "MB_AGENT_GO=${FAKE_AGENT_GO-go1.26.9}"
        echo "MB_TUN_SID=t1 MB_TUN_PTOK=tp1 MB_CFG=c1 MB_VIS_SID=v1 MB_VIS_PTOK=vp1 MB_VISITOR_B64=dmlz" ;;
      # The admin API on the server box (srv_api); the tunnel name is the last word.
      *"python3 -I - clear "*) echo "${FAKE_API_CLEAR:-MB_API_CLEARED=1}" ;;
      *"python3 -I - add "*)
        name="${args##* }"
        [ "$name" = "${FAKE_API_ADD_FAIL:-}" ] || echo "MB_API_TUNNEL=$name MB_VISITOR_B64=bGF0ZQ==" ;;
      *"box_tunnelbox.sh late "*)
        echo "TUNNEL_FRPC_CONNECTED ${FAKE_TUNNEL_LATE:-TUNNEL_LATE_OK} ${FAKE_TUNNEL_SYNC:-TUNNEL_SYNC_HASH_OK}" ;;
      *"box_tunnelbox.sh mark "*) echo "TUNNEL_SSH_USER=ah TUNNEL_MARK_OK" ;;
      *"box_tunnelbox.sh reload "*) echo "${FAKE_TUNNEL_RELOAD:-TUNNEL_RELOAD_OK}" ;;
      *box_tunnelbox.sh*) echo "TUNNEL_SSHD_OK TUNNEL_PROVISION_OK ${FAKE_TUNNEL_BEFORE:-TUNNEL_BEFORE_OK}" ;;
      *"box_visitorbox.sh hold "*) echo "${FAKE_VIS_HOLD:-VIS_SESSION_OPEN}" ;;
      *"box_visitorbox.sh check"*) echo "${FAKE_VIS_CHECK:-VIS_SESSION_SURVIVED}" ;;
      *box_visitorbox.sh*) echo "VIS_TUNNEL_SSH_OK VIS_SSH_PUB_B64=cHVi" ;;
      *"logs --no-color frps"*)
        for t in ${FAKE_FRPS_TUNNELS:-mb-ssh-late mb-ssh-reload}; do echo "new proxy [mb-tunnel.$t] type [stcp] success"; done ;;
      *box_agentbox.sh*)
        echo "AGENT_PROVISION_OK ${FAKE_AGENT_RUN:-AGENT_RUN_OK} AGENT_CERT_OK AGENT_REPO_OK AGENT_CAFLIP_OK" ;;
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
[ "$(tunnel_steps)" = "clear tunnel:10.0.0.1 add:mb-ssh-late tunnel:late visitor:10.0.0.1 tunnel:mark visitor:hold add:mb-ssh-reload tunnel:reload visitor:check " ] \
  && ok "delete the seeded tunnel, provision, add, agent run, visitor, session, add, reload, check" \
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
    if method == "GET" and path == "/api/frp/generate/visitor-toml":
        return Resp(b"visitor")
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

echo "── the agent run on a host without a tunnel ──"
reset_state
OUT=$(bash "$MB" --agents 1 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q '^  ok   agent 3002: run --once green without a tunnel' <<<"$OUT" \
  && ok "a green agent run is an ok of its own" || bad "agent run ok: rc=$rc; $(grep -a 'agent 3002' <<<"$OUT")"
reset_state
OUT=$(FAKE_AGENT_RUN=AGENT_RUN_FAIL bash "$MB" --agents 1 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q '^  FAIL agent 3002: run --once failed' <<<"$OUT" \
  && ok "a failed agent run fails the run" || bad "agent run failed: rc=$rc; $(grep -a 'agent 3002' <<<"$OUT")"

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
