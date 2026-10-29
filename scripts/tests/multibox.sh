#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# multibox.sh — distributed, multi-host AdminHelper E2E on Proxmox VMs (scenario S1+).
#
# Clones a SERVER box + N AGENT boxes on the same bridge and wires a real
# cross-host topology the single-host scripts/tests/*.sh cannot reach:
#   server-box  = full docker-compose stack (gateway 443/8444/8445, frps 7000/7443)
#   agent-box(s)= real .deb install + `adminhelper-agent provision` over a network hop
# Then asserts each agent enrolled an mTLS identity and pushed a monitoring report.
#
#   bash scripts/tests/multibox.sh [--agents N] [--rpm] [--tunnel] [--docker]
#       [--desktop] [--moncheck] [--enforce] [--capstone] [--keep] [--strict]
#   --strict   a guard that could not run fails the capstone (release gate)
#   --rpm      + a cross-distro rpm agent (rockylinux)      (S2)
#   --tunnel   + frps + agent frpc STCP server + a visitor  (S4, 3-host tunnel); frps
#              reaches no other host from its network frpedge, the server container
#              reaches the tunnel box's sshd; the tunnel comes after the provisioning, a
#              second one by a reload while the visitor holds an SSH session over the
#              first (R-0398); then a change of the FRP config restarts frps once, and
#              the agent's frpc and a new visitor connection come back without a hand on
#              them (R-0411)
#   --docker   + the Docker Host template on the agent's host and real Docker on its
#              box: a running container -> ok, a container with exit 1 -> critical,
#              the daemon stopped -> warning (R-0419); no box of its own
#   --desktop  + the real Tauri GUI vs the remote server     (S3)
#   --moncheck + pull ping-checks + a closed-loop email alert (S5)
#   --enforce  + MTLS_ENFORCE=true: the certless data plane must be rejected
#   --capstone = --agents 1 --rpm --tunnel --docker --desktop --moncheck --enforce
#              (S6: all in one run — the release gate)
#   --keep     leave the VMs up after the run (still bounded by their ttl)
#
# Every VM of one run carries the same `sc-` tag, so the teardown is a single
# `vm.py destroy --scenario`: a box whose clone succeeded but whose boot did not
# is torn down with the rest instead of surviving as a leak. AH_DESKTOP_VM
# reuses an already warm desktop box (AH_DESKTOP_ID is the old name, kept for
# one release).
#
# Validates over the single-host suites: cross-host mTLS with SAN=<server IP> (not
# localhost), real package install + systemd, and the monitoring pipeline over a real
# hop. Box-side logic lives in scripts/tests/box_serverbox.sh / box_agentbox.sh.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/vm/lib.sh
. "$DIR/../vm/lib.sh"
cd "$VM_ROOT" || exit 1

AGENTS=1; KEEP=0; DESKTOP=0; RPM=0; TUNNEL=0; MONCHECK=0; ENFORCE=0; DOCKER=0
SKIPPED=0; MB_DEBIAN9_SKIPPED=0
while [ $# -gt 0 ]; do case "$1" in
  --agents) AGENTS="${2:?}"; shift ;; --keep) KEEP=1 ;; --desktop) DESKTOP=1 ;; --rpm) RPM=1 ;;
  --tunnel) TUNNEL=1 ;; --moncheck) MONCHECK=1 ;; --enforce) ENFORCE=1 ;;  # D2: MTLS_ENFORCE=true
  --docker) DOCKER=1 ;;
  # S6: everything, one run. --enforce included (R-0022): without it the
  # MTLS_ENFORCE guard never ran in a release capstone, which is the one place
  # the cert-gated data plane is supposed to be proven. --docker likewise (R-0419):
  # only a box with real Docker shows a container outage arriving at the server.
  --capstone) AGENTS=1; RPM=1; TUNNEL=1; DOCKER=1; DESKTOP=1; MONCHECK=1; ENFORCE=1 ;;
  # A flag, not just the env: AH_STRICT is set by run.sh alone, which never
  # starts this script, and a `AH_STRICT=1 multibox.sh` prefix is what
  # .claude/rules/testing.md forbids ("Env-Bedarf loest das Skript auf").
  --strict) AH_STRICT=1 ;;
  *) echo "unknown arg: $1"; exit 2 ;; esac; shift; done

vm_load_env || exit 1

# One scenario tag for the whole run — the teardown's only handle, and what
# keeps `vm.py list` from calling this run's seven boxes a leak while it lasts.
SCENARIO="mb-$$"; export AH_VM_SCENARIO="$SCENARIO"
PASS=0; FAIL=0; RPM_AGENTS=0
ok(){ echo "  ok   $*"; PASS=$((PASS+1)); }; bad(){ echo "  FAIL $*"; FAIL=$((FAIL+1)); }
# A check that could not run is its own outcome: counted, named in the summary,
# and a failure under AH_STRICT=1 — a capstone that quietly dropped a guard is
# not the evidence a release needs ("SKIP heisst nicht verifiziert").
skipped(){ echo "  SKIP $*"; SKIPPED=$((SKIPPED+1)); [ "${AH_STRICT:-0}" = "1" ] && bad "strict: $*"; return 0; }
cleanup() {
  [ "$KEEP" = 1 ] && { echo "--keep: leaving scenario $SCENARIO up (bounded by the ttl)"; return; }
  echo "== teardown scenario $SCENARIO =="
  # By tag, not by a list this script kept: a clone that came back and then
  # failed to boot never made it into any list, and it is exactly the box that
  # would otherwise be left running.
  vm_py destroy --scenario "$SCENARIO" 2>&1 | sed 's/^/  /' || true
}
trap cleanup EXIT INT TERM

DESKTOP_VM="${AH_DESKTOP_VM:-${AH_DESKTOP_ID:-}}"
# Only when this run actually has a desktop role to reuse — `--agents 3` in a
# shell that still exports the old name is not being told anything useful.
[ "$DESKTOP" = 1 ] && [ -n "${AH_DESKTOP_ID:-}" ] && [ -z "${AH_DESKTOP_VM:-}" ] \
  && echo "note: AH_DESKTOP_ID is the old name — use AH_DESKTOP_VM (the alias goes after the next release)"

