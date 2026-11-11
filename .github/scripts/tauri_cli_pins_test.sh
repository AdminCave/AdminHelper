#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Hermetic test of tauri_cli_pins.sh: needs bash, sed and grep only. Runs in the CI job ops-scripts.

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
pins="$here/tauri_cli_pins.sh"
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
    bash "$pins" "$@" >"$work/out" 2>&1 || rc=$?
    echo "$rc"
}

cat >"$work/ci.yml" <<'YML'
      # Keep in lockstep: run: cargo install tauri-cli --version "1.0.0" (a comment, not counted)
      - name: Install tauri-cli
        run: cargo install tauri-cli --locked --version "2.12.4"
      - run: cargo install tauri-cli --locked --version 2.12.4
YML
cat >"$work/release.yml" <<'YML'
        run: cargo install tauri-cli --locked --version "2.12.4"
        run: cargo install cargo-audit --locked --version 0.22.2
YML

check "same version everywhere: green" 0 "$(run "$work/ci.yml" "$work/release.yml")"
check "summary counts per file" "tauri-cli pins: ci.yml 2, release.yml 1, versions: 2.12.4 " "$(head -1 "$work/out")"

cp "$work/ci.yml" "$work/drift.yml"
sed -i '$ s/2\.12\.4/2.12.5/' "$work/drift.yml"
check "second pin of a file drifts: red" 1 "$(run "$work/drift.yml" "$work/release.yml")"

printf '        run: cargo install tauri-cli --locked\n' >"$work/nover.yml"
check "a pin without a version: red" 1 "$(run "$work/ci.yml" "$work/nover.yml")"

printf '        run: cargo install tauri-cli --locked --version "^2.12"\n' >"$work/range.yml"
check "a version range: red" 1 "$(run "$work/ci.yml" "$work/range.yml")"

printf '        run: echo nothing here\n' >"$work/none.yml"
check "a file without a pin: red" 1 "$(run "$work/ci.yml" "$work/none.yml")"

# Each of these files also holds a plain pin, so only the extra one can turn it red.
cat >"$work/block.yml" <<'YML'
        run: cargo install tauri-cli --locked --version "2.12.4"
        run: |
          rustup show
          cargo install tauri-cli --locked --version "2.12.9"
YML
check "a pin inside a run: | block counts: red on drift" 1 "$(run "$work/ci.yml" "$work/block.yml")"

printf '        run: cargo install tauri-cli --locked --version 2.12.4\n        run: cargo install --locked tauri-cli --version "9.9.9"\n' >"$work/order.yml"
check "flags before the crate name count: red on drift" 1 "$(run "$work/ci.yml" "$work/order.yml")"

cat >"$work/cont.yml" <<'YML'
        run: cargo install tauri-cli --locked --version "2.12.4"
        run: |
          cargo install tauri-cli --locked \
            --version "2.12.9"
YML
check "a continued line counts as one pin: red on drift" 1 "$(run "$work/ci.yml" "$work/cont.yml")"
sed -i 's/2\.12\.9/2.12.4/' "$work/cont.yml"
check "a continued line with the same version: green" 0 "$(run "$work/ci.yml" "$work/cont.yml")"

check "no arguments: usage" 2 "$(run)"

echo "tauri_cli_pins_test.sh: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
