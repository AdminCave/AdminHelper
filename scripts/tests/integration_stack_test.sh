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
#   8. /ca/renew with the enrolled cert -> a renewed cert
#   8b. re-enrolling the device names the first cert as replaced: the first cert
#       neither renews nor reaches the API, the new one does — until the device
#       revokes itself (R-0224)
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
e2e_login "${CERT[@]}"; JWT=$E2E_JWT
[ -n "$JWT" ] && ok "login through the gateway returned a JWT" || bad "login did not yield a JWT ($E2E_LOGIN_ERR)"

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

# ── 7b. The server takes the identity headers from the gateway alone ─────────
# The gateway sets X-Client-Verify/X-Client-Cert from the verified cert (step 7); the server
# reads them only from a request whose direct peer is an address of the compose service
# gateway (app.core.identity). Every other service of the default network reaches server:8080
# as well; the server itself stands in for one here, sending the headers the gateway would set
# for the cert of step 2 (8b revokes it later). Enforced, a request without an identity gets the
# 403 of the scope guard on /api/servers. Then the gateway is recreated, as an update does, on
# a new address (a placeholder holds its old one), and the server has to take its headers from
# the first request on.

# default_ip <service> — the address of the service's container in the project's default
# network; empty when it is not running, has none there or a lookup fails.
default_ip() { container_ip "$(e2e_dc ps -q "$1" 2>/dev/null)"; }

# container_ip <container> — the same for a container by ID or name.
container_ip() {
    local net
    net=$(docker network ls -q --no-trunc --filter "label=com.docker.compose.project=$E2E_PROJECT" \
        --filter "label=com.docker.compose.network=default" 2>/dev/null)
    [ -n "$1" ] && [ -n "$net" ] && [ "$(wc -l <<<"$net")" = 1 ] || return 0
    docker inspect --format \
        "{{range .NetworkSettings.Networks}}{{if eq .NetworkID \"$net\"}}{{.IPAddress}}{{end}}{{end}}" \
        "$1" 2>/dev/null
}

# direct_servers <with|without> — "<status> <body>" of GET /api/servers with the JWT of step 5,
# sent from the server container straight to server:8080; "with" adds X-Client-Verify: SUCCESS
# and X-Client-Cert, the PEM on stdin escaped like nginx's $ssl_client_escaped_cert. Empty when
# the exec fails. server:8080, not localhost: uvicorn takes the peer from X-Forwarded-For when
# the request comes over loopback.
direct_servers() {
    e2e_dc exec -T server python -c '
import sys, urllib.error, urllib.parse, urllib.request
jwt, mode = sys.argv[1:3]
headers = {"Authorization": "Bearer " + jwt}
if mode == "with":
    headers["X-Client-Verify"] = "SUCCESS"
    headers["X-Client-Cert"] = urllib.parse.quote(sys.stdin.read())
req = urllib.request.Request("http://server:8080/api/servers", headers=headers)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        status, body = resp.status, resp.read()
except urllib.error.HTTPError as e:
    status, body = e.code, e.read()
print(status, body.decode("ascii", "backslashreplace"))' "$JWT" "$1" 2>/dev/null
}

# via_gateway — the status of the same GET with the cert of step 2 and the JWT through the
# gateway, as in step 6.
via_gateway() {
    curl -k -s "${CERT[@]}" -H "Authorization: Bearer $JWT" \
        -o /dev/null -w '%{http_code}' --max-time 5 "$E2E_SERVER_URL/api/servers" 2>/dev/null || echo 000
}

# The container that holds the gateway's old address in (d): a one-off of the service redis,
# which is on the default network alone, so the teardown's `down` removes it with the stack. A
# container compose did not start would stay behind and keep the network in use, with `down`
# still exiting 0.
IP_PLACEHOLDER="$E2E_PROJECT-ip-placeholder"

# gateway_moved — (d): the gateway stopped, the placeholder started on the address it freed, the
# gateway recreated (no build, nothing else touched) on another one; once it rejects a certless
# request again as in step 3, the very next request with the cert -> 200. Leaves the placeholder
# to the caller.
gateway_moved() {
    local old held new code deadline log="$E2E_WORK/gateway-recreate.log"
    old=$(default_ip gateway)
    [ -n "$old" ] || { bad "the gateway has no address in the default network before the recreate"; return; }
    if ! e2e_dc stop gateway >"$log" 2>&1; then
        bad "stopping the gateway failed"; tail -20 "$log"; return
    fi
    # No fixed address: compose run takes none, and docker run --ip on a network without a subnet
    # of its own needs Docker 29.0.4 (moby#51583). Docker hands out the lowest free address (seen
    # on Docker 29; in CI the recreated gateway got its own back), the one the gateway just freed.
    e2e_dc run -d --no-deps --name "$IP_PLACEHOLDER" --entrypoint sleep redis 600 >>"$log" 2>&1
    held=$(container_ip "$IP_PLACEHOLDER")
    echo "  info address the stopped gateway freed / the placeholder holds: '$old' / '$held'"
    [ "$held" = "$old" ] && ok "a placeholder holds the address the stopped gateway freed" \
        || { bad "the placeholder does not hold the address the stopped gateway freed"; tail -20 "$log"; }
    if ! e2e_dc up -d --no-deps --force-recreate gateway >>"$log" 2>&1; then
        bad "recreating the gateway failed"; tail -20 "$log"; return
    fi
    deadline=$((SECONDS + 60))
    while :; do
        code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "$E2E_SERVER_URL/api/auth/me" 2>/dev/null || echo 000)
        [ "$code" != 400 ] || break
        if [ "$SECONDS" -ge "$deadline" ]; then
            bad "the recreated gateway did not reject a certless request with 400 within 60 s (last '$code')"
            e2e_dc logs --tail 20 gateway; return
        fi
        sleep 1
    done
    code=$(via_gateway)
    new=$(default_ip gateway)
    echo "  info gateway address in the default network before/after the recreate: '$old' -> '$new'"
    [ -n "$new" ] && [ "$new" != "$old" ] && ok "the recreated gateway came back on another address" \
        || bad "the recreated gateway did not come back on another address: the fresh lookup goes unproven"
    [ "$code" = 200 ] && ok "right after the gateway was recreated: cert + JWT through it -> 200" \
        || bad "right after the gateway was recreated: cert + JWT through it expected 200, got '$code'"
}

identity_from_gateway() {
    local pem forged bare code

    pem=$(openssl x509 -in "$E2E_WORK/client-fullchain.pem" 2>/dev/null) && [ -n "$pem" ] \
        || { bad "identity headers: no certificate in client-fullchain.pem"; return; }

    # a. The gateway's headers straight to server:8080: no identity, the 403.
    # b. Counter-check: the same request without them reaches the server and gets the same 403,
    #    so (a) rests on nothing but the identity the server did not take.
    forged=$(direct_servers with <<<"$pem")
    bare=$(direct_servers without)
    [ "${forged%% *}" = 403 ] && [ "$forged" = "$bare" ] \
        && ok "identity headers straight to server:8080, not from the gateway: no identity (403 as without them)" \
        || bad "identity headers straight to server:8080: got '$forged', expected 403 as without them ('$bare')"
    [ "${bare%% *}" = 403 ] && ok "counter-check: server:8080 without the headers -> 403 (reached, no identity)" \
        || bad "server:8080 without the headers: expected 403, got '$bare'"

    # c. The same cert through the gateway -> 200.
    code=$(via_gateway)
    [ "$code" = 200 ] && ok "the same cert + JWT through the gateway -> 200" \
        || bad "cert + JWT through the gateway: expected 200, got '$code'"

    # d. The gateway recreated on another address.
    gateway_moved
    docker rm -f "$IP_PLACEHOLDER" >/dev/null 2>&1
}
identity_from_gateway

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

