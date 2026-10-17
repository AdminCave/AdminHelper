#!/usr/bin/env bash
#
# box_visitorbox.sh — S4 phase 2. The STCP VISITOR that completes the tunnel
# data path across three hosts: it connects through the REMOTE frps to the
# tunnel-agent's frpc STCP server and reaches that agent's sshd — proving data
# flows visitor-host → frps-host → agent-host with none of them co-located.
#
# The desktop normally supplies its enrolled ACCESS identity for the visitor's TLS;
# here the box provisions (a tunnel-scoped, CA-signed identity frps also trusts) and
# the fetched visitor.toml is rewired to point at it. Prints VIS_* markers.
#
# Then an SSH session through the tunnel stays open while the tunnel agent reloads
# frpc for a second tunnel, and has to live through it (R-0398).
#
# Called by scripts/tests/multibox.sh --tunnel via `vm.py run`, one mode per step:
#   box_visitorbox.sh <SRV_IP> <VIS_SID> <VIS_PTOK> <VISITOR_TOML_B64>
#   box_visitorbox.sh hold <TUNNEL_BOX_USER>   an SSH session through the tunnel, left open
#   box_visitorbox.sh check                    did that session live through the reload?
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1
# shellcheck source=scripts/vm/lib.sh
. "$(dirname "$0")/../vm/lib.sh"

# The SSH key and the session, between the modes. Outside the checkout: a later
# `vm.py run --sync` replaces it.
STATE="$HOME/.mb-visitor"

# step_hold <TUNNEL_BOX_USER> — the visitor frpc again, and an SSH session through it as the
# tunnel box's user (box_tunnelbox.sh mark let this key in). The remote side prints a tick a
# second, so step_check can see the session still carry data. Both run detached, like the
# visitor frpc below, or `vm.py run` would wait for them.
step_hold() {
  local user="$1" vport up=0 ticks=0
  local opts=(-i "$STATE/id_ed25519" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no
              -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=2 -o ServerAliveCountMax=3
              -o LogLevel=ERROR)
  vport="$(sudo grep -E '^bindPort' /etc/frp/visitor.toml 2>/dev/null | head -1 | grep -oE '[0-9]+')"
  [ -n "$vport" ] || { echo "VIS_SESSION_NOT_OPEN"; echo "    no bindPort in /etc/frp/visitor.toml"; return 0; }
  echo "[visitorbox] hold: visitor frpc on 127.0.0.1:$vport, then an SSH session as $user through it"
  # shellcheck disable=SC2024  # the log is this user's on purpose, read below without sudo
  sudo setsid /usr/bin/frpc -c /etc/frp/visitor.toml </dev/null >/tmp/frpc-vis-hold.log 2>&1 &
  for _ in $(seq 1 30); do [ -n "$(ss -tlnH "sport = :$vport" 2>/dev/null)" ] && { up=1; break; }; sleep 1; done
  [ "$up" = 1 ] || { echo "VIS_SESSION_NOT_OPEN"; sed 's/^/    frpc: /' /tmp/frpc-vis-hold.log; return 0; }
  setsid ssh "${opts[@]}" -p "$vport" "$user@127.0.0.1" "while sleep 1; do date +%s; done" </dev/null >"$STATE/session.log" 2>&1 &
  echo "$!" > "$STATE/ssh.pid"
  for _ in $(seq 1 45); do
    ticks="$(grep -cE '^[0-9]+$' "$STATE/session.log" 2>/dev/null)"
    [ "${ticks:-0}" -ge 2 ] && break
    sleep 1
  done
  if [ "${ticks:-0}" -ge 2 ]; then
    echo "VIS_SESSION_OPEN"
  else
    echo "VIS_SESSION_NOT_OPEN"; sed 's/^/    ssh: /' "$STATE/session.log"; sed 's/^/    frpc: /' /tmp/frpc-vis-hold.log
  fi
}

# step_check — after the reload on the tunnel box: the same ssh process still runs (ssh does
# not reconnect), and its ticks still come in. A restarted frpc would have ended it.
step_check() {
  local pid alive=0 before after
  pid="$(cat "$STATE/ssh.pid" 2>/dev/null)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && [ "$(cat "/proc/$pid/comm" 2>/dev/null)" = ssh ]; then
    alive=1
  fi
  before="$(grep -cE '^[0-9]+$' "$STATE/session.log" 2>/dev/null)"
  sleep 5
  after="$(grep -cE '^[0-9]+$' "$STATE/session.log" 2>/dev/null)"
  if [ "$alive" = 1 ] && [ "${after:-0}" -gt "${before:-0}" ]; then
    echo "VIS_SESSION_SURVIVED"
  else
    echo "VIS_SESSION_LOST"; echo "    ssh running: $alive, ticks ${before:-0} -> ${after:-0}"
    tail -5 "$STATE/session.log" 2>/dev/null | sed 's/^/    ssh: /'
  fi
  if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; fi
  sudo pkill -f "frpc -c /etc/frp/visitor.toml" 2>/dev/null || true
}

case "${1:-}" in
  hold)  step_hold "${2:?}"; exit 0 ;;
  check) step_check; exit 0 ;;
