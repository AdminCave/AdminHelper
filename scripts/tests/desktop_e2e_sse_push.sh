#!/usr/bin/env bash
#
# desktop_e2e_sse_push.sh — live desktop E2E: a notification pushed to the hub
# shows up in the bell in REAL TIME via SSE, not via the 30s poll fallback.
#
# Boots the stack permissive (incl. Redis — the SSE fan-out needs it), seeds the
# admin a scope=all subscription so it actually receives events, then drives the
# real app under xvfb + a fresh D-Bus session/keyring. The spec waits for the
# Rust SSE client to connect, injects an event via POST /api/internal/events, and
# asserts the bell badge appears within a few seconds (<< 30s poll = proof of
# push). Boot/seed/teardown are shared via lib_e2e_stack.sh. Needs the same tools
# as desktop_e2e_crud.sh. Run: bash scripts/tests/desktop_e2e_sse_push.sh

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

# Subscribe the admin to everything (scope=all) so resolve_recipients routes the
# injected event to them — without a subscription the bell stays empty.
curl -sk -X PUT "$E2E_SERVER_URL/api/users/me/notification-prefs" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"email":null,"telegram_chat_id":null,"subscriptions":[{"scope_type":"all","min_severity":"info","channel_email":false,"channel_telegram":false,"enabled":true}]}' \
    >/dev/null && ok "seeded scope=all subscription" || { bad "seed subscription"; exit 1; }

# The spec injects the event itself (Node context); hand it the internal key.
MONITOR_API_KEY=$(grep '^MONITOR_API_KEY=' "$E2E_WORK/.env" | cut -d= -f2-)
export MONITOR_API_KEY

XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
mkdir -p "$XDG_DATA_HOME/com.adminhelper.app"
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$XDG_DATA_HOME/com.adminhelper.app/settings.json"

echo "[e2e-sse] running the SSE push spec under xvfb..."
export AH_SERVER_URL="$E2E_SERVER_URL" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$E2E_ADMIN_PW" E2E_DIR

dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/notification-push.live.js
' && ok "GUI spec (SSE push -> bell in real time) passed" || bad "GUI spec failed"

echo ""
echo "desktop_e2e_sse_push: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
