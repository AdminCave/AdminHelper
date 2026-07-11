#!/usr/bin/env bash
#
# crabbox_desktopbox.sh — runs ON a crabbox desktop-client box (full bootstrap
# profile: Tauri + xvfb + WebKitWebDriver + tauri-driver + frpc + gnome-keyring).
# Drives the REAL Tauri desktop GUI headless against the REMOTE server-box — the
# operator seat on its own machine (scenario S3), the dimension single-host
# desktop_e2e (localhost) can't reach.
#
#   crabbox_desktopbox.sh <SRV_IP> <ADMIN_PW> <MONITOR_KEY> [spec ...]
#
# Points the app at https://<SRV_IP> (server mode, self-signed/IP-SAN trusted),
# logs in as admin, and runs the requested *.live.js wdio specs. Prints markers.
# Called by scripts/tests/crabbox_multibox.sh --desktop via `crabbox run`.
set -uo pipefail
SRV_IP="${1:?}"; ADMIN_PW="${2:?}"; MONITOR_KEY="${3:-}"; shift $(( $# < 3 ? $# : 3 ))
SPECS=("$@"); [ "${#SPECS[@]}" -gt 0 ] || SPECS=(server-crud.live.js monitoring-check.live.js)
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1
E2E_DIR="$ROOT/apps/desktop/e2e"

echo "[desktopbox] hydrate (full profile: Tauri + xvfb + tauri-driver)"
AH_BOOTSTRAP_PROFILE=full bash scripts/tests/crabbox_bootstrap.sh || { echo "[desktopbox] bootstrap failed"; exit 1; }
# shellcheck disable=SC1091
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
export PATH="$PATH:$HOME/.cargo/bin:/usr/local/go/bin"

echo "[desktopbox] npm ci (ui + e2e)"
( cd apps/desktop/ui && npm ci --no-audit --no-fund ) || { echo "[desktopbox] npm ci ui failed"; exit 1; }
( cd "$E2E_DIR" && npm ci --no-audit --no-fund ) || { echo "[desktopbox] npm ci e2e failed"; exit 1; }

echo "[desktopbox] point the app at the REMOTE server https://$SRV_IP (server mode)"
XDG_DATA_HOME="$ROOT/.dt-xdg"; export XDG_DATA_HOME
mkdir -p "$XDG_DATA_HOME/com.admincave.adminhelper"
echo '{"mode": "server", "allowSelfSignedCerts": true}' > "$XDG_DATA_HOME/com.admincave.adminhelper/settings.json"

export AH_SERVER_URL="https://$SRV_IP" AH_ADMIN_USER="admin" AH_ADMIN_PASS="$ADMIN_PW" \
       MONITOR_API_KEY="$MONITOR_KEY" E2E_DIR
export WEBKIT_DISABLE_DMABUF_RENDERER=1 WEBKIT_DISABLE_COMPOSITING_MODE=1
# Headless boxes default to LANG=C; the webview then feeds "C" to Intl.NumberFormat
# -> RangeError at module init -> Svelte never mounts (blank #app). Force a valid tag.
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 LANGUAGE=en_US:en
export AH_OUT_DIR="$ROOT/.crabbox-out"   # wdio afterTest drops screenshots here on failure

fails=0
for spec in "${SPECS[@]}"; do
  echo "[desktopbox] === GUI spec: $spec (against https://$SRV_IP) ==="
  # xvfb + a fresh D-Bus session + an empty gnome-keyring so the OS-keyring path
  # works headless; wdio.conf.js onPrepare builds the debug Tauri binary.
  if dbus-run-session -- bash -c '
        eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets 2>/dev/null)" || true
        export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
        cd "$E2E_DIR" && xvfb-run -a npx wdio run wdio.conf.js --spec "test/specs/'"$spec"'"
     '; then
    echo "DESKTOP_SPEC_OK $spec"
  else
    echo "DESKTOP_SPEC_FAIL $spec"; fails=$((fails+1))
  fi
done

[ "$fails" -eq 0 ] && echo "DESKTOP_ALL_OK (${#SPECS[@]} specs)" || { echo "DESKTOP_FAILED ($fails/${#SPECS[@]})"; exit 1; }