# The roles this run is about to clone, in the order they will be asked for.
planned_roles() {
  local roles="server" i
  for i in $(seq 1 "$AGENTS"); do roles="$roles,agent"; done
  [ "$MONCHECK" = 1 ] && roles="$roles,moncheck"
  [ "$RPM" = 1 ] && roles="$roles,rpm"
  [ "$TUNNEL" = 1 ] && roles="$roles,tunnel,visitor"
  [ "$DESKTOP" = 1 ] && [ -z "$DESKTOP_VM" ] && roles="$roles,desktop"
  printf '%s' "$roles"
}

# Capacity BEFORE the first clone: seven boxes that die on the fifth leave four
# running and an hour spent. doctor answers 74 with the arithmetic and the list
# of VMs already holding the RAM, which is what makes it actionable.
echo "== doctor: does this hypervisor fit $(planned_roles)? =="
doctor_rc=0
vm_py doctor --roles "$(planned_roles)" || doctor_rc=$?
if [ "$doctor_rc" != 0 ]; then
  # NOT `if ! vm_py doctor`: inside that branch $? is the status of the
  # negation, which is 0 — a refused capacity check would exit 0 and read as a
  # run that passed without doing anything.
  echo ""
  echo "  multibox: 0 ok, 1 failed, 0 skipped  (doctor refused the scenario, exit $doctor_rc)"
  exit "$doctor_rc"
fi

# lease <role> <profile> -> echoes "<vmid> <ip>"; blocks until the box answers ssh.
# No retry: the clone is a two-second API call against the hypervisor, and every
# reason it fails (capacity, no free VMID, no template, a lost privilege) is one
# a second attempt meets again. vm.py answers those with 74 and names them.
lease() {
  local role="$1" profile="$2" vmid ip
  vmid="$(vm_py clone --profile "$profile" --role "$role" --scenario "$SCENARIO" --ttl 90m \
          | awk 'NR==1{print $1}')" || { echo "clone failed for role $role" >&2; return 1; }
  [ -n "$vmid" ] || { echo "clone printed no VMID for role $role" >&2; return 1; }
  ip="$(vm_py wait "$vmid" | tail -1)" || { echo "$role box $vmid never came up" >&2; return 1; }
  [ -n "$ip" ] || { echo "no address for $role box $vmid" >&2; return 1; }
  echo "$vmid $ip"
}

# box <vmid> <timeout> <command…> — a role script on a box, with the checkout
# synced first. 3000 s for every agent-profile role setup: each one runs the
# bootstrap, and a bootstrap that waits out the apt-lock race can take 20+
# minutes on its own. The 2026-09-11 weekly lost the moncheck and tunnel setups
# to a smaller bound, and every later failure that day was a consequence.
box() { local vmid="$1" tmo="$2"; shift 2; vm_py run "$vmid" --sync --timeout "$tmo" -- "$@"; }
# ask <vmid> <timeout> <command…> — a short query on a box that already has the
# tree. No --sync: re-pushing the checkout for a `docker logs` is a minute of
# rsync per question.
ask() { local vmid="$1" tmo="$2"; shift 2; vm_py run "$vmid" --timeout "$tmo" -- "$@"; }

echo "== clone 1 server + $AGENTS agent box(es) (scenario $SCENARIO) =="
read -r SRV_VM SRV_IP < <(lease server linux-server) || { bad "server lease"; exit 1; }
ok "server-box $SRV_VM @ $SRV_IP"
AGENT_VMS=()
for i in $(seq 1 "$AGENTS"); do
  if read -r a_vm a_ip < <(lease agent linux-server); then
    AGENT_VMS+=("$a_vm"); ok "agent-box$i $a_vm @ $a_ip"
    [ "$a_ip" = "$SRV_IP" ] && bad "agent$i IP $a_ip collides with server — DHCP/capacity? (need distinct concurrent VMs)"
  else bad "agent$i lease"; fi
done

MC_VM=""; MC_IP=""
if [ "$MONCHECK" = 1 ]; then
  echo "== moncheck (S5): clone the client/sink box + start mailhog (before the seed) =="
  if read -r MC_VM MC_IP < <(lease moncheck linux-server); then
    ok "moncheck-box $MC_VM @ $MC_IP"
    MCSTART="$(box "$MC_VM" 3000 bash scripts/tests/box_moncheckbox.sh start "$MC_IP" 2>&1)"
    echo "$MCSTART" | grep -vE 'Compiling|Downloaded ' | tail -20
    printf '%s' "$MCSTART" | grep -q MC_MAILHOG_UP && ok "mailpit sink up on $MC_IP (:1025/:8025, STARTTLS)" || bad "mailpit did not start"
    # The sink's self-signed cert travels to the server box so the monitoring
    # container can verify it — the alerter refuses unverified TLS (3.24).
    MC_CA_B64="$(vm_marker MC_CA_B64 "$MCSTART")"
    [ -n "$MC_CA_B64" ] || bad "sink CA marker missing (STARTTLS verify will fail)"
  else bad "moncheck-box lease"; fi
fi

