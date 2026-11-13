#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# freebsd_box.sh — the Go agent on real FreeBSD (R-1247). On the dev box it cross-builds the
# agent's test binaries, the FreeBSD agent, a stand-in monitoring service and fetches frpc of the
# frp release (pinned sha256); then it leases one box from the template ah-tpl-base-freebsd
# (`vm.py import --profile base-freebsd`) and runs scripts/tests/box_freebsdbox.sh there in three
# phases: the tests as the box user, the few that need root, then the package (built on the box:
# pkg-create and pkg-repo are FreeBSD's own), the signed repo, the cron entry, the rc.d tunnel and
# one agent run as root. The one agent test that calls go runs here instead.
#
#   bash scripts/tests/freebsd_box.sh [--keep]
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

# The frpc the package carries; the version is the one bootstrap_linux.sh installs on the Linux
# boxes. The sha256 is the line for frp_<v>_freebsd_amd64.tar.gz of the release's checksum file.
FRP_VERSION=0.72.0
FRP_SHA256_FREEBSD_AMD64=584662abdb72ca01cf01fb9734d99b3bb7183d4cb564dc50b549ee4a46bbf21b
FRP_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/adminhelper/frp"
# Below apps/agent/bin (gitignored) and outside rsync-exclude.txt: `vm.py run --sync` carries it.
BUILD_REL=apps/agent/bin/freebsd-box
BUILD="$VM_ROOT/$BUILD_REL"

PASS=0; FAIL=0
ok(){ echo "  ok   $*"; PASS=$((PASS+1)); }; bad(){ echo "  FAIL $*"; FAIL=$((FAIL+1)); }
summary(){ echo ""; echo "freebsd_box: $PASS passed, $FAIL failed"; }
not_verified(){ echo "SKIP $*"; summary; exit 75; }

# Env needs are this script's to resolve (.claude/rules/testing.md): Go comes from .devenv.sh.
if ! command -v go >/dev/null 2>&1 && [ -f "$VM_ROOT/.devenv.sh" ]; then
  # shellcheck source=/dev/null
  . "$VM_ROOT/.devenv.sh"
fi
command -v go >/dev/null 2>&1 || not_verified "no go on the PATH, not even after .devenv.sh"
vm_load_env || exit 1

SCENARIO="fb-$$"; export AH_VM_SCENARIO="$SCENARIO"
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
mkdir -p "$BUILD/tests" "$VM_ROOT/.ah-out" || exit 1

# The cross-build guard (go vet for freebsd/amd64 over every package) needs go, which the box
# lacks; the box leaves it out (box_freebsdbox.sh skip_for).
guard_log="$(mktemp -p "$VM_ROOT/.ah-out")"
if (cd apps/agent && go test -count=1 -v -run '^TestAgentPackagesBuildForFreeBSD$' ./cmd/adminhelper-agent) \
     >"$guard_log" 2>&1 && grep -q '^--- PASS: TestAgentPackagesBuildForFreeBSD ' "$guard_log"; then
  ok "cmd/adminhelper-agent TestAgentPackagesBuildForFreeBSD (dev box)"
else
  bad "cmd/adminhelper-agent TestAgentPackagesBuildForFreeBSD (dev box)"; tail -n 30 "$guard_log"
fi
rm -f -- "$guard_log"

export CGO_ENABLED=0 GOOS=freebsd GOARCH=amd64

# One binary per package with tests, run on the box from the package's directory (testdata).
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
[ "$built" -gt 0 ] && ok "test binaries: $built packages" || bad "no test binary built"

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

# The stand-in monitoring service: TLS on 127.0.0.1 with a certificate of its own (the agent
# pins it on `monitor init --insecure`), 200 {} to every request, one SINK_REPORT line per POST
# with what the box script asserts. Go, because the template has no Python.
sink_src="$(mktemp -d -p "$VM_ROOT/.ah-out")"
cat > "$sink_src/sink.go" <<'GO'
package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

func main() {
	dir := os.Args[1]
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	check(err)
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(time.Now().UnixNano()),
		Subject:               pkix.Name{CommonName: "fbsdbox-sink"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(24 * time.Hour),
		IPAddresses:           []net.IP{net.IPv4(127, 0, 0, 1)},
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		BasicConstraintsValid: true,
		IsCA:                  true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	check(err)
	cert := tls.Certificate{Certificate: [][]byte{der}, PrivateKey: key}
	ln, err := tls.Listen("tcp", "127.0.0.1:0", &tls.Config{Certificates: []tls.Certificate{cert}})
	check(err)
	// Written, then renamed: the box script polls for the file and must not read half a port.
	port := fmt.Sprint(ln.Addr().(*net.TCPAddr).Port)
	check(os.WriteFile(filepath.Join(dir, "port.tmp"), []byte(port), 0o644))
	check(os.Rename(filepath.Join(dir, "port.tmp"), filepath.Join(dir, "port")))
	var mu sync.Mutex
	n := 0
	check(http.Serve(ln, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			body, _ := io.ReadAll(r.Body)
			mu.Lock()
			n++
			name := filepath.Join(dir, fmt.Sprintf("report-%d.json", n))
			mu.Unlock()
			_ = os.WriteFile(name, body, 0o644)
			fmt.Println(summary(r.URL.Path, r.Header.Get("X-API-Key") != "", body))
		} else {
			fmt.Printf("%s %s\n", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, "{}")
	})))
}