# ── 8b. Per-device revocation through the gateway (R-0224) ────────────────────
# Re-enrolling the same device names its first certificate as replaced; the issuer
# revokes that device line. From then on the first certificate neither renews nor
# gets past the server, while the new one does both — until the device revokes
# itself with it. Every step goes through the real gateway headers.
renew_with() {  # renew_with <fullchain> <key> -> ok | <status>
    python3 - "$E2E_WORK" "$E2E_SERVER_URL" "$1" "$2" <<'PY'
import sys, json, ssl, urllib.request
work, base, chain, key = sys.argv[1:5]
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
ctx.load_cert_chain(chain, key)
req = urllib.request.Request(f"{base}/ca/renew",
    data=json.dumps({"csr": open(f"{work}/renew.csr").read()}).encode(),
    headers={"Content-Type": "application/json"})
try:
    body = urllib.request.urlopen(req, context=ctx, timeout=5).read().decode()
    print("ok" if "BEGIN CERTIFICATE" in body else "no-cert")
except Exception as e:
    print(getattr(e, "code", "err"))
PY
}
TOKEN2=$(e2e_dc exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')
FIRST_FP=$(openssl x509 -in "$E2E_WORK/client-fullchain.pem" -outform DER 2>/dev/null | sha256sum | cut -d' ' -f1)
openssl ecparam -name prime256v1 -genkey -noout -out "$E2E_WORK/client2.key" 2>/dev/null
openssl req -new -key "$E2E_WORK/client2.key" -subj "/CN=itest" -out "$E2E_WORK/client2.csr" 2>/dev/null
if [ -n "$TOKEN2" ] && python3 - "$E2E_WORK" "$ENROLL" "$TOKEN2" "$FIRST_FP" <<'PY'
import json, ssl, sys, urllib.request
work, enroll, token, replaces = sys.argv[1:5]
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
body = json.dumps({"token": token, "csr": open(f"{work}/client2.csr").read(), "replaces": replaces})
req = urllib.request.Request(f"{enroll}/enroll", data=body.encode(),
    headers={"Content-Type": "application/json"})
data = json.load(urllib.request.urlopen(req, context=ctx, timeout=15))
open(f"{work}/client2-fullchain.pem", "w").write(data["fullchain"])
PY
then
    ok "re-enrolled the device, naming the first cert as replaced"
else
    bad "re-enrollment with replaces failed"
fi
code=$(renew_with "$E2E_WORK/client-fullchain.pem" "$E2E_WORK/client.key")
[ "$code" = "403" ] && ok "the replaced cert no longer renews (403)" || bad "replaced cert renew: expected 403, got '$code'"
code=$(renew_with "$E2E_WORK/client2-fullchain.pem" "$E2E_WORK/client2.key")
[ "$code" = "ok" ] && ok "the new cert renews" || bad "new cert renew failed: got '$code'"

CERT2=(--cert "$E2E_WORK/client2-fullchain.pem" --key "$E2E_WORK/client2.key")
resp=$(curl -k -s "${CERT[@]}" -H "Authorization: Bearer $JWT" -w '\n%{http_code}' --max-time 5 \
    "$E2E_SERVER_URL/api/servers" 2>/dev/null)
code=${resp##*$'\n'}
if [ "$code" = "403" ] && [[ "$resp" == *ERR_CERT_REVOKED* ]]; then
    ok "the replaced cert is refused on the API (403 ERR_CERT_REVOKED)"
else
    bad "replaced cert on the API: expected 403 ERR_CERT_REVOKED, got '$code'"
fi
code=$(curl -k -s "${CERT2[@]}" -H "Authorization: Bearer $JWT" -o /dev/null -w '%{http_code}' \
    --max-time 5 "$E2E_SERVER_URL/api/servers" 2>/dev/null || echo 000)
[ "$code" = "200" ] && ok "the new cert + JWT -> 200" || bad "new cert on the API: expected 200, got '$code'"
code=$(curl -k -s "${CERT2[@]}" -X POST -o /dev/null -w '%{http_code}' --max-time 5 \
    "$E2E_SERVER_URL/api/enrollment/self/revoke" 2>/dev/null || echo 000)
[ "$code" = "204" ] && ok "the device revoked itself with its cert (204)" || bad "self-revoke: expected 204, got '$code'"
code=$(curl -k -s "${CERT2[@]}" -H "Authorization: Bearer $JWT" -o /dev/null -w '%{http_code}' \
    --max-time 5 "$E2E_SERVER_URL/api/servers" 2>/dev/null || echo 000)
[ "$code" = "403" ] && ok "after self-revocation the cert is refused (403)" || bad "after self-revoke: expected 403, got '$code'"

# ── 9. The enroll plane throttles a burst to 429 — token brute-force brake (6.124)
codes=$(for _ in $(seq 1 40); do
    curl -k -s -o /dev/null -w '%{http_code}\n' --max-time 5 \
        -X POST "$ENROLL/enroll" -H 'Content-Type: application/json' \
        -d '{"token":"bogus","csr":"x"}' 2>/dev/null
done)
grep -q '^429$' <<<"$codes" && ok "enroll plane returns 429 after a burst (limit_req)" \
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

# ── 11b. frps takes its configuration over by itself (R-0411) ─────────────────
# frps runs under a supervisor (apps/frps) that starts it only from a checked copy of the
# frps.toml the server writes and the PEM files in frps-certs, and takes a change over once it
# stayed the same for two polls (5 s apart). Seen from outside: whether frps answers TLS on its
# published bind port — a TLS handshake, since docker's port proxy accepts a bare TCP connect
# with nothing listening behind it —, the state admins see over the API, and the event sequence
# of the status file the server reads. Every wait ends in a FAIL at its deadline; "nothing
# happened" is checked only after the supervisor has polled often enough to have acted.
CERT3=(--cert "$E2E_WORK/client3-fullchain.pem" --key "$E2E_WORK/client3.key")
JWT3=""
FRPS_PORT=""   # the host port compose publishes the bind port on
FRPS_LEAF=""   # sha256 of the leaf in frps-certs/frps.crt, which frps must present
LAST=""        # what the last probe saw, for its FAIL line

# enroll <token> <name> — redeems the token for E2E_WORK/<name>.csr into <name>-fullchain.pem.
enroll() {
    python3 - "$E2E_WORK" "$ENROLL" "$1" "$2" <<'PY'
import json, ssl, sys, urllib.request
work, enroll, token, name = sys.argv[1:5]
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
body = json.dumps({"token": token, "csr": open(f"{work}/{name}.csr").read()})
req = urllib.request.Request(f"{enroll}/enroll", data=body.encode(),
    headers={"Content-Type": "application/json"})
data = json.load(urllib.request.urlopen(req, context=ctx, timeout=15))
open(f"{work}/{name}-fullchain.pem", "w").write(data["fullchain"])
PY
}

# api <method> <path> [<json>] — the response body; non-zero unless the status is 2xx.
api() {
    local data=() resp
    [ $# -lt 3 ] || data=(-d "$3")
    resp=$(curl -k -s "${CERT3[@]}" -H "Authorization: Bearer $JWT3" -H 'Content-Type: application/json' \
        -X "$1" "${data[@]}" -w '\n%{http_code}' --max-time 10 "$E2E_SERVER_URL$2" 2>/dev/null)
    printf '%s\n' "${resp%$'\n'*}"
    [[ "${resp##*$'\n'}" == 2?? ]]
}

# json_get <key> — a top-level value of the JSON object on stdin; empty for null or no JSON.
json_get() {
    python3 -c 'import json, sys; v = json.load(sys.stdin).get(sys.argv[1]); print("" if v is None else v)' \
        "$1" 2>/dev/null
}

# sv_api — "<state> <reason> <stale>" as GET /api/frp/supervisor-status shows them to admins.
sv_api() {
    api GET /api/frp/supervisor-status | python3 -c '
import json, sys
s = json.load(sys.stdin)
print(s["state"], s["reason"], str(s["stale"]).lower())' 2>/dev/null
}
sv_api_is() { LAST=$(sv_api); [ "$LAST" = "$1" ]; }

# frp_status — "total <n>" from GET /api/frp/status as admins see it, or "error <text>" while it
# reports one; empty when it gives neither.
frp_status() {
    api GET /api/frp/status | python3 -c '
import json, sys
s = json.load(sys.stdin)
if s.get("error"):
    print("error", s["error"])
elif type(s["total"]) is int:
    print("total", s["total"])' 2>/dev/null
}
frp_status_ok() { LAST=$(frp_status); [ "${LAST%% *}" = total ]; }

# sv_file mark | since <mark> | heartbeat — from the supervisor's status file, read where the
# server reads it. mark: "<boot> <last seq>"; since: "=" followed by the events after the mark
# as <event>:<reason>:<tokenChanged>, or "rebooted" when the supervisor has started anew since.
# Empty when the file cannot be read, so that no comparison passes on it.
sv_file() {
    e2e_dc exec -T server cat /app/frps-state/status.json 2>/dev/null | python3 -c '
import json, sys
s, what = json.load(sys.stdin), sys.argv[1]
events = s["events"]
if what == "mark":
    print(s["boot"], events[-1]["seq"] if events else 0)
elif what == "since":
    boot, seq = sys.argv[2].split()
    new = ["%s:%s:%s" % (e["event"], e["reason"], str(e["tokenChanged"]).lower())
           for e in events if e["seq"] > int(seq)]
    print("rebooted" if boot != s["boot"] else "=" + " ".join(new))
else:
    print(s[what])' "$@" 2>/dev/null
}
sv_has_new() { LAST=$(sv_file since "$1"); [ -n "$LAST" ] && [ "$LAST" != "=" ]; }

# tls_probe <port> — "ok <sha256 of the leaf>" when a TLS handshake on the port completes with a
# certificate that chains to frps-certs/ca.crt; "no <error>" when the connection is refused,
# reset, closed or times out; "bad <error>" for a handshake that fails otherwise.
tls_probe() {
    python3 - "$1" "$E2E_WORK/frps-ca.crt" "$E2E_WORK/client3-fullchain.pem" "$E2E_WORK/client3.key" <<'PY'
import hashlib, socket, ssl, sys
port, ca, chain, key = sys.argv[1:5]
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.load_verify_locations(ca)
ctx.load_cert_chain(chain, key)
try:
    with socket.create_connection(("127.0.0.1", int(port)), timeout=5) as raw:
        with ctx.wrap_socket(raw) as conn:
            print("ok", hashlib.sha256(conn.getpeercert(binary_form=True)).hexdigest())
except (ConnectionError, socket.timeout, ssl.SSLEOFError, ssl.SSLZeroReturnError) as e:
    print("no", type(e).__name__)
except OSError as e:
    print("bad", type(e).__name__)
PY
}
tls_answers() { LAST=$(tls_probe "$FRPS_PORT"); [ "$LAST" = "ok $FRPS_LEAF" ]; }
tls_silent()  { LAST=$(tls_probe "$FRPS_PORT"); [ "${LAST%% *}" = no ]; }

# frps_pid — the pid of frps in its container, empty when none runs (pidof exits 1); non-zero
# when pidof fails otherwise or the exec does, so that "no process" never rests on an error.
frps_pid() {
    local out
    # shellcheck disable=SC2016 # expanded by the container's sh
    out=$(e2e_dc exec -T frps sh -c 'pids=$(pidof frps); echo "rc=$? $pids"' 2>/dev/null) || return 2
    case $out in
    "rc=0 "?*) echo "${out#rc=0 }" ;;
    "rc=1 ") ;;
    *) return 2 ;;
    esac
}

