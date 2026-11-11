#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Hermetic test of retry.sh: needs bash and coreutils only. Runs in the CI job ops-scripts.

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
retry="$here/retry.sh"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
export RETRY_PAUSE=0

passed=0 failed=0
check() { # check <name> <expected> <actual>
    if [ "$2" = "$3" ]; then
        passed=$((passed + 1))
    else
        failed=$((failed + 1))
        echo "FAIL $1: expected '$2', got '$3'" >&2
    fi
}

# A command that fails until its n-th call, counting calls in a file.
cat >"$work/flaky.sh" <<'SH'
#!/usr/bin/env bash
count=$(( $(cat "$1" 2>/dev/null || echo 0) + 1 ))
echo "$count" >"$1"
[ "$count" -ge "$2" ] || exit 7
SH
chmod +x "$work/flaky.sh"

calls() { cat "$work/$1"; }

rc=0; bash "$retry" 3 5 "$work/flaky.sh" "$work/first" 1 2>/dev/null || rc=$?
check "success at once: exit" 0 "$rc"
check "success at once: one call" 1 "$(calls first)"

rc=0; bash "$retry" 5 5 "$work/flaky.sh" "$work/third" 3 2>/dev/null || rc=$?
check "success in attempt 3: exit" 0 "$rc"
check "success in attempt 3: stops there" 3 "$(calls third)"

rc=0; bash "$retry" 2 5 "$work/flaky.sh" "$work/never" 99 2>"$work/never.err" || rc=$?
check "always failing: exit of the last attempt" 7 "$rc"
check "always failing: every attempt" 2 "$(calls never)"
check "always failing: one note per attempt" 2 "$(grep -c '^retry.sh: attempt' "$work/never.err")"

start=$SECONDS
rc=0; bash "$retry" 2 1 sleep 30 2>/dev/null || rc=$?
check "stalled: exit 124" 124 "$rc"
check "stalled: killed per attempt, not waited out" yes "$([ $((SECONDS - start)) -lt 10 ] && echo yes || echo no)"

rc=0; bash "$retry" 3 5 2>/dev/null || rc=$?
check "usage: exit 2" 2 "$rc"

echo "retry_test.sh: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
