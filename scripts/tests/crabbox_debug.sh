#!/usr/bin/env bash
#
# crabbox_debug.sh — on-box failure collector. Dumps docker container logs, the
# agent journal, tool versions and (if a display is up) a framebuffer screenshot
# into .crabbox-out/, which crabbox_iter.sh pulls back via -artifact-glob so a
# failure is diagnosable WITHOUT a re-run. Invoked by run.sh when a layer FAILS and
# AH_CAPTURE=1; the wdio afterTest hook writes GUI screenshots into the same tree.
# Best-effort — never fails the run.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 0
OUT="${AH_OUT_DIR:-$ROOT/.crabbox-out}"
mkdir -p "$OUT/logs" "$OUT/screenshots" 2>/dev/null || true
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"

{
  echo "=== versions ==="
  docker --version 2>/dev/null || true
  docker compose version 2>/dev/null | head -1 || true
  go version 2>/dev/null || true
  node --version 2>/dev/null && echo "node ok" || true
  cargo --version 2>/dev/null || true
  tauri-driver --version 2>/dev/null || true
  echo "LANG=$LANG LC_ALL=${LC_ALL:-} DISPLAY=${DISPLAY:-}"
} > "$OUT/logs/versions.txt" 2>&1 || true

# Every container's logs (robust to whichever compose file set is up).
if command -v docker >/dev/null 2>&1; then
  $SUDO docker ps -a > "$OUT/logs/docker-ps.txt" 2>/dev/null || true
  for c in $($SUDO docker ps -aq 2>/dev/null); do
    name="$($SUDO docker inspect --format '{{.Name}}' "$c" 2>/dev/null | tr -d /)"
    $SUDO docker logs --tail 400 "$c" > "$OUT/logs/container-${name:-$c}.log" 2>&1 || true
  done
fi

# Agent (systemd) journal, if this box ran the agent role.
$SUDO journalctl -u adminhelper-agent --no-pager -n 300 > "$OUT/logs/agent.journal" 2>/dev/null || true

# Framebuffer screenshot fallback (when a wdio saveScreenshot could not run because
# the WebDriver session never initialised).
if [ -n "${DISPLAY:-}" ]; then
  if command -v import >/dev/null 2>&1; then import -window root "$OUT/screenshots/xvfb-root.png" 2>/dev/null || true
  elif command -v scrot >/dev/null 2>&1; then scrot "$OUT/screenshots/xvfb-root.png" 2>/dev/null || true; fi
fi

echo "[crabbox_debug] captured -> $OUT" >&2
