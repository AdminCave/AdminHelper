# shellcheck shell=bash
#
# lib_e2e_stack.sh — shared boot/seed/teardown for the docker-compose-backed
# integration + E2E tests. Source it, then:
#
#   e2e_require [extra-bins...]      # preconditions; SKIPs (exit 0) when missing
#   e2e_init <true|false>            # MTLS_ENFORCE; sets up env + EXIT teardown
#   e2e_up <service...>              # build + start services, wait for the gateway
#   token=$(e2e_admin_token)         # admin JWT through the gateway
#   e2e_dc <compose-args...>         # raw `docker compose` for this run
#
# Everything is hermetic: throwaway secrets, images built from THIS checkout
# under local tags (docker-compose.test.yml), per-run host ports + named volumes,
# and a `down -v` teardown installed on EXIT.

_E2E_LIB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
E2E_REPO_ROOT=$(cd "$_E2E_LIB_DIR/../.." && pwd)
_E2E_COMPOSE=(-f "$E2E_REPO_ROOT/docker-compose.yml" -f "$E2E_REPO_ROOT/docker-compose.test.yml")
_E2E_API="$_E2E_LIB_DIR/e2e_api.py"

# e2e_api <token> <op> [args...] — admin-API seed/query over the test gateway.
# Ops: server <name> <hostname> | config <name> <addr> <port> |
#      tunnel <server_id> <config_id> <name> <port> | count-tunnels <server_id>.
e2e_api() { python3 "$_E2E_API" "$E2E_SERVER_URL" "$@"; }

# Populated by e2e_init.
E2E_WORK=""
E2E_PROJECT=""
E2E_HTTPS_PORT=""
E2E_ENROLL_PORT=""
E2E_SERVER_URL=""
E2E_ADMIN_PW=""

e2e_rand() { openssl rand -hex 16; }

e2e_require() {
    local bin
    # Exit 75 (EX_TEMPFAIL) is run.sh's self-SKIP sentinel: a missing precondition
    # must report SKIP, not a green PASS via a bare exit 0 (6.9).
    for bin in docker openssl curl python3 "$@"; do
        command -v "$bin" >/dev/null 2>&1 || { echo "SKIP: '$bin' not available"; exit 75; }
    done
    docker compose version >/dev/null 2>&1 || { echo "SKIP: docker compose v2 missing"; exit 75; }
    docker info >/dev/null 2>&1 || { echo "SKIP: docker daemon not reachable"; exit 75; }
}

e2e_dc() {
    docker compose -p "$E2E_PROJECT" "${_E2E_COMPOSE[@]}" --env-file "$E2E_WORK/.env" "$@"
}

e2e_teardown() {
    e2e_dc down -v --remove-orphans >/dev/null 2>&1 || true
    pkill -9 -f tauri-driver >/dev/null 2>&1 || true
    pkill -9 -f "target/debug/adminhelper" >/dev/null 2>&1 || true
    rm -rf "$E2E_WORK"
}

# e2e_init <MTLS_ENFORCE>
e2e_init() {
    E2E_PROJECT="ah-e2e-$$"
    E2E_WORK=$(mktemp -d)
    # High, per-run host ports so the test never collides with a real stack on
    # 443/8444 or a second run in parallel.
    E2E_HTTPS_PORT=$(( 21000 + ($$ % 18000) ))
    # The desktop app derives the enrollment plane as <server-host>:8444, so this
    # one must be the fixed 8444 — only the data plane gets a high per-run port.
    E2E_ENROLL_PORT=8444
    E2E_SERVER_URL="https://localhost:$E2E_HTTPS_PORT"
    E2E_ADMIN_PW="e2e-$(e2e_rand)"
    cat > "$E2E_WORK/.env" <<EOF
DOMAIN=localhost
SECRET_KEY=$(e2e_rand)$(e2e_rand)
POSTGRES_PASSWORD=$(e2e_rand)
CA_ROOT_PASSPHRASE=$(e2e_rand)
MONITOR_API_KEY=$(e2e_rand)
ADMIN_PASSWORD=$E2E_ADMIN_PW
MTLS_ENFORCE=${1:?e2e_init needs MTLS_ENFORCE (true|false)}
ITEST_HTTPS_PORT=$E2E_HTTPS_PORT
ITEST_ENROLL_PORT=$E2E_ENROLL_PORT
EOF
    trap e2e_teardown EXIT
}

# e2e_up <service...> — build + start the given services (+ deps), wait for :443.
# Returns non-zero (and dumps gateway logs) if the gateway never answers.
e2e_up() {
    echo "[e2e] building + starting: $* (on :$E2E_HTTPS_PORT)..."
    e2e_dc up --build -d "$@" >/dev/null 2>&1 || return 1
    local code
    for _ in $(seq 1 120); do
        code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 3 "$E2E_SERVER_URL/" 2>/dev/null || echo 000)
        [ "$code" != "000" ] && return 0
        sleep 2
    done
    e2e_dc logs --tail 40 gateway
    return 1
}

# e2e_admin_token — print the admin JWT (retries until the startup lifespan has
# created the admin from ADMIN_PASSWORD). Empty output on failure.
e2e_admin_token() {
    python3 - "$E2E_SERVER_URL" admin "$E2E_ADMIN_PW" <<'PY'
import json, ssl, sys, time, urllib.request
base, user, pw = sys.argv[1:4]
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
for _ in range(30):
    try:
        req = urllib.request.Request(
            base + "/api/auth/login",
            data=json.dumps({"username": user, "password": pw}).encode(),
            headers={"Content-Type": "application/json"},
        )
        print(json.load(urllib.request.urlopen(req, context=ctx, timeout=15))["access_token"])
        break
    except Exception:
        time.sleep(2)
PY
}
