#!/usr/bin/env bash
#
# crabbox_visitorbox.sh — S4 phase 2. The STCP VISITOR that completes the tunnel
# data path across three hosts: it connects through the REMOTE frps to the
# tunnel-agent's frpc STCP server and reaches that agent's sshd — proving data
# flows visitor-host → frps-host → agent-host with none of them co-located.
#
# The desktop normally supplies its enrolled ACCESS identity for the visitor's TLS;
# here the box provisions (a tunnel-scoped, CA-signed identity frps also trusts) and
# the fetched visitor.toml is rewired to point at it. Prints VIS_* markers.
#
# Called by scripts/tests/crabbox_multibox.sh --tunnel via `crabbox run`.
#   crabbox_visitorbox.sh <SRV_IP> <VIS_SID> <VIS_PTOK> <VISITOR_TOML_B64>
set -uo pipefail
SRV_IP="${1:?}"; VSID="${2:?}"; VPTOK="${3:?}"; VB64="${4:?}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1

echo "[visitorbox] hydrate + build/install the agent (for the binary + frpc sidecar)"
AH_BOOTSTRAP_PROFILE=agent bash scripts/tests/crabbox_bootstrap.sh || { echo "[visitorbox] bootstrap failed"; exit 1; }
export PATH="$PATH:/usr/local/go/bin"
( cd apps/agent && make build-linux ) || { echo "[visitorbox] go build failed"; exit 1; }
cp -f apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu ./frpc 2>/dev/null || true
VERSION="0.0.0-test" bash apps/agent/build-deb.sh >/dev/null 2>&1 || true
DEB="$(ls -1 ./adminhelper-agent_*_amd64.deb 2>/dev/null | head -1)"
[ -n "$DEB" ] && { sudo apt-get install -y "$DEB" 2>/dev/null || sudo dpkg -i "$DEB"; } || { echo "[visitorbox] no .deb"; exit 1; }

echo "[visitorbox] provision -> CA-signed mTLS identity for the visitor's TLS to frps"
sudo adminhelper-agent provision --url "https://$SRV_IP" --token "$VPTOK" --server-id "$VSID" --insecure \
  && echo "VIS_PROVISION_OK" || { echo "VIS_PROVISION_FAIL"; exit 1; }

echo "[visitorbox] write + rewire the visitor.toml (relative identity/ -> the provisioned cert)"
sudo mkdir -p /etc/frp
printf '%s' "$VB64" | base64 -d | sudo tee /etc/frp/visitor.toml >/dev/null
sudo sed -i \
  -e 's#identity/ca.crt#/etc/adminhelper/identity/ca.crt#' \
  -e 's#identity/cert.pem#/etc/adminhelper/identity/agent.crt#' \
  -e 's#identity/key.pem#/etc/adminhelper/identity/agent.key#' \
  /etc/frp/visitor.toml
VPORT="$(grep -E '^bindPort' /etc/frp/visitor.toml | head -1 | grep -oE '[0-9]+')"
[ -n "$VPORT" ] && echo "VIS_BIND_PORT=$VPORT" || { echo "VIS_NO_BIND_PORT"; sudo cat /etc/frp/visitor.toml; exit 1; }

echo "[visitorbox] run frpc visitor -> bind 127.0.0.1:$VPORT (through frps to the agent's sshd)"
sudo /usr/bin/frpc -c /etc/frp/visitor.toml >/tmp/frpc-vis.log 2>&1 &
sleep 8
if grep -qiE 'start.*visitor.*success|login to server success|start proxy success' /tmp/frpc-vis.log; then
  echo "VIS_FRPC_UP"
else
  echo "VIS_FRPC_DOWN"; sed 's/^/    /' /tmp/frpc-vis.log
fi

echo "[visitorbox] pull the SSH banner through the tunnel (proves the cross-host data path)"
BANNER="$(timeout 8 bash -c "exec 3<>/dev/tcp/127.0.0.1/$VPORT; head -c 40 <&3" 2>/dev/null || true)"
echo "    banner: ${BANNER%%$'\n'*}"
printf '%s' "$BANNER" | grep -q 'SSH-' && echo "VIS_TUNNEL_SSH_OK" || { echo "VIS_TUNNEL_SSH_FAIL"; sed 's/^/    frpc: /' /tmp/frpc-vis.log; }
echo "VIS_DONE"
