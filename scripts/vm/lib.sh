#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# lib.sh — the shell side of scripts/vm/vm.py. SOURCE this, don't execute it.
#
# Provides: the Proxmox/VM environment (vm_load_env), warm-slot persistence in
# .vm/warm.env, the lane identity, and the two helpers the role scripts share
# (vm_marker, vm_build_agent_deb).
#
# The division of labour: everything that talks to the hypervisor lives in
# vm.py — UPID polling, TLS, tags, the reaper. This file holds only what a
# wrapper needs before or after such a call, and it is deliberately the part
# that can be tested without a VM (scripts/tests/lib_vm_test.sh).

# Repo root, regardless of the sourcing script's location.
VM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AH_VM_STATE_DIR="${AH_VM_STATE_DIR:-$VM_ROOT/.vm}"

# --- environment -------------------------------------------------------------
# Load AH_PVE_*/AH_VM_* from .claude/settings.local.json (gitignored — the only
# place the token lives). A variable that is already set wins, which is the same
# precedence vm.py uses, so a runner can inject its own without a file.
# Idempotent.
vm_load_env() {
  [ -n "${AH_PVE_URL:-}" ] && return 0
  # shlex.quote, not %r: a value holding a single quote flips Python's repr to
  # DOUBLE quotes, and the shell would then expand $…, backticks and backslashes
  # inside a token this file is supposed to pass through untouched.
  eval "$(cd "$VM_ROOT" && python3 -c '
import json, os, shlex
try:
    env = json.load(open(".claude/settings.local.json")).get("env", {})
except Exception:
    env = {}
for k, v in env.items():
    if (k.startswith("AH_PVE_") or k.startswith("AH_VM_")) and not os.environ.get(k):
        print("export %s=%s" % (k, shlex.quote(str(v))))')"
  [ -n "${AH_PVE_URL:-}" ] || { echo "vm_lib: AH_PVE_URL unset (.claude/settings.local.json -> env)" >&2; return 1; }
}

# --- lane identity -----------------------------------------------------------
# Parallel lanes (git worktrees, scripts/dev/lane.sh) must not sweep each
# other's VMs: vm.py reaps by the `lane-` tag, so a shared name would let lane A
# destroy lane B's boxes. Same precedence and same spelling rules as vm.py's
# current_lane(), or the two would disagree about which VMs are whose.
# NOT `tr -s`: squeezing would fold `a--b` into `a-b`, while vm.py's tag_safe()
# turns every bad character into its own dash. The two would then disagree about
# whether `lane-a-b` and `lane-a--b` are one lane or two — and one side would
# sweep what the other believes is leased. Non-ASCII is the documented limit:
# `tr` counts bytes where Python counts codepoints, so an umlaut lane falls back
# to `main` here and may not there. `lane.sh new` only ever writes [a-z0-9-].
vm_lane() {
  local lane="${AH_LANE:-}"
  [ -n "$lane" ] || lane="$(cat "$AH_VM_STATE_DIR/lane" 2>/dev/null || true)"
  lane="$(printf '%s' "$lane" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9-' '-')"
  while [ "${lane#-}" != "$lane" ]; do lane="${lane#-}"; done
  while [ "${lane%-}" != "$lane" ]; do lane="${lane%-}"; done
  printf '%s\n' "${lane:-main}"
}

# --- warm-slot persistence (.vm/warm.env: one KEY=value line per slot) -------
# Role slots hold a VMID (`desktop=3001`); the server role also parks the
# credentials its neighbours need (`server_ip`, `server_admin_pw`, …). vm.py's
# leak sweep reads only the keys WITHOUT an underscore as VMIDs — a session id
# that happens to be four digits must not excuse a leaked VM.
vm_warm_file() { echo "$AH_VM_STATE_DIR/warm.env"; }
warm_get() {  # warm_get <key> -> prints the value (empty if none)
  local f; f="$(vm_warm_file)"; [ -f "$f" ] || return 0
  grep -E "^$1=" "$f" 2>/dev/null | tail -1 | cut -d= -f2-
}
warm_set() {  # warm_set <key> <value>
  local f; f="$(vm_warm_file)"; mkdir -p "$(dirname "$f")"; touch "$f"
  { grep -vE "^$1=" "$f" 2>/dev/null || true; echo "$1=$2"; } > "$f.tmp"; mv "$f.tmp" "$f"
}
warm_clear() {  # warm_clear <key>
  local f; f="$(vm_warm_file)"; [ -f "$f" ] || return 0
  { grep -vE "^$1=" "$f" 2>/dev/null || true; } > "$f.tmp"; mv "$f.tmp" "$f"
}

# --- markers -----------------------------------------------------------------
# Extract the LAST 'KEY=value' marker from a captured box output (last in case a
# line repeats).
# -f2- (NOT -f2): base64 payload markers (MB_VISITOR_B64, MC_CA_B64) end in '='
# padding, and -f2 silently dropped it — the receiving box then died with
# "base64: invalid input" and the tunnel/alert paths failed for years.
vm_marker() { printf '%s' "$2" | grep -oE "$1=[^ ]+" | tail -1 | cut -d= -f2-; }

# --- the agent .deb ----------------------------------------------------------
# Build the Go agent + its .deb from the synced checkout (run from the repo
# root), echo the .deb path. build-deb.sh needs a frpc at the repo root and
# MOVES the package to the repo root (not dist/). Shared by the agent, tunnel
# and visitor roles so a build-path change lands once — and no role can swallow
# the build error.
# Build noise goes to STDERR: every caller captures stdout via $(...) and
# expects a bare path; make's echoed go-build recipe and dpkg-deb's chatter on
# stdout once poisoned the captured value into a multi-line string, which then
# failed `dpkg -i "$DEB"` at all four call sites.
vm_build_agent_deb() {  # vm_build_agent_deb <tag> -> echoes ONLY the .deb path, returns 1 on failure
  local tag="${1:?}" deb
  ( cd apps/agent && make build-linux ) >&2 || { echo "[$tag] go build failed" >&2; return 1; }
  cp -f apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu ./frpc 2>/dev/null || true
  VERSION="0.0.0-test" bash apps/agent/build-deb.sh >&2 || { echo "[$tag] build-deb failed" >&2; return 1; }
  deb="$(ls -1 ./adminhelper-agent_*_amd64.deb 2>/dev/null | head -1)"
  [ -n "$deb" ] || { echo "[$tag] no .deb produced (looked in repo root)" >&2; return 1; }
  echo "$deb"
}