esac

SRV_IP="${1:?}"; VSID="${2:?}"; VPTOK="${3:?}"; VB64="${4:?}"

echo "[visitorbox] hydrate + build/install the agent (for the binary + frpc sidecar)"
AH_BOOTSTRAP_PROFILE=agent bash scripts/vm/bootstrap_linux.sh || { echo "[visitorbox] bootstrap failed"; exit 1; }
export PATH="$PATH:/usr/local/go/bin"
DEB="$(vm_build_agent_deb visitorbox)" || exit 1
sudo apt-get install -y -o DPkg::Lock::Timeout=300 "$DEB" 2>/dev/null || sudo dpkg -i "$DEB" || { echo "[visitorbox] install failed"; exit 1; }

echo "[visitorbox] provision -> CA-signed mTLS identity for the visitor's TLS to frps"
sudo adminhelper-agent provision --url "https://$SRV_IP" --token "$VPTOK" --server-id "$VSID" --insecure \
  && echo "VIS_PROVISION_OK" || { echo "VIS_PROVISION_FAIL"; exit 1; }

echo "[visitorbox] write + rewire the visitor.toml ({{IDENTITY_DIR}} placeholder -> the provisioned cert)"
sudo mkdir -p /etc/frp
printf '%s' "$VB64" | base64 -d | sudo tee /etc/frp/visitor.toml >/dev/null
# The server emits {{IDENTITY_DIR}} placeholders (config_generator.py); the desktop
# replaces them with its keyring-exported identity dir. This box has no desktop, so
# it maps the placeholder straight to the agent's provisioned mTLS material.
sudo sed -i \
  -e 's#{{IDENTITY_DIR}}/ca.crt#/etc/adminhelper/identity/ca.crt#' \
  -e 's#{{IDENTITY_DIR}}/cert.pem#/etc/adminhelper/identity/agent.crt#' \
  -e 's#{{IDENTITY_DIR}}/key.pem#/etc/adminhelper/identity/agent.key#' \
  /etc/frp/visitor.toml
# sudo: the agent package keeps /etc/frp root-only (it holds tunnel credentials),
# so a plain grep here died with "Permission denied" and the whole visitor leg
# was reported as "could not reach the agent's sshd".
VPORT="$(sudo grep -E '^bindPort' /etc/frp/visitor.toml | head -1 | grep -oE '[0-9]+')"
[ -n "$VPORT" ] && echo "VIS_BIND_PORT=$VPORT" || { echo "VIS_NO_BIND_PORT"; sudo cat /etc/frp/visitor.toml; exit 1; }

echo "[visitorbox] run frpc visitor -> bind 127.0.0.1:$VPORT (through frps to the agent's sshd)"
# Detached on purpose (setsid, stdin from /dev/null, both outputs to the log):
# `sudo sh -c '…' &` left sudo and sh holding the ssh session's stdout/stderr, so
# `vm.py run` — no pty — never saw EOF and sat there until its 3000 s timeout
# (capstone 2026-09-18). The tunnel box has the same daemon under systemd; this
# one is a per-run helper and is stopped again below.
# shellcheck disable=SC2024  # the log is opened by THIS user on purpose: the poll
# loop below reads it without sudo, and a root-owned file would make it unreadable.
sudo setsid /usr/bin/frpc -c /etc/frp/visitor.toml </dev/null >/tmp/frpc-vis.log 2>&1 &
# Poll for the visitor registration instead of a fixed sleep — it can lag on a loaded box (6.137).
vis_ok=0
for _ in $(seq 1 20); do grep -qiE 'start.*visitor.*success|login to server success|start proxy success' /tmp/frpc-vis.log 2>/dev/null && { vis_ok=1; break; }; sleep 1; done
if [ "$vis_ok" = 1 ]; then
  echo "VIS_FRPC_UP"
else
  echo "VIS_FRPC_DOWN"; sed 's/^/    /' /tmp/frpc-vis.log
fi

echo "[visitorbox] pull the SSH banner through the tunnel (proves the cross-host data path)"
BANNER="$(timeout 8 bash -c "exec 3<>/dev/tcp/127.0.0.1/$VPORT; head -c 40 <&3" 2>/dev/null || true)"
echo "    banner: ${BANNER%%$'\n'*}"
printf '%s' "$BANNER" | grep -q 'SSH-' && echo "VIS_TUNNEL_SSH_OK" || { echo "VIS_TUNNEL_SSH_FAIL"; sed 's/^/    frpc: /' /tmp/frpc-vis.log; }
sudo pkill -f "frpc -c /etc/frp/visitor.toml" 2>/dev/null || true

# The key step_hold logs in to the tunnel box with. multibox.sh carries the public half
# there (box_tunnelbox.sh mark); made here, so that needs no round trip of its own.
install -d -m 700 "$STATE"
[ -f "$STATE/id_ed25519" ] || ssh-keygen -q -t ed25519 -N "" -C mb-visitor -f "$STATE/id_ed25519"
echo "VIS_SSH_PUB_B64=$(base64 -w0 < "$STATE/id_ed25519.pub")"
echo "VIS_DONE"
