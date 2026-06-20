#!/usr/bin/env bash
#
# desktop_e2e_monitoring.sh — live desktop E2E for the monitoring-check journey
# against REAL agent data: a real Go agent enrolls + pushes metrics for the
# seeded server, then the desktop creates an agent_resources check through the
# GUI and it shows up (reloaded from the monitoring service via the 443 proxy).
#
# Combines the desktop harness (xvfb + tauri-driver + fresh D-Bus/keyring) with
# the agent push from agent_monitoring_test.sh. Shared boot/seed/teardown via
# lib_e2e_stack.sh. Run: bash scripts/tests/desktop_e2e_monitoring.sh

# shellcheck disable=SC2015
set -uo pipefail

# shellcheck source=scripts/tests/lib_e2e_stack.sh
. "$(cd "$(dirname "$0")" && pwd)/lib_e2e_stack.sh"

E2E_DIR="$E2E_REPO_ROOT/apps/desktop/e2e"
AGENT_BIN="$E2E_REPO_ROOT/apps/agent/bin/adminhelper-agent"

PASS=0
FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

e2e_require node xvfb-run WebKitWebDriver tauri-driver dbus-run-session gnome-keyring-daemon docker go
( cd "$E2E_REPO_ROOT/apps/desktop/src-tauri" && cargo tauri --version >/dev/null 2>&1 ) \
    || { echo "SKIP: tauri-cli (cargo tauri) not available"; exit 0; }

echo "[mon] building the linux agent..."
( cd "$E2E_REPO_ROOT/apps/agent" && make build-linux >/dev/null 2>&1 ) && [ -x "$AGENT_BIN" ] \
    && ok "agent built" || { bad "agent build failed"; exit 1; }

e2e_init false
e2e_up gateway monitoring \
    && ok "gateway + monitoring live on :$E2E_HTTPS_PORT" \
    || { bad "stack never came up"; e2e_dc logs --tail 30 monitoring; exit 1; }

TOKEN=$(e2e_admin_token)
[ -n "$TOKEN" ] && ok "admin login" || { bad "admin login failed"; exit 1; }
SID=$(e2e_api "$TOKEN" server e2e-server e2e.local)
[ -n "$SID" ] && ok "seeded server" || { bad "seed server"; exit 1; }

# A real agent enrolls + pushes metrics for the server so the check has data to
# evaluate (host network + localhost:<port> so the test gateway cert verifies).
PTOK=$(e2e_api "$TOKEN" provision-token "$SID")
docker run --rm --network host -v "$AGENT_BIN:/agent:ro" debian:bookworm-slim \
    sh -c "/agent provision --url 'https://localhost:$E2E_HTTPS_PORT' --token '$PTOK' --server-id '$SID' --insecure; /agent run --once" \
    > "$E2E_WORK/agent.log" 2>&1
grep -q "Report gesendet" "$E2E_WORK/agent.log" \
    && ok "real agent enrolled + pushed metrics" \
    || { bad "agent push failed"; sed 's/^/    /' "$E2E_WORK/agent.log"; }

XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
mkdir -p "$XDG_DATA_HOME/com.adminhelper.app"
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$XDG_DATA_HOME/com.adminhelper.app/settings.json"

echo "[mon] running the monitoring-check spec under xvfb..."
export AH_SERVER_URL="$E2E_SERVER_URL" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$E2E_ADMIN_PW" E2E_DIR
dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/monitoring-check.live.js
' && ok "monitoring-check GUI spec passed" || bad "monitoring-check GUI spec failed"

echo ""
echo "desktop_e2e_monitoring: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
