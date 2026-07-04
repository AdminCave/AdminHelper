#!/usr/bin/env bash
#
# crabbox_serverbox.sh — runs ON the crabbox server-box. Brings up the full stack
# reachable at https://<SRV_IP> on the production ports (443/8444/8445 + frps
# 7000/7443), seeds an admin, a server record and a provision token, and prints
#   MB_SID=<server-uuid> MB_PTOK=<provision-token>
# on stdout for the orchestrator to hand to the agent box.
#
# Called by scripts/tests/crabbox_multibox.sh via `crabbox run`.
set -uo pipefail
SRV_IP="${1:?usage: crabbox_serverbox.sh <server-ip> [tunnel] [moncheck <SMTP_IP>]}"; shift || true
# Independent, composable modes (so the S6 capstone can do BOTH at once):
#   tunnel            S4: seed an STCP tunnel + bring up frps
#   moncheck <IP>     S5: seed ping checks + an email alert to the mailhog sink <IP>
DO_TUNNEL=0; DO_MONCHECK=0; DO_ENFORCE=0; SMTP_IP=""
while [ $# -gt 0 ]; do case "$1" in
  tunnel)   DO_TUNNEL=1 ;;
  moncheck) DO_MONCHECK=1; SMTP_IP="${2:-}"; shift ;;
  enforce)  DO_ENFORCE=1 ;;   # S5-hardening (D2): MTLS_ENFORCE=true + cert-based seed
  *) ;; esac; shift; done
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1

echo "[serverbox] hydrate (server profile: docker stack, no Tauri)"
AH_BOOTSTRAP_PROFILE=server bash scripts/tests/crabbox_bootstrap.sh || { echo "[serverbox] bootstrap failed"; exit 1; }