# toml_id — "<inode> <sha256>" of the frps.toml the server wrote; empty without one.
toml_id() {
    # shellcheck disable=SC2016 # expanded by the container's sh
    e2e_dc exec -T server sh -c 'stat -c "%i" "$1" && sha256sum "$1"' _ /app/frp-config/frps.toml 2>/dev/null \
        | awk 'NR == 1 { inode = $1 } NR == 2 { print inode, $1 }'
}

# frps_notices — "<sourceId> <eventType> <agent-hint|->" for each frps notification of the
# admin; agent-hint: the text says that agent tunnels take a while (a new token).
frps_notices() {
    api GET '/api/notifications?limit=1000' | python3 -c '
import json, sys
for n in json.load(sys.stdin):
    if n["sourceType"] == "frps":
        print(n["sourceId"], n["eventType"], "agent-hint" if "Agent-Tunnel" in n["body"] else "-")' 2>/dev/null
}
notice_for() { LAST=$(frps_notices); grep -q "^$1 " <<<"$LAST"; }

# watch_runs — how many runs of the scheduler's frps watch job have ended so far, by its log.
watch_runs() {
    e2e_dc logs --no-color scheduler 2>/dev/null | grep -c '_run_frps_supervisor_watch .* executed successfully'
}
watch_runs_reach() { LAST=$(watch_runs); [ "$LAST" -ge "$1" ] 2>/dev/null; }

# until_ok <seconds> <command...> — the command once a second until it succeeds; 1 at the deadline.
until_ok() {
    local deadline=$((SECONDS + $1))
    shift
    until "$@"; do
        [ "$SECONDS" -lt "$deadline" ] || return 1
        sleep 1
    done
}

# wait_polls <n> — until the supervisor has rewritten its status n more times (once a poll); 1 at
# the deadline. A change written before the call is taken over by the third poll at the latest:
# the first may have read the input before the change, the second notes it, the third acts.
wait_polls() {
    local last now seen=0 deadline=$((SECONDS + 10 * $1 + 10))
    last=$(sv_file heartbeat)
    while [ "$seen" -lt "$1" ]; do
        [ "$SECONDS" -lt "$deadline" ] || return 1
        sleep 1
        now=$(sv_file heartbeat)
        if [ -n "$now" ] && [ "$now" != "$last" ]; then seen=$((seen + 1)); last=$now; fi
    done
}

# dep_ids — "server=<id> ca-issuer=<id>", the running containers of both; "-" for one not running.
dep_ids() {
    local s c
    s=$(e2e_dc ps -q server 2>/dev/null); c=$(e2e_dc ps -q ca-issuer 2>/dev/null)
    s=${s:0:12}; c=${c:0:12}
    echo "server=${s:--} ca-issuer=${c:--}"
}

