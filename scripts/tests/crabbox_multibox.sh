#!/usr/bin/env bash
#
# crabbox_multibox.sh — distributed, multi-host AdminHelper E2E on crabbox (scenario S1+).
#
# Leases a SERVER box + N AGENT boxes on the same Proxmox bridge (vmbr1) and wires a
# real cross-host topology the single-host scripts/tests/*.sh cannot reach:
#   server-box  = full docker-compose stack (gateway 443/8444/8445, frps 7000/7443)
#   agent-box(s)= real .deb install + `adminhelper-agent provision` over a network hop
# Then asserts each agent enrolled an mTLS identity and pushed a monitoring report.
#
#   bash scripts/tests/crabbox_multibox.sh [--agents N] [--rpm] [--tunnel]
#       [--desktop] [--moncheck] [--capstone] [--keep]
#   --rpm      + a cross-distro rpm agent (rockylinux)      (S2)
#   --tunnel   + frps + agent frpc STCP server + a visitor  (S4, 3-host tunnel)
#   --desktop  + the real Tauri GUI vs the remote server     (S3)
#   --moncheck + pull ping-checks + a closed-loop email alert (S5)
#   --capstone = --agents 1 --rpm --tunnel --desktop --moncheck (S6: all in one run)
#
# Validates over the single-host suites: cross-host mTLS with SAN=<server IP> (not
# localhost), real package install + systemd, and the monitoring pipeline over a real
# hop. Box-side logic lives in crabbox_serverbox.sh / crabbox_agentbox.sh.
#
# NOTE: first run is a live shake-out — IP-SAN issuance (DOMAIN=<IP>), east-west
# reachability on vmbr1, gateway port publishing and the build-deb path are confirmed
# by an actual 2-box run; failures here are findings to iterate, not silent skips.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1
# shellcheck source=scripts/tests/crabbox_lib.sh
. "$(dirname "$0")/crabbox_lib.sh"

AGENTS=1; KEEP=0; DESKTOP=0; RPM=0; TUNNEL=0; MONCHECK=0; ENFORCE=0
while [ $# -gt 0 ]; do case "$1" in
  --agents) AGENTS="${2:?}"; shift ;; --keep) KEEP=1 ;; --desktop) DESKTOP=1 ;; --rpm) RPM=1 ;;
  --tunnel) TUNNEL=1 ;; --moncheck) MONCHECK=1 ;; --enforce) ENFORCE=1 ;;  # D2: MTLS_ENFORCE=true
  --capstone) AGENTS=1; RPM=1; TUNNEL=1; DESKTOP=1; MONCHECK=1 ;;  # S6: everything, one run
  *) echo "unknown arg: $1"; exit 2 ;; esac; shift; done

# Proxmox provider env via the shared lib (secret in gitignored settings.local.json).
command -v crabbox >/dev/null || { echo "crabbox not installed"; exit 1; }
cbx_load_env || exit 1

POND="ah-mb-$$"
LEASES=(); PASS=0; FAIL=0; RPM_AGENTS=0
ok(){ echo "  ok   $*"; PASS=$((PASS+1)); }; bad(){ echo "  FAIL $*"; FAIL=$((FAIL+1)); }
cleanup() {
  [ "$KEEP" = 1 ] && { echo "--keep: leaving pond $POND up (bounded by --ttl)"; return; }
  echo "== teardown pond $POND =="
  for l in "${LEASES[@]:-}"; do [ -n "$l" ] && crabbox stop --id "$l" >/dev/null 2>&1 || true; done
  # sweep anything in the pond the array missed (partial-failure boxes)
  crabbox list --pond "$POND" 2>/dev/null | grep -oE 'cbx_[a-z0-9]+' | while read -r id; do
    crabbox stop --id "$id" >/dev/null 2>&1 || true; done
}
trap cleanup EXIT INT TERM

