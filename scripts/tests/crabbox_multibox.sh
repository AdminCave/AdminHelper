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
#   bash scripts/tests/crabbox_multibox.sh [--agents N] [--keep]
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

AGENTS=1; KEEP=0; DESKTOP=0
while [ $# -gt 0 ]; do case "$1" in
  --agents) AGENTS="${2:?}"; shift ;; --keep) KEEP=1 ;; --desktop) DESKTOP=1 ;;
  *) echo "unknown arg: $1"; exit 2 ;; esac; shift; done

# Proxmox provider env (secret in the gitignored settings.local.json).
if [ -z "${CRABBOX_PROVIDER:-}" ]; then
  eval "$(python3 -c '
import json
for f in [".claude/settings.json",".claude/settings.local.json"]:
    try: d=json.load(open(f)).get("env",{})
    except Exception: d={}
    for k,v in d.items():
        if k.startswith("CRABBOX_"): print("export %s=%r"%(k,v))')"
fi
command -v crabbox >/dev/null || { echo "crabbox not installed"; exit 1; }
[ -n "${CRABBOX_PROVIDER:-}" ] || { echo "CRABBOX_PROVIDER unset (proxmox env not loaded)"; exit 1; }

POND="ah-mb-$$"
LEASES=(); PASS=0; FAIL=0
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

echo "== bring up the server stack on $SRV_SLUG ($SRV_IP) =="
SRVOUT="$(timeout 2700 crabbox run --id "$SRV_SLUG" -- bash scripts/tests/crabbox_serverbox.sh "$SRV_IP" 2>&1)"; echo "$SRVOUT" | grep -vE 'Compiling|Downloaded ' | tail -40
SID="$(printf '%s' "$SRVOUT" | grep -oE 'MB_SID=[^ ]+' | tail -1 | cut -d= -f2)"
PTOK="$(printf '%s' "$SRVOUT" | grep -oE 'MB_PTOK=[^ ]+' | tail -1 | cut -d= -f2)"
ADMIN_PW="$(printf '%s' "$SRVOUT" | grep -oE 'MB_ADMIN_PW=[^ ]+' | tail -1 | cut -d= -f2)"
MONITOR_KEY="$(printf '%s' "$SRVOUT" | grep -oE 'MB_MONITOR_KEY=[^ ]+' | tail -1 | cut -d= -f2)"
[ -n "$SID" ] && [ -n "$PTOK" ] && ok "stack up + provision token minted (server $SID)" \
  || { bad "server bring-up / token seed"; exit 1; }

echo "== provision each agent against https://$SRV_IP =="
for a in "${AGENT_SLUGS[@]:-}"; do
  [ -n "$a" ] || continue
  AOUT="$(timeout 1800 crabbox run --id "$a" -- bash scripts/tests/crabbox_agentbox.sh "$SRV_IP" "$SID" "$PTOK" 2>&1)"; echo "$AOUT" | grep -vE 'Compiling|Downloaded |go: downloading' | tail -50
  printf '%s' "$AOUT" | grep -q AGENT_PROVISION_OK && printf '%s' "$AOUT" | grep -q AGENT_CERT_OK \
    && ok "agent $a: provisioned + mTLS-enrolled over the network hop" \
    || bad "agent $a: provision/enroll (see output above; check IP-SAN + vmbr1 firewall)"
done

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

echo "== assert monitoring ingested a report from the remote agent(s) =="
REPORTS="$(timeout 300 crabbox run --id "$SRV_SLUG" -- bash -c 'sudo docker compose -f docker-compose.yml -f docker-compose.test.yml -f /tmp/mb-ports.yml logs monitoring 2>/dev/null | grep -cE "POST /agent/[^/]+/report HTTP"' 2>/dev/null | grep -oE '^[0-9]+$' | tail -1)"
[ -n "${REPORTS:-}" ] && [ "$REPORTS" -ge "${#AGENT_SLUGS[@]}" ] 2>/dev/null \
  && ok "monitoring ingested $REPORTS report(s) from remote agent(s)" \
  || bad "monitoring saw ${REPORTS:-0} reports (expected >= ${#AGENT_SLUGS[@]})"

echo ""
echo "──────────────────────────────────────────────"
echo "  crabbox_multibox: $PASS ok, $FAIL failed  (server=$SRV_IP, agents=${AGENT_SLUGS[*]:-none})"
[ "$FAIL" -gt 0 ] && exit 1 || exit 0
