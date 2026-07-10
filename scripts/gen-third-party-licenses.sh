#!/usr/bin/env bash
# gen-third-party-licenses.sh — regenerate the raw third-party license inventory
# that feeds THIRD_PARTY_LICENSES.md, reproducibly across all four language stacks.
#
# Emits one machine-readable file per shipped component under the output dir
# (default: ./third-party-inventory, gitignored). The Markdown doc is then
# hand-assembled from these — the obligation sections (Apache NOTICE / LGPL /
# MPL) still need human legal review, but the per-package tables come straight
# from here so they never drift from the real dependency set again (7.6).
#
# Requires network on first run: installs pip-licenses / go-licenses /
# cargo-license / license-checker on demand. No sudo, no repo mutation.
#
# Usage: scripts/gen-third-party-licenses.sh [output-dir]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$REPO_ROOT/third-party-inventory}"
mkdir -p "$OUT"
echo "== third-party inventory -> $OUT =="

# --- Python (server, monitoring, ca-issuer) ----------------------------------
# A throwaway venv with ONLY the shipped requirements.txt, so the dev tooling
# (pytest, ruff, …) that lives in the working venvs never leaks into the report.
gen_python() {
  local app="$1"
  local req="$REPO_ROOT/apps/$app/requirements.txt"
  [ -f "$req" ] || { echo "skip python/$app (no requirements.txt)"; return; }
  local venv; venv="$(mktemp -d)/venv"
  python3 -m venv "$venv"
  "$venv/bin/pip" install -q --upgrade pip pip-licenses >/dev/null
  "$venv/bin/pip" install -q -r "$req" >/dev/null
  "$venv/bin/pip-licenses" --format=csv --order=license --with-urls \
    --ignore-packages pip setuptools > "$OUT/python-$app.csv"
  echo "python/$app -> $(($(wc -l < "$OUT/python-$app.csv") - 1)) packages"
  rm -rf "$(dirname "$venv")"
}
gen_python server
gen_python monitoring
gen_python ca-issuer

# --- Go (agent) --------------------------------------------------------------
# Report per target OS — the //go:build tags pull in different packages.
gen_go() {
  command -v go >/dev/null || { echo "skip go (no toolchain)"; return; }
  go install github.com/google/go-licenses@latest
  local gl; gl="$(go env GOPATH)/bin/go-licenses"
  for os in linux windows; do
    ( cd "$REPO_ROOT/apps/agent" \
      && GOOS="$os" "$gl" csv ./cmd/adminhelper-agent > "$OUT/go-$os.csv" 2>/dev/null ) \
      || echo "  (go/$os report incomplete — inspect manually)"
    echo "go/$os -> $(wc -l < "$OUT/go-$os.csv" 2>/dev/null || echo 0) packages"
  done
}
gen_go

# --- Rust (desktop) ----------------------------------------------------------
# The whole crate graph (all targets), grouped by license.
gen_rust() {
  command -v cargo >/dev/null || { echo "skip rust (no cargo)"; return; }
  command -v cargo-license >/dev/null || cargo install cargo-license >/dev/null 2>&1
  ( cd "$REPO_ROOT/apps/desktop/src-tauri" && cargo license --json > "$OUT/rust.json" )
  echo "rust -> $(cd "$REPO_ROOT/apps/desktop/src-tauri" && cargo license 2>/dev/null | grep -c '' ) license groups"
}
gen_rust

# --- JavaScript / TypeScript (desktop/ui, web, desktop/e2e) ------------------
# Production deps only; needs node_modules present (run `npm ci` first).
gen_js() {
  local app="$1"
  local dir="$REPO_ROOT/apps/$app" tag="${1//\//-}"
  [ -d "$dir/node_modules" ] || { echo "skip js/$app (run npm ci first)"; return; }
  ( cd "$dir" && npx --yes license-checker --production --json > "$OUT/js-$tag.json" )
  echo "js/$app -> $(grep -c '"licenses"' "$OUT/js-$tag.json" 2>/dev/null || echo 0) packages"
}
gen_js desktop/ui
gen_js web
gen_js desktop/e2e

echo "== done — assemble THIRD_PARTY_LICENSES.md from the files in $OUT =="
