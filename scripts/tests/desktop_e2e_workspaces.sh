#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# desktop_e2e_workspaces.sh — two installations side by side in two workspaces (R-0431).
#
# Two stacks with two PKIs, a and b (lib_e2e_stack.sh, e2e_init <mtls> a|b), seeded alike:
# a server, an FRP config, the SSH connection ssh-tunnel and the STCP tunnel e2e-ssh-tun
# linked to it, which an agent-provisioned frpc serves towards an SSH target of the stack's
# own (127.0.0.1:2222 for a, :2223 for b). Both installations give that tunnel the same
# visitor port, which the suite checks over the API first.
#
# Then the real app under xvfb, with a fresh XDG_DATA_HOME and a keyring of its own
# (dbus-run-session): a settings.json of a version before workspaces, in server mode at
# stack a, becomes the workspace "Standard"; in the launcher, workspace-add-server.live.js
# makes the server workspace "Kunde B" at stack b; then two workspace processes at once
# (wdio.workspaces.conf.js) run two-installations.workspaces.js: each registers at its
# stack, signs in, starts its tunnel and opens its SSH connection through the GUI.
# Afterwards each SSH target must have seen exactly one SSH client, the window of its own
# installation, and each workspace dir must hold the connection of its own server only.
# The suite itself opens no connection through the tunnels.
# Last, in the launcher again, workspace-delete-server.live.js deletes "Kunde B" in the
# picker: its purge revokes the device at stack b, which the suite checks there (open before,
# revoked by itself after), and its directory goes.
#
# Shared boot/seed/teardown via lib_e2e_stack.sh; SKIPs (exit 75) when a tool is missing.
# Run: bash scripts/tests/desktop_e2e_workspaces.sh

# shellcheck disable=SC2015
set -uo pipefail

# shellcheck source=scripts/tests/lib_e2e_stack.sh
. "$(cd "$(dirname "$0")" && pwd)/lib_e2e_stack.sh"

E2E_DIR="$E2E_REPO_ROOT/apps/desktop/e2e"
AGENT_BIN="$E2E_REPO_ROOT/apps/agent/bin/adminhelper-agent"
# As desktop_e2e_connect_tunnel.sh pins them.
SSH_IMAGE="lscr.io/linuxserver/openssh-server:latest@sha256:67d4c3a1402179a6579aa217a38b52ced557eb8a0c17a8e32fe986a4549fdee4"
FRPC_IMAGE="snowdreamtech/frpc:0.69.1"
# The names two-installations.workspaces.js expects in both installations.
TUNNEL=e2e-ssh-tun
CONNECTION=ssh-tunnel

PASS=0
FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

# Left by setup_stack for each stack; CONN_<key> too, which only its name reads.
URL_a=""; URL_b=""; ADMIN_PW_a=""; ADMIN_PW_b=""; TOKEN_a=""; TOKEN_b=""
ENROLL_a=""; ENROLL_b=""; SSH_C_a=""; SSH_C_b=""

CONTAINERS=()
VOLUMES=()
cleanup_extra() {
    local c v
    for c in "${CONTAINERS[@]:-}"; do [ -n "$c" ] && docker rm -f "$c" >/dev/null 2>&1; done
    for v in "${VOLUMES[@]:-}"; do [ -n "$v" ] && docker volume rm "$v" >/dev/null 2>&1; done
}
wait_log() { for _ in $(seq 1 "$3"); do docker logs "$1" 2>&1 | grep -qE "$2" && return 0; sleep 1; done; return 1; }

# ssh_clients <container> — how many SSH clients the target saw: the client ends (address and
# port) on the lines sshd logs once a client spoke SSH, all tagged [preauth] before a sign-in.
# A bare TCP connection leaves "Connection closed by <addr> port <p>" without the tag and does
# not count. Checked against the OpenSSH 10.2 of the pinned image: bare TCP, ssh at the
# host-key prompt and ssh at the password prompt.
ssh_clients() {
    docker logs "$1" 2>&1 \
        | grep -E '\[preauth\]|Accepted |Disconnected from ' \
        | grep -oE '[[:digit:]]+(\.[[:digit:]]+){3} port [[:digit:]]+' \
        | sort -u | grep -c .
}

# conn_ids <connections.json> — the ids of the connections a workspace keeps, one per line.
conn_ids() {
    python3 -c 'import json, sys; print("\n".join(c["id"] for c in json.load(open(sys.argv[1]))))' \
        "$1" 2>/dev/null
}

