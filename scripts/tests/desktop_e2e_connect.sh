#!/usr/bin/env bash
#
# desktop_e2e_connect.sh — live desktop E2E: open a connection through the GUI to
# a REAL target container and verify the target received the connection. The
# desktop launches ssh/xfreerdp3/the browser as an EXTERNAL process (not in the
# webview), so the assertion is the target container's log (like the tunnel test
# checks the frps log), not GUI state.
#
# This file covers the DIRECT SSH journey; web/rdp and the over-tunnel variants
# build on the same pattern. Shared boot/seed/teardown via lib_e2e_stack.sh.
# Run: bash scripts/tests/desktop_e2e_connect.sh

# shellcheck disable=SC2015
set -uo pipefail

# shellcheck source=scripts/tests/lib_e2e_stack.sh
. "$(cd "$(dirname "$0")" && pwd)/lib_e2e_stack.sh"

E2E_DIR="$E2E_REPO_ROOT/apps/desktop/e2e"
# Digest-pinned like docker-compose.yml — a latest/tagless upstream push must not
# turn the suite red without an AdminHelper defect (6.136).
SSH_IMAGE="lscr.io/linuxserver/openssh-server:latest@sha256:67d4c3a1402179a6579aa217a38b52ced557eb8a0c17a8e32fe986a4549fdee4"

PASS=0
FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

TARGETS=()
cleanup_targets() { for c in "${TARGETS[@]:-}"; do [ -n "$c" ] && docker rm -f "$c" >/dev/null 2>&1; done; }

wait_log() {  # container pattern timeout — readiness via the log, so we don't
    # pollute the target with a host-side probe (which would look like a client).
    for _ in $(seq 1 "$3"); do docker logs "$1" 2>&1 | grep -qE "$2" && return 0; sleep 1; done
    return 1
}


e2e_require node xvfb-run WebKitWebDriver tauri-driver dbus-run-session gnome-keyring-daemon docker
( cd "$E2E_REPO_ROOT/apps/desktop/src-tauri" && cargo tauri --version >/dev/null 2>&1 ) \
    || { echo "SKIP: tauri-cli (cargo tauri) not available"; exit 0; }

e2e_init false
# Chain target cleanup in front of the lib's compose teardown (don't replace it).
trap 'cleanup_targets; e2e_teardown' EXIT
e2e_up gateway && ok "gateway live on :$E2E_HTTPS_PORT" || { bad "gateway never came up"; exit 1; }

TOKEN=$(e2e_admin_token)
[ -n "$TOKEN" ] && ok "admin login" || { bad "admin login failed"; exit 1; }
e2e_api "$TOKEN" server e2e-server e2e.local >/dev/null || { bad "seed server"; exit 1; }

# ── SSH target + a direct SSH connection ─────────────────────────────────────
SSH_C="ah-e2e-ssh-$$"
docker run -d --name "$SSH_C" -p 127.0.0.1:2222:2222 \
    -e PASSWORD_ACCESS=true -e USER_NAME=e2e -e USER_PASSWORD=e2e -e LOG_STDOUT=true \
    "$SSH_IMAGE" >/dev/null || { echo "[e2e] SSH target ($SSH_C) failed to start — is 127.0.0.1:2222 in use? (4.126)" >&2; exit 1; }
TARGETS+=("$SSH_C")
wait_log "$SSH_C" "listening on port 2222" 40 && ok "SSH target listening on :2222" || { bad "SSH target never came up"; docker logs --tail 20 "$SSH_C"; exit 1; }
e2e_api "$TOKEN" connection ssh-direct ssh 127.0.0.1 2222 e2e >/dev/null && ok "seeded direct SSH connection" || { bad "seed SSH connection"; exit 1; }

# ── Web target (nginx) + a direct Web connection ─────────────────────────────
WEB_C="ah-e2e-web-$$"
docker run -d --name "$WEB_C" -p 127.0.0.1:8080:80 nginx:alpine >/dev/null || { echo "[e2e] web target ($WEB_C) failed to start — is 127.0.0.1:8080 in use? (4.126)" >&2; exit 1; }
TARGETS+=("$WEB_C")
wait_log "$WEB_C" "worker process" 30 && ok "Web target listening on :8080" || { bad "Web target never came up"; docker logs --tail 20 "$WEB_C"; exit 1; }
e2e_api "$TOKEN" web-connection web-direct "http://127.0.0.1:8080" >/dev/null && ok "seeded direct Web connection" || { bad "seed Web connection"; exit 1; }

