#!/usr/bin/env bash
#
# desktop_e2e_live.sh — live desktop E2E: drive the REAL Tauri app (tauri-driver
# + WebdriverIO) against a REAL backend to create a connection tunnel via the GUI.
#
# Boots the stack PERMISSIVE (MTLS_ENFORCE=false) so login (JWT) alone reaches the
# API — enrollment is only needed to *start* a tunnel (a later step). Seeds an
# admin + server + FRP config, points an ISOLATED app config (XDG_DATA_HOME +
# server mode + self-signed trusted) at the stack, runs the live wdio spec under
# xvfb in a fresh D-Bus session with an empty gnome-keyring (so the developer's
# real enrolled identity doesn't break the TOFU login), and independently
# re-checks the created tunnel via the server API.
#
# Boot/seed/teardown are shared via lib_e2e_stack.sh. Needs docker(+compose),
# openssl, curl, python3, node, xvfb-run, WebKitWebDriver, tauri-driver,
# tauri-cli, dbus-run-session, gnome-keyring-daemon. SKIPs when any is missing.
# Run: bash scripts/tests/desktop_e2e_live.sh

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

e2e_init false                                 # permissive: login (JWT) reaches the API
e2e_up gateway && ok "gateway live on :$E2E_HTTPS_PORT" || { bad "gateway never came up"; exit 1; }

# ── Seed an admin token + a server + an FRP config ───────────────────────────
TOKEN=$(e2e_admin_token)
[ -n "$TOKEN" ] && ok "admin login through the gateway" || { bad "admin login failed"; e2e_dc logs --tail 40 server; exit 1; }
SERVER_ID=$(e2e_api "$TOKEN" server e2e-server e2e.local) || { bad "seed server"; exit 1; }
e2e_api "$TOKEN" config e2e-frps localhost 7000 >/dev/null || { bad "seed FRP config"; exit 1; }
ok "seeded a server + FRP config"

# ── Isolated app config: server mode + trust the stack's self-signed cert ─────
XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
mkdir -p "$XDG_DATA_HOME/com.admincave.adminhelper"
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$XDG_DATA_HOME/com.admincave.adminhelper/settings.json"

# ── Drive the GUI ────────────────────────────────────────────────────────────
echo "[e2e-live] running the live wdio spec under xvfb..."
export AH_SERVER_URL="$E2E_SERVER_URL" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$E2E_ADMIN_PW" E2E_DIR
SPEC="${AH_SPEC:-test/specs/tunnel-create.live.js}"; export SPEC

# Fresh D-Bus session + empty gnome-keyring → a CLEAN app keyring: the developer's
# real keyring (system-wide "com.admincave.adminhelper") may hold an enrolled identity
# whose pinned CA rejects this throwaway stack's gateway cert (is_enrolled() true
# → login fails CA-pin/MITM). A fresh secret-service makes is_enrolled() false.
dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js --spec "$SPEC"
' && ok "live GUI spec (login → create tunnel) passed" || bad "live GUI spec failed"

# ── Independent server-side check: the tunnel really persisted ───────────────
COUNT=$(e2e_api "$TOKEN" count-tunnels "$SERVER_ID" 2>/dev/null || echo 0)
[ "${COUNT:-0}" -ge 1 ] && ok "tunnel persisted on the server (count=$COUNT)" \
    || bad "no tunnel found on the server (count=${COUNT:-0})"

echo ""
echo "desktop_e2e_live: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
