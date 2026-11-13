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
#
# The third spec (arch-monitoring-ui-3 T11) opens the service list of the fixture
# server and "Mehr Log" of a unit. That needs an SSH connection of the fixture
# server: an SSH target container whose journalctl is a stand-in that prints its
# arguments, so the spec sees what the remote shell made of the fixed command.

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

e2e_require ssh ssh-keygen node xvfb-run WebKitWebDriver tauri-driver dbus-run-session dbus-send gnome-keyring-daemon docker go
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
# Seeing the host's dockerd, it also needs the docker socket and CLI: a dockerd
# whose published ports cannot be read closes every port of the host (R-1324).
AGENT_CTR="$E2E_PROJECT-agent"
FIX_CTR="$E2E_PROJECT-fixture"
SSH_CTR="$E2E_PROJECT-ssh"
DOCKER_CLI=$(command -v docker)
trap 'docker rm -f "$AGENT_CTR" "$FIX_CTR" "$SSH_CTR" >/dev/null 2>&1; e2e_teardown' EXIT
docker run -d --rm --name "$AGENT_CTR" --network host --pid host \
    --cap-add SYS_PTRACE --security-opt apparmor=unconfined -v "$AGENT_BIN:/agent:ro" \
    -v /var/run/docker.sock:/var/run/docker.sock -v "$DOCKER_CLI:/usr/bin/docker:ro" \
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

# The SSH target of the fixture server's connection, on a port docker picks (the
# image and its user as in desktop_e2e_connect.sh). Readiness and sign-ins come
# from its log, so no probe from the host counts as a client.
SSH_IMAGE="lscr.io/linuxserver/openssh-server:latest@sha256:67d4c3a1402179a6579aa217a38b52ced557eb8a0c17a8e32fe986a4549fdee4"
docker run -d --name "$SSH_CTR" -p 127.0.0.1::2222 \
    -e PASSWORD_ACCESS=true -e USER_NAME=e2e -e USER_PASSWORD=e2e -e LOG_STDOUT=true \
    "$SSH_IMAGE" >/dev/null || { bad "SSH target did not start"; exit 1; }
SSH_PORT=$(docker port "$SSH_CTR" 2222/tcp | sed -n 's/^127\.0\.0\.1://p' | head -1)
ssh_up=0
for _ in $(seq 1 40); do
    docker logs "$SSH_CTR" 2>&1 | grep -q "listening on port 2222" && { ssh_up=1; break; }
    sleep 1
done
[ "$ssh_up" = 1 ] && [ -n "$SSH_PORT" ] && ok "SSH target listening on 127.0.0.1:$SSH_PORT" \
    || { bad "SSH target never came up"; docker logs --tail 20 "$SSH_CTR"; exit 1; }
# The image has no journalctl: the stand-in prints each argument on a line of its
# own, then their count.
docker exec -i "$SSH_CTR" sh -c 'cat > /usr/bin/journalctl && chmod 755 /usr/bin/journalctl' <<'JOURNALCTL' \
    && ok "stand-in journalctl on the SSH target" || { bad "stand-in journalctl"; exit 1; }
#!/bin/sh
for a in "$@"; do printf 'AH_E2E_ARG %s\n' "$a"; done
printf 'AH_E2E_ARGS %s\n' "$#"
JOURNALCTL
e2e_api "$TOKEN" connection fixture-ssh ssh 127.0.0.1 "$SSH_PORT" e2e "$FIX_SID" >/dev/null \
    && ok "seeded the fixture server's SSH connection" || { bad "seed SSH connection"; exit 1; }

# ssh would check the user's own known_hosts (the home of the passwd entry, not
# $HOME): a shim gives the app's ssh a known_hosts of the run, empty at the start
# (desktop_e2e_connect.sh). Only the third spec runs with it on its PATH.
SHIM_DIR="$E2E_WORK/bin"; mkdir -p "$SHIM_DIR"
REAL_SSH=$(command -v ssh) || { bad "ssh not found"; exit 1; }
E2E_KNOWN_HOSTS="$E2E_WORK/known_hosts"; : > "$E2E_KNOWN_HOSTS"
printf '#!/bin/bash\nexec %q -o %q "$@"\n' "$REAL_SSH" "UserKnownHostsFile=$E2E_KNOWN_HOSTS" > "$SHIM_DIR/ssh"
chmod +x "$SHIM_DIR/ssh"

echo "[mon] running the monitoring-services spec under xvfb..."
export AH_E2E_SSH_CONNECTION="fixture-ssh"
PATH="$SHIM_DIR:$PATH" dbus-run-session -- bash -c '
    e2e_keyring_start || exit 1
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/monitoring-services.live.js
' && ok "monitoring-services GUI spec passed" || bad "monitoring-services GUI spec failed"

if ssh-keygen -F "[127.0.0.1]:$SSH_PORT" -f "$E2E_KNOWN_HOSTS" >/dev/null 2>&1; then
    ok "the run's own known_hosts holds the SSH target's key"
else
    bad "the run's own known_hosts holds no key for the SSH target: ssh went past the shim"
fi
# "Mehr Log" signed in once, with the password the spec typed. The desktop reaches
# the published port with an IPv4 source. Polled: the log can lag on a loaded box.
signed_in=0
for _ in $(seq 1 30); do
    signed_in=$(docker logs "$SSH_CTR" 2>&1 \
        | grep -cE 'Accepted password for e2e from [[:digit:]]+(\.[[:digit:]]+){3} port ')
    [ "$signed_in" = 1 ] && break
    sleep 1
done
[ "$signed_in" = 1 ] && ok "sshd logged the sign-in of \"Mehr Log\"" \
    || { bad "sshd logged $signed_in sign-ins of e2e, expected 1"; docker logs --tail 25 "$SSH_CTR"; }

echo ""
echo "desktop_e2e_monitoring: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