# lease <role-slug> -> echoes "<slug> <ip>"; records the lease id for cleanup FIRST.
# Blocks until the box is SSH-ready and resolves the IP authoritatively (not from
# the warmup line, which can be stale) — the first live run showed warmup returning
# before SSH-auth was up and a stale duplicate IP.
lease() {
  local out id slug ip
  # Every crabbox call is timeout-bounded so a stuck lease can NEVER hang the run
  # (the -ttl backstop + trap cleanup still bound cost even if a timeout fires).
  out="$(timeout 420 crabbox warmup -slug "$1" -pond "$POND" -proxmox-bridge vmbr1 -ttl 90m -idle-timeout 30m 2>&1)" \
    || { echo "warmup failed/timed out: $out" >&2; return 1; }
  id="$(printf '%s' "$out" | grep -oE 'cbx_[a-z0-9]+' | head -1)"
  [ -n "$id" ] && LEASES+=("$id")                        # record BEFORE anything else (avoid leaks)
  slug="$(printf '%s' "$out" | grep -oE 'slug=[a-z0-9-]+' | head -1 | cut -d= -f2)"
  [ -n "$slug" ] || { echo "no slug parsed from warmup" >&2; return 1; }
  timeout 300 crabbox status --id "$slug" --wait >/dev/null 2>&1 || true   # bounded wait-for-ready
  # authoritative IP from the ssh target, falling back to the warmup line
  ip="$(crabbox ssh --id "$slug" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
  [ -n "$ip" ] || ip="$(printf '%s' "$out" | grep -oE 'ip=[0-9.]+' | head -1 | cut -d= -f2)"
  [ -n "$ip" ] || { echo "could not resolve ip for $slug" >&2; return 1; }
  echo "$slug $ip"
}

echo "== lease 1 server + $AGENTS agent box(es) on vmbr1 (pond $POND) =="
read -r SRV_SLUG SRV_IP < <(lease ah-srv) || { bad "server lease"; exit 1; }
ok "server-box $SRV_SLUG @ $SRV_IP"
AGENT_SLUGS=()
for i in $(seq 1 "$AGENTS"); do
  if read -r a_slug a_ip < <(lease "ah-agent$i"); then
    AGENT_SLUGS+=("$a_slug"); ok "agent-box$i $a_slug @ $a_ip"
    [ "$a_ip" = "$SRV_IP" ] && bad "agent$i IP $a_ip collides with server — proxmox capacity/DHCP? (need distinct concurrent VMs on vmbr1)"
  else bad "agent$i lease"; fi
done

MC_SLUG=""; MC_IP=""
if [ "$MONCHECK" = 1 ]; then
  echo "== moncheck (S5): lease the client/sink box + start mailhog (before the seed) =="
  if read -r MC_SLUG MC_IP < <(lease ah-moncheck); then
    ok "moncheck-box $MC_SLUG @ $MC_IP"
    MCSTART="$(timeout 1500 crabbox run --id "$MC_SLUG" -- bash scripts/tests/crabbox_moncheckbox.sh start 2>&1)"
    echo "$MCSTART" | grep -vE 'Compiling|Downloaded ' | tail -20
    printf '%s' "$MCSTART" | grep -q MC_MAILHOG_UP && ok "mailhog sink up on $MC_IP (:1025/:8025)" || bad "mailhog did not start"
  else bad "moncheck-box lease"; fi
fi

echo "== bring up the server stack on $SRV_SLUG ($SRV_IP) =="
SRVARG=""
[ "$TUNNEL" = 1 ]   && SRVARG="$SRVARG tunnel"
[ "$MONCHECK" = 1 ] && SRVARG="$SRVARG moncheck $MC_IP"
[ "$ENFORCE" = 1 ]  && SRVARG="$SRVARG enforce"
SRVOUT="$(timeout 2700 crabbox run --id "$SRV_SLUG" -- bash scripts/tests/crabbox_serverbox.sh "$SRV_IP" $SRVARG 2>&1)"; echo "$SRVOUT" | grep -vE 'Compiling|Downloaded |Container |Network |Volume |Pulling|Waiting|Pull complete' | tail -40
SID="$(printf '%s' "$SRVOUT" | grep -oE 'MB_SID=[^ ]+' | tail -1 | cut -d= -f2)"
PTOK="$(printf '%s' "$SRVOUT" | grep -oE 'MB_PTOK=[^ ]+' | tail -1 | cut -d= -f2)"
ADMIN_PW="$(printf '%s' "$SRVOUT" | grep -oE 'MB_ADMIN_PW=[^ ]+' | tail -1 | cut -d= -f2)"
MONITOR_KEY="$(printf '%s' "$SRVOUT" | grep -oE 'MB_MONITOR_KEY=[^ ]+' | tail -1 | cut -d= -f2)"
SID2="$(printf '%s' "$SRVOUT" | grep -oE 'MB_SID2=[^ ]+' | tail -1 | cut -d= -f2)"
PTOK2="$(printf '%s' "$SRVOUT" | grep -oE 'MB_PTOK2=[^ ]+' | tail -1 | cut -d= -f2)"
TUN_SID="$(printf '%s' "$SRVOUT" | grep -oE 'MB_TUN_SID=[^ ]+' | tail -1 | cut -d= -f2)"
TUN_PTOK="$(printf '%s' "$SRVOUT" | grep -oE 'MB_TUN_PTOK=[^ ]+' | tail -1 | cut -d= -f2)"
VIS_SID="$(printf '%s' "$SRVOUT" | grep -oE 'MB_VIS_SID=[^ ]+' | tail -1 | cut -d= -f2)"
VIS_PTOK="$(printf '%s' "$SRVOUT" | grep -oE 'MB_VIS_PTOK=[^ ]+' | tail -1 | cut -d= -f2)"
VIS_B64="$(printf '%s' "$SRVOUT" | grep -oE 'MB_VISITOR_B64=[^ ]+' | tail -1 | cut -d= -f2)"
MC_OK_STATUS="$(printf '%s' "$SRVOUT" | grep -oE 'MC_OK_STATUS=[^ ]+' | tail -1 | cut -d= -f2)"
MC_CRIT_STATUS="$(printf '%s' "$SRVOUT" | grep -oE 'MC_CRIT_STATUS=[^ ]+' | tail -1 | cut -d= -f2)"
[ -n "$SID" ] && [ -n "$PTOK" ] && ok "stack up + provision token minted (server $SID)" \
  || { bad "server bring-up / token seed"; exit 1; }
