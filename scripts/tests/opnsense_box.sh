#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# opnsense_box.sh — the plugin os-adminhelper on a real OPNsense (R-1248). On the dev box it builds
# what freebsd_box.sh builds (the agent's test binaries, the FreeBSD agent, frpc of the pinned frp
# release, the stand-in monitoring service; pin and sink are read from freebsd_box.sh, not copied)
# and a monitoring plan of the catalog's opnsense module. Then it leases one box from the template
# ah-tpl-base-opnsense (`vm.py bake --profile base-opnsense`) and runs three phases there: the
# agent's tests as the box user and as root (box_freebsdbox.sh: OPNsense is FreeBSD underneath),
# then box_opnsensebox.sh as root: the plugin and the agent from a signed local repo, the five
# views against the real configctl, one agent run with that plan, the settings switch and
# pkg delete.
#
#   bash scripts/tests/opnsense_box.sh [--keep]
#   --keep   leave the box up after a green run as well (bounded by its ttl)
#
# A red run leaves the box up for a look (bounded by the ttl) and names the destroy call.
# Without the template or without Go the run is not verified: exit 75.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/vm/lib.sh
. "$DIR/../vm/lib.sh"
cd "$VM_ROOT" || exit 1

KEEP=0
while [ $# -gt 0 ]; do case "$1" in
  --keep) KEEP=1 ;;
  *) echo "unknown arg: $1"; exit 2 ;; esac; shift; done

FRP_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/adminhelper/frp"
# Below apps/agent/bin (gitignored) and outside rsync-exclude.txt: `vm.py run --sync` carries it.
BUILD_REL=apps/agent/bin/opnsense-box
BUILD="$VM_ROOT/$BUILD_REL"

PASS=0; FAIL=0
ok(){ echo "  ok   $*"; PASS=$((PASS+1)); }; bad(){ echo "  FAIL $*"; FAIL=$((FAIL+1)); }
summary(){ echo ""; echo "opnsense_box: $PASS passed, $FAIL failed"; }
not_verified(){ echo "SKIP $*"; summary; exit 75; }

# Env needs are this script's to resolve (.claude/rules/testing.md): Go comes from .devenv.sh.
if ! command -v go >/dev/null 2>&1 && [ -f "$VM_ROOT/.devenv.sh" ]; then
  # shellcheck source=/dev/null
  . "$VM_ROOT/.devenv.sh"
fi
command -v go >/dev/null 2>&1 || not_verified "no go on the PATH, not even after .devenv.sh"
vm_load_env || exit 1

# The frp pin of the FreeBSD box: both boxes carry the same frpc, and one place keeps it.
FRP_VERSION="$(sed -n 's/^FRP_VERSION=//p' "$DIR/freebsd_box.sh")"
FRP_SHA256_FREEBSD_AMD64="$(sed -n 's/^FRP_SHA256_FREEBSD_AMD64=//p' "$DIR/freebsd_box.sh")"
# Classes spelled out: bash's ranges follow the locale.
[[ $FRP_VERSION =~ ^[0123456789]+\.[0123456789]+\.[0123456789]+$ ]] \
  && [[ $FRP_SHA256_FREEBSD_AMD64 =~ ^[0123456789abcdef]{64}$ ]] \
  || { bad "no frp pin in freebsd_box.sh (FRP_VERSION, FRP_SHA256_FREEBSD_AMD64)"; summary; exit 1; }

SCENARIO="ob-$$"; export AH_VM_SCENARIO="$SCENARIO"
VMID=""
cleanup() {
  [ -n "$VMID" ] || return 0
  if [ "$KEEP" = 1 ] || [ "$FAIL" -gt 0 ]; then
    echo "box $VMID stays up (ttl); done with it: python3 scripts/vm/vm.py destroy --scenario $SCENARIO"
    return 0
  fi
  echo "== teardown scenario $SCENARIO =="
  vm_py destroy --scenario "$SCENARIO" 2>&1 | sed 's/^/  /' || true
}
trap cleanup EXIT INT TERM

echo "== build on the dev box ($BUILD_REL) =="
rm -rf -- "$BUILD"
# freebsd_box.sh's build would travel along with every sync: / on the box has some 600 MB free.
rm -rf -- "$VM_ROOT/apps/agent/bin/freebsd-box"
mkdir -p "$BUILD/tests" "$VM_ROOT/.ah-out" || exit 1

