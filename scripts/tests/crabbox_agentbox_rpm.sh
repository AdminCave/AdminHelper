#!/usr/bin/env bash
#
# crabbox_agentbox_rpm.sh — cross-distro coverage (scenario S2). All crabbox templates
# are apt (Ubuntu/Debian); to prove the .rpm path this builds the real package on the
# Ubuntu box, then installs + provisions it INSIDE a rockylinux container (--network
# host) against the remote server box over a real network hop. Prints RPM_* markers.
#
# Called by scripts/tests/crabbox_multibox.sh --rpm via `crabbox run`.
#   crabbox_agentbox_rpm.sh <SRV_IP> <SID> <PTOK>
set -uo pipefail
SRV_IP="${1:?}"; SID="${2:?}"; PTOK="${3:?}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1

echo "[rpmbox] hydrate (agent profile: Go + packaging + docker)"
AH_BOOTSTRAP_PROFILE=agent bash scripts/tests/crabbox_bootstrap.sh || { echo "[rpmbox] bootstrap failed"; exit 1; }
export PATH="$PATH:/usr/local/go/bin"

echo "[rpmbox] build the Go agent + .rpm from the repo root"
( cd apps/agent && make build-linux ) || { echo "[rpmbox] go build failed"; exit 1; }
cp -f apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu ./frpc 2>/dev/null || true
# RPM forbids '-' in the Version field (it is the version-release separator) — the
# deb path tolerates 0.0.0-test, rpm does not; use a hyphen-free test version.
VERSION="0.0.0" bash apps/agent/build-rpm.sh || { echo "[rpmbox] build-rpm failed"; exit 1; }
RPM="$(ls -1 ./adminhelper-agent-*.rpm 2>/dev/null | head -1)"
[ -n "$RPM" ] || { echo "[rpmbox] no .rpm produced (looked in repo root)"; ls -1 ./*.rpm 2>/dev/null; exit 1; }
echo "AGENT_RPM=$RPM"

echo "[rpmbox] install + provision inside rockylinux:8 (--network host) vs https://$SRV_IP (server $SID)"
# Env (-e) instead of host interpolation into the container script — clean quoting.
sudo docker run --rm --network host \
  -e SRV_IP="$SRV_IP" -e SID="$SID" -e PTOK="$PTOK" -e RPMFILE="/w/$(basename "$RPM")" \
  -v "$ROOT:/w" -w /w rockylinux:8 bash -c '
    set -e
    dnf install -y -q "$RPMFILE" >/dev/null 2>&1 || rpm -i --nodeps "$RPMFILE"
    command -v adminhelper-agent >/dev/null || { echo "rpm did not install the binary"; exit 1; }
    adminhelper-agent provision --url "https://$SRV_IP" --token "$PTOK" --server-id "$SID" --insecure && echo RPM_PROVISION_OK
    adminhelper-agent run --once && echo RPM_RUN_OK
    { test -f /etc/adminhelper/identity/agent.crt || ls /etc/adminhelper/identity/ 2>/dev/null | grep -q .; } && echo RPM_CERT_OK
  ' && echo "RPM_ALL_OK" || { echo "RPM_FAILED"; exit 1; }
