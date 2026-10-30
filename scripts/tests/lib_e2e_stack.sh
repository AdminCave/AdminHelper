# shellcheck shell=bash
#
# lib_e2e_stack.sh — shared boot/seed/teardown for the docker-compose-backed
# integration + E2E tests. Source it, then:
#
#   e2e_require [extra-bins...]      # preconditions; SKIPs (exit 75) when missing
#   e2e_npm_ready <dir...>           # npm ci where node_modules is missing or stale
#   e2e_init <true|false> [a|b]      # MTLS_ENFORCE; sets up env + EXIT teardown
#   e2e_stack_use <a|b>              # point the globals at stack a or b
#   e2e_up <service...>              # build + start services, wait for the gateway
#   token=$(e2e_admin_token)         # admin JWT through the gateway
#   e2e_login [curl-args...]         # one admin login: E2E_JWT, or E2E_LOGIN_ERR + rc 1
#   e2e_dc <compose-args...>         # raw `docker compose` for this run
#   e2e_keyring_start                # in a dbus-run-session: a keyring of its own, or rc 1
#
# Everything is hermetic: throwaway secrets, images built from THIS checkout
# under local tags (docker-compose.test.yml), per-run host ports + named volumes,
# and a `down -v` teardown installed on EXIT.
#
# Two installations side by side: `e2e_init <mtls> a` and `e2e_init <mtls> b` set up two
# stacks with their own project, work dir, secrets, ports and loopback address. The one
# initialised last is current; e2e_stack_use switches, the teardown takes both down.
# Each key once, and a stack without a key stands alone.

_E2E_LIB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
E2E_REPO_ROOT=$(cd "$_E2E_LIB_DIR/../.." && pwd)
_E2E_COMPOSE=(-f "$E2E_REPO_ROOT/docker-compose.yml" -f "$E2E_REPO_ROOT/docker-compose.test.yml")
_E2E_API="$_E2E_LIB_DIR/e2e_api.py"

# e2e_api <token> <op> [args...] — admin-API seed/query over the test gateway.
# Ops: server | config | tunnel | count-tunnels | count-connections | tunnel-conn |
#      visitor-port | provision-token | connection | web-connection — see e2e_api.py for the
#      args (2.122).
e2e_api() { python3 "$_E2E_API" "$E2E_SERVER_URL" "$@"; }

# Headless WebKit: disable GPU paths xvfb can't provide (else the webview may fail to
# render). box_desktopbox set these inline; exporting them here — every desktop_e2e_*
# suite sources this lib, and export reaches the dbus-run-session subshells — gives them
# all the same env instead of only some; the divergence was already real. The full
# dbus/keyring/xvfb wrapper dedup is a separate, riskier refactor (2.40).
export WEBKIT_DISABLE_DMABUF_RENDERER=1 WEBKIT_DISABLE_COMPOSITING_MODE=1

# The workspace wdio.conf.js opens (test/lib/app-args.js; empty opens the launcher). The
# desktop suites seed the settings.json of a version before workspaces, which the app moves
# into the workspace "standard" at its first start (R-0431); no other id is there to open.
export AH_E2E_WORKSPACE=standard

# e2e_keyring_start — in the `dbus-run-session -- bash -c` block of a desktop suite: an
# unlocked gnome-keyring (empty password) for the app on that session bus. Exports
# GNOME_KEYRING_CONTROL and SSH_AUTH_SOCK. Returns 1, with the daemon's stderr on stderr,
# when org.freedesktop.secrets gets no owner on the bus within 5 s. Exported like the
# variables above, so the block can call it.
#
# The control directory is its own (R-0566). Without one the daemon takes the user's
# $XDG_RUNTIME_DIR/keyring: on a box systemd's gnome-keyring-daemon.socket listens there,
# and the session's daemon replaced it and removed the directory when it quit; on a
# developer's machine the running keyring sits there. With --control-directory the daemon
# looks nowhere else. A fresh mktemp -d, no deeper work dir: the socket path has at most
# 107 bytes (sun_path), beyond that the daemon fails with "couldn't bind to control socket".
# An EXIT trap in the calling shell removes the directory again. That assumes the block has
# no EXIT trap of its own, which this one would replace; the suites' blocks have none. The
# daemon outlives its directory until the bus goes with the session: it keeps the name,
# then quits and recreates nothing.
# The owner check: a session without a daemon on its bus let D-Bus start one at the app's
# first call, its password prompt failed without a display, and the specs ran into their
# 20 s timeouts. NameHasOwner asks the bus and starts nothing.
e2e_keyring_start() {
    local dir reply end
    dir=$(mktemp -d "${TMPDIR:-/tmp}/ah-keyring.XXXXXX") || return 1
    # The path goes into the trap now, so it holds once the function has returned.
    # shellcheck disable=SC2064
    trap "rm -rf -- $(printf '%q' "$dir")" EXIT
    eval "$(printf '\n' | gnome-keyring-daemon --unlock --components=secrets \
        --control-directory="$dir" 2>"$dir/stderr")"
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    end=$((SECONDS + 5))
    while :; do
        reply=$(dbus-send --session --print-reply --reply-timeout=1000 \
            --dest=org.freedesktop.DBus /org/freedesktop/DBus \
            org.freedesktop.DBus.NameHasOwner string:org.freedesktop.secrets 2>/dev/null)
        [[ $reply == *"boolean true"* ]] && return 0
        [ "$SECONDS" -lt "$end" ] || break
        sleep 0.1
    done
    echo "keyring: no unlocked secret service on this session bus" >&2
    cat "$dir/stderr" >&2
    return 1
}
export -f e2e_keyring_start

