#!/usr/bin/env bash
#
# crabbox_warm.sh — warm a hydrated crabbox box ONCE and remember its slug, so the
# fast loop (crabbox_iter.sh) reuses it instead of re-leasing + re-bootstrapping +
# rebuilding (~40 min) on every run. Idempotent: if the recorded slug is still
# ready, reuse it; if it was reaped, transparently re-warm.
#
#   bash scripts/tests/crabbox_warm.sh <desktop|server|pond>
#     desktop  full bootstrap profile (Tauri + xvfb) — GUI fast loop (no server)
#     server   server profile — brings the docker stack UP and leaves it up,
#              stashing the server IP + admin/monitor creds for iter
#     pond     server (stack up) + desktop — the distributed desktop fast loop
#
# Warm boxes carry `-ttl 8h -idle-timeout 4h` (self-reap) and the `ah-warm` pond;
# sweep strays with crabbox_reap.sh. State is in .crabbox/warm.env (gitignored).
set -uo pipefail
ROLE="${1:-}"
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/tests/crabbox_lib.sh
. "$DIR/crabbox_lib.sh"
cd "$CBX_ROOT" || exit 1
command -v crabbox >/dev/null || { echo "crabbox not installed"; exit 1; }
cbx_load_env || exit 1
POND="ah-warm"

# warm_role <role> <profile> -> stdout: slug ; stderr: progress
warm_role() {
  local role="$1" profile="$2" slug ip
  slug="$(warm_get "$role")"
  if [ -n "$slug" ] && box_ready "$slug"; then
    echo "  reuse $role box $slug (already warm)" >&2; echo "$slug"; return 0
  fi
  [ -n "$slug" ] && { echo "  recorded $role slug $slug is gone — re-warming" >&2; warm_clear "$role"; }
  echo "  lease + hydrate $role box (profile=$profile) — one-time bootstrap" >&2
  read -r slug ip < <(cbx_lease "ah-$role" "$POND") || { echo "  lease failed" >&2; return 1; }
  echo "  $role box $slug @ ${ip:-?} — hydrating" >&2
  CBX_TIMEOUT=2700 cbx run --id "$slug" -no-hydrate -- \
    "AH_BOOTSTRAP_PROFILE=$profile bash scripts/tests/crabbox_bootstrap.sh" >&2 \
    || { echo "  bootstrap failed on $slug (kept for inspection)" >&2; return 1; }
  warm_set "$role" "$slug"; echo "$slug"
}

# warm_server: warm a server box AND bring the stack up (leaving it up), stashing
# the IP + provision token + admin/monitor creds so iter can drive against it.
# crabbox_serverbox.sh does its OWN bootstrap (server profile) + stack up, so lease
# directly and run it — do NOT warm_role first (that would bootstrap twice).
warm_server() {
  local slug ip out sid ptok pw key
  slug="$(warm_get server)"
  if [ -n "$slug" ] && box_ready "$slug" && [ -n "$(warm_get server_ip)" ]; then
    echo "  reuse server box $slug (stack up @ $(warm_get server_ip))" >&2; return 0
  fi
  [ -n "$slug" ] && { echo "  recorded server slug $slug is gone — re-warming" >&2; warm_clear server; }
  echo "  lease server box + hydrate + bring up the stack (one-time)" >&2
  read -r slug ip < <(cbx_lease "ah-server" "$POND") || { echo "  server lease failed" >&2; return 1; }
  echo "  server box $slug @ ${ip:-?} — crabbox_serverbox.sh (bootstrap + stack up)" >&2
  out="$(CBX_TIMEOUT=2700 cbx run --id "$slug" -no-hydrate -- bash scripts/tests/crabbox_serverbox.sh "$ip" 2>&1)"
  sid="$(printf '%s' "$out"  | grep -oE 'MB_SID=[^ ]+'         | tail -1 | cut -d= -f2)"
  ptok="$(printf '%s' "$out" | grep -oE 'MB_PTOK=[^ ]+'        | tail -1 | cut -d= -f2)"
  pw="$(printf '%s' "$out"   | grep -oE 'MB_ADMIN_PW=[^ ]+'    | tail -1 | cut -d= -f2)"
  key="$(printf '%s' "$out"  | grep -oE 'MB_MONITOR_KEY=[^ ]+' | tail -1 | cut -d= -f2)"
  [ -n "$sid" ] && [ -n "$ptok" ] || { echo "  server stack bring-up failed:" >&2; printf '%s\n' "$out" | tail -20 >&2; return 1; }
  warm_set server "$slug"; warm_set server_ip "$ip"; warm_set server_admin_pw "$pw"; warm_set server_monitor_key "$key"
  warm_set server_sid "$sid"; warm_set server_ptok "$ptok"
  echo "  server stack up @ $ip (sid=$sid)" >&2
}

case "$ROLE" in
  desktop) warm_role desktop full >/dev/null || exit 1 ;;
  server)  warm_server || exit 1 ;;
  pond)    warm_server || exit 1; warm_role desktop full >/dev/null || exit 1 ;;
  *) echo "usage: crabbox_warm.sh <desktop|server|pond>"; exit 2 ;;
esac

echo ""
echo "── warm boxes ready (.crabbox/warm.env) ──"
grep -vE '_admin_pw=|_monitor_key=|_ptok=' "$(cbx_warm_file)" 2>/dev/null | sed 's/^/  /'
echo "  (server creds stashed in warm.env — gitignored, not printed)"
echo "  iterate:  bash scripts/tests/crabbox_iter.sh [--desktop] <quick|integration|e2e>"
echo "  reap:     bash scripts/tests/crabbox_reap.sh"
