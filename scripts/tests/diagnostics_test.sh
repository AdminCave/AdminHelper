#!/usr/bin/env bash
#
# Hermetic test for the redaction in diagnostics.sh — no docker required. Sources
# the script (main is guarded) and checks that .env secret values and generic
# token shapes are masked, while non-secrets survive.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/diagnostics.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/.env" <<'EOF'
SECRET_KEY=topsecret123value
POSTGRES_PASSWORD=pgpw456word
MONITOR_API_KEY=mon789key
SMTP_PASSWORD=smtprelay999pw
ADMIN_PASSWORD=
DOMAIN=example.com
EOF

sedfile="$tmp/redact.sed"
build_redaction_sedfile "$tmp/.env" "$sedfile"

input='SECRET_KEY=topsecret123value pw=pgpw456word mon=mon789key smtp=smtprelay999pw host=example.com'
input="$input Authorization: Bearer abcdefgh12345 key ah_aBcDeFgH1234"
input="$input jwt eyJhbGciOi.eyJzdWIiOiJ.sigpart"
out="$(printf '%s\n' "$input" | redact "$sedfile")"

fail=0

# Secret values must be gone.
for leak in topsecret123value pgpw456word mon789key smtprelay999pw; do
    if printf '%s' "$out" | grep -q "$leak"; then
        echo "LEAK: secret '$leak' survived redaction" >&2
        fail=1
    fi
done

# Non-secret values must survive.
printf '%s' "$out" | grep -q 'example.com' || { echo "non-secret was over-redacted" >&2; fail=1; }

# Generic token shapes must be masked.
printf '%s' "$out" | grep -q '<redacted>' || { echo "missing <redacted> marker" >&2; fail=1; }
printf '%s' "$out" | grep -q '<redacted-jwt>' || { echo "JWT not redacted" >&2; fail=1; }
printf '%s' "$out" | grep -q 'ah_<redacted>' || { echo "ah_ key not redacted" >&2; fail=1; }
printf '%s' "$out" | grep -q 'Bearer <redacted>' || { echo "bearer not redacted" >&2; fail=1; }

if [ "$fail" = 0 ]; then
    echo "diagnostics_test: OK"
else
    echo "diagnostics_test: FAILED" >&2
    exit 1
fi
