#!/usr/bin/env bash
#
# crabbox_tunnelbox.sh — S4 tunnel-agent role. Installs the agent, provisions it
# (which fetches + writes /etc/frp/frpc.toml for the seeded STCP tunnel plus the
# mTLS identity), and runs frpc as the STCP SERVER, exposing this box's own sshd
# (:22) through the REMOTE frps on the server box. The cross-host half of the
# tunnel (visitor is added separately). Prints TUNNEL_* markers.
#
# Called by scripts/tests/crabbox_multibox.sh --tunnel via `crabbox run`.
#   crabbox_tunnelbox.sh <SRV_IP> <TUN_SID> <TUN_PTOK>
set -uo pipefail
SRV_IP="${1:?}"; SID="${2:?}"; PTOK="${3:?}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1

echo "[tunnelbox] hydrate (agent profile: Go + packaging)"
AH_BOOTSTRAP_PROFILE=agent bash scripts/tests/crabbox_bootstrap.sh || { echo "[tunnelbox] bootstrap failed"; exit 1; }
export PATH="$PATH:/usr/local/go/bin"

echo "[tunnelbox] build + install the .deb"
( cd apps/agent && make build-linux ) || { echo "[tunnelbox] go build failed"; exit 1; }
cp -f apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu ./frpc 2>/dev/null || true
VERSION="0.0.0-test" bash apps/agent/build-deb.sh || { echo "[tunnelbox] build-deb failed"; exit 1; }
DEB="$(ls -1 ./adminhelper-agent_*_amd64.deb 2>/dev/null | head -1)"
[ -n "$DEB" ] || { echo "[tunnelbox] no .deb produced"; exit 1; }
sudo apt-get install -y "$DEB" 2>/dev/null || sudo dpkg -i "$DEB" || { echo "[tunnelbox] install failed"; exit 1; }

echo "[tunnelbox] ensure sshd is listening on :22 (the STCP target)"
sudo systemctl enable --now ssh 2>/dev/null || sudo systemctl enable --now sshd 2>/dev/null || true
if ss -tlnH 'sport = :22' 2>/dev/null | grep -q .; then echo "TUNNEL_SSHD_OK"; else echo "TUNNEL_SSHD_MISSING"; fi

echo "[tunnelbox] provision against https://$SRV_IP (server $SID) -> writes frpc.toml"
sudo adminhelper-agent provision --url "https://$SRV_IP" --token "$PTOK" --server-id "$SID" --insecure \
  && echo "TUNNEL_PROVISION_OK" || { echo "TUNNEL_PROVISION_FAIL"; exit 1; }
if sudo test -f /etc/frp/frpc.toml; then echo "TUNNEL_FRPC_TOML_OK"; else echo "TUNNEL_FRPC_TOML_MISSING"; sudo ls -la /etc/frp/ 2>/dev/null; fi

echo "[tunnelbox] start frpc (STCP server) -> registers with frps at $SRV_IP:7000"
sudo systemctl restart frpc 2>/dev/null || sudo systemctl start frpc 2>/dev/null || true
# Poll for the frpc registration instead of a fixed sleep — it can lag on a loaded box (6.137).
tun_ok=0
for _ in $(seq 1 20); do sudo journalctl -u frpc --no-pager -n 60 2>/dev/null | grep -qiE 'start proxy success|login to server success|new proxy|proxy added' && { tun_ok=1; break; }; sleep 1; done
if [ "$tun_ok" = 1 ]; then
  echo "TUNNEL_FRPC_CONNECTED"
else
  echo "TUNNEL_FRPC_NOT_CONNECTED"; sudo journalctl -u frpc --no-pager -n 30 2>/dev/null | sed 's/^/    /'
fi
echo "TUNNEL_AGENT_DONE"
