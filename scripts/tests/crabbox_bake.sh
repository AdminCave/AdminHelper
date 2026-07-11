#!/usr/bin/env bash
#
# crabbox_bake.sh — prepare a FAT hydrated image so COLD starts skip the ~18 min
# toolchain bootstrap. On this proxmox provider crabbox has no usable checkpoint/
# pool (archive checkpoints capture only the synced workdir, not docker/go/rust/
# node), so the real win is a baked PROXMOX TEMPLATE. This hydrates a box + warms
# the build caches + cleans it, then prints the exact PVE-host steps to convert it
# to a template and repoint crabbox at it.
#
# PROVISIONS a VM and leaves it up (you need it for the `qm template` step). Run it
# deliberately — it is not part of the automatic loop.
#
#   bash scripts/tests/crabbox_bake.sh [desktop|server]
set -uo pipefail
ROLE="${1:-desktop}"
case "$ROLE" in desktop) PROFILE=full ;; server) PROFILE=server ;;
  *) echo "usage: crabbox_bake.sh [desktop|server]"; exit 2 ;; esac
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/tests/crabbox_lib.sh
. "$DIR/crabbox_lib.sh"
cd "$CBX_ROOT" || exit 1
command -v crabbox >/dev/null || { echo "crabbox not installed"; exit 1; }
cbx_load_env || exit 1

echo "== bake a hydrated box for role=$ROLE (profile=$PROFILE) — PROVISIONS a VM =="
read -r SLUG IP < <(cbx_lease "ah-bake" "ah-bake") || { echo "lease failed"; exit 1; }
echo "  baking box $SLUG @ ${IP:-?}"
CBX_TIMEOUT=2700 cbx run --id "$SLUG" -no-hydrate -- \
  "AH_BOOTSTRAP_PROFILE=$PROFILE bash scripts/tests/crabbox_bootstrap.sh" \
  || { echo "  bootstrap failed ($SLUG kept for inspection)"; exit 1; }
echo "  warming build caches (populate target/ + node_modules)"
CBX_TIMEOUT=2700 cbx run --id "$SLUG" -no-hydrate -- \
  "AH_ALLOW_REAL=1 bash scripts/tests/run.sh unit" || true
echo "  cleaning for templating"
cbx run --id "$SLUG" -no-hydrate -- \
  'sudo apt-get clean; sudo cloud-init clean 2>/dev/null || true; sudo docker system prune -af 2>/dev/null || true; sudo truncate -s0 /etc/machine-id 2>/dev/null || true' || true

VMID="$(cbx list 2>/dev/null | grep -E "slug=$SLUG( |\$)" | grep -oE '^[0-9]+' | head -1)"
cat <<EOF

── Box $SLUG (VMID ${VMID:-?}) hydrated + cleaned. To bake it into a reusable template ──
On the Proxmox host (node babo):
    qm shutdown ${VMID:-<VMID>} && qm template ${VMID:-<VMID>}
    # then set CRABBOX_PROXMOX_TEMPLATE_ID=<that id> in .claude/settings.local.json
    # (NOT settings.json — that file is public, homelab details stay in the gitignored local file)
Afterwards crabbox_warm.sh clones the fat template → cold starts SKIP the ~18 min bootstrap
(only an incremental build runs). Rebuild the template whenever the pinned tool versions in
crabbox_bootstrap.sh bump (FRP/Go/Node/tauri-cli). This box is NOT auto-stopped — after
templating: crabbox stop --id $SLUG
EOF
