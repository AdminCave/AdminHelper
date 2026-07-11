#!/usr/bin/env bash
#
# crabbox_lib.sh — shared helpers for the crabbox test harness. SOURCE this, don't
# execute it. Provides: Proxmox env loading, a timeout-bounded `crabbox` wrapper
# (a stuck lease once ran ~7 h — every call is now bounded), warm-slug persistence
# in .crabbox/warm.env, box readiness/IP resolution, and a lease helper.
#
# Used by crabbox_warm.sh / crabbox_iter.sh / crabbox_reap.sh and (for env loading)
# crabbox_multibox.sh.

# Repo root, regardless of the sourcing script's location.
CBX_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Load the Proxmox provider env from .claude/settings.json (+ the gitignored
# settings.local.json for the token secret). Idempotent.
cbx_load_env() {
  [ -n "${CRABBOX_PROVIDER:-}" ] && return 0
  eval "$(cd "$CBX_ROOT" && python3 -c '
import json
for f in [".claude/settings.json",".claude/settings.local.json"]:
    try: d=json.load(open(f)).get("env",{})
    except Exception: d={}
    for k,v in d.items():
        if k.startswith("CRABBOX_"): print("export %s=%r"%(k,v))')"
  [ -n "${CRABBOX_PROVIDER:-}" ] || { echo "crabbox_lib: CRABBOX_PROVIDER unset (proxmox env not loaded)" >&2; return 1; }
}

# Timeout-bounded crabbox. Override the bound per-call with CBX_TIMEOUT (seconds);
# default 420s suits warmup/status/ssh/stop. Use a larger CBX_TIMEOUT for `run`.
cbx() { timeout "${CBX_TIMEOUT:-420}" crabbox "$@"; }

# --- lane identity ----------------------------------------------------------------
# Parallel lanes (git worktrees, scripts/dev/lane.sh) must not share a pond:
# crabbox_reap.sh sweeps a WHOLE pond, so a shared name would let lane A reap
# lane B's warm boxes. Derive a lane id from the checkout dir name; AH_LANE
# overrides. The main checkout ("AdminHelper") maps to "" so solo behavior and
# the historic ah-warm pond stay unchanged.
cbx_lane() {
  local lane="${AH_LANE:-}"
  [ -n "$lane" ] || lane="$(basename "$CBX_ROOT")"
  lane="$(printf '%s' "$lane" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
  lane="${lane#-}"; lane="${lane%-}"
  case "$lane" in adminhelper) lane="" ;; adminhelper-*) lane="${lane#adminhelper-}" ;; esac
  printf '%s\n' "$lane"
}
cbx_pond() { local l; l="$(cbx_lane)"; printf 'ah-warm%s\n' "${l:+-$l}"; }

# --- warm-slug persistence (.crabbox/warm.env: one ROLE=slug line per role) -------
cbx_warm_file() { echo "$CBX_ROOT/.crabbox/warm.env"; }
warm_get() {  # warm_get <role> -> prints the slug (empty if none)
  local f; f="$(cbx_warm_file)"; [ -f "$f" ] || return 0
  grep -E "^$1=" "$f" 2>/dev/null | tail -1 | cut -d= -f2-
}
warm_set() {  # warm_set <role> <slug>
  local f; f="$(cbx_warm_file)"; mkdir -p "$(dirname "$f")"; touch "$f"
  { grep -vE "^$1=" "$f" 2>/dev/null || true; echo "$1=$2"; } > "$f.tmp"; mv "$f.tmp" "$f"
}
warm_clear() {  # warm_clear <role>
  local f; f="$(cbx_warm_file)"; [ -f "$f" ] || return 0
  { grep -vE "^$1=" "$f" 2>/dev/null || true; } > "$f.tmp"; mv "$f.tmp" "$f"
}

# --- box readiness + IP -----------------------------------------------------------
box_ready() {  # box_ready <slug> -> 0 if crabbox lists the slug as running/ready
  cbx list 2>/dev/null | grep -E "slug=$1( |\$)" | grep -qiE 'running|ready'
}
box_ip() {  # box_ip <slug> -> prints the box IPv4
  cbx ssh --id "$1" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1
}

