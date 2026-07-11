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

# Seed the repo mount BEFORE the stack starts, so the gateway bind-mounts a
# host-owned ./repo — docker would otherwise create it root-owned and unwritable,
# and the :8445 path-filter test (step 10) needs /apt genuinely served (6.125).
mkdir -p "$E2E_REPO_ROOT/repo/apt" && echo probe-ok > "$E2E_REPO_ROOT/repo/apt/probe"

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

# ── 7. Smuggled identity headers must never reach the app (6.7) ──────────────
# A client sending its own X-Client-Verify/X-Client-Cert-CN must not spoof a
# verified identity: the gateway overwrites them from the real cert. With a valid
# cert but no JWT the app still answers 401 — the forged headers grant nothing.
code=$(curl -k -s "${CERT[@]}" \
    -H 'X-Client-Verify: SUCCESS' -H 'X-Client-Cert-CN: CN=admin-forged' \
    -o /dev/null -w '%{http_code}' --max-time 5 "$E2E_SERVER_URL/api/auth/me" 2>/dev/null || echo 000)
[ "$code" = "401" ] && ok "smuggled X-Client-* neutralized on :443 (401)" \
    || bad "header smuggling not neutralized on :443: got '$code'"

# Same on the SSE route, whose location re-declares its own header list — the very
# block the audit flagged as an easy place to forget the overwrites.
code=$(curl -k -s "${CERT[@]}" \
    -H 'X-Client-Verify: SUCCESS' -H 'X-Client-Cert-CN: CN=admin-forged' \
    -o /dev/null -w '%{http_code}' --max-time 5 "$E2E_SERVER_URL/api/notifications/stream" 2>/dev/null || echo 000)
[ "$code" = "401" ] && ok "smuggled X-Client-* neutralized on the SSE route (401)" \
    || bad "header smuggling not neutralized on SSE route: got '$code'"

# ── 8. /ca/renew through the gateway — the real ssl_client_escaped_cert path (6.48)
# The renew endpoint takes the gateway-verified current cert (not a fresh token), so
# this exercises the header/cert data path the enroll test doesn't. A fresh CSR reusing
# the enrolled key stands in for a renewal request.
openssl req -new -key "$E2E_WORK/client.key" -subj "/CN=itest" -out "$E2E_WORK/renew.csr" 2>/dev/null
code=$(python3 - "$E2E_WORK" "$E2E_SERVER_URL" <<'PY'
import sys, json, ssl, urllib.request
work, base = sys.argv[1], sys.argv[2]
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
ctx.load_cert_chain(f"{work}/client-fullchain.pem", f"{work}/client.key")
req = urllib.request.Request(f"{base}/ca/renew",
    data=json.dumps({"csr": open(f"{work}/renew.csr").read()}).encode(),
    headers={"Content-Type": "application/json"})
try:
    body = urllib.request.urlopen(req, context=ctx, timeout=5).read().decode()
    print("ok" if "BEGIN CERTIFICATE" in body else "no-cert")
except Exception as e:
    print(getattr(e, "code", "err"))
PY
)
[ "$code" = "ok" ] && ok "/ca/renew through the gateway returned a cert (6.48)" || bad "/ca/renew failed: got '$code'"

# ── 9. The enroll plane throttles a burst to 429 — token brute-force brake (6.124)
codes=$(for _ in $(seq 1 40); do
    curl -k -s -o /dev/null -w '%{http_code}\n' --max-time 5 \
        -X POST "$ENROLL/enroll" -H 'Content-Type: application/json' \
        -d '{"token":"bogus","csr":"x"}' 2>/dev/null
done)
echo "$codes" | grep -q '^429$' && ok "enroll plane returns 429 after a burst (limit_req)" \
    || bad "no 429 after 40 enroll requests"

# ── 10. Repo plane :8445 path filtering (6.63 exposes it, 6.125 asserts it) ──
# Seed the host repo mount so /apt is genuinely served — else every path 404s and
# the filter can't be told from a missing file. Only /apt|/rpm may be reachable;
# traversal and everything else must 404 (never escape to the container fs).
REPO="https://localhost:$E2E_REPO_PORT"
code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "$REPO/apt/probe" 2>/dev/null || echo 000)
[ "$code" = "200" ] && ok "repo plane serves /apt (200)" || bad "/apt/probe expected 200, got '$code'"
for path in /etc/passwd /apt/../etc/passwd /secret /rpm; do
    code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "$REPO$path" 2>/dev/null || echo 000)
    [ "$code" = "404" ] && ok "repo plane blocks $path (404)" || bad "repo plane leaked $path -> $code"
done
rm -f "$E2E_REPO_ROOT/repo/apt/probe" 2>/dev/null || true

# ── 11. Network segmentation: the PKI plane is off the default net (1.1) ──────
# ca-issuer sits on the internal `pki` net (gateway + postgres only). A default-net
# service — here the server, standing in for the internet-facing frps — must NOT reach
# ca-issuer:8090, else it could forge the gateway's mTLS headers and mint certs. The
# positive side (the gateway CAN reach it) is already proven by steps 1-9's enrollment,
# which renews through the gateway→issuer path.
# Positive control (server CAN reach a default-net peer, redis) + negative (NOT the
# pki-only ca-issuer), so a broken exec/DNS can't masquerade as "isolated".
if e2e_dc exec -T server python -c "
import socket, sys
socket.create_connection(('redis', 6379), timeout=4).close()          # default net: must work
try:
    socket.create_connection(('ca-issuer', 8090), timeout=4).close()  # pki plane: must NOT
    sys.exit(2)
except OSError:
    sys.exit(0)
" >/dev/null 2>&1; then
    ok "PKI plane isolated: server reaches redis (default) but NOT ca-issuer:8090 (1.1)"
else
    bad "segmentation check failed: server reached ca-issuer:8090, or the redis control failed"
fi

# ── 12. frps is fenced off the internal net (3.28) ────────────────────────────
# frps sits on its own frpedge net; redis:6379 + victoria:8428 (both auth-less) are on
# the default net. A compromised frps must not reach them. redis is already up (server
# needs it); frps + victoria aren't in the gateway dependency chain, so start them here.
e2e_dc up -d frps victoria >/dev/null 2>&1
for _ in $(seq 1 15); do
    [ -n "$(e2e_dc ps -q frps 2>/dev/null)" ] && e2e_dc exec -T frps sh -c 'command -v nc >/dev/null 2>&1' && break
    sleep 1
done
if ! e2e_dc exec -T frps sh -c 'command -v nc >/dev/null 2>&1'; then
    bad "frps container/nc not available — 3.28 negative test inconclusive"
elif e2e_dc exec -T frps sh -c 'nc -z -w2 redis 6379 || nc -z -w2 victoria 8428' >/dev/null 2>&1; then
    bad "frps reached redis or victoria from frpedge — isolation broken (3.28)"
else
    ok "frps (frpedge) cannot reach auth-less redis:6379 / victoria:8428 (3.28)"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "integration_stack_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