[ "$ENFORCE" = 1 ] && { printf '%s' "$SRVOUT" | grep -q 'MB_ENFORCE_CERTLESS_REJECTED=1' \
  && ok "MTLS_ENFORCE=true: certless :443 rejected (400) — cert-gated data plane over the hop" \
  || bad "enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED)"; }

echo "== provision each agent against https://$SRV_IP =="
for a in "${AGENT_SLUGS[@]:-}"; do
  [ -n "$a" ] || continue
  AOUT="$(timeout 1800 crabbox run --id "$a" -- bash scripts/tests/crabbox_agentbox.sh "$SRV_IP" "$SID" "$PTOK" 2>&1)"; echo "$AOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -50
  printf '%s' "$AOUT" | grep -q AGENT_PROVISION_OK && printf '%s' "$AOUT" | grep -q AGENT_CERT_OK \
    && ok "agent $a: provisioned + mTLS-enrolled over the network hop" \
    || bad "agent $a: provision/enroll (see output above; check IP-SAN + vmbr1 firewall)"
done

if [ "$RPM" = 1 ]; then
  echo "== cross-distro (S2): build the .rpm + provision it in a rockylinux container =="
  if read -r R_SLUG R_IP < <(lease ah-agent-rpm); then
    ok "rpm-agent-box $R_SLUG @ $R_IP"
    ROUT="$(timeout 1800 crabbox run --id "$R_SLUG" -- bash scripts/tests/crabbox_agentbox_rpm.sh "$SRV_IP" "$SID2" "$PTOK2" 2>&1)"
    echo "$ROUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -45
    printf '%s' "$ROUT" | grep -q RPM_ALL_OK \
      && { ok "rpm agent: built + installed + mTLS-enrolled in rockylinux over the hop"; RPM_AGENTS=1; } \
      || bad "rpm agent (see output above)"
  else bad "rpm-agent lease"; fi
fi

if [ "$TUNNEL" = 1 ]; then
  echo "== tunnel (S4): agent frpc STCP server over the hop to frps on $SRV_IP =="
  printf '%s' "$SRVOUT" | grep -q 'MB_FRPS_UP=1' && ok "frps up on the server box" || bad "frps did not start on the server"
  if [ -n "$TUN_SID" ] && [ -n "$TUN_PTOK" ] && read -r T_SLUG T_IP < <(lease ah-tunnel); then
    ok "tunnel-agent-box $T_SLUG @ $T_IP"
    TOUT="$(timeout 1800 crabbox run --id "$T_SLUG" -- bash scripts/tests/crabbox_tunnelbox.sh "$SRV_IP" "$TUN_SID" "$TUN_PTOK" 2>&1)"
    echo "$TOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -40
    printf '%s' "$TOUT" | grep -q TUNNEL_FRPC_CONNECTED \
      && ok "tunnel agent: frpc STCP server connected to the remote frps" \
      || bad "tunnel agent: frpc did not connect (see output above)"
    # Independent check on the server: frps logged the STCP registration cross-host.
    FRPSLOG="$(timeout 300 crabbox run --id "$SRV_SLUG" -- bash -c 'sudo docker compose -f docker-compose.yml -f docker-compose.test.yml -f /tmp/mb-ports.yml logs --no-color frps 2>/dev/null | grep -iE "new proxy|start proxy success|stcp" | tail -5' 2>/dev/null)"
    printf '%s' "$FRPSLOG" | grep -qiE 'new proxy|start proxy success|stcp' \
      && ok "frps registered the agent's STCP tunnel (cross-host)" \
      || bad "frps shows no STCP registration from the agent"
    # Phase 2: a visitor on a THIRD box completes the data path (visitor -> frps ->
    # agent frpc -> the agent's sshd), proving the full cross-host tunnel.
    if [ -n "$VIS_SID" ] && [ -n "$VIS_B64" ] && read -r V_SLUG V_IP < <(lease ah-visitor); then
      ok "visitor-box $V_SLUG @ $V_IP"
      VOUT="$(timeout 1800 crabbox run --id "$V_SLUG" -- bash scripts/tests/crabbox_visitorbox.sh "$SRV_IP" "$VIS_SID" "$VIS_PTOK" "$VIS_B64" 2>&1)"
      echo "$VOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -40
      printf '%s' "$VOUT" | grep -q VIS_TUNNEL_SSH_OK \
        && ok "visitor reached the agent's sshd THROUGH the tunnel (3-host data path)" \
        || bad "visitor could not reach the agent's sshd through the tunnel"
    else bad "visitor lease or missing visitor config"; fi
  else bad "tunnel-agent lease or missing tunnel seed"; fi
