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

# has <pattern> <text> — grep -q over the text without a pipe. In `printf | grep -q`
# under pipefail, grep may stop at a match before printf is done writing; printf then
# dies of SIGPIPE (141) and the pipeline reads as no match (R-0264).
has() { grep -q -- "$1" <<<"$2"; }

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

# has() itself: a match in the first line of more than a pipe holds, where the pipe
# form ends with 141 every time.
big="$(printf 'first\n'; head -c 300000 /dev/zero | tr '\0' x)"
has '^first$' "$big" || { echo "has() missed a match in front of a large text" >&2; fail=1; }

# Secret values must be gone.
for leak in topsecret123value pgpw456word mon789key smtprelay999pw; do
    if has "$leak" "$out"; then
        echo "LEAK: secret '$leak' survived redaction" >&2
        fail=1
    fi
done

# Non-secret values must survive.
has 'example.com' "$out" || { echo "non-secret was over-redacted" >&2; fail=1; }

# Generic token shapes must be masked.
has '<redacted>' "$out" || { echo "missing <redacted> marker" >&2; fail=1; }
has '<redacted-jwt>' "$out" || { echo "JWT not redacted" >&2; fail=1; }
has 'ah_<redacted>' "$out" || { echo "ah_ key not redacted" >&2; fail=1; }
has 'Bearer <redacted>' "$out" || { echo "bearer not redacted" >&2; fail=1; }

# --- sanitize_env: the second, independent redaction path (env.sanitized) (6.65) ---
# Untested before; if it broke (extending SECRET_KEYS, a bad IFS='|' join) .env cleartext
# secrets would land in a bundle advertised as issue-safe while the test stayed green.
env2="$tmp/.env-sanitize"
cat > "$env2" <<'EOF'
SECRET_KEY=supersecret111
POSTGRES_PASSWORD=pgpass222
  ADMIN_PASSWORD=indented333
NORMAL_VAR=notasecret
EOF
sanitized="$(sanitize_env "$env2")"
for leak in supersecret111 pgpass222 indented333; do
    has "$leak" "$sanitized" && { echo "LEAK: '$leak' survived sanitize_env" >&2; fail=1; }
done
has '^SECRET_KEY=<redacted>' "$sanitized" || { echo "SECRET_KEY not masked by sanitize_env" >&2; fail=1; }
has '^  ADMIN_PASSWORD=<redacted>' "$sanitized" || { echo "indented key not masked" >&2; fail=1; }
has 'NORMAL_VAR=notasecret' "$sanitized" || { echo "non-secret var dropped/masked" >&2; fail=1; }

if [ "$fail" = 0 ]; then
    echo "diagnostics_test: OK"
else
    echo "diagnostics_test: FAILED" >&2
    exit 1
fi
