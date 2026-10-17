#!/usr/bin/env bash
#
# box_tunnelbox.sh — S4 tunnel-agent role. Installs the agent and provisions it while
# the host has no tunnel yet (multibox.sh deletes the seeded one first), so no frpc
# runs. multibox.sh then creates the tunnel over the API, and one agent run has to set
# up frpc as the STCP SERVER on its own, exposing this box's own sshd (:22) through the
# REMOTE frps on the server box. A second tunnel must come by a reload, not a restart,
# while the visitor holds an SSH session over the first (R-0398). The cross-host half
# of the tunnel (visitor) is added separately. Prints TUNNEL_* markers.
#
# Called by scripts/tests/multibox.sh --tunnel via `vm.py run`, one mode per step:
#   box_tunnelbox.sh <SRV_IP> <TUN_SID> <TUN_PTOK>  install + provision, no tunnel yet
#   box_tunnelbox.sh late <TUNNEL>                  one agent run takes the tunnel created since
#   box_tunnelbox.sh mark <SSH_PUB_B64>             let the visitor in, note frpc and the agent log
#   box_tunnelbox.sh reload <TUNNEL>                a second tunnel: frpc reloads, no restart
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1
# shellcheck source=scripts/vm/lib.sh
. "$(dirname "$0")/../vm/lib.sh"

# The agent logs to stdout and to this file (internal/logging), the timer's runs included.
AGENT_LOG=/var/log/adminhelper/agent.log
# What mark notes for reload. Outside the checkout: a later `vm.py run --sync` replaces it.
MARK_FILE="$HOME/.mb-tunnel-mark"

# proxy_started <TUNNEL> — poll the frpc journal for the tunnel instead of a fixed sleep, it
# can lag on a loaded box (6.137). frp v0.69.1 logs "[<proxy>] start proxy success" once frps
# took the proxy (client/control.go).
proxy_started() {
  local journal
  for _ in $(seq 1 30); do
    journal="$(sudo journalctl -u frpc --no-pager -n 300 2>/dev/null)"
    grep -qF "[$1] start proxy success" <<<"$journal" && return 0
    sleep 1
  done
  return 1
}

# step_late <TUNNEL> — the tunnel was created after the provisioning. One agent run, as the
# timer does it, has to set frpc up for good: active, enabled (so it also runs after a
# reboot), and the tunnel taken by frps.
step_late() {
  local name="$1" rc=0 connected=0 active enabled hash_before hash_after sync_out
  echo "[tunnelbox] late: one agent run takes tunnel $name, created after the provisioning"
  sudo adminhelper-agent run --once || rc=$?
  proxy_started "$name" && connected=1
  active="$(systemctl is-active frpc.service 2>/dev/null)"
  enabled="$(systemctl is-enabled frpc.service 2>/dev/null)"
  if [ "$connected" = 1 ]; then
    echo "TUNNEL_FRPC_CONNECTED"
  else
    echo "TUNNEL_FRPC_NOT_CONNECTED"; sudo journalctl -u frpc --no-pager -n 30 2>/dev/null | sed 's/^/    /'
  fi
  if [ "$rc" = 0 ] && [ "$active" = active ] && [ "$enabled" = enabled ] && [ "$connected" = 1 ]; then
    echo "TUNNEL_LATE_OK"
  else
    echo "TUNNEL_LATE_FAIL"; echo "    agent run exit $rc, frpc.service $active/$enabled"
  fi

  # The agent's own sync, once more (R-0315): config-hash over the route bound to its server,
  # with its mTLS identity and its API key. The run above stored the hash of the config it
  # applied; the same hash back means the bound route answers this agent with that config.
  hash_before="$(sudo cat /etc/frp/.config-hash 2>/dev/null)"
  echo "[tunnelbox] frpc sync: config-hash over the route of its server with the agent certificate"
  if sync_out="$(sudo adminhelper-agent frpc sync 2>&1)"; then
    hash_after="$(sudo cat /etc/frp/.config-hash 2>/dev/null)"
    if [ -n "$hash_before" ] && [ "$hash_before" = "$hash_after" ] \
       && ! grep -q 'Config-Aenderung erkannt' <<<"$sync_out"; then
      echo "TUNNEL_SYNC_HASH_OK"
    else
      echo "TUNNEL_SYNC_HASH_CHANGED"; printf '%s\n' "$sync_out" | sed 's/^/    /'
    fi
  else
    echo "TUNNEL_SYNC_FAILED"; printf '%s\n' "$sync_out" | sed 's/^/    /'
  fi
}

# step_mark <SSH_PUB_B64> — before the second tunnel: let the visitor log in over the tunnel
# with its key (box_visitorbox.sh hold), and note frpc's PID and the end of the agent log,
# which step_reload holds the reload against.
step_mark() {
  local pub pid size
  pub="$(printf '%s' "$1" | base64 -d 2>/dev/null)"
  case "$pub" in
    ssh-ed25519\ *) ;;
    *) echo "TUNNEL_MARK_FAIL"; echo "    no visitor key (VIS_SSH_PUB_B64)"; return 0 ;;
  esac
  install -d -m 700 "$HOME/.ssh"
  printf '%s\n' "$pub" >> "$HOME/.ssh/authorized_keys"
  chmod 600 "$HOME/.ssh/authorized_keys"
  echo "TUNNEL_SSH_USER=$(id -un)"
  pid="$(systemctl show -p MainPID --value frpc.service 2>/dev/null)"
  size="$(sudo stat -c %s "$AGENT_LOG" 2>/dev/null)"
  printf 'PID=%s\nLOG_SIZE=%s\n' "$pid" "${size:-0}" > "$MARK_FILE"
  if [ -n "$pid" ] && [ "$pid" != 0 ]; then
    echo "TUNNEL_MARK_OK"
  else
    echo "TUNNEL_MARK_FAIL"; echo "    frpc is not running"
  fi
}

