#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# desktop_e2e_skip_test.sh — proves the seven desktop GUI suites report SKIP
# (exit 75), never a silent green, when the tauri CLI is missing.
#
# That branch is the one that fired on every un-hydrated box: `cargo tauri`
# absent, the suite exited 0, run.sh counted a PASS, and the summary claimed
# seven green GUI journeys that never started. Here every OTHER precondition is
# satisfied by a PATH shim while `cargo` is kept out, so each script must reach
# exactly that branch — the assertion is the tauri-cli message AND code 75, so a
# suite skipping for some other reason cannot pass this test.
#
# No docker, no display, no network: the scripts exit before e2e_init.
#
# Run: bash scripts/tests/desktop_e2e_skip_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
SHIM="$WORK/bin"; mkdir -p "$SHIM"

# Plumbing the scripts themselves need (dirname/pwd/mktemp …), linked from the
# real PATH; the toolchains are stubs.
for t in bash sh dirname basename pwd mktemp rm cat grep sed awk timeout env printf; do
  src=$(command -v "$t" 2>/dev/null) && ln -sf "$src" "$SHIM/$t"
done
# Every binary e2e_require checks. The blanket docker stub also answers its
# `docker compose version` and `docker info` probes, since it succeeds at anything.
for t in docker openssl curl python3 node xvfb-run WebKitWebDriver tauri-driver \
         dbus-run-session gnome-keyring-daemon go; do
  printf '#!/bin/sh\nexit 0\n' > "$SHIM/$t"; chmod +x "$SHIM/$t"
done

# cargo must NOT be reachable — that is the whole point of the fixture. PATH is
# replaced, not prefixed, so only what is linked above can be found.
[ -e "$SHIM/cargo" ] && { echo "fixture broken: cargo is on the shim PATH" >&2; exit 1; }

# Derived from the directory, not written out: a hand-kept list would have to be
# updated in two places (here and run.sh's layer_e2e) and an eighth suite added
# with a silent `exit 0` would be missed by exactly the test meant to catch it.
SUITES=""
for f in "$HERE"/desktop_e2e_*.sh; do
  b=$(basename "$f" .sh)
  [ "$b" = "desktop_e2e_skip_test" ] && continue
  SUITES="$SUITES $b"
done
[ -n "$SUITES" ] || { echo "found no desktop_e2e_*.sh to check" >&2; exit 1; }

for s in $SUITES; do
  # `timeout` guards the failure mode this test exists to catch: if the skip
  # branch ever stopped firing, the script would try to bring a stack up.
  out=$(cd "$REPO_ROOT" && PATH="$SHIM" "$SHIM/timeout" 30 "$SHIM/bash" "scripts/tests/$s.sh" 2>&1); rc=$?
  if [ "$rc" -eq 75 ] && printf '%s' "$out" | grep -q "SKIP: tauri-cli"; then
    ok "$s -> exit 75 (tauri-cli)"
  else
    bad "$s -> rc=$rc, out: $(printf '%s' "$out" | tail -1)"
  fi
done

echo ""
echo "desktop_e2e_skip_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