# setup_stack <a|b> <ssh port> — one installation, up to the frpc that serves the tunnel and an
# enrollment token for the app. Leaves URL_<key>, ADMIN_PW_<key>, TOKEN_<key>, CONN_<key>,
# ENROLL_<key> and SSH_C_<key>.
setup_stack() {
    local key=$1 port=$2 token server config conn ssh_c frp_vol id_vol ptok frpc_c enroll frps_ok
    e2e_stack_use "$key" || return 1
    e2e_up gateway && ok "[$key] gateway live on $E2E_SERVER_URL" \
        || { bad "[$key] gateway never came up"; return 1; }
    token=$(e2e_admin_token)
    [ -n "$token" ] && ok "[$key] admin login" \
        || { bad "[$key] admin login failed"; e2e_dc logs --tail 40 server; return 1; }
    server=$(e2e_api "$token" server e2e-server e2e.local) || { bad "[$key] seed server"; return 1; }
    # frpc of the agent and of the app reach frps on localhost, at the stack's own port.
    config=$(e2e_api "$token" config e2e-frps localhost "$E2E_FRP_BIND_PORT") \
        || { bad "[$key] seed FRP config"; return 1; }

    # The SSH target of this stack: a clean log, so every client there came through its tunnel.
    ssh_c="ah-e2e-wssh-$key-$$"
    # Listed before the start: docker creates the container even when publishing its port
    # fails, and cleanup_extra removes only what is listed.
    CONTAINERS+=("$ssh_c")
    docker run -d --name "$ssh_c" -p "127.0.0.1:$port:2222" \
        -e PASSWORD_ACCESS=true -e USER_NAME=e2e -e USER_PASSWORD=e2e -e LOG_STDOUT=true \
        "$SSH_IMAGE" >/dev/null \
        || { bad "[$key] SSH target ($ssh_c) failed to start — is 127.0.0.1:$port in use?"; return 1; }
    wait_log "$ssh_c" "listening on port 2222" 40 && ok "[$key] SSH target up on :$port" \
        || { bad "[$key] SSH target never came up"; docker logs --tail 20 "$ssh_c"; return 1; }

    # The connection's own host and port are a dead placeholder: only the resolve through the
    # tunnel reaches the target.
    conn=$(e2e_api "$token" connection "$CONNECTION" ssh 127.0.0.1 22 e2e) \
        || { bad "[$key] seed connection"; return 1; }
    e2e_api "$token" tunnel-conn "$server" "$config" "$TUNNEL" "$port" ssh "$conn" >/dev/null \
        && ok "[$key] seeded $CONNECTION + the STCP tunnel $TUNNEL linked to it" \
        || { bad "[$key] seed tunnel"; return 1; }

    # Built from apps/frps, so --build: a local image from an earlier run would be stale.
    e2e_dc up -d --build frps >/dev/null 2>&1 && ok "[$key] frps started on :$E2E_FRP_BIND_PORT" \
        || { bad "[$key] frps failed"; e2e_dc logs --tail 30 frps; return 1; }

    # The agent writes frpc.toml and its mTLS identity into two volumes the frpc container shares.
    frp_vol="ah-e2e-wfrp-$key-$$"; id_vol="ah-e2e-wid-$key-$$"
    docker volume create "$frp_vol" >/dev/null && VOLUMES+=("$frp_vol")
    docker volume create "$id_vol" >/dev/null && VOLUMES+=("$id_vol")
    ptok=$(e2e_api "$token" provision-token "$server") || { bad "[$key] provision token"; return 1; }
    docker run --rm --network host -v "$AGENT_BIN:/agent:ro" -v "$frp_vol:/etc/frp" \
        -v "$id_vol:/etc/adminhelper" debian:bookworm-slim \
        sh -c "/agent provision --url '$E2E_SERVER_URL' --token '$ptok' --server-id '$server' --insecure" \
        > "$E2E_WORK/agent-prov.log" 2>&1
    grep -q "frpc.toml geschrieben" "$E2E_WORK/agent-prov.log" \
        && ok "[$key] agent wrote the frpc.toml (STCP server config)" \
        || { bad "[$key] agent did not write frpc.toml"; sed 's/^/    /' "$E2E_WORK/agent-prov.log"; return 1; }

    frpc_c="ah-e2e-wfrpc-$key-$$"
    CONTAINERS+=("$frpc_c")  # before the start, as the SSH target's
    # No `-c`: the image defaults to `frpc -c /etc/frp/frpc.toml`, its entrypoint mangles extra args.
    docker run -d --name "$frpc_c" --network host -v "$frp_vol:/etc/frp" -v "$id_vol:/etc/adminhelper" \
        "$FRPC_IMAGE" >/dev/null || { bad "[$key] frpc container ($frpc_c) failed to start"; return 1; }
    frps_ok=0
    for _ in $(seq 1 15); do
        e2e_dc logs frps 2>/dev/null | grep -qiE "new proxy|start proxy success|stcp" && { frps_ok=1; break; }
        sleep 1
    done
    if [ "$frps_ok" = 1 ]; then
        ok "[$key] agent frpc registered the STCP server with frps"
    else
        bad "[$key] agent frpc did not register with frps"
        echo "    frpc log:"; docker logs --tail 15 "$frpc_c" 2>&1 | sed 's/^/    /'
        echo "    frps log:"; e2e_dc logs --tail 15 frps 2>&1 | sed 's/^/    /'
    fi

    # Device enrollment token, redeemed by the app over the certless :8444 of this stack.
    enroll=$(e2e_dc exec -T server python -m app.cli mint-enroll-token --username admin 2>/dev/null | tr -d '\r\n')
    [ -n "$enroll" ] && ok "[$key] minted an enrollment token" \
        || { bad "[$key] could not mint an enrollment token"; return 1; }

    printf -v "URL_$key" '%s' "$E2E_SERVER_URL"
    printf -v "ADMIN_PW_$key" '%s' "$E2E_ADMIN_PW"
    printf -v "TOKEN_$key" '%s' "$token"
    printf -v "CONN_$key" '%s' "$conn"
    printf -v "ENROLL_$key" '%s' "$enroll"
    printf -v "SSH_C_$key" '%s' "$ssh_c"
}