echo "[serverbox] .env: DOMAIN=$SRV_IP (IP-SAN gateway+frps leaf), MTLS_ENFORCE=false, admin pw"
[ -f .env ] || cp .env.example .env
bash scripts/init-secrets.sh || true
ADMIN_PW="$(openssl rand -hex 16)"
upsert() { if grep -qE "^#?[[:space:]]*$1=" .env; then sed -i -E "s|^#?[[:space:]]*$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi; }
# DOMAIN must be set BEFORE first `up` — the ca-issuer mints the gateway leaf SAN once.
upsert DOMAIN "$SRV_IP"
upsert EXTRA_SANS "$SRV_IP"
upsert FRP_SERVER_ADDR "$SRV_IP"
upsert MTLS_ENFORCE "$([ "$DO_ENFORCE" = 1 ] && echo true || echo false)"
upsert ADMIN_PASSWORD "$ADMIN_PW"

# The test overlay supplies build: contexts but drops the :8445 plane and moves
# :443 to a high port — restore the production gateway ports on top.
cat > /tmp/mb-ports.yml <<'YML'
services:
  gateway:
    ports: !override
      - "443:443"
      - "8444:8444"
      - "8445:8445"
YML

DC=(sudo docker compose -f docker-compose.yml -f docker-compose.test.yml -f /tmp/mb-ports.yml)
echo "[serverbox] build + up (images from checkout, production ports)"
# Start ONLY the services S1 needs (+their deps auto-start). Excludes `scheduler`
# and `frps`, whose image: is the ghcr.io/admincave/* tag the test overlay does NOT
# rebuild — starting them would try to PULL a not-yet-published image (unauthorized).
"${DC[@]}" up -d --build gateway server ca-issuer monitoring \
  || { echo "[serverbox] compose up failed"; "${DC[@]}" ps; exit 1; }

echo "[serverbox] wait for the gateway data plane on :443"
up=0; for _ in $(seq 1 60); do curl -sk "https://localhost/" >/dev/null 2>&1 && { up=1; break; }; sleep 3; done
[ "$up" = 1 ] || { echo "[serverbox] gateway never came up"; "${DC[@]}" logs --tail 30 gateway ca-issuer server; exit 1; }

# Enforce mode (D2): the data plane (:443) now requires a client cert, so the seed
# below must present one. Enroll an admin cert on the certless enroll plane (:8444,
# mirrors integration_stack_test), and prove a certless :443 request is rejected.
if [ "$DO_ENFORCE" = 1 ]; then
  echo "[serverbox] enforce: enroll an admin client cert (:8444) + assert certless :443 is rejected"
  # The admin user is created by the startup lifespan only AFTER Alembic migration,
  # so minting can be too early right after gateway-up — retry (like integration_stack_test).
  ETOK=""
  for _ in $(seq 1 45); do
    ETOK="$("${DC[@]}" exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')"
    [ -n "$ETOK" ] && break; sleep 2
  done
  [ -n "$ETOK" ] || { echo "[serverbox] mint-enroll-token failed (admin not ready)"; exit 1; }
  openssl ecparam -name prime256v1 -genkey -noout -out /tmp/mb-admin.key 2>/dev/null
  openssl req -new -key /tmp/mb-admin.key -subj "/CN=mb-admin" -out /tmp/mb-admin.csr 2>/dev/null
  python3 - "$ETOK" <<'PY'
import json, ssl, sys, urllib.request
tok = sys.argv[1]; csr = open("/tmp/mb-admin.csr").read()
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request("https://localhost:8444/enroll",
    data=json.dumps({"token": tok, "csr": csr}).encode(), headers={"Content-Type": "application/json"})
open("/tmp/mb-admin-fullchain.pem", "w").write(json.load(urllib.request.urlopen(req, context=ctx, timeout=20))["fullchain"])
PY
  [ -s /tmp/mb-admin-fullchain.pem ] || { echo "[serverbox] admin enroll failed"; exit 1; }
  code="$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "https://localhost/api/auth/me" 2>/dev/null || echo 000)"
  [ "$code" = 400 ] && echo "MB_ENFORCE_CERTLESS_REJECTED=1" || echo "MB_ENFORCE_CERTLESS_REJECTED=0 (got $code)"
  export AH_CERT=/tmp/mb-admin-fullchain.pem AH_KEY=/tmp/mb-admin.key
fi

echo "[serverbox] seed admin JWT -> server record -> provision token"
export ADMIN_PW SRV_IP DO_TUNNEL
OUT="$(python3 - <<'PY'
import json, ssl, os, time, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
if os.environ.get("AH_CERT"):  # enforce mode: present the enrolled admin client cert
    ctx.load_cert_chain(os.environ["AH_CERT"], os.environ.get("AH_KEY"))
base = "https://localhost"
def call(method, path, tok=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    if tok: req.add_header("Authorization", "Bearer " + tok)
    return json.load(urllib.request.urlopen(req, context=ctx, timeout=20))
tok = ""
for _ in range(45):  # admin is created by the startup lifespan after Alembic
    try:
        tok = call("POST", "/api/auth/login", body={"username": "admin", "password": os.environ["ADMIN_PW"]})["access_token"]; break
    except Exception: time.sleep(2)
if not tok: raise SystemExit("login failed")
sid = call("POST", "/api/servers", tok, {"name": "mb-agent", "hostname": "mb-agent.local"})["id"]
ptok = call("POST", f"/api/servers/{sid}/provision/token", tok, {})["token"]
# A second server + token for the cross-distro (rpm) agent so it enrolls as its own
# identity — no shared/one-shot provision-token conflict with the deb agent (S2).
sid2 = call("POST", "/api/servers", tok, {"name": "mb-agent-rpm", "hostname": "mb-agent-rpm.local"})["id"]
ptok2 = call("POST", f"/api/servers/{sid2}/provision/token", tok, {})["token"]
print(f"MB_SID={sid} MB_PTOK={ptok} MB_SID2={sid2} MB_PTOK2={ptok2}")
# Tunnel mode (S4): an FRP config pointing at THIS server's IP + an STCP tunnel
# exposing the tunnel-agent's own sshd (:22). Creating the config writes frps.toml
# into the shared volume; the caller then brings frps up. The agent provisions
# against MB_TUN_* and its frpc.toml (fetched for these tunnels) runs the STCP server.
if os.environ.get("DO_TUNNEL") == "1":
    srv_ip = os.environ["SRV_IP"]
    tsid = call("POST", "/api/servers", tok, {"name": "mb-tunnel", "hostname": "mb-tunnel.local"})["id"]
    tptok = call("POST", f"/api/servers/{tsid}/provision/token", tok, {})["token"]
    cfg = call("POST", "/api/frp/server-config", tok, {"name": "mb-frps", "server_addr": srv_ip, "bind_port": 7000})["id"]
    call("POST", "/api/frp/tunnels", tok, {"server_id": tsid, "frp_config_id": cfg, "name": "mb-ssh", "tunnel_type": "stcp", "protocol": "ssh", "local_port": 22})
    # A visitor server+token (its provisioned tunnel-scoped cert is CA-signed -> frps
    # accepts it for the visitor's TLS) + the generated visitor.toml for the container.
    vsid = call("POST", "/api/servers", tok, {"name": "mb-visitor", "hostname": "mb-visitor.local"})["id"]
    vptok = call("POST", f"/api/servers/{vsid}/provision/token", tok, {})["token"]
    import base64
    vreq = urllib.request.Request(base + "/api/frp/generate/visitor-toml", headers={"Authorization": "Bearer " + tok})
    vtoml = urllib.request.urlopen(vreq, context=ctx, timeout=20).read()
    print(f"MB_TUN_SID={tsid} MB_TUN_PTOK={tptok} MB_CFG={cfg} MB_VIS_SID={vsid} MB_VIS_PTOK={vptok}")
    print("MB_VISITOR_B64=" + base64.b64encode(vtoml).decode())
PY
)" || { echo "[serverbox] seeding failed"; exit 1; }
echo "$OUT"
# Also hand the desktop-capstone box what it needs to log in + inject SSE events.
echo "MB_ADMIN_PW=$ADMIN_PW"
echo "MB_MONITOR_KEY=$(grep -E '^MONITOR_API_KEY=' .env | head -1 | cut -d= -f2-)"
# Tunnel mode: the FRP config seed above wrote frps.toml into the shared volume;
# bring frps up now (its ca-issuer-provisioned leaf carries the DOMAIN=$SRV_IP SAN).
if [ "$DO_TUNNEL" = 1 ]; then
  echo "[serverbox] tunnel mode: bring up frps (STCP relay :7000/:7443)"
  "${DC[@]}" up -d frps >/dev/null 2>&1 && echo "MB_FRPS_UP=1" || { echo "MB_FRPS_UP=0"; "${DC[@]}" logs --tail 20 frps; }
fi
# Moncheck mode (S5): seed pull (ping) checks + an email alert rule via the
# monitoring internal API (reachable only inside the compose net -> exec), then
# trigger them. The critical transition dispatches email to the mailhog sink
# (smtp_host in channel_config; SMTP is not SSRF-guarded, so a private IP is fine).
if [ "$DO_MONCHECK" = 1 ]; then
  echo "[serverbox] moncheck mode: seed ping checks + email alert (smtp -> $SMTP_IP:1025)"
  "${DC[@]}" exec -T monitoring python - <<PY
import os, json, urllib.request
key = os.environ.get("MONITOR_API_KEY", "")
base = "http://localhost:8080"
def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
        headers={"Content-Type": "application/json", "X-Internal-Key": key})
    return json.load(urllib.request.urlopen(req, timeout=25))
def st(r):
    return r.get("status") or (r.get("state") or {}).get("status") or "?"
ok_id = call("POST", "/checks", {"name": "mc-ping-ok", "check_type": "ping", "config": {"target": "$SMTP_IP"}, "consecutive_fails": 1, "severity": "critical"})["id"]
crit_id = call("POST", "/checks", {"name": "mc-ping-crit", "check_type": "ping", "config": {"target": "192.0.2.1"}, "consecutive_fails": 1, "severity": "critical"})["id"]
call("POST", "/alerts", {"name": "mc-email", "channel": "email", "match_severity": "critical", "channel_config": {"recipients": ["ops@example.com"], "smtp_host": "$SMTP_IP", "smtp_port": 1025}})
ok_r = call("POST", f"/checks/{ok_id}/run")
crit_r = call("POST", f"/checks/{crit_id}/run")
print("MC_OK_STATUS=" + st(ok_r))
print("MC_CRIT_STATUS=" + st(crit_r))
PY
fi
echo "[serverbox] READY at https://$SRV_IP"