echo "== bring up the server stack on $SRV_VM ($SRV_IP) =="
SRVARG=""
[ "$TUNNEL" = 1 ]   && SRVARG="$SRVARG tunnel"
# Only when the lease succeeded — an empty MC_IP would pass `moncheck` with no IP,
# shifting serverbox's positional args (4.124).
[ "$MONCHECK" = 1 ] && [ -n "$MC_IP" ] && SRVARG="$SRVARG moncheck $MC_IP ${MC_CA_B64:-none}"
[ "$ENFORCE" = 1 ]  && SRVARG="$SRVARG enforce"
# shellcheck disable=SC2086
SRVOUT="$(box "$SRV_VM" 2700 bash scripts/tests/box_serverbox.sh "$SRV_IP" $SRVARG 2>&1)"; echo "$SRVOUT" | grep -vE 'Compiling|Downloaded |Container |Network |Volume |Pulling|Waiting|Pull complete' | tail -40
# mb <KEY> — server-box marker via the shared vm_marker (scripts/vm/lib.sh),
# bound to $SRVOUT. Dedups 13 near-identical greps; a parsing fix lands once.
mb() { vm_marker "$1" "$SRVOUT"; }
SID="$(mb MB_SID)"
PTOK="$(mb MB_PTOK)"
ADMIN_PW="$(mb MB_ADMIN_PW)"
MONITOR_KEY="$(mb MB_MONITOR_KEY)"
SID2="$(mb MB_SID2)"
PTOK2="$(mb MB_PTOK2)"
TUN_SID="$(mb MB_TUN_SID)"
TUN_PTOK="$(mb MB_TUN_PTOK)"
TUN_CFG="$(mb MB_CFG)"
VIS_SID="$(mb MB_VIS_SID)"
VIS_PTOK="$(mb MB_VIS_PTOK)"
MC_OK_STATUS="$(mb MC_OK_STATUS)"
MC_CRIT_STATUS="$(mb MC_CRIT_STATUS)"
REPO_FP="$(mb MB_REPO_GPG_FP)"
CAFP="$(mb MB_CA_FP)"
OLDDPKG="$(mb MB_DEB_OLDDPKG_OK)"
AGENT_GO="$(mb MB_AGENT_GO)"
[ -n "$SID" ] && [ -n "$PTOK" ] && ok "stack up + provision token minted (server $SID)" \
  || { bad "server bring-up / token seed"; exit 1; }
# The signed test repo is the backbone of the user install path — its absence
# means the dogfooded agent-install.sh flow silently degrades, so fail loudly.
[ -n "$REPO_FP" ] && ok "signed test repo live on :8445 (gpg $REPO_FP)" \
  || bad "signed repo missing on :8445 (serverbox package/repo build failed — agents fall back to the local .deb path)"
[ -n "$CAFP" ] && ok "internal CA root fingerprint extracted (--ca-fp $CAFP)" \
  || bad "MB_CA_FP missing — agents fall back to TOFU first contact"
# Old-Debian regression guard: the .deb must install AND its binary must run on
# debian:9 (dpkg 1.18 + glibc 2.24 = Stretch / UniFi firmware). "0" is either the
# zstd-compression break (v0.43.0) or the dynamic-glibc break (v0.43.1); empty
# means the archived image could not pull (skip, not verified).
case "$OLDDPKG" in
  1) ok "agent .deb installs + binary runs on old Debian (debian:9: dpkg 1.18, glibc 2.24)" ;;
  0) bad "agent .deb/binary fails on debian:9 — zstd-compression OR dynamic-glibc regression!" ;;
  *) MB_DEBIAN9_SKIPPED=1
     skipped "old-Debian check (marker missing: debian:9 not pullable, or the .deb build failed) — the two release-breaking regressions of 0.43.x are unguarded" ;;
esac
if [ "$ENFORCE" = 1 ]; then
  printf '%s' "$SRVOUT" | grep -q 'MB_ENFORCE_CERTLESS_REJECTED=1' \
    && ok "MTLS_ENFORCE=true: certless :443 rejected (400) — cert-gated data plane over the hop" \
    || bad "enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED)"
else
  skipped "MTLS_ENFORCE guard (no --enforce; --capstone implies it) — the cert-gated data plane is unverified"
fi

echo "== provision each agent against https://$SRV_IP =="
# The box that holds host $SID: its provision token is single-use, so it is the first that
# provisioned. --docker works on it.
DOCK_VM=""
for a in "${AGENT_VMS[@]:-}"; do
  [ -n "$a" ] || continue
  AOUT="$(box "$a" 3000 bash scripts/tests/box_agentbox.sh "$SRV_IP" "$SID" "$PTOK" "$REPO_FP" "$CAFP" 2>&1)"; echo "$AOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -50
  [ -z "$DOCK_VM" ] && grep -q AGENT_PROVISION_OK <<<"$AOUT" && DOCK_VM="$a"
  printf '%s' "$AOUT" | grep -q AGENT_PROVISION_OK && printf '%s' "$AOUT" | grep -q AGENT_CERT_OK \
    && ok "agent $a: provisioned + mTLS-enrolled over the network hop" \
    || bad "agent $a: provision/enroll (see output above; check IP-SAN + firewall)"
  # This host has no tunnel: with --tunnel the server has an FRP config, without it none.
  # Either way the agent run ends without an error (R-0398).
  grep -q AGENT_RUN_OK <<<"$AOUT" \
    && ok "agent $a: run --once green without a tunnel (frpc sync + monitor push)" \
    || bad "agent $a: run --once failed (AGENT_RUN_OK missing, see output above)"
  if [ -n "$REPO_FP" ]; then
    printf '%s' "$AOUT" | grep -q AGENT_REPO_OK && printf '%s' "$AOUT" | grep -q AGENT_CAFLIP_OK \
      && ok "agent $a: installed from the :8445 repo via agent-install.sh, CA-pinned steady state" \
      || bad "agent $a: user-path markers missing (AGENT_REPO_OK/AGENT_CAFLIP_OK)"
  else
    skipped "agent $a: user install path (no MB_REPO_GPG_FP) — the :8445 repo and the CA-pin flip are unverified"
  fi
done

if [ "$RPM" = 1 ]; then
  echo "== cross-distro (S2): build the .rpm + provision it in a rockylinux container =="
  if read -r R_VM R_IP < <(lease rpm linux-server); then
    ok "rpm-agent-box $R_VM @ $R_IP"
    ROUT="$(box "$R_VM" 3000 bash scripts/tests/box_agentbox_rpm.sh "$SRV_IP" "$SID2" "$PTOK2" 2>&1)"
    echo "$ROUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -45
    printf '%s' "$ROUT" | grep -q RPM_ALL_OK \
      && { ok "rpm agent: built + installed + mTLS-enrolled in rockylinux over the hop"; RPM_AGENTS=1; } \
      || bad "rpm agent (see output above)"
  else bad "rpm-agent lease"; fi
fi

