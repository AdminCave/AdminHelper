#!/usr/bin/env bash
#
# desktop_e2e_tunnel.sh — live desktop E2E: START a tunnel and prove it connects.
#
# The "test it" half of "create a connection with a tunnel and test it": after
# Increment 1 (create via the GUI), this drives the real app to actually bring a
# tunnel up against a real frps and verifies frpc connected end to end.
#
# Flow: boot the stack + frps (permissive), seed an admin + server + FRP config +
# an STCP tunnel, mint an enrollment token. The app (under a fresh D-Bus session +
# empty gnome-keyring) enrolls a device cert (setup, via the bridge), logs in
# through the GUI, and AppShell auto-starts the seeded tunnel. We assert the GUI's
# tunnel indicator reaches "connected" AND that the frps container log shows the
# desktop's frpc logging in — the full PKI + frps + enrollment chain.
#
# Boot/seed/teardown shared via lib_e2e_stack.sh. Needs docker(+compose), openssl,
# curl, python3, node, xvfb-run, WebKitWebDriver, tauri-driver, tauri-cli,
# dbus-run-session, gnome-keyring-daemon. SKIPs when any is missing.
# Run: bash scripts/tests/desktop_e2e_tunnel.sh

# shellcheck disable=SC2015
set -uo pipefail

# shellcheck source=scripts/tests/lib_e2e_stack.sh
. "$(cd "$(dirname "$0")" && pwd)/lib_e2e_stack.sh"

E2E_DIR="$E2E_REPO_ROOT/apps/desktop/e2e"

PASS=0
FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

e2e_require node xvfb-run WebKitWebDriver tauri-driver dbus-run-session gnome-keyring-daemon
( cd "$E2E_REPO_ROOT/apps/desktop/src-tauri" && cargo tauri --version >/dev/null 2>&1 ) \
    || { echo "SKIP: tauri-cli (cargo tauri) not available"; exit 0; }

e2e_init false                                 # permissive; enrollment gives the tunnel cert
e2e_up gateway && ok "gateway live on :$E2E_HTTPS_PORT" || { bad "gateway never came up"; exit 1; }

# ── Seed admin token + server + FRP config + an STCP tunnel ──────────────────
TOKEN=$(e2e_admin_token)
[ -n "$TOKEN" ] && ok "admin login through the gateway" || { bad "admin login failed"; e2e_dc logs --tail 40 server; exit 1; }
SERVER_ID=$(e2e_api "$TOKEN" server e2e-server e2e.local)         || { bad "seed server"; exit 1; }
CONFIG_ID=$(e2e_api "$TOKEN" config e2e-frps localhost 7000)      || { bad "seed FRP config"; exit 1; }
e2e_api "$TOKEN" tunnel "$SERVER_ID" "$CONFIG_ID" e2e-ssh 22 >/dev/null || { bad "seed tunnel"; exit 1; }
ok "seeded a server + FRP config + STCP tunnel"

# Creating the FRP config wrote frps.toml into the shared volume; bring frps up
# now so it reads that config + its ca-issuer-provisioned (tunnel-signed) cert.
e2e_dc up -d frps >/dev/null 2>&1 && ok "frps started" || { bad "frps failed to start"; e2e_dc logs --tail 30 frps; exit 1; }

# One-time enrollment token (redeemed by the app over the certless :8444 plane).
ENROLL_TOKEN=$(e2e_dc exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')
[ -n "$ENROLL_TOKEN" ] && ok "minted enrollment token" || { bad "could not mint enrollment token"; exit 1; }

# ── Isolated app config: server mode + trust the stack's self-signed cert ─────
XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
mkdir -p "$XDG_DATA_HOME/com.admincave.adminhelper"
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$XDG_DATA_HOME/com.admincave.adminhelper/settings.json"

# ── Drive the GUI: enroll (setup) → login → auto-start the tunnel ────────────
echo "[e2e-tunnel] running the tunnel-start spec under xvfb..."
export AH_SERVER_URL="$E2E_SERVER_URL" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$E2E_ADMIN_PW" \
       AH_ENROLL_TOKEN="$ENROLL_TOKEN" E2E_DIR
dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js --spec test/specs/tunnel-start.live.js
' && ok "GUI: enrolled, logged in, tunnel indicator connected" || bad "GUI tunnel-start spec failed"

# ── Independent check: frps logged the desktop's frpc connecting ─────────────
FRPS_LOG=$(e2e_dc logs --no-color frps 2>/dev/null)
if printf '%s' "$FRPS_LOG" | grep -qiE "new proxy|client login|login to the server|new work connection|start proxy success|get a new work connection"; then
    ok "frps shows the desktop tunnel connected"
else
    bad "frps shows no successful tunnel connection"
    printf '%s\n' "$FRPS_LOG" | tail -25
fi

echo ""
echo "desktop_e2e_tunnel: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
