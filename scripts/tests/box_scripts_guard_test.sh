#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# box_scripts_guard_test.sh — a background process started by a box script must
# not inherit the ssh session's stdout/stderr. `vm.py run` uses no pty, so a
# `cmd … &` whose parent (sudo, sh -c) still holds those descriptors keeps the
# ssh channel open after the script exits, and the run only ends at its timeout
# (box_visitorbox.sh, capstone 2026-09-18: 50 minutes for an 8-second check).
# The rule: every `… &` line in scripts/tests/box_*.sh starts its daemon under
# setsid or nohup with stdin from /dev/null, or hands it to systemd.
#
# Run: bash scripts/tests/box_scripts_guard_test.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

files=$(ls "$HERE"/box_*.sh 2>/dev/null)
[ -n "$files" ] && ok "box scripts found: $(echo "$files" | wc -l)" || bad "no box_*.sh found — the guard scans nothing"

# Lines that end a command in the background, ignoring comments and `&&`.
bg=$(grep -nE '(^|[^&])&[[:space:]]*$' $files | grep -vE '^[^:]+:[0-9]+:[[:space:]]*#' || true)
if [ -z "$bg" ]; then
  ok "no background process in the box scripts"
else
  while IFS= read -r line; do
    case "$line" in
      *setsid*/dev/null*|*nohup*/dev/null*) ok "detached: ${line%%:*}:$(cut -d: -f2 <<<"$line")" ;;
      *) bad "background process still tied to the session: $line" ;;
    esac
  done <<<"$bg"
fi

echo ""
echo "box_scripts_guard_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