# srv_api <clear|add|docker-assign|docker-state> <server-id> [<frp-config-id> <tunnel>] — the
# admin API of the server box, called ON that box: under --enforce only it holds the admin
# client certificate (box_serverbox.sh enrolls it into /tmp). clear deletes the tunnels of a
# host; add creates an STCP tunnel to its sshd and prints the visitor.toml that has it.
# `srv_api frps-config <frp-config-id> <n>` sets max_ports_per_client of an FRP config.
# docker-assign gives a host the standard template Docker Host; docker-state names the state
# of its Docker Health check, the monitoring service answering through the proxy of the
# server as it does for the desktop. The program travels base64-encoded: vm.py joins the
# command into one `bash -lc` string.
srv_api_py() {
  cat <<'PY'
import base64, json, os, ssl, sys, urllib.request

action, password, server_id = sys.argv[1:4]
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
if os.path.exists("/tmp/mb-admin-fullchain.pem"):  # --enforce: :443 wants the admin cert
    ctx.load_cert_chain("/tmp/mb-admin-fullchain.pem", "/tmp/mb-admin.key")


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("https://localhost" + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    return urllib.request.urlopen(req, context=ctx, timeout=20).read()


login = {"username": "admin", "password": password}
token = json.loads(call("POST", "/api/auth/login", body=login))["access_token"]
listed = "/api/frp/tunnels?server_id=" + server_id
if action == "clear":
    tunnels = json.loads(call("GET", listed, token))
    for tunnel in tunnels:
        call("DELETE", "/api/frp/tunnels/" + tunnel["id"], token)
    if json.loads(call("GET", listed, token)):
        sys.exit("tunnels of server %s left after the delete" % server_id)
    print("MB_API_CLEARED=%d" % len(tunnels))
elif action == "add":
    config_id, name = sys.argv[4:6]
    call("POST", "/api/frp/tunnels", token, {"server_id": server_id, "frp_config_id": config_id,
                                             "name": name, "tunnel_type": "stcp",
                                             "protocol": "ssh", "local_port": 22})
    print("MB_API_TUNNEL=" + name)
    print("MB_VISITOR_B64=" + base64.b64encode(call("GET", "/api/frp/generate/visitor-toml", token)).decode())
elif action == "frps-config":
    # The third word names an FRP config here. max_ports_per_client goes into frps.toml
    # (maxPortsPerClient) and into no frpc.toml: a change frps alone has to take over.
    config_id, value = server_id, int(sys.argv[4])
    body = {"max_ports_per_client": value}
    changed = json.loads(call("PUT", "/api/frp/server-config/" + config_id, token, body))
    if changed.get("maxPortsPerClient") != value:
        sys.exit("FRP config %s has max_ports_per_client %r after the PUT, want %d"
                 % (config_id, changed.get("maxPortsPerClient"), value))
    print("MB_API_FRPS_CONFIG=%d" % value)
elif action == "docker-assign":
    # By its slug: a user may rename a standard template.
    found = [t for t in json.loads(call("GET", "/api/monitoring/templates", token))
             if t.get("builtinSlug") == "docker-host"]
    if len(found) != 1:
        sys.exit("%d standard templates docker-host, want 1" % len(found))
    server = json.loads(call("GET", "/api/servers/" + server_id, token))
    body = {"server_id": server_id, "hostname": server["hostname"], "server_name": server["name"]}
    created = json.loads(call("POST", "/api/monitoring/templates/%s/assign" % found[0]["id"], token, body))
    if not created.get("checksCreated"):
        sys.exit("the Docker Host template created no check on server %s" % server_id)
    print("MB_API_TEMPLATE=docker-host")
elif action == "docker-state":
    checks = [c for c in json.loads(call("GET", "/api/monitoring/checks?server_id=" + server_id, token))
              if c.get("checkType") == "docker_health"]
    if len(checks) != 1:
        sys.exit("%d docker_health checks on server %s, want 1" % (len(checks), server_id))
    need = checks[0].get("consecutiveFails")
    state = checks[0].get("state") or {}
    status, fails = state.get("status"), state.get("failCount")
    details = state.get("details") or {}
    rated = {c.get("name"): "%s/%s" % (c.get("category"), c.get("reason") or "-")
             for c in details.get("containers") or []}
    run, ended = rated.get("mb-dock-run"), rated.get("mb-dock-exit")
    counted = isinstance(fails, int) and isinstance(need, int)
    up = details.get("available") is True and details.get("error") is None and run == "ok/-"
    # An ok status alone proves nothing: a first warning or critical of a new check reads ok
    # until consecutive_fails (check_engine.effective_status). The counter tells them apart.
    marker = "DOCKER_STATE_OTHER"
    if up and ended is None and status == "ok" and fails == 0:
        marker = "DOCKER_OK"
    elif up and ended == "critical/exit:1" and counted and status == "ok" and 0 < fails < need:
        marker = "DOCKER_EXIT_DAMPED"
    elif up and ended == "critical/exit:1" and counted and status == "critical" and fails >= need:
        marker = "DOCKER_EXIT_CRIT"
    elif details.get("available") is False and details.get("error") == "daemon_unreachable" \
            and status == "warning":
        marker = "DOCKER_UNAVAIL_WARN"
    print("MB_DOCKER_STATE=" + marker)
    print("MB_DOCKER_SEEN=status:%s,fails:%s/%s,available:%s,error:%s,mb-dock-run:%s,mb-dock-exit:%s"
          % (status, fails, need, details.get("available"), details.get("error"), run or "-", ended or "-"))
else:
    sys.exit("unknown action " + action)
PY
}
srv_api() {
  local action="$1"; shift
  ask "$SRV_VM" 300 "printf %s $(srv_api_py | base64 -w0) | base64 -d | python3 -I - $action $ADMIN_PW $*"
}
# frps_registered <tunnel> — frps logged the STCP registration of this tunnel; frp v0.69.1
# writes "new proxy [<frpc user>.<tunnel>] type [stcp] success" (server/control.go).
frps_registered() {
  local log
  log="$(ask "$SRV_VM" 300 'mb-dc logs --no-color frps 2>/dev/null | grep -F "new proxy ["' 2>/dev/null)"
  grep -qE "new proxy \[[^]]*\.$1\] type \[stcp\] success" <<<"$log"
}

# frps_restart <tunnel…> — R-0411, once the visitor got through: a change of the FRP config over
# the API. The supervisor in the frps container takes it over and restarts frps exactly once;
# the agent's frpc logs in again by itself, so frps registers each tunnel anew; and a new
# visitor connection goes through the first. box_serverbox.sh watches frps on the server box,
# every wait there bounded and ending in a verdict.
frps_restart() {
  local out mark api verdict seen back hold check
  echo "== tunnel (R-0411): a config change restarts frps once, the agent and a visitor come back =="
  out="$(ask "$SRV_VM" 300 bash scripts/tests/box_serverbox.sh frps-mark 2>&1)"
  mark="$(vm_marker MB_FRPS_MARK "$out")"
  if [ -z "$mark" ]; then
    echo "$out" | tail -5; bad "frps: no supervisor mark before the config change (see output above)"
    skipped "the frps restart for a config change (no mark) — R-0411 is unverified"; return
  fi
  api="$(srv_api frps-config "$TUN_CFG" "$FRPS_MAX_PORTS" 2>&1)"
  if [ "$(vm_marker MB_API_FRPS_CONFIG "$api")" != "$FRPS_MAX_PORTS" ]; then
    echo "$api" | tail -5; bad "could not set max_ports_per_client of the FRP config over the API (see output above)"
    skipped "the frps restart for a config change (the config did not change) — R-0411 is unverified"; return
  fi
  ok "max_ports_per_client of the FRP config set to $FRPS_MAX_PORTS over the API"
  out="$(ask "$SRV_VM" 900 bash scripts/tests/box_serverbox.sh frps-restart "$mark" "$@" 2>&1)"
  echo "$out" | tail -25
  verdict="$(vm_marker MB_FRPS_RESTART "$out")"; seen="$(vm_marker MB_FRPS_SEEN "$out")"
  [ "$verdict" = OK ] \
    && ok "frps restarted exactly once for the change: one event, applied, one start and no exit in its log, a new frps process ($seen)" \
    || bad "frps did not restart exactly once for the change: ${verdict:-no marker} (${seen:-nothing seen})"
  back="$(vm_marker MB_FRPS_TUNNELS "$out")"
  if [ "$back" != OK ]; then
    bad "the agent's frpc did not log in again after the restart: ${back:-no marker} (see output above)"
    skipped "a new visitor connection after the restart (the agent's tunnels are not back) — R-0411 is unverified"
    return
  fi
  ok "the agent's frpc logged in again by itself: frps registered $* anew after the restart"
  out="$(ask "$V_VM" 300 bash scripts/tests/box_visitorbox.sh hold "${T_USER:-none}" 2>&1)"
  echo "$out" | tail -20
  hold="$(grep -oE 'VIS_SESSION_[A-Z_]+' <<<"$out" | head -1)"
  if [ "$hold" != VIS_SESSION_OPEN ]; then
    bad "no new visitor connection through $1 after the restart: ${hold:-no marker} (see output above)"; return
  fi
  ok "a new visitor connection after the restart: an SSH session through $1 carries data"
  out="$(ask "$V_VM" 300 bash scripts/tests/box_visitorbox.sh check 2>&1)"
  echo "$out" | tail -10
  check="$(grep -oE 'VIS_SESSION_[A-Z_]+' <<<"$out" | head -1)"
  [ "$check" = VIS_SESSION_SURVIVED ] \
    && ok "the new SSH session through $1 still carries data seconds later" \
    || bad "the new SSH session through $1 broke off: ${check:-no marker}"
}

if [ "$TUNNEL" = 1 ]; then
  echo "== tunnel (S4): agent frpc STCP server over the hop to frps on $SRV_IP =="
  printf '%s' "$SRVOUT" | grep -q 'MB_FRPS_UP=1' && ok "frps up on the server box, run by its supervisor from the seeded config" \
    || bad "frps did not start on the server"
  LATE_TUNNEL=mb-ssh-late; RELOAD_TUNNEL=mb-ssh-reload
  # The seeded config leaves max_ports_per_client unset, which frps.toml writes as 16: any other
  # value above 0 changes frps.toml (0 means the default as well).
  FRPS_MAX_PORTS=32
  if [ -n "$TUN_SID" ] && [ -n "$TUN_PTOK" ] && [ -n "$TUN_CFG" ] && read -r T_VM T_IP < <(lease tunnel linux-server); then
    ok "tunnel-agent-box $T_VM @ $T_IP"
    # frpedge runs without IP masquerading: frps reaches no host beyond the server box, while
    # the server container does reach this box's sshd (box_serverbox.sh frps-egress).
    EOUT="$(ask "$SRV_VM" 300 bash scripts/tests/box_serverbox.sh frps-egress "$T_IP" 22 2>&1)"
    EGRESS="$(vm_marker MB_FRPS_EGRESS "$EOUT")"
    [ "$EGRESS" = frps:blocked,server:open ] \
      && ok "frps reaches no second host from frpedge, the server container does ($T_IP:22)" \
      || { echo "$EOUT" | tail -5; bad "frps egress to $T_IP:22: ${EGRESS:-no marker} (want frps:blocked,server:open)"; }
    # R-0398, goal 2: the host is provisioned BEFORE its tunnel exists, and its own agent
    # run has to set frpc up for the tunnel created afterwards. box_serverbox.sh seeds a
    # tunnel with the host, so that one goes first.
    API="$(srv_api clear "$TUN_SID" 2>&1)"
    [ -n "$(vm_marker MB_API_CLEARED "$API")" ] \
      && ok "the seeded tunnel is deleted over the API before the host is provisioned" \
      || { echo "$API" | tail -5; bad "could not delete the seeded tunnel over the API (see output above)"; }
    TOUT="$(box "$T_VM" 3000 bash scripts/tests/box_tunnelbox.sh "$SRV_IP" "$TUN_SID" "$TUN_PTOK" 2>&1)"
    echo "$TOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -40
    grep -q TUNNEL_BEFORE_OK <<<"$TOUT" \
      && ok "tunnel agent: provisioned before its tunnel existed (sync config written, no frpc)" \
      || bad "tunnel agent: provisioning without a tunnel (TUNNEL_BEFORE_OK missing, see output above)"
    API="$(srv_api add "$TUN_SID" "$TUN_CFG" "$LATE_TUNNEL" 2>&1)"
    LATE_VIS_B64=""
    if [ "$(vm_marker MB_API_TUNNEL "$API")" = "$LATE_TUNNEL" ]; then
      ok "tunnel $LATE_TUNNEL created over the API after the provisioning"
      LATE_VIS_B64="$(vm_marker MB_VISITOR_B64 "$API")"
    else
      echo "$API" | tail -5; bad "could not create tunnel $LATE_TUNNEL over the API (see output above)"
    fi
    LOUT="$(ask "$T_VM" 600 bash scripts/tests/box_tunnelbox.sh late "$LATE_TUNNEL" 2>&1)"
    echo "$LOUT" | tail -40
    grep -q TUNNEL_FRPC_CONNECTED <<<"$LOUT" \
      && ok "tunnel agent: frpc STCP server connected to the remote frps" \
      || bad "tunnel agent: frpc did not connect (see output above)"
    LATE_MARK="$(grep -oE 'TUNNEL_LATE_[A-Z_]+' <<<"$LOUT" | head -1)"
    [ "$LATE_MARK" = TUNNEL_LATE_OK ] \
      && ok "tunnel agent: one agent run set frpc up for the later tunnel (active, enabled)" \
      || bad "tunnel agent: the agent run did not take the later tunnel: ${LATE_MARK:-no marker} (see output above)"
    # The agent's own sync over the route bound to its server, with its certificate:
    # under --enforce nothing else gets through the gateway (R-0315).
    SYNC_MARK="$(printf '%s' "$LOUT" | grep -oE 'TUNNEL_SYNC_[A-Z_]+' | head -1)"
    SYNC_CERT=""; [ "$ENFORCE" = 1 ] && SYNC_CERT=", with its certificate (enforced)"
    [ "$SYNC_MARK" = TUNNEL_SYNC_HASH_OK ] \
      && ok "tunnel agent: frpc sync got config-hash over its server's route, the hash its run applied$SYNC_CERT" \
      || bad "tunnel agent: frpc sync over its server's route: ${SYNC_MARK:-no marker} (see output above)"
    # Independent check on the server: frps logged the STCP registration cross-host.
    frps_registered "$LATE_TUNNEL" \
      && ok "frps registered the agent's STCP tunnel $LATE_TUNNEL (cross-host)" \
      || bad "frps shows no STCP registration of $LATE_TUNNEL from the agent"
    # Phase 2: a visitor on a THIRD box completes the data path (visitor -> frps ->
    # agent frpc -> the agent's sshd), proving the full cross-host tunnel. Its visitor.toml
    # is the one from after the late tunnel: the seeded one names the deleted tunnel.
    if [ -n "$VIS_SID" ] && [ -n "$LATE_VIS_B64" ] && read -r V_VM V_IP < <(lease visitor linux-server); then
      ok "visitor-box $V_VM @ $V_IP"
      VOUT="$(box "$V_VM" 3000 bash scripts/tests/box_visitorbox.sh "$SRV_IP" "$VIS_SID" "$VIS_PTOK" "$LATE_VIS_B64" 2>&1)"
      echo "$VOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -40
      printf '%s' "$VOUT" | grep -q VIS_TUNNEL_SSH_OK \
        && ok "visitor reached the agent's sshd THROUGH the tunnel (3-host data path)" \
        || bad "visitor could not reach the agent's sshd through the tunnel"
      # R-0398, goal 3: a second tunnel comes by a reload of frpc, and the tunnels it leaves
      # unchanged keep their connections. The visitor holds an SSH session over the first
      # meanwhile; a restart of frpc would end it.
      VIS_PUB="$(vm_marker VIS_SSH_PUB_B64 "$VOUT")"
      MOUT="$(ask "$T_VM" 300 bash scripts/tests/box_tunnelbox.sh mark "${VIS_PUB:-none}" 2>&1)"
      echo "$MOUT" | tail -10
      T_USER="$(vm_marker TUNNEL_SSH_USER "$MOUT")"
      HOUT="$(ask "$V_VM" 300 bash scripts/tests/box_visitorbox.sh hold "${T_USER:-none}" 2>&1)"
      echo "$HOUT" | tail -20
      HOLD_MARK="$(grep -oE 'VIS_SESSION_[A-Z_]+' <<<"$HOUT" | head -1)"
      [ "$HOLD_MARK" = VIS_SESSION_OPEN ] \
        && ok "visitor holds an SSH session open through $LATE_TUNNEL" \
        || bad "visitor could not open an SSH session through $LATE_TUNNEL: ${HOLD_MARK:-no marker} (see output above)"
      API="$(srv_api add "$TUN_SID" "$TUN_CFG" "$RELOAD_TUNNEL" 2>&1)"
      [ "$(vm_marker MB_API_TUNNEL "$API")" = "$RELOAD_TUNNEL" ] \
        && ok "second tunnel $RELOAD_TUNNEL created over the API" \
        || { echo "$API" | tail -5; bad "could not create tunnel $RELOAD_TUNNEL over the API (see output above)"; }
      RLOUT="$(ask "$T_VM" 600 bash scripts/tests/box_tunnelbox.sh reload "$RELOAD_TUNNEL" 2>&1)"
      echo "$RLOUT" | tail -40
      RELOAD_MARK="$(grep -oE 'TUNNEL_RELOAD_[A-Z_]+' <<<"$RLOUT" | head -1)"
      [ "$RELOAD_MARK" = TUNNEL_RELOAD_OK ] \
        && ok "tunnel agent: frpc took $RELOAD_TUNNEL by a reload, no restart (same frpc PID, agent log)" \
        || bad "tunnel agent: $RELOAD_TUNNEL without a clean reload: ${RELOAD_MARK:-no marker} (see output above)"
      frps_registered "$RELOAD_TUNNEL" \
        && ok "frps registered the second tunnel $RELOAD_TUNNEL" \
        || bad "frps shows no STCP registration of $RELOAD_TUNNEL from the agent"
      if [ "$HOLD_MARK" = VIS_SESSION_OPEN ]; then
        COUT="$(ask "$V_VM" 300 bash scripts/tests/box_visitorbox.sh check 2>&1)"
        echo "$COUT" | tail -10
        CHECK_MARK="$(grep -oE 'VIS_SESSION_[A-Z_]+' <<<"$COUT" | head -1)"
        [ "$CHECK_MARK" = VIS_SESSION_SURVIVED ] \
          && ok "the visitor's SSH session through $LATE_TUNNEL lived through the reload" \
          || bad "the visitor's SSH session through $LATE_TUNNEL did not live through the reload: ${CHECK_MARK:-no marker}"
      else
        # On top of the FAIL above, not instead of it: without a session goal 3 is unverified.
        skipped "the SSH session through the reload (none was open) — goal 3 of R-0398 is unverified"
      fi
      # After R-0398, whose check stops the visitor's frpc: the visitor after the restart is a
      # new frpc and a new SSH session.
      if grep -q VIS_TUNNEL_SSH_OK <<<"$VOUT"; then
        frps_restart "$LATE_TUNNEL" "$RELOAD_TUNNEL"
      else
        skipped "the frps restart for a config change (the visitor never got through before it) — R-0411 is unverified"
      fi
    else bad "visitor lease or missing visitor config"; fi
  else bad "tunnel-agent lease or missing tunnel seed"; fi
fi

# docker_step <step> <what> — one step of box_agentbox.sh docker on the agent box: it changes
# Docker as the step says, then one agent run pushes the report. The start step names the
# engine and the image, which the verdict carries.
docker_step() {
  local out verdict engine image what="$2"
  out="$(ask "$DOCK_VM" 900 bash scripts/tests/box_agentbox.sh docker "$1" 2>&1)"
  echo "$out" | tail -15
  verdict="$(vm_marker AGENT_DOCKER_STEP "$out")"
  engine="$(vm_marker AGENT_DOCKER_ENGINE "$out")"; image="$(vm_marker AGENT_DOCKER_IMAGE "$out")"
  [ -n "$engine" ] && what="$what (Docker $engine, image ${image:-none})"
  [ "$verdict" = OK ] && ok "docker agent box: $what" || bad "docker agent box: $what: ${verdict:-no marker} (see output above)"
}
# docker_state <marker> <what> — the Docker Health check of host $SID, read on the server box
# after the push of the step before.
docker_state() {
  local out mark seen
  out="$(srv_api docker-state "$SID" 2>&1)"
  mark="$(vm_marker MB_DOCKER_STATE "$out")"; seen="$(vm_marker MB_DOCKER_SEEN "$out")"
  if [ "$mark" = "$1" ]; then
    ok "$2 ($1; $seen)"
  else
    echo "$out" | tail -5; bad "$2: ${mark:-no marker} (expected $1; ${seen:-nothing seen})"
  fi
}

if [ "$DOCKER" = 1 ]; then
  echo "== docker (R-0419): real Docker on the agent box, the Docker Host template, three states =="
  if [ -n "$DOCK_VM" ]; then
    API="$(srv_api docker-assign "$SID" 2>&1)"
    if [ "$(vm_marker MB_API_TEMPLATE "$API")" = docker-host ]; then
      ok "the Docker Host template is assigned to the host of agent $DOCK_VM over the API"
      docker_step start "the agent timer is stopped, a container keeps running, one agent run"
      docker_state DOCKER_OK "docker: a running container -> ok"
      # consecutive_fails 2 (Docker Host, builtin_templates.py): the first critical result
      # keeps the status ok and counts 1 of 2, the second turns it critical. The stopped
      # daemon continues that count, so its warning stands after one run.
      docker_step exit "a second container ended with exit 1, no restart policy, one agent run"
      docker_state DOCKER_EXIT_DAMPED "docker: the first report of the exit 1 -> critical exit:1 in the details, the status damped"
      docker_step rerun "one more agent run"
      docker_state DOCKER_EXIT_CRIT "docker: the second report -> critical, reason exit:1"
      docker_step down "Docker daemon and socket stopped, one agent run"
      docker_state DOCKER_UNAVAIL_WARN "docker: the stopped daemon -> warning, error daemon_unreachable"
    else
      echo "$API" | tail -5; bad "could not assign the Docker Host template over the API (see output above)"
      skipped "the three Docker states (no Docker Host check) — ok, exit 1 and the stopped daemon are unverified"
    fi
  else
    skipped "the Docker stage (no provisioned agent box) — ok, exit 1 and the stopped daemon are unverified"
  fi
fi

if [ "$DESKTOP" = 1 ]; then
  # AH_DESKTOP_VM reuses an already-warm desktop box (skip clone + re-bootstrap).
  if [ -n "$DESKTOP_VM" ]; then
    DT_VM="$DESKTOP_VM"; ok "desktop-box $DT_VM (reused via AH_DESKTOP_VM)"
  elif read -r DT_VM DT_IP < <(lease desktop linux-full); then
    ok "desktop-box $DT_VM @ $DT_IP"
  else DT_VM=""; bad "desktop lease"; fi
  if [ -n "$DT_VM" ]; then
    # With --enforce the data plane is cert-gated, so the GUI has to enroll a device
    # identity before it can log in. Two constraints shape this:
    #   - one token per SPEC, not per run: every spec is its own `wdio run` in its
    #     own dbus session with an empty keyring, so each starts un-enrolled; and
    #     an enrollment token is one-time.
    #   - minted HERE, not on the server box hours ago: the default TTL is 60 min
    #     and this stage starts after the agent, rpm, tunnel and visitor boxes.
    # Kept in sync with the default in box_desktopbox.sh — named here because
    # the number of tokens to mint depends on it.
    DESK_SPECS="server-crud.live.js monitoring-check.live.js"
    DESK_ETOKS=""
    if [ "$ENFORCE" = 1 ]; then
      # ONE run for all tokens, not one per spec: the first capstone lost one of
      # two that way, with no diagnosis left because the output had been thrown
      # at /dev/null.
      # --ttl-minutes 240, not the 60-minute default: the last token is redeemed
      # after the box bootstrap, the ~20 min Tauri build and every earlier spec.
      # The stage's own deckel is the 3000 s below — the TTL has to outlive it
      # with room, or raising that timeout breaks this silently.
      MINTLOG="${AH_OUT_DIR:-$VM_ROOT/.ah-out}/mint-desktop-tokens.log"
      mkdir -p "$(dirname "$MINTLOG")" 2>/dev/null
      n_want=0; for _ in $DESK_SPECS; do n_want=$((n_want + 1)); done
      ask "$SRV_VM" 600 \
        "for i in \$(seq 1 $n_want); do mb-dc exec -T server python -m app.cli mint-enroll-token --username admin --ttl-minutes 240; done" \
        >"$MINTLOG" 2>&1
      # Anchored: the CLI prints each token on a line of its own, so ^…$ cannot
      # pick up a long word from the wrapper's own output.
      DESK_ETOKS="$(tr -d '\r' < "$MINTLOG" | grep -oE '^[A-Za-z0-9_-]{20,}$' | tail -n "$n_want" | paste -sd' ' -)"
      [ -n "$DESK_ETOKS" ] || echo "  (mint failed — see $MINTLOG)"
    fi
    # The values are hex/IPv4/token_urlsafe today, none can contain a quote.
    n_tok=0; for _ in $DESK_ETOKS; do n_tok=$((n_tok + 1)); done
    n_spec=0; for _ in $DESK_SPECS; do n_spec=$((n_spec + 1)); done
    if [ "$ENFORCE" = 1 ] && [ "$n_tok" -lt "$n_spec" ]; then
      # Skip the stage rather than spend up to 50 minutes of VM time on a run that
      # cannot pass: without a token per spec the enforced gateway rejects the login.
      bad "desktop: only $n_tok of $n_spec enrollment tokens minted (see ${MINTLOG:-the mint log})"
      skipped "desktop GUI journeys (not enough enrollment tokens under --enforce) — the S3 scenario is unverified"
      DTOUT=""
    else
      echo "== drive the real Tauri GUI on $DT_VM against https://$SRV_IP =="
      DTOUT="$(box "$DT_VM" 3000 \
        "AH_DESKTOP_ENROLL_TOKENS='$DESK_ETOKS' bash scripts/tests/box_desktopbox.sh '$SRV_IP' '$ADMIN_PW' '$MONITOR_KEY' $DESK_SPECS" 2>&1)"
      echo "$DTOUT" | grep -vE 'Compiling|Downloaded |npm warn|go: downloading' | tail -40
      printf '%s' "$DTOUT" | grep -q DESKTOP_ALL_OK \
        && ok "desktop GUI journeys green against the remote server (login/CRUD/monitoring)" \
        || bad "desktop GUI journeys (see output above)"
    fi
  else
    # On top of the lease FAIL above, not instead of it: the two facts differ —
    # the box could not be had, AND the S3 journeys are therefore unverified.
    # Only the second one is what a reader of "N skipped" is looking for.
    skipped "desktop GUI journeys (no desktop box) — the S3 scenario is unverified"
  fi
fi

if [ "$MONCHECK" = 1 ]; then
  echo "== moncheck (S5): pull-check verdicts + closed-loop alert delivery =="
  [ "$MC_CRIT_STATUS" = critical ] && ok "ping check to an unreachable target -> critical" || bad "unreachable ping check status=${MC_CRIT_STATUS:-?} (expected critical)"
  [ "$MC_OK_STATUS" = ok ] && ok "ping check to the reachable client -> ok" || bad "reachable ping check status=${MC_OK_STATUS:-?} (expected ok)"
  if [ -n "$MC_VM" ]; then
    MCA="$(ask "$MC_VM" 300 bash scripts/tests/box_moncheckbox.sh assert 2>&1)"
    printf '%s' "$MCA" | grep -E 'MC_MAIL_COUNT|MC_ALERT' | sed 's/^/  /'
    printf '%s' "$MCA" | grep -q MC_ALERT_RECEIVED \
      && ok "critical alert email delivered to the mailhog sink over the network (closed loop)" \
      || bad "no alert email reached the sink"
  else
    skipped "closed-loop alert delivery (no moncheck box) — S5 mail delivery is unverified"
  fi
fi

echo "== assert monitoring ingested a report from the remote agent(s) =="
REPORTS="$(ask "$SRV_VM" 300 'mb-dc logs monitoring 2>/dev/null | grep -cE "POST /agent/[^/]+/report HTTP"' 2>/dev/null | grep -oE '^[0-9]+$' | tail -1)"
EXPECT=$(( ${#AGENT_VMS[@]} + RPM_AGENTS ))
if [ $(( AGENTS + RPM )) -ge 1 ]; then
  # Floor of 1 (R-0021): every agent lease failing left EXPECT=0, and "0 >= 0"
  # passed a run in which no agent ever reported. Keyed on the agents ASKED FOR,
  # not on the ones that arrived — `--agents 0 --desktop` (server + GUI, no .deb)
  # is a real partial run and must not fail for a hop it never requested.
  [ "$EXPECT" -lt 1 ] && EXPECT=1
  [ -n "${REPORTS:-}" ] && [ "$REPORTS" -ge "$EXPECT" ] 2>/dev/null \
    && ok "monitoring ingested $REPORTS report(s) from remote agent(s)" \
    || bad "monitoring saw ${REPORTS:-0} reports (expected >= $EXPECT)"
else
  skipped "monitoring ingest (no agent role requested) — the report hop is unverified"
fi

echo ""
echo "──────────────────────────────────────────────"
echo "  multibox: $PASS ok, $FAIL failed, $SKIPPED skipped  (server=$SRV_IP, agents=${AGENT_VMS[*]:-none})"
# Beside the verdict, not in it: heavy.sh quotes only the line above.
echo "  go version (agent .deb, server box): ${AGENT_GO:-unknown (no MB_AGENT_GO marker)}"
[ "${MB_DEBIAN9_SKIPPED:-0}" = 1 ] && echo "  MB_DEBIAN9_SKIPPED=1"
[ "$FAIL" -gt 0 ] && exit 1 || exit 0
