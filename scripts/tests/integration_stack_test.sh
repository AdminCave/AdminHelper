#!/usr/bin/env bash
#
# integration_stack_test.sh — from-outside mTLS smoke test against the real stack.
#
# This is the ONE integration path the component/unit tests cannot cover: it
# boots the actual multi-container stack from the repo's docker-compose.yml with
# MTLS_ENFORCE=true and talks to it ONLY from outside, through the nginx gateway —
# exercising the full enrollment + mTLS + JWT round-trip end to end:
#
#   1. mint a one-time enrollment token in-container (python -m app.cli)
#   2. outside: EC P-256 key + CSR -> POST :8444/enroll (certless) -> client cert
#   3. certless GET :443            -> rejected by the gateway's mTLS (400)
#   4. cert-only GET :443/api/...   -> 401 (the app's JWT layer is independent)
#   5. cert + login :443           -> JWT
#   6. cert + JWT GET :443/api/...  -> 200 (real routing + DB + admin authz)
#
# Hermetic: throwaway secrets, locally-built images, an isolated compose project
# + project dir (so the ./data bind-mount lands in a tempdir, never the repo),
# and a full `down -v` teardown. Needs docker (+ compose v2), openssl, curl,
# python3. SKIPs cleanly when docker is unavailable (e.g. a sandboxed dev box).
#
# Run: bash scripts/tests/integration_stack_test.sh

# ok()/bad() never fail, so the `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"
OVERLAY="$HERE/docker-compose.itest.yml"
PROJECT="ah-itest-$$"

# High, per-run host ports so the test never collides with a real stack on the
# fixed 443/8444 or a second run in parallel (the overlay maps these onto the
# gateway). Derived from the PID; range 20000–39999, well below 65535.
HTTPS_PORT=$(( 20000 + ($$ % 20000) ))
ENROLL_PORT=$(( HTTPS_PORT + 1 ))
GW="https://localhost:$HTTPS_PORT"
ENROLL="https://localhost:$ENROLL_PORT"
IMG_PREFIX="adminhelper-itest"