# --- lease a box (warmup + wait-for-ready), echo "<slug> <ip>". Callers (warm/bake)
# self-reap via -ttl/-idle-timeout, so there's no lease-id tracking to leak here (4.55).
# Serialize `crabbox warmup` host-globally: CONCURRENT warmups on this provider hang
# (ssh-lease, coordinator:never — once ran ~7 h). Only the lease is locked; bootstrap
# and runs stay parallel. Used by cbx_lease AND crabbox_multibox.sh's lease() — every
# warmup in the repo must go through here or the serialization guarantee is void.
# fd 9 is closed for the child (9>&-) so an orphaned warmup process surviving the
# `timeout` kill cannot keep the lock held past this group. Diagnostics go to stdout
# on purpose — callers capture it into $out and print it in their failure banner.
cbx_warmup_locked() {
  local lock="${XDG_RUNTIME_DIR:-$HOME/.cache}/adminhelper-crabbox-lease.lock"
  mkdir -p "$(dirname "$lock")" 2>/dev/null || true
  : >>"$lock" 2>/dev/null || { echo "lease lock $lock not writable"; return 1; }
  { flock -w 1800 9 || { echo "lease lock timeout (another lane leasing?)"; return 1; }
    # 1200s, not 420: cloning the FAT template (baked toolchains, raid5) measured
    # 637s — the old bound SIGTERMed crabbox mid-clone ("context canceled") and
    # left an orphaned VM behind. Override per-call with CBX_LEASE_TIMEOUT.
    CBX_TIMEOUT="${CBX_LEASE_TIMEOUT:-1200}" cbx warmup "$@" 2>&1 9>&-
  } 9>"$lock"
}

cbx_lease() {  # cbx_lease <slug-hint> <pond> [ttl] [idle]
  local slug="$1" pond="$2" ttl="${3:-8h}" idle="${4:-4h}" out ip rslug
  out="$(cbx_warmup_locked -slug "$slug" -pond "$pond" -proxmox-bridge vmbr1 \
        -ttl "$ttl" -idle-timeout "$idle")" \
    || { echo "warmup failed/timed out: $out" >&2; return 1; }
  rslug="$(printf '%s' "$out" | grep -oE 'slug=[a-z0-9-]+' | head -1 | cut -d= -f2)"; [ -n "$rslug" ] && slug="$rslug"
  CBX_TIMEOUT=300 cbx status --id "$slug" --wait >/dev/null 2>&1 || true
  ip="$(box_ip "$slug")"; [ -n "$ip" ] || ip="$(printf '%s' "$out" | grep -oE 'ip=[0-9.]+' | head -1 | cut -d= -f2)"
  [ -n "$slug" ] || { echo "no slug parsed from warmup" >&2; return 1; }
  echo "$slug ${ip:-}"
}

# Extract the LAST 'KEY=value' marker from a captured box output (last in case a
# line repeats). Shared by multibox + warm so a warmup-parsing fix lands once (2.39).
cbx_marker() { printf '%s' "$2" | grep -oE "$1=[^ ]+" | tail -1 | cut -d= -f2; }

# Build the Go agent + its .deb from the synced checkout (run from the repo root), echo
# the .deb path. build-deb.sh needs a frpc at the repo root and MOVES the package to the
# repo root (not dist/). Shared by agentbox/tunnelbox/visitorbox so a build-path change
# lands once — and no box can swallow the build error (visitorbox did, surfacing only as
# a cryptic 'no .deb') (2.118).
cbx_build_agent_deb() {  # cbx_build_agent_deb <tag> -> echoes the .deb path, returns 1 on failure
  local tag="${1:?}" deb
  ( cd apps/agent && make build-linux ) || { echo "[$tag] go build failed" >&2; return 1; }
  cp -f apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu ./frpc 2>/dev/null || true
  VERSION="0.0.0-test" bash apps/agent/build-deb.sh || { echo "[$tag] build-deb failed" >&2; return 1; }
  deb="$(ls -1 ./adminhelper-agent_*_amd64.deb 2>/dev/null | head -1)"
  [ -n "$deb" ] || { echo "[$tag] no .deb produced (looked in repo root)" >&2; return 1; }
  echo "$deb"
}