# The cross-build guard needs go, which the box lacks; box_freebsdbox.sh leaves it out there.
guard_log="$(mktemp -p "$VM_ROOT/.ah-out")"
if (cd apps/agent && go test -count=1 -v -run '^TestAgentPackagesBuildForFreeBSD$' ./cmd/adminhelper-agent) \
     >"$guard_log" 2>&1 && grep -q '^--- PASS: TestAgentPackagesBuildForFreeBSD ' "$guard_log"; then
  ok "cmd/adminhelper-agent TestAgentPackagesBuildForFreeBSD (dev box)"
else
  bad "cmd/adminhelper-agent TestAgentPackagesBuildForFreeBSD (dev box)"; tail -n 30 "$guard_log"
fi
rm -f -- "$guard_log"

export CGO_ENABLED=0 GOOS=freebsd GOARCH=amd64

# One binary per package with tests, in the manifest box_freebsdbox.sh reads.
pkgs="$(cd apps/agent && go list -f '{{if or .TestGoFiles .XTestGoFiles}}{{.ImportPath}} {{.Dir}}{{end}}' ./...)" \
  || { bad "go list"; summary; exit 1; }
built=0
while read -r pkg dir; do
  [ -n "$pkg" ] || continue
  rel="${dir#"$VM_ROOT"/apps/agent/}"
  bin="$(printf '%s' "$rel" | tr '/' '_').test"
  if (cd apps/agent && go test -c -o "$BUILD/tests/$bin" "$pkg"); then
    printf '%s %s\n' "$rel" "$bin" >> "$BUILD/manifest"; built=$((built+1))
  else
    bad "go test -c $pkg"
  fi
done <<<"$pkgs"
[ "$built" -gt 0 ] && ok "test binaries: $built packages ($(du -sh "$BUILD/tests" | cut -f1))" || bad "no test binary built"

if make -C apps/agent build-freebsd >/dev/null && cp apps/agent/bin/adminhelper-agent-freebsd "$BUILD/"; then
  ok "agent: $(file -b "$BUILD/adminhelper-agent-freebsd" | cut -d, -f1-2)"
else
  bad "make build-freebsd"
fi

# frpc: the release archive into its own empty directory, checked before anything reads it.
mkdir -p "$FRP_CACHE"
tgz="$FRP_CACHE/frp_${FRP_VERSION}_freebsd_amd64.tar.gz"
if [ ! -f "$tgz" ] || ! echo "$FRP_SHA256_FREEBSD_AMD64  $tgz" | sha256sum -c --status -; then
  rm -f -- "$tgz"
  curl -fsSL --retry 3 -o "$tgz.part" \
    "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_freebsd_amd64.tar.gz" \
    && mv "$tgz.part" "$tgz"
fi
frp_dir="$(mktemp -d -p "$VM_ROOT/.ah-out")"
if echo "$FRP_SHA256_FREEBSD_AMD64  $tgz" | sha256sum -c --status - \
   && tar -xzf "$tgz" -C "$frp_dir" "frp_${FRP_VERSION}_freebsd_amd64/frpc" \
   && cp "$frp_dir/frp_${FRP_VERSION}_freebsd_amd64/frpc" "$BUILD/frpc"; then
  ok "frpc $FRP_VERSION freebsd_amd64 (sha256 pinned)"
else
  bad "frpc $FRP_VERSION: download, checksum or unpack failed ($tgz)"
fi
rm -rf -- "$frp_dir"

# The stand-in monitoring service of freebsd_box.sh, its heredoc taken as it stands there: 200 {}
# to every request (the agent refuses that as a plan and runs its saved one), one SINK_REPORT line
# and one report-N.json per POST.
sink_src="$(mktemp -d -p "$VM_ROOT/.ah-out")"
sed -n "/<<'GO'\$/,/^GO\$/p" "$DIR/freebsd_box.sh" | sed '1d;$d' > "$sink_src/sink.go"
if grep -q '^package main$' "$sink_src/sink.go" && grep -q 'report-%d.json' "$sink_src/sink.go" \
   && (cd "$sink_src" && go build -o "$BUILD/sink" sink.go); then
  ok "stand-in monitoring service (sink.go of freebsd_box.sh)"
else
  bad "the sink of freebsd_box.sh: not found or not built"
fi
rm -rf -- "$sink_src"
unset CGO_ENABLED GOOS GOARCH

# The plan the monitoring service sends a host with the opnsense module, from the catalog's own
# MODULE (module_plan.py's form; the check ids are the database's there). scan asks for the
# discovery that finds the module by its marker.
if python3 -I - "$VM_ROOT/apps/monitoring/app/catalog/modules/opnsense.py" "$BUILD/plan.json" <<'PY'
import json
import runpy
import sys

