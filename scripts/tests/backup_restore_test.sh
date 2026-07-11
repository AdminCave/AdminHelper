#!/usr/bin/env bash
#
# backup_restore_test.sh — full crown-jewel DR roundtrip: backup -> total loss -> restore.
#
# ADR 0001 §5 promises backup.sh bundles the ca-pki (crown jewel) + both DBs + ./data,
# and restore.sh brings it all back so agents stay trusted. Nothing exercised that path
# before (6.64) — a wrong ${PROJECT}_${vol} prefix, a pg_restore flag, or an empty dump
# would only surface in a real disaster, the costliest possible moment. This seeds a
# server record + captures the CA the gateway presents, wipes the stack (down -v),
# restores, and asserts BOTH the record is back AND the CA chain is identical.
#
# backup/restore drive `docker compose` via env (project + compose files + .env vars),
# not the e2e wrapper, so we point that env at the same e2e stack.
#
# Run: AH_ALLOW_REAL=1 bash scripts/tests/backup_restore_test.sh   (needs docker + compose)

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib_e2e_stack.sh
. "$HERE/lib_e2e_stack.sh"

PASS=0
FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

e2e_require
trap e2e_teardown EXIT
e2e_init false # MTLS_ENFORCE=false — plain admin-token seeding, no client cert needed
# backup.sh dumps ca-issuer + monitoring + server /app/data, so ALL three must run —
# monitoring is NOT in the gateway dependency chain, so start it explicitly (6.64).
e2e_up gateway monitoring || { echo "stack never came up"; exit 1; }

# ── Seed: a server record + the CA the gateway currently presents ─────────────
TOKEN=$(e2e_admin_token)
SID=$(e2e_api "$TOKEN" server dr-probe dr.local)
[ -n "$SID" ] && ok "seeded server record (id=$SID)" || { bad "could not seed server record"; exit 1; }
# The gateway leaf is signed by the issuer's intermediate; issuer_hash is stable across
# a restore ONLY if ca-pki round-trips (the issuer re-provisions the leaf from it on boot).
ca_fingerprint() {
    echo | openssl s_client -connect "localhost:$E2E_HTTPS_PORT" -showcerts 2>/dev/null \
        | openssl x509 -noout -issuer_hash 2>/dev/null || true
}
CA_BEFORE=$(ca_fingerprint)
[ -n "$CA_BEFORE" ] && ok "captured CA before ($CA_BEFORE)" || bad "could not read gateway CA"

# ── backup.sh against the e2e stack ───────────────────────────────────────────
export COMPOSE_PROJECT_NAME="$E2E_PROJECT"
export COMPOSE_FILE="$E2E_REPO_ROOT/docker-compose.yml:$E2E_REPO_ROOT/docker-compose.test.yml"
set -a
# shellcheck disable=SC1091
. "$E2E_WORK/.env" # POSTGRES_PASSWORD etc. for docker compose ${VAR} interpolation
set +a
mkdir -p "$E2E_WORK/bk"
if (cd "$E2E_REPO_ROOT" && ./scripts/backup.sh --output "$E2E_WORK/bk") >"$E2E_WORK/backup.log" 2>&1; then
    ok "backup.sh completed"
else
    bad "backup.sh failed"; tail -15 "$E2E_WORK/backup.log" >&2
fi
BK=$(ls "$E2E_WORK"/bk/*.tar.gz 2>/dev/null | head -1)
[ -s "$BK" ] && ok "backup archive is non-empty ($(du -h "$BK" | cut -f1))" || bad "no/empty backup archive"

# ── Total loss + restore ──────────────────────────────────────────────────────
e2e_dc down -v >/dev/null 2>&1
if [ -n "$BK" ] && (cd "$E2E_REPO_ROOT" && ./scripts/restore.sh "$BK" --yes) >"$E2E_WORK/restore.log" 2>&1; then
    ok "restore.sh completed"
else
    bad "restore.sh failed"; tail -20 "$E2E_WORK/restore.log" >&2
fi

# ── Assert: server record back + CA chain identical ───────────────────────────
code=000
for _ in $(seq 1 60); do
    code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 3 "$E2E_SERVER_URL/" 2>/dev/null || echo 000)
    [ "$code" != "000" ] && break
    sleep 2
done
[ "$code" != "000" ] && ok "restored stack answers again" || bad "restored stack never came back"

TOKEN2=$(e2e_admin_token)
SERVERS=$(curl -k -s -H "Authorization: Bearer $TOKEN2" "$E2E_SERVER_URL/api/servers" 2>/dev/null || echo "")
echo "$SERVERS" | grep -q "dr-probe" \
    && ok "server record survived the roundtrip (dr-probe present)" \
    || bad "server record LOST after restore"

CA_AFTER=$(ca_fingerprint)
[ -n "$CA_BEFORE" ] && [ "$CA_BEFORE" = "$CA_AFTER" ] \
    && ok "CA chain identical after restore ($CA_AFTER) — agents stay trusted" \
    || bad "CA chain changed across restore: '$CA_BEFORE' -> '$CA_AFTER'"

echo ""
echo "backup_restore_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