fi

if [ "$DESKTOP" = 1 ]; then
  # AH_DESKTOP_ID reuses an already-warm desktop box (skip lease + re-bootstrap).
  if [ -n "${AH_DESKTOP_ID:-}" ]; then
    DT_SLUG="$AH_DESKTOP_ID"; ok "desktop-box $DT_SLUG (reused via AH_DESKTOP_ID)"
  elif read -r DT_SLUG DT_IP < <(lease ah-desktop); then
    ok "desktop-box $DT_SLUG @ $DT_IP"
  else DT_SLUG=""; bad "desktop lease"; fi
  if [ -n "$DT_SLUG" ]; then
    echo "== drive the real Tauri GUI on $DT_SLUG against https://$SRV_IP =="
    DTOUT="$(timeout 3000 crabbox run --id "$DT_SLUG" -- bash scripts/tests/crabbox_desktopbox.sh "$SRV_IP" "$ADMIN_PW" "$MONITOR_KEY" 2>&1)"
    echo "$DTOUT" | grep -vE 'Compiling|Downloaded |npm warn|go: downloading' | tail -40
    printf '%s' "$DTOUT" | grep -q DESKTOP_ALL_OK \
      && ok "desktop GUI journeys green against the remote server (login/CRUD/monitoring)" \
      || bad "desktop GUI journeys (see output above)"
  fi
fi

if [ "$MONCHECK" = 1 ]; then
  echo "== moncheck (S5): pull-check verdicts + closed-loop alert delivery =="
  [ "$MC_CRIT_STATUS" = critical ] && ok "ping check to an unreachable target -> critical" || bad "unreachable ping check status=${MC_CRIT_STATUS:-?} (expected critical)"
  [ "$MC_OK_STATUS" = ok ] && ok "ping check to the reachable client -> ok" || bad "reachable ping check status=${MC_OK_STATUS:-?} (expected ok)"
  if [ -n "$MC_SLUG" ]; then
    MCA="$(timeout 300 crabbox run --id "$MC_SLUG" -- bash scripts/tests/crabbox_moncheckbox.sh assert 2>&1)"
    printf '%s' "$MCA" | grep -E 'MC_MAIL_COUNT|MC_ALERT' | sed 's/^/  /'
    printf '%s' "$MCA" | grep -q MC_ALERT_RECEIVED \
      && ok "critical alert email delivered to the mailhog sink over the network (closed loop)" \
      || bad "no alert email reached the sink"
  fi
fi

echo "== assert monitoring ingested a report from the remote agent(s) =="
REPORTS="$(timeout 300 crabbox run --id "$SRV_SLUG" -- bash -c 'sudo docker compose -f docker-compose.yml -f docker-compose.test.yml -f /tmp/mb-ports.yml logs monitoring 2>/dev/null | grep -cE "POST /agent/[^/]+/report HTTP"' 2>/dev/null | grep -oE '^[0-9]+$' | tail -1)"
EXPECT=$(( ${#AGENT_SLUGS[@]} + RPM_AGENTS ))
[ -n "${REPORTS:-}" ] && [ "$REPORTS" -ge "$EXPECT" ] 2>/dev/null \
  && ok "monitoring ingested $REPORTS report(s) from remote agent(s)" \
  || bad "monitoring saw ${REPORTS:-0} reports (expected >= $EXPECT)"

echo ""
echo "──────────────────────────────────────────────"
echo "  crabbox_multibox: $PASS ok, $FAIL failed  (server=$SRV_IP, agents=${AGENT_SLUGS[*]:-none})"
[ "$FAIL" -gt 0 ] && exit 1 || exit 0