PASS=0
FAIL=0
ok()   { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad()  { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
note() { echo "  note $*"; }

# ── Preconditions ────────────────────────────────────────────────────────────
for bin in docker openssl curl python3; do
    command -v "$bin" >/dev/null 2>&1 || { echo "SKIP: '$bin' not available"; exit 0; }
done
docker compose version >/dev/null 2>&1 || { echo "SKIP: 'docker compose' v2 not available"; exit 0; }
docker info >/dev/null 2>&1 || { echo "SKIP: docker daemon not reachable"; exit 0; }

WORK=$(mktemp -d)

dc() {
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" -f "$OVERLAY" \
        --project-directory "$WORK" --env-file "$WORK/.env" "$@"
}

cleanup() {
    dc down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

rand() { openssl rand -hex 16; }

# ── Throwaway secrets + image overrides ──────────────────────────────────────
ADMIN_PW="itest-$(rand)"
cat > "$WORK/.env" <<EOF
DOMAIN=localhost
SECRET_KEY=$(rand)$(rand)
POSTGRES_PASSWORD=$(rand)
CA_ROOT_PASSPHRASE=$(rand)
MONITOR_API_KEY=$(rand)
ADMIN_PASSWORD=$ADMIN_PW
MTLS_ENFORCE=true
SERVER_IMAGE=$IMG_PREFIX/server:latest
GATEWAY_IMAGE=$IMG_PREFIX/gateway:latest
CA_ISSUER_IMAGE=$IMG_PREFIX/ca-issuer:latest
ITEST_HTTPS_PORT=$HTTPS_PORT
ITEST_ENROLL_PORT=$ENROLL_PORT
EOF

# ── Build the images under test (local worktree code) ────────────────────────
# Only the services the gateway depends on are needed; monitoring/frps/victoria
# are never brought up, so their images are not built.
echo "[itest] building images (server, gateway, ca-issuer)..."
docker build -q -t "$IMG_PREFIX/server:latest"    -f "$REPO_ROOT/Dockerfile" "$REPO_ROOT" \
    >/dev/null || { bad "server image build"; exit 1; }
docker build -q -t "$IMG_PREFIX/gateway:latest"   "$REPO_ROOT/apps/gateway" \
    >/dev/null || { bad "gateway image build"; exit 1; }
docker build -q -t "$IMG_PREFIX/ca-issuer:latest" "$REPO_ROOT/apps/ca-issuer" \
    >/dev/null || { bad "ca-issuer image build"; exit 1; }

# ── Boot the stack (gateway pulls in server, ca-issuer, postgres, redis) ──────
echo "[itest] starting stack..."
dc up -d gateway >/dev/null 2>&1 || { bad "compose up"; exit 1; }

# Wait until nginx answers on :443 (the ca-issuer must provision the gateway's
# TLS material first). A non-000 HTTP code means the TLS edge is live.
ready=0
for _ in $(seq 1 90); do
    code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 3 "$GW/" 2>/dev/null || echo 000)
    [ "$code" != "000" ] && { ready=1; break; }
    sleep 2
done
[ "$ready" = 1 ] && ok "gateway TLS edge is live on :443" || { bad "gateway never came up"; dc logs --tail 40 gateway; exit 1; }

# ── 1. Mint a one-time enrollment token in-container ──────────────────────────
# Retries because the admin user is created by the server's startup lifespan
# (from ADMIN_PASSWORD) only after Alembic migration completes.
TOKEN=""
for _ in $(seq 1 45); do
    TOKEN=$(dc exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')
    [ -n "$TOKEN" ] && break
    sleep 2
done
[ -n "$TOKEN" ] && ok "minted enrollment token in-container" || { bad "could not mint enrollment token"; dc logs --tail 40 server; exit 1; }

# ── 2. Client key + CSR, then redeem on the certless enroll plane :8444 ───────
# EC P-256 matches the desktop client; the issuer overrides the CN from the
# token grant, so the CSR subject is irrelevant.
openssl ecparam -name prime256v1 -genkey -noout -out "$WORK/client.key" 2>/dev/null
openssl req -new -key "$WORK/client.key" -subj "/CN=itest" -out "$WORK/client.csr" 2>/dev/null

if python3 - "$WORK" "$ENROLL" "$TOKEN" <<'PY'
import json, ssl, sys, urllib.request

work, enroll, token = sys.argv[1], sys.argv[2], sys.argv[3]
csr = open(f"{work}/client.csr").read()
body = json.dumps({"token": token, "csr": csr}).encode()
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request(
    f"{enroll}/enroll", data=body, headers={"Content-Type": "application/json"}
)
data = json.load(urllib.request.urlopen(req, context=ctx, timeout=15))
# fullchain = leaf + intermediate (presented in mTLS); the private key stays local.
open(f"{work}/client-fullchain.pem", "w").write(data["fullchain"])
PY
then
    ok "enrolled a client cert via :8444/enroll"
else
    bad "enrollment on the certless plane failed"
    dc logs --tail 40 ca-issuer
    exit 1
fi

CERT=(--cert "$WORK/client-fullchain.pem" --key "$WORK/client.key")

# ── 3. Certless request is rejected by the gateway's mTLS ─────────────────────
code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "$GW/api/auth/me" 2>/dev/null || echo 000)
[ "$code" = "400" ] && ok "certless :443 request rejected by mTLS (400)" || bad "certless expected 400, got '$code'"

# ── 4. Cert without a JWT -> 401 (the app's auth layer is independent) ────────
code=$(curl -k -s "${CERT[@]}" -o /dev/null -w '%{http_code}' --max-time 5 "$GW/api/auth/me" 2>/dev/null || echo 000)
[ "$code" = "401" ] && ok "cert without JWT -> 401" || bad "cert-only expected 401, got '$code'"

# ── 5. Cert + login -> JWT ───────────────────────────────────────────────────
JWT=$(curl -k -s "${CERT[@]}" --max-time 5 -X POST "$GW/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"admin\",\"password\":\"$ADMIN_PW\"}" 2>/dev/null \
    | python3 -c 'import sys, json; print(json.load(sys.stdin).get("access_token", ""))' 2>/dev/null)
[ -n "$JWT" ] && ok "login through the gateway returned a JWT" || bad "login did not yield a JWT"

# ── 6. Cert + JWT -> 200 on a protected, admin-only route ────────────────────
code=$(curl -k -s "${CERT[@]}" -H "Authorization: Bearer $JWT" \
    -o /dev/null -w '%{http_code}' --max-time 5 "$GW/api/servers" 2>/dev/null || echo 000)
[ "$code" = "200" ] && ok "cert + JWT -> 200 on /api/servers (routing + DB + authz)" || bad "authenticated request expected 200, got '$code'"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "integration_stack_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
