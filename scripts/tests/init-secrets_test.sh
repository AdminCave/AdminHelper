#!/usr/bin/env bash
#
# init-secrets_test.sh — hermetic test for scripts/init-secrets.sh.
#
# Pure .env manipulation (openssl-generated secrets + upsert), no docker. Covers:
# fresh generation, idempotence (a re-run leaves existing secrets stable — the
# POSTGRES_PASSWORD stability the stale-volume auth guard depends on), placeholder
# replacement, and quoted-value recognition (audit 6.71).
#
# Run: bash scripts/tests/init-secrets_test.sh   (needs bash, openssl, coreutils)

# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
INIT="$REPO_ROOT/scripts/init-secrets.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

val() { grep -E "^$1=" "$2" | head -1 | sed -E "s/^$1=//; s/^\"//; s/\"\$//"; }

# ── 1. fresh generation: empty secrets get 64-hex values ─────────────────────
ENV="$WORK/env1"
printf 'SECRET_KEY=\nMONITOR_API_KEY=\nPOSTGRES_PASSWORD=\nCA_ROOT_PASSPHRASE=\nDOMAIN=localhost\n' > "$ENV"
bash "$INIT" "$ENV" >/dev/null 2>&1
allgen=1
for k in SECRET_KEY MONITOR_API_KEY POSTGRES_PASSWORD CA_ROOT_PASSPHRASE; do
  v=$(val "$k" "$ENV"); [ "${#v}" -eq 64 ] || allgen=0
done
[ "$allgen" = 1 ] && ok "fresh: all four secrets generated (64-hex)" || bad "fresh generation incomplete"
[ "$(val DOMAIN "$ENV")" = "localhost" ] && ok "unrelated key (DOMAIN) untouched" || bad "DOMAIN mutated"

# ── 2. idempotence: a second run leaves the existing secrets stable ──────────
before=$(val POSTGRES_PASSWORD "$ENV")
bash "$INIT" "$ENV" >/dev/null 2>&1
after=$(val POSTGRES_PASSWORD "$ENV")
{ [ -n "$before" ] && [ "$before" = "$after" ]; } \
  && ok "idempotent: POSTGRES_PASSWORD stable across re-run" || bad "POSTGRES_PASSWORD changed on re-run (stale-volume risk)"
[ "$(grep -c '^POSTGRES_PASSWORD=' "$ENV")" -eq 1 ] && ok "no duplicate key line" || bad "duplicate POSTGRES_PASSWORD lines"

# ── 3. placeholder is treated as unset and replaced ──────────────────────────
ENV="$WORK/env2"
printf 'SECRET_KEY=change-me-in-production\nMONITOR_API_KEY=x\nPOSTGRES_PASSWORD=x\nCA_ROOT_PASSPHRASE=x\n' > "$ENV"
bash "$INIT" "$ENV" >/dev/null 2>&1
v=$(val SECRET_KEY "$ENV")
{ [ "$v" != "change-me-in-production" ] && [ "${#v}" -eq 64 ]; } \
  && ok "placeholder SECRET_KEY replaced" || bad "placeholder not replaced: $v"

# ── 4. quoted value counts as set (not regenerated) ──────────────────────────
ENV="$WORK/env3"
printf 'SECRET_KEY="already-quoted-secret-value"\nMONITOR_API_KEY=y\nPOSTGRES_PASSWORD=y\nCA_ROOT_PASSPHRASE=y\n' > "$ENV"
bash "$INIT" "$ENV" >/dev/null 2>&1
grep -q '^SECRET_KEY="already-quoted-secret-value"' "$ENV" \
  && ok "quoted existing value left alone" || bad "quoted value regenerated"

echo
echo "──────────────────────────────────────────"
echo "  init-secrets_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