# ── RDP target (xrdp) + a direct RDP connection ──────────────────────────────
RDP_C="ah-e2e-rdp-$$"
docker run -d --name "$RDP_C" -p 127.0.0.1:3389:3389 danielguerra/ubuntu-xrdp@sha256:1a00da32f4e486f2f5fd8f656fc23bb235987c219153a587894469cad300b12d >/dev/null || { echo "[e2e] RDP target ($RDP_C) failed to start — is 127.0.0.1:3389 in use? (4.126)" >&2; exit 1; }
TARGETS+=("$RDP_C")
wait_log "$RDP_C" "xrdp entered RUNNING state" 60 && { sleep 3; ok "RDP target (xrdp) up on :3389"; } || { bad "RDP target never came up"; docker logs --tail 20 "$RDP_C"; exit 1; }
e2e_api "$TOKEN" connection rdp-direct rdp 127.0.0.1 3389 e2e >/dev/null && ok "seeded direct RDP connection" || { bad "seed RDP connection"; exit 1; }

# xdg-open shim: the desktop's open::that(url) resolves "xdg-open" via PATH. This
# shim fetches the URL so the nginx access log proves the right URL was opened
# (headless has no real browser to do it).
SHIM_DIR="$E2E_WORK/bin"; mkdir -p "$SHIM_DIR"
AH_XDG_LOG="$E2E_WORK/xdg-open.log"; export AH_XDG_LOG
cat > "$SHIM_DIR/xdg-open" <<'SHIM'
#!/bin/sh
echo "$1" >> "$AH_XDG_LOG"
curl -s -m 5 "$1" >/dev/null 2>&1 || true
SHIM
chmod +x "$SHIM_DIR/xdg-open"

XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
mkdir -p "$XDG_DATA_HOME/com.admincave.adminhelper"
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$XDG_DATA_HOME/com.admincave.adminhelper/settings.json"

echo "[connect] driving the connect specs under xvfb..."
export AH_SERVER_URL="$E2E_SERVER_URL" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$E2E_ADMIN_PW" E2E_DIR
export PATH="$SHIM_DIR:$PATH"  # the app inherits this -> open::that finds the xdg-open shim
dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/ssh-connect.live.js \
        --spec test/specs/web-connect.live.js \
        --spec test/specs/rdp-connect.live.js
' && ok "connect GUI specs ran" || bad "connect GUI specs failed"

# Verify from the target side: sshd logged an incoming connection from the
# desktop. The desktop reaches the published port via the docker bridge, so it
# appears as a private (non-loopback) source — distinct from the image's own
# loopback (::1) self-test.
# Poll for the sshd log line instead of a fixed sleep — it can lag on a loaded box (6.137).
ssh_ok=0
for _ in $(seq 1 10); do docker logs "$SSH_C" 2>&1 | grep -E "Connection (closed by|from|received)|Accepted" | grep -qE "172\.|10\.|192\.168\." && { ssh_ok=1; break; }; sleep 1; done
if [ "$ssh_ok" = 1 ]; then
    ok "sshd logged the desktop's SSH connection (direct)"
else
    bad "sshd saw no connection from the desktop"
    docker logs --tail 25 "$SSH_C"
fi

# Web: nginx logged the fetch the desktop's open::that(url) triggered (via shim).
if docker logs "$WEB_C" 2>&1 | grep -qE "\"GET / HTTP"; then
    ok "nginx logged the desktop's web fetch (direct)"
else
    bad "nginx saw no request from the desktop"
    echo "    xdg-open shim log:"; sed 's/^/    /' "$AH_XDG_LOG" 2>/dev/null
    docker logs --tail 15 "$WEB_C"
fi

# RDP: the xrdp server logged the desktop's incoming connection (xfreerdp3).
if docker exec "$RDP_C" sh -c 'cat /var/log/xrdp.log /var/log/xrdp-sesman.log 2>/dev/null' 2>/dev/null \
        | grep -qiE "connect|incoming|login|session|TLS"; then
    ok "xrdp logged the desktop's RDP connection (direct)"
elif docker logs "$RDP_C" 2>&1 | grep -qiE "connect|incoming"; then
    ok "xrdp logged the desktop's RDP connection (direct)"
else
    bad "xrdp saw no connection from the desktop"
    docker exec "$RDP_C" sh -c 'tail -25 /var/log/xrdp.log 2>/dev/null' 2>/dev/null
    docker logs --tail 15 "$RDP_C"
fi

echo ""
echo "desktop_e2e_connect: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