# Populated by e2e_init.
E2E_WORK=""
E2E_PROJECT=""
E2E_HTTPS_PORT=""
E2E_ENROLL_PORT=""
E2E_REPO_PORT=""
E2E_PG_PORT=""
E2E_REDIS_PORT=""
E2E_SERVER_URL=""
E2E_ADMIN_PW=""
# The gateway's host address (ITEST_BIND_IP); empty publishes it with no address.
E2E_BIND_IP=""
E2E_FRP_BIND_PORT=""
E2E_FRP_HTTPS_PORT=""
# Exported by e2e_init: the stack's Postgres and Redis as the host sees them
# (127.0.0.1, docker-compose.test.yml), for tests that run outside the containers.
ITEST_DATABASE_URL=""
ITEST_REDIS_URL=""
# What one stack owns: e2e_init <mtls> <a|b> keeps a copy as _E2E_<key>_<name>,
# e2e_stack_use puts it back. _E2E_STACKS lists the keys initialised.
_E2E_STACK_VARS=(E2E_WORK E2E_PROJECT E2E_HTTPS_PORT E2E_ENROLL_PORT E2E_REPO_PORT
    E2E_PG_PORT E2E_REDIS_PORT E2E_SERVER_URL E2E_ADMIN_PW E2E_BIND_IP
    E2E_FRP_BIND_PORT E2E_FRP_HTTPS_PORT ITEST_DATABASE_URL ITEST_REDIS_URL)
_E2E_STACKS=()
# Set by e2e_init without a key.
_E2E_KEYLESS=""
# Set by e2e_login.
E2E_JWT=""
E2E_LOGIN_ERR=""

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

# e2e_npm_ready <dir>... — `npm ci` in each dir whose node_modules is missing or older
# than its package-lock.json, the rule of run.sh's npm_ci_if_stale (5.26). A suite run
# with --step skips the desktop-e2e-smoke step that applies it, and node_modules from
# the template then lacks every package the lockfile gained since.
e2e_npm_ready() {
    local d
    for d in "$@"; do
        ( cd "$d" || exit 1
          if [ ! -d node_modules ] || [ package-lock.json -nt node_modules ]; then
              echo "  npm ci in $d (node_modules missing or older than package-lock.json)"
              npm ci --no-audit --no-fund
          fi ) || return 1
    done
}

e2e_dc() {
    docker compose -p "$E2E_PROJECT" "${_E2E_COMPOSE[@]}" --env-file "$E2E_WORK/.env" "$@"
}

e2e_teardown() {
    local key works=()
    if [ "${#_E2E_STACKS[@]}" = 0 ]; then
        e2e_dc down -v --remove-orphans >/dev/null 2>&1 || true
        works=("$E2E_WORK")
    fi
    for key in "${_E2E_STACKS[@]}"; do
        e2e_stack_use "$key"
        e2e_dc down -v --remove-orphans >/dev/null 2>&1 || true
        works+=("$E2E_WORK")
    done
    pkill -9 -f tauri-driver >/dev/null 2>&1 || true
    pkill -9 -f "target/debug/adminhelper" >/dev/null 2>&1 || true
    rm -rf "${works[@]}"
}

# e2e_stack_use <a|b> — make a stack from `e2e_init <mtls> <a|b>` the current one: every
# global in _E2E_STACK_VARS, so e2e_dc, e2e_up, e2e_api and e2e_login reach that stack.
e2e_stack_use() {
    local key=${1-} v src known=""
    for v in "${_E2E_STACKS[@]}"; do [ "$v" != "$key" ] || known=1; done
    if [ -z "$known" ]; then
        echo "e2e_stack_use: no stack '$key' (e2e_init <mtls> a|b first)" >&2
        return 1
    fi
    for v in "${_E2E_STACK_VARS[@]}"; do
        src="_E2E_${key}_$v"
        printf -v "$v" '%s' "${!src}"
    done
}

