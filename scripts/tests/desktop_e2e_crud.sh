#!/usr/bin/env bash
#
# desktop_e2e_crud.sh — live desktop E2E for CRUD journeys through the GUI:
# create/rename/delete a connection, a tunnel, and create/delete a server. Each
# spec verifies itself via the reloaded list (GUI → gateway → server → DB).
#
# Boots the stack permissive, seeds an admin + a server + an FRP config (context
# for the connection/tunnel tabs), then drives the real app under xvfb + a fresh
# D-Bus session/keyring. Boot/seed/teardown are shared via lib_e2e_stack.sh.
# Needs the same tools as desktop_e2e_live.sh. Run: bash scripts/tests/desktop_e2e_crud.sh

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

e2e_init false
e2e_up gateway && ok "gateway live on :$E2E_HTTPS_PORT" || { bad "gateway never came up"; exit 1; }

TOKEN=$(e2e_admin_token)
[ -n "$TOKEN" ] && ok "admin login" || { bad "admin login failed"; e2e_dc logs --tail 40 server; exit 1; }
e2e_api "$TOKEN" server e2e-server e2e.local >/dev/null || { bad "seed server"; exit 1; }
e2e_api "$TOKEN" config e2e-frps localhost 7000 >/dev/null || { bad "seed FRP config"; exit 1; }
ok "seeded a server + FRP config"

XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
mkdir -p "$XDG_DATA_HOME/com.admincave.adminhelper"
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$XDG_DATA_HOME/com.admincave.adminhelper/settings.json"

echo "[e2e-crud] running the CRUD specs under xvfb..."
export AH_SERVER_URL="$E2E_SERVER_URL" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$E2E_ADMIN_PW" E2E_DIR

# Order: enroll-form is login-screen-only (never logs in, touches no server data),
# so it leads; connection + tunnel run while only the seeded server exists; the
# server spec (which adds/removes its own server) runs last.
dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/enroll-form.live.js \
        --spec test/specs/connection-crud.live.js \
        --spec test/specs/tunnel-crud.live.js \
        --spec test/specs/provisioning.live.js \
        --spec test/specs/server-crud.live.js \
        --spec test/specs/settings-mode.live.js
' && ok "GUI specs (enroll / connection / tunnel / provisioning / server / settings) passed" || bad "GUI specs failed"

echo ""
echo "desktop_e2e_crud: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
