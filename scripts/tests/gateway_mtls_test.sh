#!/usr/bin/env bash
#
# gateway_mtls_test.sh — the gateway entrypoint's MTLS_ENFORCE parsing must be
# FAIL-CLOSED: an unrecognized/typo'd value (or the default) enforces mTLS, never
# silently drops to permissive. This is security-critical shell logic with no other
# coverage (the ops-scripts CI tests only scripts/, integration_stack runs only
# MTLS_ENFORCE=true). Hermetic: extracts just the case block, no nginx/postgres (6.46).
#
# Run: bash scripts/tests/gateway_mtls_test.sh

set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
ENTRYPOINT="$REPO/apps/gateway/docker-entrypoint.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

# Just the MTLS_ENFORCE case (writes the ssl_verify_client snippet) — no nginx/DB.
CASE=$(awk '/^case .*MTLS_ENFORCE/,/^esac/' "$ENTRYPOINT")
[ -n "$CASE" ] || { echo "FAIL: could not extract the MTLS_ENFORCE case from $ENTRYPOINT"; exit 1; }

check() {  # <MTLS_ENFORCE value> <expected snippet content>
    local val="$1" expect="$2" dir got
    dir=$(mktemp -d)
    MTLS_ENFORCE="$val" SNIPPET_DIR="$dir" sh -c "$CASE" >/dev/null 2>&1
    got=$(cat "$dir/data-plane-mtls.conf" 2>/dev/null)
    rm -rf "$dir"
    [ "$got" = "$expect" ] && ok "MTLS_ENFORCE='$val' -> $expect" \
        || bad "MTLS_ENFORCE='$val' -> got '$got', want '$expect'"
}

ENF="ssl_verify_client on;"
PERM="ssl_verify_client optional;"

check true      "$ENF"    # canonical enforce
check false     "$PERM"   # canonical permissive
check on        "$ENF"    # the obvious alias — now recognized, not dropped
check off       "$PERM"
check ture      "$ENF"    # typo of 'true' -> FAIL CLOSED (was: silently permissive)
check enforced  "$ENF"    # any unknown value -> FAIL CLOSED
check ""        "$ENF"    # empty/unset default -> enforced (2.103; matches compose)

echo
echo "──────────────────────────────────────────"
echo "  gateway_mtls_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
