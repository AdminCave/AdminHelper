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
SRV_IP="${1:?usage: crabbox_serverbox.sh <server-ip>}"
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
upsert MTLS_ENFORCE false
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

echo "[serverbox] seed admin JWT -> server record -> provision token"
export ADMIN_PW
OUT="$(python3 - <<'PY'
import json, ssl, os, time, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
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
print(f"MB_SID={sid} MB_PTOK={ptok}")
PY
)" || { echo "[serverbox] seeding failed"; exit 1; }
echo "$OUT"
# Also hand the desktop-capstone box what it needs to log in + inject SSE events.
echo "MB_ADMIN_PW=$ADMIN_PW"
echo "MB_MONITOR_KEY=$(grep -E '^MONITOR_API_KEY=' .env | head -1 | cut -d= -f2-)"
echo "[serverbox] READY at https://$SRV_IP"