e2e_require node xvfb-run WebKitWebDriver tauri-driver dbus-run-session gnome-keyring-daemon docker go
( cd "$E2E_REPO_ROOT/apps/desktop/src-tauri" && cargo tauri --version >/dev/null 2>&1 ) \
    || { echo "SKIP: tauri-cli (cargo tauri) not available"; exit 75; }
e2e_npm_ready "$E2E_REPO_ROOT/apps/desktop/ui" "$E2E_DIR" || exit 1

echo "[ws] building the linux agent..."
( cd "$E2E_REPO_ROOT/apps/agent" && make build-linux >/dev/null 2>&1 ) && [ -x "$AGENT_BIN" ] \
    && ok "agent built" || { bad "agent build failed"; exit 1; }

e2e_init false a || { bad "e2e_init a"; exit 1; }
e2e_init false b || { bad "e2e_init b"; exit 1; }
trap 'cleanup_extra; e2e_teardown' EXIT
setup_stack a 2222 || exit 1
setup_stack b 2223 || exit 1

# Fresh stacks each seed one STCP tunnel, so both give it the first port of the range.
e2e_stack_use a; VPORT_a=$(e2e_api "$TOKEN_a" visitor-port "$TUNNEL")
e2e_stack_use b; VPORT_b=$(e2e_api "$TOKEN_b" visitor-port "$TUNNEL")
[ -n "$VPORT_a" ] && [ "$VPORT_a" = "$VPORT_b" ] \
    && ok "both installations gave $TUNNEL the visitor port $VPORT_a" \
    || { bad "visitor ports of $TUNNEL: a '$VPORT_a', b '$VPORT_b'"; exit 1; }

# A fresh app data dir per run, under the work dir of stack a (the teardown removes it). The
# keyring of gnome-keyring-daemon lands there too, so neither workspace starts registered.
e2e_stack_use a
XDG_DATA_HOME="$E2E_WORK/xdg-data"; export XDG_DATA_HOME
APP_DATA="$XDG_DATA_HOME/com.admincave.adminhelper"
mkdir -p "$APP_DATA"
# A settings.json of a version before workspaces, in server mode at stack a: the app moves it
# into the workspace "standard" at its first start (R-0431).
printf '{"mode": "server", "serverUrl": "%s", "allowSelfSignedCerts": true}\n' "$URL_a" \
    > "$APP_DATA/settings.json"
WS_B_FILE="$E2E_WORK/workspace-b.id"
export E2E_DIR

# In the launcher: an empty AH_E2E_WORKSPACE (test/lib/app-args.js).
echo "[ws] making the workspace of stack b in the launcher under xvfb..."
AH_E2E_WORKSPACE='' AH_E2E_SERVER_URL_B="$URL_b" AH_E2E_WS_B_FILE="$WS_B_FILE" \
dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/workspace-add-server.live.js
' && ok "launcher: made the server workspace of stack b" || { bad "launcher spec failed"; exit 1; }
WS_B=$(tr -d '\n' < "$WS_B_FILE" 2>/dev/null)
# The class spelled out: under a de_DE locale a-z also matches other letters.
[[ $WS_B =~ ^[abcdefghijklmnopqrstuvwxyz0123456789-]{1,32}$ ]] && [ "$WS_B" != standard ] \
    && ok "the workspace of stack b has the id $WS_B" \
    || { bad "no workspace id of stack b in $WS_B_FILE: '$WS_B'"; exit 1; }