# e2e_init <MTLS_ENFORCE> [a|b] — without a key the one stack of a run; with one, stack a
# or b of two side by side, which then becomes the current one.
e2e_init() {
    local key=${2-} off=0 bind="" frp_bind=7000 frp_https=7443 k
    # Each stack gets a loopback address of its own, so both gateways hold the fixed
    # 8444/8445 below. frps publishes on every interface, so stack b moves its ports;
    # Postgres and Redis stay on 127.0.0.1, so stack b takes the next port of each range.
    case "$key" in
        "") ;;
        a) bind=127.0.0.1 ;;
        b) bind=127.0.0.2; off=1; frp_bind=7001; frp_https=7444 ;;
        *) echo "e2e_init: stack key '$key' is neither a nor b" >&2; return 1 ;;
    esac
    # The teardown takes down either the one stack without a key or the keyed ones, from the
    # globals each left: a second call for a key would leave the first work dir behind, a mix
    # of both kinds the project and work dir of the stack without a key. Checked before any
    # global changes, so a rejected call keeps the current stack.
    if [ -n "$_E2E_KEYLESS" ] || { [ -z "$key" ] && [ "${#_E2E_STACKS[@]}" != 0 ]; }; then
        echo "e2e_init: a stack without a key cannot run beside another one" >&2
        return 1
    fi
    for k in "${_E2E_STACKS[@]}"; do
        [ "$k" != "$key" ] || { echo "e2e_init: stack '$key' is set up already" >&2; return 1; }
    done
    E2E_BIND_IP=$bind; E2E_FRP_BIND_PORT=$frp_bind; E2E_FRP_HTTPS_PORT=$frp_https
    E2E_PROJECT="ah-e2e-$$${key:+-$key}"
    E2E_WORK=$(mktemp -d)
    # High, per-run host ports so the test never collides with a real stack on
    # 443/8444 or a second run in parallel.
    E2E_HTTPS_PORT=$(( 21000 + ($$ + off) % 18000 ))
    # The desktop app derives the enrollment plane as <server-host>:8444, so this
    # one must be the fixed 8444 — only the data plane gets a high per-run port.
    E2E_ENROLL_PORT=8444
    E2E_REPO_PORT=8445
    # Ranges of their own, below the data plane's (21000-38999) so no PID hands
    # one run's Postgres port to another run's gateway, and below Linux's
    # ephemeral range (32768-60999), where an outgoing connection may be holding
    # the port at the moment compose binds it.
    E2E_PG_PORT=$(( 11000 + ($$ + off) % 5000 ))
    E2E_REDIS_PORT=$(( 16000 + ($$ + off) % 5000 ))
    # A keyed stack is reached on its own address, and so is its enrollment plane.
    E2E_SERVER_URL="https://${E2E_BIND_IP:-localhost}:$E2E_HTTPS_PORT"
    E2E_ADMIN_PW="e2e-$(e2e_rand)"
    local pg_pw
    pg_pw="$(e2e_rand)"
    cat > "$E2E_WORK/.env" <<EOF
DOMAIN=localhost
SECRET_KEY=$(e2e_rand)$(e2e_rand)
POSTGRES_PASSWORD=$pg_pw
SERVER_DB_PASSWORD=$(e2e_rand)
SCHEDULER_DB_PASSWORD=$(e2e_rand)
MONITOR_DB_PASSWORD=$(e2e_rand)
CA_DB_PASSWORD=$(e2e_rand)
CA_ROOT_PASSPHRASE=$(e2e_rand)
MONITOR_API_KEY=$(e2e_rand)
ADMIN_PASSWORD=$E2E_ADMIN_PW
MTLS_ENFORCE=${1:?e2e_init needs MTLS_ENFORCE (true|false)}
ITEST_HTTPS_PORT=$E2E_HTTPS_PORT
ITEST_ENROLL_PORT=$E2E_ENROLL_PORT
ITEST_REPO_PORT=$E2E_REPO_PORT
ITEST_PG_PORT=$E2E_PG_PORT
ITEST_REDIS_PORT=$E2E_REDIS_PORT
EOF
    # EXTRA_SANS puts the stack's address into the gateway certificate: the ca-issuer adds only
    # localhost and 127.0.0.1, and a client that checks the name (the agent after its pin, the
    # desktop once registered) refuses stack b on 127.0.0.2 without it.
    if [ -n "$key" ]; then
        cat >> "$E2E_WORK/.env" <<EOF
