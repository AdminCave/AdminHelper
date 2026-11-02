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
# R-0224: the restore reopens the transition of the certificate register, so its
# install time moves from the migration to the restore.
register_installed_at() {
    e2e_dc exec -T postgres sh -c \
        'PGPASSWORD=$POSTGRES_PASSWORD psql -h 127.0.0.1 -U adminhelper -d adminhelper -tAc "SELECT extract(epoch FROM installed_at)::bigint FROM certificate_register_state WHERE id = 1"' \
        2>/dev/null | tr -d '[:space:]'
}
INSTALLED_BEFORE=$(register_installed_at)
[ -n "$INSTALLED_BEFORE" ] && ok "read the install time of the register ($INSTALLED_BEFORE)" \
    || bad "could not read the install time of the register"

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

INSTALLED_AFTER=$(register_installed_at)
{ [ -n "$INSTALLED_BEFORE" ] && [ -n "$INSTALLED_AFTER" ] && [ "$INSTALLED_AFTER" -gt "$INSTALLED_BEFORE" ]; } \
    && ok "the restore reopened the register transition (install time $INSTALLED_BEFORE -> $INSTALLED_AFTER)" \
    || bad "the install time of the register did not move: '$INSTALLED_BEFORE' -> '$INSTALLED_AFTER'"

TOKEN2=$(e2e_admin_token)
SERVERS=$(curl -k -s -H "Authorization: Bearer $TOKEN2" "$E2E_SERVER_URL/api/servers" 2>/dev/null || echo "")
grep -q "dr-probe" <<<"$SERVERS" \
    && ok "server record survived the roundtrip (dr-probe present)" \
    || bad "server record LOST after restore"

CA_AFTER=$(ca_fingerprint)
[ -n "$CA_BEFORE" ] && [ "$CA_BEFORE" = "$CA_AFTER" ] \
    && ok "CA chain identical after restore ($CA_AFTER) — agents stay trusted" \
    || bad "CA chain changed across restore: '$CA_BEFORE' -> '$CA_AFTER'"

# ── Restore on an empty host, COMPOSE_PROJECT_NAME only in the .env (R-0665) ──
# An install directory of its own named unlike the project: restore.sh must take the
# project (the volume prefix) and the .env from the backup, with nothing exported.
INST="$E2E_WORK/dr-host"
# Created up front so docker does not create them as root; the restore still hands
# ./data to the container user, so the section empties it in a container at its end.
mkdir -p "$INST/scripts" "$INST/data" "$INST/repo"
cp "$E2E_REPO_ROOT/docker-compose.yml" "$E2E_REPO_ROOT/docker-compose.test.yml" "$INST/"
cp "$E2E_REPO_ROOT/scripts/backup.sh" "$E2E_REPO_ROOT/scripts/restore.sh" "$INST/scripts/"
{ cat "$E2E_WORK/.env"; echo "COMPOSE_PROJECT_NAME=$E2E_PROJECT"; echo "COMPOSE_FILE=docker-compose.yml:docker-compose.test.yml"; } > "$INST/.env"
chmod 600 "$INST/.env"
# in_inst <cmd…> — run in $INST with none of the variables this test exported.
in_inst() {
    (cd "$INST" && env -i PATH="$PATH" HOME="$HOME" ${DOCKER_HOST:+DOCKER_HOST="$DOCKER_HOST"} \
        ${DOCKER_CONTEXT:+DOCKER_CONTEXT="$DOCKER_CONTEXT"} "$@")
}
mkdir -p "$E2E_WORK/bk2"
in_inst ./scripts/backup.sh --output "$E2E_WORK/bk2" >"$E2E_WORK/backup2.log" 2>&1 \
    && ok "empty host: backup.sh from the install directory completed" \
    || { bad "empty host: backup.sh failed"; tail -15 "$E2E_WORK/backup2.log" >&2; }
BK2=$(ls "$E2E_WORK"/bk2/*.tar.gz 2>/dev/null | head -1)
in_inst docker compose down -v >/dev/null 2>&1
rm -f "$INST/.env"
if [ -n "$BK2" ] && in_inst ./scripts/restore.sh "$BK2" --yes >"$E2E_WORK/restore2.log" 2>&1; then
    ok "empty host: restore.sh without .env completed"
else
    bad "empty host: restore.sh failed"; tail -20 "$E2E_WORK/restore2.log" >&2
fi
{ [ -n "$BK2" ] && tar xzf "$BK2" -O ./env.sanitized; echo 'CA_ROOT_PASSPHRASE='; } > "$E2E_WORK/expected.env" 2>/dev/null
{ [ -f "$INST/.env" ] && [ "$(stat -c '%a' "$INST/.env")" = 600 ] && cmp -s "$E2E_WORK/expected.env" "$INST/.env"; } \
    && ok "empty host: .env is env.sanitized of the backup plus CA_ROOT_PASSPHRASE=, 0600" \
    || bad "empty host: .env missing, not 0600 or not the one of the backup"
! docker volume inspect "dr-host_ca-pki" >/dev/null 2>&1 \
    && ok "empty host: no volume named after the directory (dr-host_ca-pki)" \
    || bad "empty host: restore.sh wrote volumes of the directory name"
code=000
for _ in $(seq 1 60); do
    code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 3 "$E2E_SERVER_URL/" 2>/dev/null || echo 000)
    [ "$code" != "000" ] && break
    sleep 2
done
TOKEN3=$(e2e_admin_token)
curl -k -s -H "Authorization: Bearer $TOKEN3" "$E2E_SERVER_URL/api/servers" 2>/dev/null | grep -q "dr-probe" \
    && ok "empty host: server record back (dr-probe present)" \
    || bad "empty host: server record LOST"
CA_EMPTY=$(ca_fingerprint)
[ -n "$CA_BEFORE" ] && [ "$CA_BEFORE" = "$CA_EMPTY" ] \
    && ok "empty host: CA chain identical ($CA_EMPTY)" \
    || bad "empty host: CA chain changed: '$CA_BEFORE' -> '$CA_EMPTY'"
docker volume rm "dr-host_ca-pki" >/dev/null 2>&1 || true
HELPER_IMAGE=$(in_inst docker compose -f docker-compose.yml config --images postgres </dev/null 2>/dev/null)
docker run --rm --network none --entrypoint find -v "$INST/data:/dst" "$HELPER_IMAGE" /dst -mindepth 1 -delete >/dev/null 2>&1
[ -z "$(ls -A "$INST/data" 2>/dev/null)" ] && ok "empty host: ./data emptied for the teardown" \
    || bad "empty host: ./data of the restore could not be emptied (the teardown leaves $INST)"

echo ""
echo "backup_restore_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
