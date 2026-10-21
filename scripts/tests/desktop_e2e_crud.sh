#!/usr/bin/env bash
#
# desktop_e2e_crud.sh — live desktop E2E for CRUD journeys through the GUI:
# create/rename/delete a connection, a tunnel, and create/delete a server. Each
# spec verifies itself via the reloaded list (GUI → gateway → server → DB). Last,
# in the launcher, the picker makes, renames and deletes a local workspace.
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
    || { echo "SKIP: tauri-cli (cargo tauri) not available"; exit 75; }

# Standalone-run self-sufficiency (fresh box, no prior run.sh layer): without the
# local node_modules, `npx wdio` fetches the interactive `wdio` WIZARD package from
# the registry instead of the local @wdio/cli, and the tauri beforeBuildCommand
# dies on `svelte-check: not found` in ui/. Older than the lockfile counts as
# missing: template node_modules lacked the junit reporter (R-0131).
e2e_npm_ready "$E2E_REPO_ROOT/apps/desktop/ui" "$E2E_DIR" || exit 1

e2e_init false
e2e_up gateway && ok "gateway live on :$E2E_HTTPS_PORT" || { bad "gateway never came up"; exit 1; }

TOKEN=$(e2e_admin_token)
[ -n "$TOKEN" ] && ok "admin login" || { bad "admin login failed"; e2e_dc logs --tail 40 server; exit 1; }
e2e_api "$TOKEN" server e2e-server e2e.local >/dev/null || { bad "seed server"; exit 1; }
e2e_api "$TOKEN" config e2e-frps localhost 7000 >/dev/null || { bad "seed FRP config"; exit 1; }
ok "seeded a server + FRP config"

XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
APP_DATA="$XDG_DATA_HOME/com.admincave.adminhelper"
SETTINGS_JSON="$APP_DATA/settings.json"
# Where the app keeps the settings of the workspace the specs open (AH_E2E_WORKSPACE,
# lib_e2e_stack.sh) once it has moved settings.json there at its first start (R-0431).
STANDARD_JSON="$APP_DATA/workspaces/standard/workspace.json"
mkdir -p "$APP_DATA"

export AH_SERVER_URL="$E2E_SERVER_URL" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$E2E_ADMIN_PW" E2E_DIR

# First contact with DEFAULT trust settings: the trust-dialog spec needs
# allowSelfSignedCerts=false (the fresh-install state that used to dead-end in a
# raw UnknownIssuer error); accepting the dialog makes the APP persist true.
echo '{"mode": "server", "allowSelfSignedCerts": false}' > "$SETTINGS_JSON"

echo "[e2e-crud] running the trust-dialog spec under xvfb..."
dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/enroll-trust-dialog.live.js
' && ok "trust-dialog spec passed" || bad "trust-dialog spec failed"
grep -Eq '"allowSelfSignedCerts": ?true' "$STANDARD_JSON" \
    && ok "accepting the dialog persisted allowSelfSignedCerts=true" \
    || bad "workspaces/standard/workspace.json does not carry the persisted opt-in"

# Known-good seed for the remaining specs, independent of the outcome above. The app
# moves settings.json only while workspaces.json is missing; without these the specs
# would open what the trust-dialog spec left.
rm -rf -- "$APP_DATA/workspaces.json" "$APP_DATA/workspaces" "$APP_DATA/prefs.json" \
    || { bad "could not remove the workspaces of the trust-dialog spec"; exit 1; }
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$SETTINGS_JSON"

echo "[e2e-crud] running the CRUD specs under xvfb..."

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
        --spec test/specs/server-crud.live.js
' && ok "GUI specs (enroll / connection / tunnel / provisioning / server) passed" || bad "GUI specs failed"

# The picker replaces the switch of the app mode (R-0431). A run of its own: an empty
# AH_E2E_WORKSPACE opens the launcher (test/lib/app-args.js). Last: the runs above opened
# "standard" and listed nothing, so the note on the migration is still due.
echo "[e2e-crud] running the picker spec in the launcher under xvfb..."
AH_E2E_WORKSPACE='' dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/workspace-picker.live.js
' && ok "picker spec passed" || bad "picker spec failed"
# The spec deletes the workspace it made, and its directory goes with it.
LEFT=$(find "$APP_DATA/workspaces" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null | sort)
[ "$LEFT" = "standard" ] && ok "only workspaces/standard is left after the picker spec" \
    || bad "workspaces/ holds: ${LEFT//$'\n'/ }"

echo ""
echo "desktop_e2e_crud: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