ITEST_BIND_IP=$E2E_BIND_IP
EXTRA_SANS=$E2E_BIND_IP
FRP_BIND_PORT=$E2E_FRP_BIND_PORT
FRP_HTTPS_PORT=$E2E_FRP_HTTPS_PORT
EOF
    fi
    # User and database as docker-compose.yml creates them; the password is hex,
    # so it needs no URL escaping.
    export ITEST_DATABASE_URL="postgresql+psycopg://adminhelper:$pg_pw@127.0.0.1:$E2E_PG_PORT/adminhelper"
    export ITEST_REDIS_URL="redis://127.0.0.1:$E2E_REDIS_PORT/0"
    trap e2e_teardown EXIT
    if [ -n "$key" ]; then
        local v
        for v in "${_E2E_STACK_VARS[@]}"; do printf -v "_E2E_${key}_$v" '%s' "${!v}"; done
        _E2E_STACKS+=("$key")
    else
        _E2E_KEYLESS=1
    fi
}

# e2e_up <service...> — build + start the given services (+ deps), wait for :443.
# Returns non-zero (and dumps gateway logs) if the gateway never answers.
e2e_up() {
    echo "[e2e] building + starting: $* (on :$E2E_HTTPS_PORT)..."
    # Don't swallow the build output: on failure the caller needs to see WHY the
    # build/up broke, not just a bare non-zero return (4.57).
    local buildlog
    buildlog="$(e2e_dc up --build -d "$@" 2>&1)" \
        || { echo "[e2e] build/up failed:" >&2; printf '%s\n' "$buildlog" | tail -30 >&2; return 1; }
    local code
    for _ in $(seq 1 120); do
        code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 3 "$E2E_SERVER_URL/" 2>/dev/null || echo 000)
        [ "$code" != "000" ] && return 0
        sleep 2
    done
    e2e_dc logs --tail 40 gateway
    return 1
}

# e2e_wait_enroll_plane [seconds] — wait until :8444 reaches the ca-issuer. e2e_up waits
# for :443 only, and the gateway hangs on the ca-issuer with service_started: right after a
# fresh PKI the enroll plane answers 502 (or resets) until the issuer listens (R-0935).
# Any other status counts as reached; rc 1 names the last one.
e2e_wait_enroll_plane() {
    local deadline=$(( $(date +%s) + ${1:-60} )) code=000
    while :; do
        code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 3 "https://localhost:$E2E_ENROLL_PORT/" 2>/dev/null) || code=000
        case "$code" in 000|502|503|504) ;; *) return 0 ;; esac
        [ "$(date +%s)" -lt "$deadline" ] || break
        sleep 1
    done
    echo "[e2e] enroll plane :$E2E_ENROLL_PORT never reached the ca-issuer (last HTTP '$code')" >&2
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

# e2e_login [curl-args...] — one admin login through the gateway, no retry; the args go
# to curl (the client cert). Prints nothing: sets E2E_JWT and returns 0, or sets
# E2E_LOGIN_ERR to one line for the caller's FAIL message and returns 1. That line never
# carries the request (the password) or a 200 body (the JWT), and nothing that varies
# with time, so heavy.sh's first_marker sees the same cause as the same FAIL line.
# E2E_LOGIN_ERR is the caller's to read.
# shellcheck disable=SC2034
e2e_login() {
    local resp code body detail rc=0
    E2E_JWT=""; E2E_LOGIN_ERR=""
    resp=$(curl -k -s "$@" --max-time 5 -X POST "$E2E_SERVER_URL/api/auth/login" \
        -H 'Content-Type: application/json' \
        -d "{\"username\":\"admin\",\"password\":\"$E2E_ADMIN_PW\"}" \
        -w '\n%{http_code}' 2>/dev/null) || rc=$?
    code=${resp##*$'\n'}; body=${resp%$'\n'*}
    # The class spelled out: under a de_DE locale [0-9] also matches other digits.
    [[ $code =~ ^[0123456789]{3}$ ]] || code=000
    if [ "$code" = 200 ]; then
        E2E_JWT=$(printf '%s' "$body" | python3 -c '
import json, sys
t = json.load(sys.stdin.buffer)["access_token"]
print(t if isinstance(t, str) else "")' 2>/dev/null)
        [ -z "$E2E_JWT" ] || return 0
        E2E_LOGIN_ERR="HTTP 200, curl exit $rc, no access_token"
        return 1
    fi
    detail=$(printf '%s' "$body" | python3 -c '
import json, sys
d = json.load(sys.stdin.buffer)["detail"]
if isinstance(d, list):  # FastAPI 422: each "input" echoes the request, password included
    d = "; ".join(".".join(map(str, e["loc"])) + ": " + str(e["msg"]) for e in d)
if isinstance(d, str):
    print("detail: " + "".join(c if c.isprintable() else " " for c in d)[:200])' 2>/dev/null)
    E2E_LOGIN_ERR="HTTP $code, curl exit $rc, ${detail:-no JSON detail}"
    return 1
}
