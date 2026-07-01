#!/usr/bin/env bash
#
# crabbox_agentbox.sh — runs ON a crabbox agent-box. Builds the real .deb from the
# synced checkout, installs it, and provisions the agent against the remote server
# box over a real network hop (cross-host mTLS). Prints AGENT_* markers.
#
# Called by scripts/tests/crabbox_multibox.sh via `crabbox run`.
#   crabbox_agentbox.sh <SRV_IP> <SID> <PTOK>
set -uo pipefail
SRV_IP="${1:?}"; SID="${2:?}"; PTOK="${3:?}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1

echo "[agentbox] hydrate (agent profile: Go + packaging, no Tauri)"
AH_BOOTSTRAP_PROFILE=agent bash scripts/tests/crabbox_bootstrap.sh || { echo "[agentbox] bootstrap failed"; exit 1; }
export PATH="$PATH:/usr/local/go/bin"

echo "[agentbox] build the Go agent + .deb from the repo root"
# build-deb.sh uses repo-root-relative paths and needs a frpc at the repo root.
( cd apps/agent && make build-linux ) || { echo "[agentbox] go build failed"; exit 1; }
cp -f apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu ./frpc 2>/dev/null || true
VERSION="0.0.0-test" bash apps/agent/build-deb.sh || { echo "[agentbox] build-deb failed"; exit 1; }
# build-deb.sh moves the package to the repo ROOT (mv ... .), not dist/.
DEB="$(ls -1 ./adminhelper-agent_*_amd64.deb 2>/dev/null | head -1)"
[ -n "$DEB" ] || { echo "[agentbox] no .deb produced (looked in repo root)"; ls -1 ./*.deb 2>/dev/null; exit 1; }
echo "AGENT_DEB=$DEB"

echo "[agentbox] install + provision against https://$SRV_IP (server $SID)"
sudo apt-get install -y "$DEB" 2>/dev/null || sudo dpkg -i "$DEB" || { echo "[agentbox] install failed"; exit 1; }
# --insecure = TOFU-pin the presented chain on first contact; the agent then pins
# the CA from the enroll response and verifies the IP-SAN leaf on every later call.
sudo adminhelper-agent provision --url "https://$SRV_IP" --token "$PTOK" --server-id "$SID" --insecure \
  && echo "AGENT_PROVISION_OK" || { echo "AGENT_PROVISION_FAIL"; exit 1; }

echo "[agentbox] one monitoring collection run"
sudo adminhelper-agent run --once && echo "AGENT_RUN_OK" || echo "AGENT_RUN_FAIL"

echo "[agentbox] assert enrolled mTLS identity present"
if sudo test -f /etc/adminhelper/identity/agent.crt || sudo ls /etc/adminhelper/identity/ 2>/dev/null | grep -q .; then
  echo "AGENT_CERT_OK"
else
  echo "AGENT_CERT_MISSING"
fi