# step_reload <TUNNEL> — the second tunnel, created since step_mark. frpc has to take it by a
# reload over its local admin API, not by a restart: a restart ends every session over the
# first tunnel, and the visitor holds one open meanwhile (R-0398, goal 3). All of it must
# hold: the sync exits 0; the agent log since step_mark says "frpc reloaded" and nothing of a
# restart (whichever run applied it, this sync or the timer's); frpc still runs under the PID
# step_mark noted; frpc took the new proxy.
step_reload() {
  local name="$1" rc=0 started=0 pid_before="" size=0 pid_after sync_out since verdict
  if [ -r "$MARK_FILE" ]; then
    pid_before="$(sed -n 's/^PID=//p' "$MARK_FILE")"
    size="$(sed -n 's/^LOG_SIZE=//p' "$MARK_FILE")"
  fi
  echo "[tunnelbox] reload: frpc sync takes tunnel $name while a session runs over the first"
  sync_out="$(sudo adminhelper-agent frpc sync 2>&1)" || rc=$?
  printf '%s\n' "$sync_out" | sed 's/^/    sync: /'
  proxy_started "$name" && started=1
  pid_after="$(systemctl show -p MainPID --value frpc.service 2>/dev/null)"
  since="$(sudo tail -c +"$((${size:-0} + 1))" "$AGENT_LOG" 2>/dev/null)"
  if [ -z "$pid_before" ] || [ "$pid_before" = 0 ]; then
    verdict=TUNNEL_RELOAD_NO_MARK
  elif [ "$rc" != 0 ]; then
    verdict=TUNNEL_RELOAD_SYNC_FAILED
  elif [ "$pid_after" != "$pid_before" ] \
       || grep -qE 'frpc (restarted|enabled and started)\.|restarting frpc instead' <<<"$since"; then
    verdict=TUNNEL_RELOAD_RESTARTED
  elif ! grep -qF 'frpc.toml updated, frpc reloaded.' <<<"$since"; then
    verdict=TUNNEL_RELOAD_NOT_RELOADED
  elif [ "$started" != 1 ]; then
    verdict=TUNNEL_RELOAD_PROXY_MISSING
  else
    verdict=TUNNEL_RELOAD_OK
  fi
  echo "$verdict"
  if [ "$verdict" != TUNNEL_RELOAD_OK ]; then
    echo "    frpc PID ${pid_before:-none} -> ${pid_after:-none}"
    printf '%s\n' "$since" | tail -20 | sed 's/^/    agent log: /'
    sudo journalctl -u frpc --no-pager -n 30 2>/dev/null | sed 's/^/    frpc: /'
  fi
}

case "${1:-}" in
  late)   step_late "${2:?}"; exit 0 ;;
  mark)   step_mark "${2:?}"; exit 0 ;;
  reload) step_reload "${2:?}"; exit 0 ;;
esac

SRV_IP="${1:?}"; SID="${2:?}"; PTOK="${3:?}"

echo "[tunnelbox] hydrate (agent profile: Go + packaging)"
AH_BOOTSTRAP_PROFILE=agent bash scripts/vm/bootstrap_linux.sh || { echo "[tunnelbox] bootstrap failed"; exit 1; }
export PATH="$PATH:/usr/local/go/bin"

echo "[tunnelbox] build + install the .deb"
DEB="$(vm_build_agent_deb tunnelbox)" || exit 1
sudo apt-get install -y -o DPkg::Lock::Timeout=300 "$DEB" 2>/dev/null || sudo dpkg -i "$DEB" || { echo "[tunnelbox] install failed"; exit 1; }

echo "[tunnelbox] ensure sshd is listening on :22 (the STCP target)"
sudo systemctl enable --now ssh 2>/dev/null || sudo systemctl enable --now sshd 2>/dev/null || true
if ss -tlnH 'sport = :22' 2>/dev/null | grep -q .; then echo "TUNNEL_SSHD_OK"; else echo "TUNNEL_SSHD_MISSING"; fi

echo "[tunnelbox] provision against https://$SRV_IP (server $SID), its tunnel does not exist yet"
sudo adminhelper-agent provision --url "https://$SRV_IP" --token "$PTOK" --server-id "$SID" --insecure \
  && echo "TUNNEL_PROVISION_OK" || { echo "TUNNEL_PROVISION_FAIL"; exit 1; }
# No tunnel, no frpc. The sync config is written all the same, or a tunnel created later
# never comes (R-0398).
frpc_state="$(systemctl is-active frpc.service 2>/dev/null)"
if sudo test -s /etc/frp/adminhelper.conf && ! sudo test -e /etc/frp/frpc.toml && [ "$frpc_state" != active ]; then
  echo "TUNNEL_BEFORE_OK"
else
  echo "TUNNEL_BEFORE_FAIL"; echo "    frpc.service: ${frpc_state:-unknown}"; sudo ls -la /etc/frp/ 2>/dev/null | sed 's/^/    /'
fi
echo "TUNNEL_AGENT_DONE"
