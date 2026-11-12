#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Hermetic test of .github/scripts/cache_settings.sh: needs bash, awk and sed only. Runs in the
# CI job ops-scripts, like tauri_cli_pins_test.sh.
# Last, the real workflows must pass it: that is the guard on ci.yml and release.yml.

set -uo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
tool="$root/.github/scripts/cache_settings.sh"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

passed=0 failed=0
check() { # check <name> <expected> <actual>
    if [ "$2" = "$3" ]; then
        passed=$((passed + 1))
    else
        failed=$((failed + 1))
        echo "FAIL $1: expected '$2', got '$3'" >&2
    fi
}
run() { # run <file…> → "<rc>"
    local rc=0
    bash "$tool" "$@" >"$work/out" 2>&1 || rc=$?
    echo "$rc"
}

cat >"$work/good.yml" <<'YML'
jobs:
  rust:
    steps:
      - uses: actions/checkout@v7
      # A comment between steps: cache-bin: true
      - uses: Swatinem/rust-cache@d1527c8f67ef9af357290475d4af4b0fab8f12e0 # v2.9.3
        with:
          workspaces: apps/desktop/src-tauri
          cache-bin: false
      - uses: Swatinem/rust-cache@v2
        with:
          cache-bin: "false" # quoted
      - uses: actions/cache@v6
        with:
          path: ~/.cache/ms-playwright
          key: playwright-${{ runner.os }}-${{ hashFiles('apps/web/package-lock.json') }}-chromium
      - uses: actions/cache@v6
        with:
          path: ~/apt-archives
          key: apt-${{ steps.week.outputs.week }}
          restore-keys: apt-
YML
check "settings in place: green" 0 "$(run "$work/good.yml")"
check "green names the file count" "cache_settings: ok (1)" "$(cat "$work/out")"

sed '9d' "$work/good.yml" >"$work/nobin.yml"
check "rust-cache without cache-bin: red" 1 "$(run "$work/nobin.yml")"
check "red names file and line" "::error file=$work/nobin.yml,line=6::rust-cache step without cache-bin: false" "$(cat "$work/out")"

sed 's/^\(          cache-bin: \)false$/\1true/' "$work/good.yml" >"$work/bintrue.yml"
check "cache-bin: true: red" 1 "$(run "$work/bintrue.yml")"

sed 's/^          cache-bin: false$/          # cache-bin: false/' "$work/good.yml" >"$work/bincomment.yml"
check "cache-bin only in a comment: red" 1 "$(run "$work/bincomment.yml")"

# cache-bin of the NEXT step must not cover a rust-cache step without it.
cat >"$work/next.yml" <<'YML'
    steps:
      - uses: Swatinem/rust-cache@v2
        with:
          workspaces: apps/desktop/src-tauri
      - name: other
        with:
          cache-bin: false
YML
check "cache-bin in the next step does not count: red" 1 "$(run "$work/next.yml")"

# Nor a key at the job level after the last step.
cat >"$work/joblevel.yml" <<'YML'
jobs:
  rust:
    steps:
      - uses: Swatinem/rust-cache@v2
  other:
    cache-bin: false
YML
check "cache-bin after the step block does not count: red" 1 "$(run "$work/joblevel.yml")"

sed "s/\${{ hashFiles('apps\/web\/package-lock.json') }}/\${{ steps.playwright.outputs.version }}/" \
    "$work/good.yml" >"$work/pwversion.yml"
check "playwright key without hashFiles: red" 1 "$(run "$work/pwversion.yml")"
check "red names the playwright step" "::error file=$work/pwversion.yml,line=13::ms-playwright cache whose key does not use hashFiles(" "$(cat "$work/out")"

sed '16a\          restore-keys: playwright-' "$work/good.yml" >"$work/pwrestore.yml"
check "playwright cache with restore-keys: red" 1 "$(run "$work/pwrestore.yml")"

check "one bad file among good ones: red" 1 "$(run "$work/good.yml" "$work/nobin.yml")"
check "no argument: usage" 2 "$(run)"
check "unreadable file: usage" 2 "$(run "$work/missing.yml")"

check "real ci.yml and release.yml: green" 0 \
    "$(run "$root/.github/workflows/ci.yml" "$root/.github/workflows/release.yml")"
[ "$(grep -c . "$work/out")" = 1 ] || cat "$work/out" >&2

echo "cache_settings_test: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
