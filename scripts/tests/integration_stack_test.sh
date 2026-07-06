#!/usr/bin/env bash
#
# integration_stack_test.sh — from-outside mTLS smoke test against the real stack.
#
# This is the ONE integration path the component/unit tests cannot cover: it
# boots the actual multi-container stack (docker-compose.yml + the test overlay)
# with MTLS_ENFORCE=true and talks to it ONLY from outside, through the nginx
# gateway — exercising the full enrollment + mTLS + JWT round-trip end to end:
#
#   1. mint a one-time enrollment token in-container (python -m app.cli)
#   2. outside: EC P-256 key + CSR -> POST :8444/enroll (certless) -> client cert
#   3. certless GET :443            -> rejected by the gateway's mTLS (400)
#   4. cert-only GET :443/api/...   -> 401 (the app's JWT layer is independent)
#   5. cert + login :443           -> JWT
#   6. cert + JWT GET :443/api/...  -> 200 (real routing + DB + admin authz)
#
# Hermetic boot/seed/teardown is shared via lib_e2e_stack.sh. Needs docker
# (+ compose v2), openssl, curl, python3. SKIPs cleanly when docker is
# unavailable (e.g. a sandboxed dev box). Run: bash scripts/tests/integration_stack_test.sh

# ok()/bad() never fail, so the `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

# shellcheck source=scripts/tests/lib_e2e_stack.sh
. "$(cd "$(dirname "$0")" && pwd)/lib_e2e_stack.sh"

PASS=0
FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

e2e_require
e2e_init true                                  # MTLS_ENFORCE=true (enforced edge)
ENROLL="https://localhost:$E2E_ENROLL_PORT"

e2e_up gateway && ok "gateway TLS edge is live on :$E2E_HTTPS_PORT" \
    || { bad "gateway never came up"; exit 1; }

# ── 1. Mint a one-time enrollment token in-container ──────────────────────────
# Retries because the admin user is created by the server's startup lifespan
# (from ADMIN_PASSWORD) only after Alembic migration completes.
TOKEN=""
for _ in $(seq 1 45); do
    TOKEN=$(e2e_dc exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')
    [ -n "$TOKEN" ] && break
    sleep 2
done
[ -n "$TOKEN" ] && ok "minted enrollment token in-container" || { bad "could not mint enrollment token"; e2e_dc logs --tail 40 server; exit 1; }

# ── 2. Client key + CSR, then redeem on the certless enroll plane :8444 ───────
# EC P-256 matches the desktop client; the issuer overrides the CN from the
# token grant, so the CSR subject is irrelevant.
openssl ecparam -name prime256v1 -genkey -noout -out "$E2E_WORK/client.key" 2>/dev/null
openssl req -new -key "$E2E_WORK/client.key" -subj "/CN=itest" -out "$E2E_WORK/client.csr" 2>/dev/null

if python3 - "$E2E_WORK" "$ENROLL" "$TOKEN" <<'PY'
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
    e2e_dc logs --tail 40 ca-issuer
    exit 1
fi

# ── 2b. One-time: redeeming the SAME token again MUST be rejected — the security
# property install.sh advertises. Without asserting it, a regression that made tokens
# replayable would pass every suite green (6.68).
code=$(python3 - "$E2E_WORK" "$ENROLL" "$TOKEN" <<'PY'
import json, ssl, sys, urllib.request, urllib.error
work, enroll, token = sys.argv[1:4]
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
body = json.dumps({"token": token, "csr": open(f"{work}/client.csr").read()}).encode()
req = urllib.request.Request(f"{enroll}/enroll", data=body, headers={"Content-Type": "application/json"})
try:
    print(urllib.request.urlopen(req, context=ctx, timeout=15).status)
except urllib.error.HTTPError as e:
    print(e.code)
PY
)
case "$code" in
  4*) ok "one-time token: second redeem rejected ($code)" ;;
  *)  bad "one-time token: second redeem NOT rejected (got '$code')" ;;
esac

CERT=(--cert "$E2E_WORK/client-fullchain.pem" --key "$E2E_WORK/client.key")

# ── 3. Certless request is rejected by the gateway's mTLS ─────────────────────
code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "$E2E_SERVER_URL/api/auth/me" 2>/dev/null || echo 000)
[ "$code" = "400" ] && ok "certless :443 request rejected by mTLS (400)" || bad "certless expected 400, got '$code'"

# ── 4. Cert without a JWT -> 401 (the app's auth layer is independent) ────────
code=$(curl -k -s "${CERT[@]}" -o /dev/null -w '%{http_code}' --max-time 5 "$E2E_SERVER_URL/api/auth/me" 2>/dev/null || echo 000)
[ "$code" = "401" ] && ok "cert without JWT -> 401" || bad "cert-only expected 401, got '$code'"

# ── 5. Cert + login -> JWT ───────────────────────────────────────────────────
JWT=$(curl -k -s "${CERT[@]}" --max-time 5 -X POST "$E2E_SERVER_URL/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"admin\",\"password\":\"$E2E_ADMIN_PW\"}" 2>/dev/null \
    | python3 -c 'import sys, json; print(json.load(sys.stdin).get("access_token", ""))' 2>/dev/null)
[ -n "$JWT" ] && ok "login through the gateway returned a JWT" || bad "login did not yield a JWT"

# ── 6. Cert + JWT -> 200 on a protected, admin-only route ────────────────────
code=$(curl -k -s "${CERT[@]}" -H "Authorization: Bearer $JWT" \
    -o /dev/null -w '%{http_code}' --max-time 5 "$E2E_SERVER_URL/api/servers" 2>/dev/null || echo 000)
[ "$code" = "200" ] && ok "cert + JWT -> 200 on /api/servers (routing + DB + authz)" || bad "authenticated request expected 200, got '$code'"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "integration_stack_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