module = runpy.run_path(sys.argv[1])["MODULE"]
markers = [
    {"id": m["id"], "paths": m.get("paths", []), "packages": m.get("packages", [])}
    for m in module["detect"]["markers"]
]
probes = [
    {
        "id": "opnsense-box.%s" % c["key"],
        "sensor": c["sensor"],
        "interval_s": c["interval"],
        "timeout_s": c["timeout_s"],
        "target": None,
        "params": c["params"],
        "fields": c["fields"],
        "credential": None,
    }
    for c in module["checks"]
]
plan = {
    "plan_version": 1,
    "catalog_version": "opnsense-box",
    "scan": True,
    "discovery": {"markers": markers},
    "probes": probes,
}
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump(plan, fh, indent=1)
PY
then
  ok "plan of the opnsense module: $(python3 -I -c 'import json,sys; print(" ".join(p["id"] for p in json.load(open(sys.argv[1]))["probes"]))' "$BUILD/plan.json")"
else
  bad "no plan from apps/monitoring/app/catalog/modules/opnsense.py"
fi
[ "$FAIL" -eq 0 ] || { summary; exit 1; }

echo "== doctor: does this hypervisor fit an opnsense box? =="
doctor_log="$(mktemp -p "$VM_ROOT/.ah-out")"
doctor_rc=0
vm_py doctor --roles opnsense >"$doctor_log" 2>&1 || doctor_rc=$?
cat "$doctor_log"
if [ "$doctor_rc" != 0 ]; then
  grep -q 'no template tagged for.*base-opnsense' "$doctor_log" && { rm -f -- "$doctor_log"; \
    not_verified "no template ah-tpl-base-opnsense: python3 scripts/vm/vm.py bake --profile base-opnsense"; }
  rm -f -- "$doctor_log"
  bad "doctor refused the box (exit $doctor_rc)"; summary; exit "$doctor_rc"
fi
rm -f -- "$doctor_log"

echo "== lease =="
VMID="$(vm_py clone --profile base-opnsense --role opnsense --scenario "$SCENARIO" --ttl 60m | awk 'NR==1{print $1}')"
[ -n "$VMID" ] || { bad "clone printed no VMID"; summary; exit 1; }
ip="$(vm_py wait "$VMID" | tail -1)"
[ -n "$ip" ] || { bad "box $VMID never came up"; summary; exit 1; }
ok "box $VMID up"

# phase <name> <timeout> <sync|nosync> <marker prefix> <command…> — one box phase, its own counts
# added to ours. box_freebsdbox.sh prints FBSD_ markers, box_opnsensebox.sh OPNS_ ones.
phase() {
  local name="$1" tmo="$2" sync="$3" prefix="$4" out rc=0 p f
  shift 4
  if [ "$sync" = sync ]; then
    out="$(vm_py run "$VMID" --sync --timeout "$tmo" -- "$@" 2>&1)" || rc=$?
  else
    out="$(vm_py run "$VMID" --timeout "$tmo" -- "$@" 2>&1)" || rc=$?
  fi
  printf '%s\n' "$out" | grep -E '^(  ok|  FAIL|  note|      |\[fbsdbox\]|fbsdbox |\[opnsbox\]|opnsbox )'
  p="$(vm_marker "${prefix}_${name}_PASSED" "$out")"; f="$(vm_marker "${prefix}_${name}_FAILED" "$out")"
  if [ -z "$p" ] || [ -z "$f" ]; then
    bad "phase $name printed no counts (exit $rc)"; printf '%s\n' "$out" | tail -n 30
    return
  fi
  PASS=$((PASS + p)); FAIL=$((FAIL + f))
  [ "$rc" = 0 ] || [ "$f" -gt 0 ] || bad "phase $name exit $rc without a failed check"
}

echo "== phase tests (box user) =="
phase tests 1800 sync FBSD sh scripts/tests/box_freebsdbox.sh tests "$BUILD_REL"
echo "== phase roottests (root) =="
phase roottests 900 nosync FBSD sudo sh scripts/tests/box_freebsdbox.sh roottests "$BUILD_REL"
echo "== phase pkg (root) =="
phase pkg 1800 nosync OPNS sudo sh scripts/tests/box_opnsensebox.sh pkg "$BUILD_REL"

summary
[ "$FAIL" -eq 0 ]
