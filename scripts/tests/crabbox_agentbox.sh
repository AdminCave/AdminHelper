#!/usr/bin/env bash
#
# crabbox_agentbox.sh — runs ON a crabbox agent-box. Installs + provisions the
# agent against the remote server box over a real network hop (cross-host mTLS)
# and prints AGENT_* markers.
#
# Primary path (REPO_FP given): the USER path — scripts/agent-install.sh sets up
# the apt source against the server's :8445 repo plane (GPG-fingerprint-checked),
# installs the .deb the server box built from the same checkout, and provisions
# with a verified first contact (--ca-fp, when CA_FP given). Fallback (no
# REPO_FP, e.g. the server-side repo build failed): build the .deb locally and
# provision with TOFU, as before.
#
# Called by scripts/tests/crabbox_multibox.sh via `crabbox run`.
#   crabbox_agentbox.sh <SRV_IP> <SID> <PTOK> [REPO_GPG_FP] [CA_FP]
set -uo pipefail
SRV_IP="${1:?}"; SID="${2:?}"; PTOK="${3:?}"; REPO_FP="${4:-}"; CA_FP="${5:-}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1
# shellcheck source=scripts/tests/crabbox_lib.sh
. "$(dirname "$0")/crabbox_lib.sh"

echo "[agentbox] hydrate (agent profile: Go + packaging, no Tauri)"
AH_BOOTSTRAP_PROFILE=agent bash scripts/tests/crabbox_bootstrap.sh || { echo "[agentbox] bootstrap failed"; exit 1; }
export PATH="$PATH:/usr/local/go/bin"

if [ -n "$REPO_FP" ]; then
  echo "[agentbox] install via scripts/agent-install.sh over the :8445 repo plane (user path)"
  ARGS=(--server "https://$SRV_IP" --token "$PTOK" --server-id "$SID" --gpg-fp "$REPO_FP")
  [ -n "$CA_FP" ] && ARGS+=(--ca-fp "$CA_FP")
  sudo bash scripts/agent-install.sh "${ARGS[@]}" \
    && echo "AGENT_PROVISION_OK" || { echo "AGENT_PROVISION_FAIL"; exit 1; }
  # Prove the package really came through the repo plane and the steady state
  # got hardened (CAInfo pin after enrollment).
  grep -q "URIs: https://$SRV_IP:8445/apt" /etc/apt/sources.list.d/adminhelper.sources 2>/dev/null \
    && echo "AGENT_REPO_OK" || echo "AGENT_REPO_MISSING"
  grep -q "CAInfo" /etc/apt/apt.conf.d/99adminhelper-ca 2>/dev/null \
    && echo "AGENT_CAFLIP_OK" || echo "AGENT_CAFLIP_MISSING"
else
  echo "[agentbox] no repo fingerprint from the server box — legacy local .deb path"
  echo "[agentbox] build the Go agent + .deb from the repo root"
  DEB="$(cbx_build_agent_deb agentbox)" || exit 1
  echo "AGENT_DEB=$DEB"

  echo "[agentbox] install + provision against https://$SRV_IP (server $SID)"
  sudo apt-get install -y "$DEB" 2>/dev/null || sudo dpkg -i "$DEB" || { echo "[agentbox] install failed"; exit 1; }
  # --insecure = TOFU-pin the presented chain on first contact; the agent then pins
  # the CA from the enroll response and verifies the IP-SAN leaf on every later call.
  sudo adminhelper-agent provision --url "https://$SRV_IP" --token "$PTOK" --server-id "$SID" --insecure \
    && echo "AGENT_PROVISION_OK" || { echo "AGENT_PROVISION_FAIL"; exit 1; }
fi

echo "[agentbox] one monitoring collection run"
sudo adminhelper-agent run --once && echo "AGENT_RUN_OK" || echo "AGENT_RUN_FAIL"

echo "[agentbox] assert enrolled mTLS identity present"
if sudo test -f /etc/adminhelper/identity/agent.crt || sudo ls /etc/adminhelper/identity/ 2>/dev/null | grep -q .; then
  echo "AGENT_CERT_OK"
else
  echo "AGENT_CERT_MISSING"
fi
