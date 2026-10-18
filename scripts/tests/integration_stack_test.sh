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
    JWT3=$(curl -k -s "${CERT3[@]}" --max-time 5 -X POST "$E2E_SERVER_URL/api/auth/login" \
        -H 'Content-Type: application/json' \
        -d "{\"username\":\"admin\",\"password\":\"$E2E_ADMIN_PW\"}" 2>/dev/null | json_get access_token)
    [ -n "$JWT3" ] || { bad "frps: login with the new device failed"; return; }

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

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "integration_stack_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