echo "[ws] two workspaces at once under xvfb: register, sign in, tunnels, ssh through each..."
AH_E2E_WORKSPACE_A=standard AH_E2E_WORKSPACE_B="$WS_B" \
AH_E2E_SERVER_URL_A="$URL_a" AH_E2E_SERVER_URL_B="$URL_b" \
AH_ENROLL_TOKEN_A="$ENROLL_a" AH_ENROLL_TOKEN_B="$ENROLL_b" \
AH_ADMIN_USER=admin AH_ADMIN_PASS_A="$ADMIN_PW_a" AH_ADMIN_PASS_B="$ADMIN_PW_b" \
dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.workspaces.conf.js \
        --spec test/specs/two-installations.workspaces.js
' && ok "GUI: both windows registered, signed in, tunnels side by side, ssh opened in each" \
  || bad "GUI two-installations spec failed"

# Each target sees its client once the ssh of the GUI has ended with the app; poll for that.
SEEN_a=0; SEEN_b=0
for _ in $(seq 1 20); do
    SEEN_a=$(ssh_clients "$SSH_C_a"); SEEN_b=$(ssh_clients "$SSH_C_b")
    [ "$SEEN_a" -ge 1 ] && [ "$SEEN_b" -ge 1 ] && break
    sleep 1
done
for key in a b; do
    seen="SEEN_$key"; c="SSH_C_$key"
    if [ "${!seen}" = 1 ]; then
        ok "SSH target $key saw one SSH client, the window of its own installation"
    else
        bad "SSH target $key saw ${!seen} SSH clients, not 1"; docker logs --tail 25 "${!c}" 2>&1 | sed 's/^/    /'
    fi
done

# The cache of a server workspace holds what its server listed, and nothing of the other one.
for pair in "standard a b" "$WS_B b a"; do
    read -r ws own other <<<"$pair"
    want="CONN_$own"; not="CONN_$other"; dir="$APP_DATA/workspaces/$ws"
    ids=$(conn_ids "$dir/connections.json")
    leak=$(grep -rlF -- "${!not}" "$dir" 2>/dev/null | tr '\n' ' ')
    if [ "$ids" = "${!want}" ] && [ -z "$leak" ]; then
        ok "workspaces/$ws holds the connection of stack $own only"
    else
        bad "workspaces/$ws: connections.json lists '${ids//$'\n'/ }', not ${!want} of stack $own${leak:+; the connection of stack $other is in $leak}"
    fi
done

# Deleting a server workspace revokes its device first (R-0431). The device wsB registered is
# the one device of the admin at stack b that is not revoked, until the delete.
e2e_stack_use b
DEVICE_B=$(e2e_api "$TOKEN_b" devices admin | awk '$2 == "-" { print $1 }')
[ -n "$DEVICE_B" ] && [ "$(grep -c . <<<"$DEVICE_B")" = 1 ] \
    && ok "stack b lists the device of $WS_B, not revoked" \
    || bad "stack b lists not one open device of the admin, but: '${DEVICE_B//$'\n'/ }'"

# In the launcher again, with the XDG_DATA_HOME of the runs before: gnome-keyring keeps its
# login keyring under it, and the daemon of this D-Bus session unlocks it anew, so the purge
# finds the identity of wsB.
echo "[ws] deleting the workspace of stack b in the launcher under xvfb..."
AH_E2E_WORKSPACE='' AH_E2E_WORKSPACE_B="$WS_B" AH_E2E_SERVER_URL_B="$URL_b" \
dbus-run-session -- bash -c '
    eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js \
        --spec test/specs/workspace-delete-server.live.js
' && ok "launcher: deleted the workspace of stack b" || bad "launcher delete spec failed"

[ ! -e "$APP_DATA/workspaces/$WS_B" ] && ok "workspaces/$WS_B is gone" \
    || bad "workspaces/$WS_B is still there"
REASON_B=$(e2e_api "$TOKEN_b" devices admin | DEVICE="$DEVICE_B" awk '$1 == ENVIRON["DEVICE"] { print $2 }')
[ -n "$DEVICE_B" ] && [ "$REASON_B" = self ] \
    && ok "stack b lists the device of $WS_B as revoked by itself" \
    || bad "the device '$DEVICE_B' at stack b is revoked '${REASON_B:-not at all}', not by itself"

echo ""
echo "desktop_e2e_workspaces: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