frps_takeover() {
    local token bind body config_id t0 mark pid toml new notices source_id runs deps

    # A device certificate of its own: 8b replaced the first one and revoked the second.
    token=$(e2e_dc exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')
    openssl ecparam -name prime256v1 -genkey -noout -out "$E2E_WORK/client3.key" 2>/dev/null
    openssl req -new -key "$E2E_WORK/client3.key" -subj "/CN=itest" -out "$E2E_WORK/client3.csr" 2>/dev/null
    if [ -z "$token" ] || ! enroll "$token" client3; then
        bad "frps: could not enroll a device for the API calls"; return
    fi
    e2e_login "${CERT3[@]}"; JWT3=$E2E_JWT
    [ -n "$JWT3" ] || { bad "frps: login with the new device failed ($E2E_LOGIN_ERR)"; return; }

    # frps as built from apps/frps, and the scheduler, whose job turns supervisor events into
    # notifications. --no-deps: without it compose rebuilds server and ca-issuer and may recreate
    # both, and the gateway re-resolves its upstreams only every 30 s, so the next API call can
    # hit the old address. Everything both need already runs since the gateway came up.
    deps=$(dep_ids)
    [[ $deps != *=-* ]] || { bad "frps: server or ca-issuer not running before frps starts ($deps)"; return; }
    if ! e2e_dc up -d --no-deps --build frps scheduler >"$E2E_WORK/frps-up.log" 2>&1; then
        bad "frps/scheduler did not come up"; tail -20 "$E2E_WORK/frps-up.log"; return
    fi
    new=$(dep_ids)
    if [ "$new" != "$deps" ]; then
        bad "frps: starting frps and the scheduler recreated or stopped server or ca-issuer ($deps -> $new)"
        tail -20 "$E2E_WORK/frps-up.log"; return
    fi
    e2e_dc exec -T ca-issuer cat /app/frps-certs/ca.crt >"$E2E_WORK/frps-ca.crt" 2>/dev/null
    FRPS_LEAF=$(e2e_dc exec -T ca-issuer cat /app/frps-certs/frps.crt 2>/dev/null \
        | openssl x509 -outform DER 2>/dev/null | sha256sum | cut -d' ' -f1) || FRPS_LEAF=""
    if [ ! -s "$E2E_WORK/frps-ca.crt" ] || [ -z "$FRPS_LEAF" ]; then
        bad "frps: no TLS material in frps-certs"; return
    fi
    # The bind port the server reports (FRP_BIND_PORT), and where compose publishes it.
    bind=$(api GET /api/frp/supervisor-status | json_get publishedBindPort)
    FRPS_PORT=$(e2e_dc port frps "${bind:-none}" 2>/dev/null | head -1)
    FRPS_PORT=${FRPS_PORT##*:}
    if [ -z "$bind" ] || [ -z "$FRPS_PORT" ]; then
        bad "frps: bind port '$bind' not published (host port '$FRPS_PORT')"; return
    fi

    # a. Up before any FRP config: the supervisor waits, frps itself does not run.
    if until_ok 60 sv_api_is "waiting config_missing false"; then
        ok "frps container up before any FRP config, supervisor waiting (config_missing)"
    else
        bad "frps supervisor not waiting before any FRP config (saw '$LAST')"
        e2e_dc logs --tail 20 frps; return
    fi
    tls_silent && ok "before any FRP config nothing answers TLS on :$FRPS_PORT ($LAST)" \
        || bad "TLS on :$FRPS_PORT before any FRP config ('$LAST')"
    pid=$(frps_pid) || pid="pidof-failed"
    [ -z "$pid" ] && ok "no frps process before any FRP config" || bad "frps runs before any FRP config (pid $pid)"

    # b. The config created, with the dashboard: within 20 s frps answers TLS with the leaf of
    #    frps-certs, run from the checked copy of the chain in frps-active, and within 20 s more
    #    the status view has the proxy lists the supervisor fetched from the dashboard.
    body="{\"name\":\"itest-frps\",\"server_addr\":\"localhost\",\"bind_port\":$bind"
    body+=",\"dashboard_port\":7500,\"dashboard_user\":\"itest\",\"dashboard_password\":\"$(openssl rand -hex 16)\"}"
    config_id=$(api POST /api/frp/server-config "$body" | json_get id)
    [ -n "$config_id" ] || { bad "frps: creating the FRP config failed"; return; }
    t0=$SECONDS
    if until_ok 20 tls_answers; then
        ok "frps answers TLS on :$FRPS_PORT $((SECONDS - t0)) s after the config, leaf of frps-certs, chain to its ca.crt"
    else
        bad "frps did not answer TLS within 20 s of the config ('$LAST')"
        e2e_dc logs --tail 20 frps; return
    fi
    # shellcheck disable=SC2016 # expanded by the container's sh
    e2e_dc exec -T frps sh -c 'cd /var/lib/frps-active/current \
        && for f in frps.crt frps.key ca.crt; do cmp -s "$f" "/etc/frp-pki/$f" || exit 1; done \
        && grep -qx "certFile = \"/var/lib/frps-active/current/frps.crt\"" frps.toml' >/dev/null 2>&1 \
        && ok "the checked copy in frps-active holds the PEM chain of frps-certs, frps.toml points at it" \
        || bad "frps-active/current does not hold the PEM chain of frps-certs"
    until_ok 10 sv_api_is "running none false" && ok "supervisor state running" \
        || bad "supervisor state after the config: '$LAST'"
    # The server cannot reach the dashboard on frpedge: the supervisor fetches the lists over
    # loopback every poll, the server reads them from frps-state while they are fresh.
    t0=$SECONDS
    if until_ok 20 frp_status_ok; then
        ok "GET /api/frp/status without an error $((SECONDS - t0)) s after frps runs ($LAST)"
    else
        bad "GET /api/frp/status 20 s after frps runs: '$LAST'"
    fi

    # c. The same config again: the server rewrites frps.toml (new inode, same bytes), and over
    #    the polls that would take a change over frps keeps running, without an event.
    mark=$(sv_file mark); pid=$(frps_pid); toml=$(toml_id)
    api PUT "/api/frp/server-config/$config_id" "$body" >/dev/null || { bad "frps: identical PUT failed"; return; }
    new=$(toml_id)
    [ -n "$toml" ] && [ -n "$new" ] && [ "${new#* }" = "${toml#* }" ] && [ "${new%% *}" != "${toml%% *}" ] \
        && ok "identical PUT rewrote frps.toml with the same content" \
        || bad "identical PUT: frps.toml '$toml' -> '$new' (expected a new inode, the same sha256)"
    wait_polls 3 || { bad "frps supervisor stopped polling"; return; }
    LAST=$(sv_file since "$mark"); new=$(frps_pid)
    [ -n "$mark" ] && [ "$LAST" = "=" ] && [ -n "$pid" ] && [ "$new" = "$pid" ] \
        && ok "identical PUT: no restart (event seq unchanged, frps pid $pid)" \
        || bad "identical PUT restarted frps (events since '$mark': '$LAST', pid $pid -> $new)"

    # d. A new token: exactly one restart (one event, applied with tokenChanged) and one
    #    notification for it, which says that agent tunnels take a while.
    mark=$(sv_file mark); pid=$(frps_pid)
    notices=$(frps_notices) || { bad "frps: notifications not readable"; return; }
    api PUT "/api/frp/server-config/$config_id" "{\"auth_token\":\"$(openssl rand -hex 16)\"}" >/dev/null \
        || { bad "frps: PUT with a new token failed"; return; }
    until_ok 30 sv_has_new "$mark" || { bad "no supervisor event within 30 s of the new token"; return; }
    source_id="${mark% *}:$((${mark#* } + 1))"
    if until_ok 45 notice_for "$source_id"; then
        ok "a notification for the restart ($source_id) reached the admin"
    else
        bad "no notification for $source_id within 45 s (frps notices: '$LAST')"
        e2e_dc logs --tail 20 scheduler
    fi
    wait_polls 2 || { bad "frps supervisor stopped polling"; return; }
    LAST=$(sv_file since "$mark"); new=$(frps_pid)
    [ "$LAST" = "=applied:none:true" ] && [ -n "$new" ] && [ "$new" != "$pid" ] \
        && ok "new token: exactly one restart (applied, tokenChanged; pid $pid -> $new)" \
        || bad "new token: events since '$mark': '$LAST' (expected one applied with tokenChanged), pid $pid -> $new"
    # Still one after a further run of the watch job, which would write a second. The run that
    # wrote the row may not have logged its end yet, hence two more ends than now.
    runs=$(watch_runs)
    until_ok 45 watch_runs_reach $((runs + 2)) \
        || bad "the frps watch job did not run again within 45 s (ended runs: $runs, then '$LAST')"
    new=$(comm -13 <(sort <<<"$notices") <(frps_notices | sort))
    [ "$new" = "$source_id lifecycle.frp.server.applied agent-hint" ] \
        && ok "new token: exactly one notification, with the agent tunnel hint" \
        || bad "new token: new frps notifications '$new'"
    until_ok 10 tls_answers && ok "frps answers TLS again after the restart" \
        || bad "frps does not answer TLS after the restart ('$LAST')"

    # e. An invalid certificate file in frps-certs: rejected, frps runs on from its last valid
    #    copy (degraded), still answers TLS with that leaf, as the same process.
    mark=$(sv_file mark); pid=$(frps_pid)
    e2e_dc exec -T ca-issuer sh -c 'printf "%s\n" "-----BEGIN CERTIFICATE-----" "bm90IGEgY2VydGlmaWNhdGU=" \
        "-----END CERTIFICATE-----" > /app/frps-certs/frps.crt' \
        || { bad "frps: could not write the invalid certificate"; return; }
    if until_ok 40 sv_api_is "degraded cert_missing false"; then
        ok "invalid frps.crt in frps-certs: supervisor degraded (cert_missing)"
    else
        bad "invalid frps.crt: supervisor state '$LAST', expected degraded cert_missing"
    fi
    wait_polls 2 || { bad "frps supervisor stopped polling"; return; }
    LAST=$(sv_file since "$mark")
    [ "$LAST" = "=rejected:cert_missing:false" ] && ok "invalid frps.crt: rejected once, no restart" \
        || bad "invalid frps.crt: events since '$mark': '$LAST'"
    tls_answers && [ -n "$pid" ] && [ "$(frps_pid)" = "$pid" ] \
        && ok "frps still answers TLS with the last valid leaf, same process (pid $pid)" \
        || bad "frps after the invalid frps.crt: TLS '$LAST', pid $pid -> $(frps_pid)"

    # f. The config deleted: frps stops, the bind port answers no more.
    mark=$(sv_file mark)
    api DELETE "/api/frp/server-config/$config_id" >/dev/null || { bad "frps: deleting the FRP config failed"; return; }
    until_ok 30 tls_silent && ok "after the delete nothing answers TLS on :$FRPS_PORT ($LAST)" \
        || bad "frps still answers on :$FRPS_PORT 30 s after the delete ('$LAST')"
    until_ok 10 sv_api_is "stopped config_missing false" && ok "supervisor state stopped (config_missing)" \
        || bad "supervisor state after the delete: '$LAST'"
    wait_polls 2 || { bad "frps supervisor stopped polling"; return; }
    LAST=$(sv_file since "$mark"); pid=$(frps_pid) || pid="pidof-failed"
    [ "$LAST" = "=stopped:config_missing:false" ] && [ -z "$pid" ] && ok "delete: one stopped event, no frps process" \
        || bad "delete: events since '$mark': '$LAST', frps pid '$pid'"
}
frps_takeover

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

# ── 13. Processes of app in server, scheduler, ca-issuer and monitoring are not dumpable ──
# Their images leave every ELF program in the bin directories and below /usr/lib/postgresql for
# anyone but root to execute only (the last RUN of each Dockerfile). A process the entrypoint
# starts as app through gosu runs from a program its user cannot read, so it is not dumpable and
# the entries in /proc/<pid> are root's.
# Checked from inside each container, as root, once PID 1 runs the service as app: before
# that the entrypoint is still at work, and a look at /proc would catch whichever helper it
# runs at that moment. A readable copy of sleep, started the same way, shows the check can fail.
APP_UID=10001
APP_SERVICES=(server scheduler ca-issuer monitoring)
# The directories whose ELF programs the step of the Dockerfiles leaves execute-only; one an
# image lacks (ca-issuer has no /usr/lib/postgresql) is skipped, as the step skips it.
EXEC_ONLY_DIRS=(/usr/local/bin /usr/local/sbin /usr/bin /usr/sbin /usr/lib/postgresql)

# app_procs <service> — "<pid> <owner of /proc/<pid>/status> <name>" for each process of app
# (Uid APP_UID) in the service; non-zero when the exec fails.
app_procs() {
    local out pid uid owner name
    # shellcheck disable=SC2016 # expanded by the container's sh
    out=$(e2e_dc exec -T "$1" sh -c 'for d in /proc/[0-9]*; do
        s=$(cat "$d/status" 2>/dev/null) && o=$(stat -c %u:%g "$d/status" 2>/dev/null) || continue
        printf "%s\n" "$s" | { n=; u=
            while read -r k v; do case $k in Name:) n=$v ;; Uid:) u=${v%%[!0-9]*} ;; esac; done
            echo "${d#/proc/} $u $o $n"; }
    done' 2>/dev/null) || return 1
    while read -r pid uid owner name; do
        [ "$uid" != "$APP_UID" ] || echo "$pid $owner $name"
    done <<<"$out"
}

# app_started — LAST: the services in which PID 1 is not yet a process of app other than the
# entrypoint's sh; 0 when there is none.
app_started() {
    local svc
    LAST=""
    for svc in "${APP_SERVICES[@]}"; do
        app_procs "$svc" | awk '$1 == 1 && $3 != "sh" { found = 1 } END { exit !found }' || LAST+=" $svc"
    done
    [ -z "$LAST" ]
}

# elf_modes <service> — "<mode> <path>" for each ELF file with an x bit in those of EXEC_ONLY_DIRS
# the service has; non-zero when the exec, find, head or stat fails or it has none of them.
elf_modes() {
    # shellcheck disable=SC2016 # expanded by the container's sh
    e2e_dc exec -T "$1" sh -c 'for d; do shift; if [ -d "$d" ]; then set -- "$@" "$d"; fi; done
        [ "$#" -gt 0 ] || exit 1
        elf=$(printf "\177ELF"); files=$(find "$@" -type f -perm /111) || exit 1
        printf "%s\n" "$files" | while IFS= read -r f; do
            m=$(head -c 4 "$f") || exit 1
            [ "$m" != "$elf" ] || stat -c "%a %n" "$f" || exit 1
        done' _ "${EXEC_ONLY_DIRS[@]}" 2>/dev/null
}

copy_seen() { LAST=$(app_procs server | awk '$3 == "sleep-readable"'); [ -n "$LAST" ]; }

app_not_dumpable() {
    local svc procs others modes mode path readable n gid copy=/tmp/sleep-readable

    # server and ca-issuer run since the gateway came up, victoria since 12, the scheduler since
    # 11b unless that stopped before it; --no-deps as in 11b, so neither server nor ca-issuer is
    # recreated.
    if ! e2e_dc up -d --no-deps --build scheduler monitoring >"$E2E_WORK/app-up.log" 2>&1; then
        bad "scheduler/monitoring did not come up"; tail -20 "$E2E_WORK/app-up.log"; return
    fi
    if ! until_ok 60 app_started; then
        bad "within 60 s PID 1 did not become a process of app (UID $APP_UID) other than the entrypoint's" \
            "sh in:$LAST"
        return
    fi

    for svc in "${APP_SERVICES[@]}"; do
        # a. Every process of app has /proc/<pid>/status owned by root.
        if ! procs=$(app_procs "$svc"); then
            bad "$svc: could not read the processes"
        elif others=$(awk '$2 != "0:0"' <<<"$procs" | paste -sd ';') && [ -n "$procs" ] && [ -z "$others" ]; then
            ok "$svc: processes of app: $(wc -l <<<"$procs")" \
                "($(awk '{ print $3 }' <<<"$procs" | sort -u | paste -sd ' ')), each /proc/<pid>/status owned by 0:0"
        else
            bad "$svc: processes of app whose /proc/<pid>/status is not 0:0 (pid owner name): ${others:-none of app}"
        fi
        # b. No ELF program with an x bit in EXEC_ONLY_DIRS is readable by group or others.
        if ! modes=$(elf_modes "$svc"); then
            bad "$svc: could not list the programs in ${EXEC_ONLY_DIRS[*]}"; continue
        fi
        n=0 readable=()
        while read -r mode path; do
            [ -n "$mode" ] || continue
            n=$((n + 1))
            if (( 8#$mode & 8#044 )); then readable+=("$path ($mode)"); fi
        done <<<"$modes"
        if [ "$n" -gt 0 ] && [ "${#readable[@]}" -eq 0 ]; then
            ok "$svc: none of its $n ELF programs in ${EXEC_ONLY_DIRS[*]} is readable by group or others"
        else
            bad "$svc: ${#readable[@]} of $n ELF programs in ${EXEC_ONLY_DIRS[*]} readable by group or others" \
                "(first ones: ${readable[*]:0:5})"
        fi
    done

    # Counter-check in server: started the same way from a readable copy of sleep, a process of
    # app keeps /proc/<pid>/status as its own, so the check above can fail.
    gid=$(e2e_dc exec -T server id -g app 2>/dev/null | tr -d '\r\n')
    # shellcheck disable=SC2016 # expanded by the container's sh
    if ! e2e_dc exec -T server sh -c 'cp /usr/bin/sleep "$1" && chmod 0755 "$1"' _ "$copy" >/dev/null 2>&1 \
        || ! e2e_dc exec -d -T server gosu app:app "$copy" 120 >/dev/null 2>&1; then
        bad "server: could not start a readable copy of sleep as app"; return
    fi
    if ! until_ok 10 copy_seen; then
        bad "server: the readable copy of sleep did not show up as a process of app"
    elif [ "${LAST#* }" = "$APP_UID:$gid sleep-readable" ]; then
        ok "counter-check: a readable copy of sleep started through gosu keeps /proc/<pid>/status as $APP_UID:$gid"
    else
        bad "counter-check: the readable copy of sleep has '$LAST', expected $APP_UID:$gid" \
            "— the check could not fail"
    fi
    # shellcheck disable=SC2016 # expanded by the container's sh
    e2e_dc exec -T server sh -c 'kill "$1"; rm -f "$2"' _ "${LAST%% *}" "$copy" >/dev/null 2>&1
}
app_not_dumpable

# ── 14. Limits, capabilities, the passphrase secret and frpedge in the running stack ──
# What docker-compose.yml sets has to hold on the containers and networks compose created:
# every service with no-new-privileges and its process limit, the gateway's nginx master with
# only the capabilities of its cap_add list and workers that are not root, ping as app in
# monitoring, the CA root passphrase as a file in the ca-issuer and not in its environment, and
# frpedge without IP masquerading. Compared with the values `docker compose config` resolves
# for this project (overlay included), not with numbers repeated here.
CFG=""   # `docker compose config --format json` of the project; holds the .env's secrets, never printed

# cfg_pids_limits — "<service> <pids_limit>" for each service in CFG; "-" for a service without a
# positive integer limit.
cfg_pids_limits() {
    python3 -c '
import json, sys
for name, svc in sorted(json.load(sys.stdin)["services"].items()):
    limit = svc.get("pids_limit")
    print(name, limit if type(limit) is int and limit > 0 else "-")' <<<"$CFG" 2>/dev/null
}

# cfg_cap_mask <service> — the cap_add list of the service in CFG as /proc/<pid>/status shows a
# set of capabilities (16 hex digits); empty when the list names one it does not know.
cfg_cap_mask() {
    python3 -c '
import json, sys
# The bit of each capability is its index here (linux/capability.h).
bits = """CHOWN DAC_OVERRIDE DAC_READ_SEARCH FOWNER FSETID KILL SETGID SETUID SETPCAP LINUX_IMMUTABLE
    NET_BIND_SERVICE NET_BROADCAST NET_ADMIN NET_RAW IPC_LOCK IPC_OWNER SYS_MODULE SYS_RAWIO SYS_CHROOT
    SYS_PTRACE SYS_PACCT SYS_ADMIN SYS_BOOT SYS_NICE SYS_RESOURCE SYS_TIME SYS_TTY_CONFIG MKNOD LEASE
    AUDIT_WRITE AUDIT_CONTROL SETFCAP MAC_OVERRIDE MAC_ADMIN SYSLOG WAKE_ALARM BLOCK_SUSPEND AUDIT_READ
    PERFMON BPF CHECKPOINT_RESTORE""".split()
svc = json.load(sys.stdin)["services"][sys.argv[1]]
caps = [c.upper().removeprefix("CAP_") for c in svc.get("cap_add") or []]
if all(c in bits for c in caps):
    print("%016x" % sum(1 << bits.index(c) for c in caps))' "$1" <<<"$CFG" 2>/dev/null
}

# pid1 <service> <field> — the value of the field in /proc/1/status in the service; empty when the
# exec fails or the field is missing.
pid1() {
    e2e_dc exec -T "$1" cat /proc/1/status 2>/dev/null | awk -v f="$2:" '$1 == f { print $2 }'
}

# gateway_procs — "<name> <ppid> <uid>,<euid>,<suid>,<fsuid>" for each process in the gateway.
gateway_procs() {
    # shellcheck disable=SC2016 # expanded by the container's sh and its awk
    e2e_dc exec -T gateway sh -c 'for s in /proc/[0-9]*/status; do awk "$1" "$s" 2>/dev/null; done' _ \
        '/^Name:/ { n = $2 } /^PPid:/ { p = $2 } /^Uid:/ { u = $2 "," $3 "," $4 "," $5 }
         END { if (n != "") print n, p, u }' 2>/dev/null
}

# env_lines <service> — the Config.Env of the service's container, one entry per line. Holds
# secrets: only compared, never printed.
env_lines() {
    local id
    id=$(e2e_dc ps -q "$1" 2>/dev/null)
    [ -n "$id" ] || return 1
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$id" 2>/dev/null
}

# net_masq <network> — the masquerade option of the project network compose calls <network>,
# empty when the network does not set it; non-zero unless exactly one such network exists.
net_masq() {
    local ids
    ids=$(docker network ls -q --filter "label=com.docker.compose.project=$E2E_PROJECT" \
        --filter "label=com.docker.compose.network=$1" 2>/dev/null)
    [ -n "$ids" ] && [ "$(wc -l <<<"$ids")" = 1 ] || return 1
    docker network inspect --format '{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}' \
        "$ids" 2>/dev/null
}

compose_limits() {
    local svc down=() names=() limits=() i id nnp have want name capeff workers root image
    local issuer_env server_env frpedge default none="<not exactly one network>"

    # The scheduler and monitoring run since 13 unless that stopped before it; --no-deps as in
    # 11b, so neither server nor ca-issuer is recreated.
    for svc in scheduler monitoring; do
        [ -n "$(e2e_dc ps -q --status running "$svc" 2>/dev/null)" ] || down+=("$svc")
    done
    if [ "${#down[@]}" -gt 0 ] \
        && ! e2e_dc up -d --no-deps --build "${down[@]}" >"$E2E_WORK/limits-up.log" 2>&1; then
        bad "${down[*]} did not come up"; tail -20 "$E2E_WORK/limits-up.log"; return
    fi
    CFG=$(e2e_dc config --format json 2>/dev/null)
    while read -r svc want; do
        [ -n "$svc" ] || continue
        names+=("$svc"); limits+=("$want")
    done <<<"$(cfg_pids_limits)"
    [ "${#names[@]}" -gt 0 ] || { bad "docker compose config listed no services"; return; }

    # a. Every service of the compose file runs with no-new-privileges and its process limit.
    for i in "${!names[@]}"; do
        svc=${names[$i]}; want=${limits[$i]}
        # db-init runs once before the services and has exited by now: its container keeps the
        # options it ran with, and its exit code says the roles are in place.
        if [ "$svc" = db-init ]; then
            id=$(e2e_dc ps -aq --status exited "$svc" 2>/dev/null)
            have=$(docker inspect --format '{{.State.ExitCode}} {{.HostConfig.PidsLimit}} {{json .HostConfig.SecurityOpt}}' \
                "$id" 2>/dev/null)
            if [ "$want" != - ] && [ "$have" = "0 $want [\"no-new-privileges:true\"]" ]; then
                ok "$svc: exited 0, ran with no-new-privileges and pids limit $want as in the compose config"
            else
                bad "$svc: exit, pids limit, security options '$have' (expected '0 $want [\"no-new-privileges:true\"]')"
            fi
            continue
        fi
        id=$(e2e_dc ps -q --status running "$svc" 2>/dev/null)
        if [ -z "$id" ]; then
            bad "$svc: not running, its limits unchecked"; continue
        fi
        nnp=$(pid1 "$svc" NoNewPrivs)
        have=$(docker inspect --format '{{.HostConfig.PidsLimit}}' "$id" 2>/dev/null)
        if [ "$nnp" = 1 ] && [ "$want" != - ] && [ "$have" = "$want" ]; then
            ok "$svc: PID 1 with NoNewPrivs 1, pids limit $have as in the compose config"
        else
            bad "$svc: NoNewPrivs '$nnp' (expected 1), pids limit '$have' (compose config: '$want')"
        fi
    done
    # Counter-check: the gateway's image outside the project without any option, cat as PID 1
    # reading its own status.
    image=$(docker inspect --format '{{.Image}}' "$(e2e_dc ps -q gateway 2>/dev/null)" 2>/dev/null)
    nnp=$(docker run --rm --network none --entrypoint cat "$image" /proc/1/status 2>/dev/null \
        | awk '$1 == "NoNewPrivs:" { print $2 }')
    [ "$nnp" = 0 ] && ok "counter-check: a container of the gateway image without the options has NoNewPrivs 0" \
        || bad "counter-check: a container of the gateway image without the options has NoNewPrivs '$nnp'" \
            "(expected 0) — the check above could not fail"

    # b. The gateway's nginx master keeps exactly its cap_add list; its workers are not root.
    want=$(cfg_cap_mask gateway)
    name=$(pid1 gateway Name); capeff=$(pid1 gateway CapEff)
    [ "$name" = nginx ] && [ -n "$want" ] && [ "$capeff" = "$want" ] \
        && ok "gateway: nginx master (PID 1) with CapEff $capeff, the cap_add list of the compose config" \
        || bad "gateway: PID 1 '$name' with CapEff '$capeff', expected nginx with '$want' (cap_add)"
    workers=$(gateway_procs | awk '$1 == "nginx" && $2 == 1 { print $3 }')
    root=$(grep -E '(^|,)0(,|$)' <<<"$workers")
    [ -n "$workers" ] && [ -z "$root" ] \
        && ok "gateway: $(wc -l <<<"$workers") nginx workers, none with UID 0 ($(sort -u <<<"$workers" | paste -sd ' '))" \
        || bad "gateway: nginx workers (uid,euid,suid,fsuid) '$(paste -sd ' ' <<<"$workers")', expected some, none with 0"

    # c. monitoring: ping as app under no-new-privileges, over the ICMP datagram socket the
    #    service's ping_group_range allows.
    e2e_dc exec -T monitoring gosu app:app ping -c1 -W2 127.0.0.1 >/dev/null 2>&1 \
        && ok "monitoring: ping as app reaches 127.0.0.1 under no-new-privileges" \
        || bad "monitoring: ping as app failed under no-new-privileges"

    # d. ca-issuer: the passphrase as a secret file, not in the container's environment.
    issuer_env=$(env_lines ca-issuer); server_env=$(env_lines server)
    if [ -z "$issuer_env" ]; then
        bad "ca-issuer: could not read Config.Env"
    elif grep -q '^CA_ROOT_PASSPHRASE=' <<<"$issuer_env"; then
        bad "ca-issuer: CA_ROOT_PASSPHRASE is in the container's environment"
    elif ! grep -qx 'CA_ROOT_PASSPHRASE_FILE=/run/secrets/ca_root_passphrase' <<<"$issuer_env"; then
        bad "ca-issuer: no CA_ROOT_PASSPHRASE_FILE=/run/secrets/ca_root_passphrase in Config.Env"
    elif ! e2e_dc exec -T ca-issuer test -s /run/secrets/ca_root_passphrase >/dev/null 2>&1; then
        bad "ca-issuer: /run/secrets/ca_root_passphrase is missing or empty"
    else
        ok "ca-issuer: CA_ROOT_PASSPHRASE not in Config.Env, CA_ROOT_PASSPHRASE_FILE points at" \
            "/run/secrets/ca_root_passphrase, which is not empty"
    fi
    grep -q '^SECRET_KEY=' <<<"$server_env" \
        && ok "counter-check: the same read of Config.Env finds SECRET_KEY in the server's" \
        || bad "counter-check: no SECRET_KEY in the server's Config.Env — the check above could not fail"

    # e. frpedge without IP masquerading; the default network keeps it (option unset or true).
    frpedge=$(net_masq frpedge) || frpedge=$none
    default=$(net_masq default) || default=$none
    [ "$frpedge" = false ] && { [ -z "$default" ] || [ "$default" = true ]; } \
        && ok "frpedge: com.docker.network.bridge.enable_ip_masquerade false; the default network keeps masquerading (${default:-unset})" \
        || bad "enable_ip_masquerade: frpedge '$frpedge' (expected false), default '$default' (expected unset or true)"
}
compose_limits

# ── 15. The server takes the client address from the gateway and from no one else ──
# Compose has the server trust the forwarded header of the gateway by name
# (TRUSTED_PROXIES=gateway): a login through the gateway is recorded with the address of the
# client the gateway saw, not the gateway's own, and a peer other than the gateway cannot set the
# address with an X-Forwarded-For of its own. Seen in the audit log, where a failed login leaves
# auth.login_failed with that address in source_ip.
# The server looks the name up in a thread of each uvicorn worker, started by the worker's first
# request that asks for the client address, and then every 30 s; until the first lookup has come
# back, and for up to 30 s after the gateway took a new address, the gateway's own address
# counts. Whether that has happened by now must not rest on what steps 1-14 sent: the stack runs
# one worker, and logins through the gateway, which ask for the address, go first until one is
# recorded with a client address, for longer than the 30 s between two lookups. Only then do the
# checks run; a server that never takes the gateway's header fails at that deadline.
CERT4=(--cert "$E2E_WORK/client4-fullchain.pem" --key "$E2E_WORK/client4.key")
GATEWAY_IP=""   # the gateway's address in the project's default network

# audit_last <action> — "<id> <source_ip>" of the newest audit_log row with that action, the
# source_ip empty when the row has none; empty without such a row or when psql fails.
audit_last() {
    e2e_dc exec -T postgres psql -U adminhelper -d adminhelper -tA -F ' ' -c \
        "SELECT id, coalesce(source_ip, '') FROM audit_log WHERE action = '$1' ORDER BY id DESC LIMIT 1" \
        2>/dev/null
}

# client_login_seen — one admin login through the gateway; true when the auth.login row it wrote
# holds an address other than the gateway's. LAST: that row, or why there is none.
client_login_seen() {
    local before
    before=$(audit_last auth.login)
    e2e_login "${CERT4[@]}" || { LAST="login failed: $E2E_LOGIN_ERR"; return 1; }
    LAST=$(audit_last auth.login)
    if [ -z "$LAST" ] || [ "${LAST%% *}" = "${before%% *}" ]; then
        LAST="no new auth.login row ('$LAST')"; return 1
    fi
    [ -n "${LAST#* }" ] && [ "${LAST#* }" != "$GATEWAY_IP" ]
}

client_address() {
    local server_env token before row code scheduler

    GATEWAY_IP=$(default_ip gateway)
    [ -n "$GATEWAY_IP" ] || { bad "client address: the gateway has no address in the default network"; return; }
    # One worker, so the logins before the checks reach the resolver the checks reach.
    server_env=$(env_lines server)
    grep -qx 'WEB_CONCURRENCY=1' <<<"$server_env" \
        || { bad "client address: the server runs without WEB_CONCURRENCY=1, the logins before the checks may reach another worker"; return; }

    # A device certificate of its own, as in 11b: 8b replaced the first one and revoked the second.
    token=$(e2e_dc exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')
    openssl ecparam -name prime256v1 -genkey -noout -out "$E2E_WORK/client4.key" 2>/dev/null
    openssl req -new -key "$E2E_WORK/client4.key" -subj "/CN=itest" -out "$E2E_WORK/client4.csr" 2>/dev/null
    if [ -z "$token" ] || ! enroll "$token" client4; then
        bad "client address: could not enroll a device for the logins"; return
    fi
    until_ok 40 client_login_seen || {
        bad "client address: no login through the gateway within 40 s recorded with an address other than" \
            "the gateway's $GATEWAY_IP (last: '$LAST')"
        return
    }

    # a. A failed login through the gateway: auth.login_failed with the client's address.
    before=$(audit_last auth.login_failed)
    code=$(curl -k -s "${CERT4[@]}" -o /dev/null -w '%{http_code}' --max-time 5 \
        -X POST "$E2E_SERVER_URL/api/auth/login" -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"not-the-password"}' 2>/dev/null || echo 000)
    row=$(audit_last auth.login_failed)
    if [ "$code" = 401 ] && [ -n "$row" ] && [ "${row%% *}" != "${before%% *}" ] \
        && [ -n "${row#* }" ] && [ "${row#* }" != "$GATEWAY_IP" ]; then
        ok "a failed login through the gateway (401) is recorded from the client (${row#* }), not the gateway ($GATEWAY_IP)"
    else
        bad "failed login through the gateway: HTTP '$code', newest auth.login_failed '$row' (before: '$before')," \
            "expected 401 and a new row with an address other than the gateway's $GATEWAY_IP"
    fi

    # b. Counter-check: the same login straight to server:8080 from the scheduler, with an
    #    X-Forwarded-For of its own, is recorded with the scheduler's address. Without a client
    #    certificate the enforced server refuses it with 403 before the password (R-0900).
    scheduler=$(default_ip scheduler)
    [ -n "$scheduler" ] || { bad "client address: the scheduler has no address in the default network"; return; }
    before=$(audit_last auth.login_failed)
    code=$(e2e_dc exec -T scheduler python -c '
import json, urllib.error, urllib.request
req = urllib.request.Request(
    "http://server:8080/api/auth/login",
    data=json.dumps({"username": "admin", "password": "not-the-password"}).encode(),
    headers={"Content-Type": "application/json", "X-Forwarded-For": "203.0.113.9"},
)
try:
    print(urllib.request.urlopen(req, timeout=10).status)
except urllib.error.HTTPError as e:
    print(e.code)' 2>/dev/null)
    row=$(audit_last auth.login_failed)
    if [ "$code" = 403 ] && [ -n "$row" ] && [ "${row%% *}" != "${before%% *}" ] && [ "${row#* }" = "$scheduler" ]; then
        ok "counter-check: the same login from the scheduler with X-Forwarded-For 203.0.113.9 is recorded" \
            "from the scheduler ($scheduler)"
    else
        bad "login from the scheduler with X-Forwarded-For 203.0.113.9: HTTP '$code', newest auth.login_failed" \
            "'$row' (before: '$before'), expected 403 and a new row from the scheduler's $scheduler"
    fi
}
client_address

# ── 16. Each service connects with its own Postgres role ─────────────────────
# db-init (app.db_roles setup) gives every service a login role without superuser rights; only
# the bootstrap account of the postgres image stays superuser. The server and the ca-issuer hold
# pooled sessions by now (steps 1-15 went through both), and ah_ca reads only the tables of the
# PKI: the users table is refused, while ah_server reads it.
pg_q() {  # pg_q <role> <sql> — tuples only; stderr folded in, so a refusal is visible
    e2e_dc exec -T postgres psql -U "$1" -d adminhelper -tA -v ON_ERROR_STOP=1 -c "$2" 2>&1
}
db_roles() {
    local supers sessions denied allowed
    supers=$(pg_q adminhelper "SELECT string_agg(rolname, ',' ORDER BY rolname) FROM pg_catalog.pg_roles
        WHERE rolsuper AND rolcanlogin AND rolname <> 'adminhelper'")
    [ -z "$supers" ] && ok "no login role but the bootstrap account is superuser" \
        || bad "superuser login roles besides adminhelper: '$supers'"
    sessions=$(pg_q adminhelper "SELECT string_agg(DISTINCT usename, ',' ORDER BY usename) FROM pg_catalog.pg_stat_activity
        WHERE datname = 'adminhelper' AND usename IN ('ah_server', 'ah_ca')")
    [ "$sessions" = "ah_ca,ah_server" ] && ok "server and ca-issuer are connected as ah_server and ah_ca" \
        || bad "sessions of ah_server/ah_ca in pg_stat_activity: '$sessions'"
    allowed=$(pg_q ah_server "SELECT count(*) >= 0 FROM public.users")
    [ "$allowed" = t ] && ok "ah_server reads the users table" || bad "ah_server on users: '$allowed'"
    denied=$(pg_q ah_ca "SELECT count(*) FROM public.users")
    case $denied in
        *"permission denied for table users"*) ok "ah_ca is refused the users table" ;;
        *) bad "ah_ca on users: '$denied' (expected permission denied)" ;;
    esac
}
db_roles

# ── 17. Rotating the intermediates in the running stack (R-0667) ─────────────
# Last, because it changes the hierarchy every later step would see. A device enrolled
# before the rotation keeps working: client-ca.pem carries the retired intermediate, so its
# leaf alone (as a browser .p12 presents it) still gets through, and it renews under the
# new intermediate. After restarting ca-issuer (healthy) and then the gateway, the gateway
# presents a leaf of the new access intermediate, a fresh enrollment gets one too, and the
# frps trust bundle holds the old and the new tunnel intermediate.
health_of() { docker inspect --format '{{.State.Health.Status}}' "$(e2e_dc ps -q "$1" 2>/dev/null)" 2>/dev/null; }
issuer_cn() { openssl x509 -noout -issuer -nameopt multiline 2>/dev/null | sed -n 's/^ *commonName *= *//p'; }
# chain_cns — the subject CN of every certificate on stdin, in order, one per line.
chain_cns() {
    openssl crl2pkcs7 -nocrl -certfile /dev/stdin 2>/dev/null | openssl pkcs7 -print_certs -noout 2>/dev/null \
        | sed -n 's/^subject=.*CN *= *\([^,]*\).*/\1/p'
}
# reach <curl cert args…> — the status of a request without a JWT: 401 from the app means the
# gateway took the certificate, 400 that it refused it.
reach() { curl -k -s "$@" -o /dev/null -w '%{http_code}' --max-time 10 "$E2E_SERVER_URL/api/servers" 2>/dev/null || echo 000; }
# renew_issuer <fullchain> <key> <csr> — the issuer CN of the leaf /ca/renew returns, or the error.
renew_issuer() {
    python3 - "$E2E_SERVER_URL" "$1" "$2" "$3" <<'PY' | issuer_cn
import json, ssl, sys, urllib.request
base, chain, key, csr = sys.argv[1:5]
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
ctx.load_cert_chain(chain, key)
req = urllib.request.Request(f"{base}/ca/renew", data=json.dumps({"csr": open(csr).read()}).encode(),
    headers={"Content-Type": "application/json"})
body = json.load(urllib.request.urlopen(req, context=ctx, timeout=10))
print(body.get("fullchain") or body.get("cert") or "")
PY
}
gateway_takes_client5() {
    [ "$(reach --cert "$E2E_WORK/client5-fullchain.pem" --key "$E2E_WORK/client5.key")" = 401 ]
}
ca_rotation() {
    local token today status out leaf_only gw_issuer gw_chain frps_cns code
    today=$(date -u +%Y-%m-%d)
    token=$(e2e_dc exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')
    openssl ecparam -name prime256v1 -genkey -noout -out "$E2E_WORK/client5.key" 2>/dev/null
    openssl req -new -key "$E2E_WORK/client5.key" -subj "/CN=itest" -out "$E2E_WORK/client5.csr" 2>/dev/null
    if [ -z "$token" ] || ! enroll "$token" client5; then
        bad "rotation: could not enroll a device before the rotation"; return
    fi

    if out=$(e2e_dc run --rm --no-deps -T ca-issuer python -m app.cli status 2>&1); then
        ok "rotation: status before the rotation exits 0"
    else
        bad "rotation: status before the rotation: $out"; return
    fi
    if out=$(e2e_dc run --rm --no-deps -T ca-issuer python -m app.cli rotate-intermediates </dev/null 2>&1); then
        ok "rotation: rotate-intermediates exits 0 (passphrase from the secret file)"
    else
        bad "rotation: rotate-intermediates failed: $out"; return
    fi
    e2e_dc restart ca-issuer >/dev/null 2>&1
    until_ok 90 eval '[ "$(health_of ca-issuer)" = healthy ]' \
        || { bad "rotation: ca-issuer not healthy within 90 s after the restart"; return; }
    e2e_dc restart gateway >/dev/null 2>&1
    until_ok 60 gateway_takes_client5 \
        || { bad "rotation: the gateway does not take a device certificate within 60 s after its restart"; return; }

    # a. status lists one retired intermediate per scope.
    status=$(e2e_dc run --rm --no-deps -T ca-issuer python -m app.cli status 2>&1)
    if [ "$(grep -c '(retired)' <<<"$status")" = 3 ] && ! grep -q 'SKIPPED' <<<"$status"; then
        ok "rotation: status lists three retired intermediates"
    else
        bad "rotation: status after the rotation: $status"
    fi

    # b. The gateway presents a leaf of today's access intermediate, and the root third (T7).
    out=$(openssl s_client -connect "localhost:$E2E_HTTPS_PORT" -servername localhost -showcerts \
        -cert "$E2E_WORK/client5-fullchain.pem" -key "$E2E_WORK/client5.key" </dev/null 2>/dev/null)
    gw_issuer=$(issuer_cn <<<"$out")
    gw_chain=$(chain_cns <<<"$out")
    if [ "$gw_issuer" = "AdminHelper Access Intermediate $today" ] \
        && [ "$(sed -n 2p <<<"$gw_chain")" = "AdminHelper Access Intermediate $today" ] \
        && [ "$(sed -n 3p <<<"$gw_chain")" = "AdminHelper Root CA" ]; then
        ok "rotation: the gateway presents a leaf of '$gw_issuer', that intermediate and the root"
    else
        bad "rotation: the gateway's chain: $(tr '\n' ';' <<<"$gw_chain") (leaf issuer '$gw_issuer'), expected" \
            "a leaf of 'AdminHelper Access Intermediate $today', that intermediate and 'AdminHelper Root CA'"
    fi

    # c. The device enrolled before reaches the app with its fullchain and with its leaf alone.
    leaf_only="$E2E_WORK/client5-leaf.pem"
    openssl x509 -in "$E2E_WORK/client5-fullchain.pem" -out "$leaf_only" 2>/dev/null
    code=$(reach --cert "$E2E_WORK/client5-fullchain.pem" --key "$E2E_WORK/client5.key")
    [ "$code" = 401 ] && ok "rotation: a device enrolled before reaches the app with its fullchain (401 without JWT)" \
        || bad "rotation: a device enrolled before, fullchain: HTTP '$code', expected 401"
    code=$(reach --cert "$leaf_only" --key "$E2E_WORK/client5.key")
    [ "$code" = 401 ] && ok "rotation: ... and with its leaf alone (the retired intermediate is in client-ca.pem)" \
        || bad "rotation: a device enrolled before, leaf only: HTTP '$code', expected 401"

    # d. It renews, and the new leaf comes from today's access intermediate.
    out=$(renew_issuer "$E2E_WORK/client5-fullchain.pem" "$E2E_WORK/client5.key" "$E2E_WORK/client5.csr" 2>&1)
    [ "$out" = "AdminHelper Access Intermediate $today" ] && ok "rotation: /ca/renew with the old certificate gives a leaf of '$out'" \
        || bad "rotation: /ca/renew with the old certificate: '$out'"

    # e. A fresh enrollment gets a leaf of the new intermediate, which reaches the app.
    token=$(e2e_dc exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')
    openssl ecparam -name prime256v1 -genkey -noout -out "$E2E_WORK/client6.key" 2>/dev/null
    openssl req -new -key "$E2E_WORK/client6.key" -subj "/CN=itest" -out "$E2E_WORK/client6.csr" 2>/dev/null
    if [ -n "$token" ] && enroll "$token" client6; then
        out=$(issuer_cn < "$E2E_WORK/client6-fullchain.pem")
        code=$(reach --cert "$E2E_WORK/client6-fullchain.pem" --key "$E2E_WORK/client6.key")
        if [ "$out" = "AdminHelper Access Intermediate $today" ] && [ "$code" = 401 ]; then
            ok "rotation: a fresh enrollment gets a leaf of '$out' and reaches the app"
        else
            bad "rotation: fresh enrollment: issuer '$out', HTTP '$code'"
        fi
    else
        bad "rotation: a fresh enrollment after the rotation failed"
    fi

    # f. frps trusts the old and the new tunnel intermediate.
    e2e_dc exec -T ca-issuer cat /app/frps-certs/ca.crt > "$E2E_WORK/frps-ca.crt" 2>/dev/null
    frps_cns=$(chain_cns < "$E2E_WORK/frps-ca.crt")
    if grep -qx "AdminHelper Tunnel Intermediate $today" <<<"$frps_cns" \
        && [ "$(grep -c '^AdminHelper Tunnel Intermediate' <<<"$frps_cns")" -ge 2 ]; then
        ok "rotation: frps-certs/ca.crt holds the old and the new tunnel intermediate"
    else
        bad "rotation: frps-certs/ca.crt holds: $(tr '\n' ';' <<<"$frps_cns")"
    fi
}
ca_rotation

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "integration_stack_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
