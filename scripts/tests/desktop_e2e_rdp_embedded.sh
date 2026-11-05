#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# desktop_e2e_rdp_embedded.sh — the embedded RDP session against a real xrdp 0.10 with the
# graphics pipeline. Builds scripts/tests/xrdp-gfx, starts it on a free loopback port and runs
# the ignored Rust test rdp_embedded::session::tests::xrdp_live_session against it: the
# certificate pin (unknown, pinned, changed), the picture over the frame WebSocket, a key
# answered by a picture only after a receipt, and the stop.
#
# The container log proves what the test cannot see. xrdp answers a failed autologon with
# its own login screen, which takes keys and sends pictures as well, so the test alone stays
# green with a wrong password; the log shows whether a session for e2e started and whether
# the picture went over the graphics pipeline.
#
# Needs docker, openssl and the desktop Rust toolchain; like every desktop_e2e_* suite it
# SKIPs (exit 75) without tauri-cli (desktop_e2e_skip_test.sh).
# Run: bash scripts/tests/desktop_e2e_rdp_embedded.sh

set -uo pipefail

# shellcheck source=scripts/tests/lib_e2e_stack.sh
. "$(cd "$(dirname "$0")" && pwd)/lib_e2e_stack.sh"

PASS=0
FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

e2e_require docker openssl
( cd "$E2E_REPO_ROOT/apps/desktop/src-tauri" && cargo tauri --version >/dev/null 2>&1 ) \
    || { echo "SKIP: tauri-cli (cargo tauri) not available"; exit 75; }

TAG="ah-xrdp-gfx:e2e"
NAME="ah-xrdp-gfx-$$-$(e2e_rand)"
WORK=$(mktemp -d)
trap 'docker rm -f "$NAME" >/dev/null 2>&1; rm -rf "$WORK"' EXIT

finish() {
    echo ""
    echo "desktop_e2e_rdp_embedded: $PASS passed, $FAIL failed"
    [ "$FAIL" -eq 0 ]
    exit
}

xrdp_log() { docker exec "$NAME" cat /var/log/xrdp.log; }

if docker build -t "$TAG" "$_E2E_LIB_DIR/xrdp-gfx" > "$WORK/build.log" 2>&1; then
    ok "xrdp-gfx image built"
else
    bad "xrdp-gfx image build"; tail -n 40 "$WORK/build.log"; finish
fi

docker run -d --init --name "$NAME" -p 127.0.0.1::3389 "$TAG" >/dev/null \
    || { bad "xrdp-gfx container start"; finish; }
ready=no
for _ in $(seq 1 60); do
    logs=$(docker logs "$NAME" 2>&1)
    if grep -qx 'xrdp-gfx: ready' <<<"$logs"; then ready=yes; break; fi
    [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ] || break
    sleep 0.5
done
if [ "$ready" = yes ]; then
    ok "xrdp listens in the container"
else
    bad "xrdp never got ready"; docker logs "$NAME" 2>&1; finish
fi

hostport=$(docker port "$NAME" 3389/tcp)
PORT=${hostport##*:}
# Under pipefail a failed read empties it; sha256sum alone would hash nothing into a valid look.
FINGERPRINT=$(docker exec "$NAME" cat /etc/xrdp/cert.pem | openssl x509 -outform DER | sha256sum) \
    || FINGERPRINT=""
FINGERPRINT=${FINGERPRINT%% *}
# Spelled out, not [0-9a-f]: a bash range under de_DE.UTF-8 matches more than these.
if [[ $FINGERPRINT =~ ^[0123456789abcdef]{64}$ ]] && [[ $PORT =~ ^[0123456789]+$ ]]; then
    ok "target 127.0.0.1:$PORT, certificate fingerprint read"
else
    bad "no port or fingerprint of the container ('$hostport')"; finish
fi

echo "[rdp-embedded] running the ignored live test against the container..."
( cd "$E2E_REPO_ROOT/apps/desktop/src-tauri" \
    && AH_RDP_E2E_HOST=127.0.0.1 AH_RDP_E2E_PORT="$PORT" AH_RDP_E2E_USER=e2e \
       AH_RDP_E2E_PASSWORD=e2e AH_RDP_E2E_FINGERPRINT="$FINGERPRINT" \
       cargo test --locked -- --ignored --exact rdp_embedded::session::tests::xrdp_live_session
) > "$WORK/test.log" 2>&1
rc=$?
cat "$WORK/test.log"
if [ "$rc" -eq 0 ] && grep -q '^test result: ok\. 1 passed; 0 failed' "$WORK/test.log"; then
    ok "xrdp_live_session: 1 passed"
else
    bad "xrdp_live_session (rc=$rc)"
fi

log=$(xrdp_log 2>&1)
if grep -Eq 'session is available on display [[:digit:]]+ for user e2e$' <<<"$log" \
    && ! grep -q 'could not be authenticated' <<<"$log"; then
    ok "xrdp logged e2e on and started its session"
else
    bad "xrdp started no session for e2e"
fi
if grep -q 'egfx created' <<<"$log" && grep -q 'gfx rfx pro codec session' <<<"$log"; then
    ok "the picture went over the graphics pipeline (RemoteFX Progressive)"
else
    bad "xrdp did not use the graphics pipeline"
fi
[ "$FAIL" -eq 0 ] || { echo "[rdp-embedded] xrdp.log of the container:"; printf '%s\n' "$log"; }

finish
