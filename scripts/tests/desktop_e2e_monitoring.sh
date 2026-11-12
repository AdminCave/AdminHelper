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
#
# The second spec (arch-monitoring-ui T11) walks the server page and the cross
# tabs and saves a screenshot of every step under .ah-out/screenshots/. The agent
# stays in its container for it: the spec lets it report again, and its first
# report made the port finding the spec adopts (the gateway's published port, a
# docker-proxy listener on the host network the agent shares).
#
# Its second part (arch-monitoring-ui-2 T11) needs a second server, created
# after the first spec so that spec sees one server only: a fixture agent is
# provisioned for it and never runs (a run would scan and report the test box),
# and the spec pushes a fixed report with that agent's key.

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

e2e_require node xvfb-run WebKitWebDriver tauri-driver dbus-run-session dbus-send gnome-keyring-daemon docker go
( cd "$E2E_REPO_ROOT/apps/desktop/src-tauri" && cargo tauri --version >/dev/null 2>&1 ) \
    || { echo "SKIP: tauri-cli (cargo tauri) not available"; exit 75; }
e2e_npm_ready "$E2E_REPO_ROOT/apps/desktop/ui" "$E2E_DIR" || exit 1

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
# Its container lives as long as the run, so a spec can let it report again.
# It sees the host's processes as an agent on the host does: the probe guard
# connects to no port whose owner it cannot read (pid namespace, ptrace of
# processes outside the container), so without them the scan finds no port.
AGENT_CTR="$E2E_PROJECT-agent"
FIX_CTR="$E2E_PROJECT-fixture"
trap 'docker rm -f "$AGENT_CTR" "$FIX_CTR" >/dev/null 2>&1; e2e_teardown' EXIT
docker run -d --rm --name "$AGENT_CTR" --network host --pid host \
    --cap-add SYS_PTRACE --security-opt apparmor=unconfined -v "$AGENT_BIN:/agent:ro" \
    debian:bookworm-slim sleep 7200 >/dev/null \
    || { bad "agent container did not start"; exit 1; }
PTOK=$(e2e_api "$TOKEN" provision-token "$SID")
docker exec "$AGENT_CTR" \
    sh -c "/agent provision --url 'https://localhost:$E2E_HTTPS_PORT' --token '$PTOK' --server-id '$SID' --insecure; /agent run --once" \
    > "$E2E_WORK/agent.log" 2>&1
grep -q "Report gesendet" "$E2E_WORK/agent.log" \
    && ok "real agent enrolled + pushed metrics" \
    || { bad "agent push failed"; sed 's/^/    /' "$E2E_WORK/agent.log"; }

# The first run of a fresh server scans: the gateway's port is a finding.
FINDING="tcp-$E2E_HTTPS_PORT"
FOUND=$(e2e_api "$TOKEN" findings "$SID")
grep -qx "$FINDING new" <<<"$FOUND" \
    && ok "the agent's scan found $FINDING" \
    || { bad "no finding $FINDING after the scan"; sed 's/^/    /' <<<"$FOUND"; }

XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
mkdir -p "$XDG_DATA_HOME/com.admincave.adminhelper"
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$XDG_DATA_HOME/com.admincave.adminhelper/settings.json"

echo "[mon] running the monitoring-check spec under xvfb..."
export AH_SERVER_URL="$E2E_SERVER_URL" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$E2E_ADMIN_PW" E2E_DIR
dbus-run-session -- bash -c '
    e2e_keyring_start || exit 1
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/monitoring-check.live.js
' && ok "monitoring-check GUI spec passed" || bad "monitoring-check GUI spec failed"

# The fixture server: provisioning writes the agent's monitor.conf and makes one
# test push of the container's own (empty) data, before the spec creates checks.
FIX_SID=$(e2e_api "$TOKEN" server e2e-fixture fixture.local)
[ -n "$FIX_SID" ] && ok "fixture server" || { bad "fixture server"; exit 1; }
docker run -d --rm --name "$FIX_CTR" --network host -v "$AGENT_BIN:/agent:ro" \
    debian:bookworm-slim sleep 7200 >/dev/null \
    || { bad "fixture agent container did not start"; exit 1; }
PTOK2=$(e2e_api "$TOKEN" provision-token "$FIX_SID")
docker exec "$FIX_CTR" /agent provision --url "https://localhost:$E2E_HTTPS_PORT" \
    --token "$PTOK2" --server-id "$FIX_SID" --insecure > "$E2E_WORK/fixture-agent.log" 2>&1
grep -q "Test-Push erfolgreich" "$E2E_WORK/fixture-agent.log" \
    && ok "fixture agent provisioned" \
    || { bad "fixture agent provisioning failed"; sed 's/^/    /' "$E2E_WORK/fixture-agent.log"; }

echo "[mon] running the monitoring-server-page spec under xvfb..."
export AH_E2E_FINDING="$FINDING" AH_E2E_AGENT="$AGENT_CTR" AH_E2E_FIXTURE_AGENT="$FIX_CTR"
dbus-run-session -- bash -c '
    e2e_keyring_start || exit 1
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/monitoring-server-page.live.js
' && ok "monitoring-server-page GUI spec passed" || bad "monitoring-server-page GUI spec failed"

echo ""
echo "desktop_e2e_monitoring: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