// summary is one line, with a space after every value, so the box script can match " key=value ".
func summary(path string, keyed bool, body []byte) string {
	var report map[string]any
	if err := json.Unmarshal(body, &report); err != nil {
		return fmt.Sprintf("SINK_REPORT path=%s json=invalid ", path)
	}
	host, _ := report["host"].(map[string]any)
	state, hasState := report["system_state"].(map[string]any)
	return fmt.Sprintf("SINK_REPORT path=%s api_key=%v os=%v platform=%v system_state=%v state_keys=%s keys=%s ",
		path, keyed, host["os"], host["platform"], hasState, keys(state), keys(report))
}

func keys(m map[string]any) string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return strings.Join(out, ",")
}

func check(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
GO
if (cd "$sink_src" && go build -o "$BUILD/sink" sink.go); then
  ok "stand-in monitoring service (sink)"
else
  bad "go build sink"
fi
rm -rf -- "$sink_src"
unset CGO_ENABLED GOOS GOARCH
[ "$FAIL" -eq 0 ] || { summary; exit 1; }

echo "== doctor: does this hypervisor fit a freebsd box? =="
doctor_log="$(mktemp -p "$VM_ROOT/.ah-out")"
doctor_rc=0
vm_py doctor --roles freebsd >"$doctor_log" 2>&1 || doctor_rc=$?
cat "$doctor_log"
if [ "$doctor_rc" != 0 ]; then
  grep -q 'no template tagged for.*base-freebsd' "$doctor_log" && { rm -f -- "$doctor_log"; \
    not_verified "no template ah-tpl-base-freebsd: python3 scripts/vm/vm.py import --profile base-freebsd"; }
  rm -f -- "$doctor_log"
  bad "doctor refused the box (exit $doctor_rc)"; summary; exit "$doctor_rc"
fi
rm -f -- "$doctor_log"

echo "== lease =="
VMID="$(vm_py clone --profile base-freebsd --role freebsd --scenario "$SCENARIO" --ttl 60m | awk 'NR==1{print $1}')"
[ -n "$VMID" ] || { bad "clone printed no VMID"; summary; exit 1; }
ip="$(vm_py wait "$VMID" | tail -1)"
[ -n "$ip" ] || { bad "box $VMID never came up"; summary; exit 1; }
ok "box $VMID up"

# phase <name> <timeout> <sync|nosync> <command…> — one box phase, its own counts added to ours.
phase() {
  local name="$1" tmo="$2" sync="$3" out rc=0 p f
  shift 3
  if [ "$sync" = sync ]; then
    out="$(vm_py run "$VMID" --sync --timeout "$tmo" -- "$@" 2>&1)" || rc=$?
  else
    out="$(vm_py run "$VMID" --timeout "$tmo" -- "$@" 2>&1)" || rc=$?
  fi
  printf '%s\n' "$out" | grep -E '^(  ok|  FAIL|      |\[fbsdbox\]|fbsdbox )'
  p="$(vm_marker "FBSD_${name}_PASSED" "$out")"; f="$(vm_marker "FBSD_${name}_FAILED" "$out")"
  if [ -z "$p" ] || [ -z "$f" ]; then
    bad "phase $name printed no counts (exit $rc)"; printf '%s\n' "$out" | tail -n 30
    return
  fi
  PASS=$((PASS + p)); FAIL=$((FAIL + f))
  [ "$rc" = 0 ] || [ "$f" -gt 0 ] || bad "phase $name exit $rc without a failed check"
}

echo "== phase tests (box user) =="
phase tests 1800 sync sh scripts/tests/box_freebsdbox.sh tests "$BUILD_REL"
echo "== phase roottests (root) =="
# AH_FREEBSD_PF=1: this box is thrown away, so the pf redirect test may change its pf.
phase roottests 900 nosync sudo env AH_FREEBSD_PF=1 sh scripts/tests/box_freebsdbox.sh roottests "$BUILD_REL"
echo "== phase pkg (root) =="
phase pkg 900 nosync sudo sh scripts/tests/box_freebsdbox.sh pkg "$BUILD_REL"

summary
[ "$FAIL" -eq 0 ]
