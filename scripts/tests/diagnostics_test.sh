#!/usr/bin/env bash
#
# Hermetic test for the redaction in diagnostics.sh — no docker required. Sources
# the script (main is guarded) and checks that .env secret values and generic
# token shapes are masked, while non-secrets survive. Beyond that:
#   (a) access-log lines of the gateway (nginx combined) and the server (uvicorn):
#       api_key, token and access_token as query parameters, the token of a
#       /hooks/trigger/<token> path and adminhelper_prov_ tokens are masked; the
#       other query values and a /hooks/trigger without a token stay as they are;
#   (b) .env values in single quotes, in double quotes, with $$ and with an inline
#       comment are masked in the form compose reads them, $$ in its file form too;
#       keys written as compose also reads them (export KEY=, KEY = value,
#       KEY: value) are found, in the logs and in sanitize_env;
#   (c) a .env with a byte outside UTF-8 and a NUL byte, under the locale C.UTF-8:
#       sanitize_env masks the whole value and keeps every other byte, and the
#       value is masked in a log line, as is a query token with such a byte;
#   (d) no rule for ah_ keys any more: no token of the project carries that prefix,
#       (a) checks the forms they do take;
#   (e) main with a docker stub: report.txt and the logs in the bundle are redacted.
#
# Run: bash scripts/tests/diagnostics_test.sh   (needs bash, coreutils, tar, gzip
#      and the locale C.UTF-8: without it case (c) cannot run, and the test ends
#      with 75)

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

# same <case> <expected> <got> — the whole redacted text, with a diff when it differs:
# a token cut short or a neighbouring value eaten shows up, which a search for the
# token alone would miss.
same() {
    [ "$2" = "$3" ] && return 0
    echo "$1: redacted text differs (< expected, > got):" >&2
    diff <(printf '%s\n' "$2") <(printf '%s\n' "$3") >&2 || true
    return 1
}

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
input="$input Authorization: Bearer abcdefgh12345"
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
has 'Bearer <redacted>' "$out" || { echo "bearer not redacted" >&2; fail=1; }

# --- (a) the token forms of the access logs ---------------------------------------
# API keys and webhook tokens are token_urlsafe(32): 43 characters from A-Za-z0-9_-.
# These are invented, each with its own prefix and the digits 0123456789, so a rest
# of any of them in the output is found.
tok_ng='fakeNginxApiKey_0123456789-abcdefghijklmnop'
tok_uv='fakeUvicornApiKey_0123456789-abcdefghijklmn'
tok_hk='fakeHookToken_0123456789-abcdefghijklmnopqr'
tok_pv='fakeProvToken_0123456789-abcdefghijklmnopqr'
tok_tk='fakeQueryToken_0123456789-abcdefghijklmnopq'
tok_at='fakeAccessToken_0123456789-abcdefghijklmnop'
log_a="$(cat <<EOF
203.0.113.7 - - [22/Oct/2026:10:00:00 +0000] "GET /api/connections?api_key=$tok_ng&limit=50 HTTP/1.1" 200 512 "-" "curl/8.5.0"
INFO:     192.0.2.6:51234 - "GET /api/connections?api_key=$tok_uv HTTP/1.1" 200 OK
203.0.113.7 - - [22/Oct/2026:10:00:01 +0000] "POST /api/hooks/trigger/$tok_hk HTTP/1.1" 202 18 "-" "curl/8.5.0"
INFO:     192.0.2.6:51236 - "POST /api/hooks/trigger HTTP/1.1" 401 Unauthorized
198.51.100.4 - - [22/Oct/2026:10:00:02 +0000] "GET /api/sync?page_token=p2&ACCESS_TOKEN=$tok_at HTTP/1.1" 200 64 "https://ah.example.com/x?token=$tok_tk" "Mozilla/5.0"
provisioning: agent enrolled with adminhelper_prov_$tok_pv from 192.0.2.9
EOF
)"
exp_a="$(cat <<'EOF'
203.0.113.7 - - [22/Oct/2026:10:00:00 +0000] "GET /api/connections?api_key=<redacted>&limit=50 HTTP/1.1" 200 512 "-" "curl/8.5.0"
INFO:     192.0.2.6:51234 - "GET /api/connections?api_key=<redacted> HTTP/1.1" 200 OK
203.0.113.7 - - [22/Oct/2026:10:00:01 +0000] "POST /api/hooks/trigger/<redacted> HTTP/1.1" 202 18 "-" "curl/8.5.0"
INFO:     192.0.2.6:51236 - "POST /api/hooks/trigger HTTP/1.1" 401 Unauthorized
198.51.100.4 - - [22/Oct/2026:10:00:02 +0000] "GET /api/sync?page_token=p2&ACCESS_TOKEN=<redacted> HTTP/1.1" 200 64 "https://ah.example.com/x?token=<redacted>" "Mozilla/5.0"
provisioning: agent enrolled with adminhelper_prov_<redacted> from 192.0.2.9
EOF
)"
out_a="$(printf '%s\n' "$log_a" | redact "$sedfile")"
same "(a) access logs" "$exp_a" "$out_a" || fail=1
if has '0123456789' "$out_a"; then
    echo "LEAK: (a) a token or a rest of one survived redaction" >&2
    fail=1
fi

# --- (b) .env values in the form compose reads them -------------------------------
# Single quotes: literal; double quotes and unquoted: $$ is $; unquoted: the comment
# from " #" on is not part of the value. The log carries the compose form; a copy of
# the .env the file form (pg$$9word).
env_b="$tmp/.env-compose"
cat > "$env_b" <<'EOF'
SMTP_PASSWORD='sq9pass'
POSTGRES_PASSWORD=pg$$9word
MONITOR_API_KEY="mon9key"
SECRET_KEY=sk9val #note
EOF
sed_b="$tmp/redact-b.sed"
build_redaction_sedfile "$env_b" "$sed_b"
log_b="$(cat <<'EOF'
smtp: login to relay failed with sq9pass
db: connect user=adminhelper password=pg$9word
monitor: key mon9key rejected
app: signing with sk9val note
env: POSTGRES_PASSWORD=pg$$9word
EOF
)"
exp_b="$(cat <<'EOF'
smtp: login to relay failed with <redacted>
db: connect user=adminhelper password=<redacted>
monitor: key <redacted> rejected
app: signing with <redacted> note
env: POSTGRES_PASSWORD=<redacted>
EOF
)"
out_b="$(printf '%s\n' "$log_b" | redact "$sed_b")"
same "(b) .env values as compose reads them" "$exp_b" "$out_b" || fail=1
# The key forms compose reads besides KEY=value: a leading "export", whitespace
# around the separator, ':' as the separator, and all of them at once.
env_k="$tmp/.env-keyforms"
cat > "$env_k" <<'EOF'
export ADMIN_PASSWORD=ex9admin
CA_ROOT_PASSPHRASE = sp9phrase
SMTP_PASSWORD: co9lon
  export MONITOR_API_KEY : 'cb9combo'
NORMAL_VAR: notasecret
EOF
sed_k="$tmp/redact-k.sed"
build_redaction_sedfile "$env_k" "$sed_k"
out_k="$(printf '%s\n' 'admin: bootstrap with ex9admin' 'ca: unlock with sp9phrase' \
    'smtp: relay auth co9lon' 'monitor: key cb9combo' 'note: notasecret' | redact "$sed_k")"
exp_k="$(printf '%s\n' 'admin: bootstrap with <redacted>' 'ca: unlock with <redacted>' \
    'smtp: relay auth <redacted>' 'monitor: key <redacted>' 'note: notasecret')"
same "(b) key forms in the logs" "$exp_k" "$out_k" || fail=1

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
# The key forms of (b): the line keeps its form up to the value, the value goes.
exp_ks="$(cat <<'EOF'
export ADMIN_PASSWORD=<redacted>
CA_ROOT_PASSPHRASE = <redacted>
SMTP_PASSWORD: <redacted>
  export MONITOR_API_KEY : <redacted>
NORMAL_VAR: notasecret
EOF
)"
same "(b) key forms in sanitize_env" "$exp_ks" "$(sanitize_env "$env_k")" || fail=1

# --- (c) a byte outside UTF-8 and a NUL byte in .env, under C.UTF-8 ---------------
# grep takes a line with a byte the locale cannot decode for binary and leaves it
# out, a NUL byte the whole file; under UTF-8, sed's `.*` and `[^…]` stop in front
# of such a byte. The results are held byte for byte (cmp) against files written
# apart with printf, never read back from the output. Without C.UTF-8 the case
# cannot run, and the test then ends with 75.
LOCALE_SKIP=""
if [ "$(LC_ALL=C.UTF-8 locale charmap 2>/dev/null)" != UTF-8 ]; then
    LOCALE_SKIP="case (c) (bytes outside UTF-8 in .env) needs the locale C.UTF-8, this system has none"
    echo "SKIP $LOCALE_SKIP"
else
    env_c="$tmp/.env-bytes"
    printf 'X=caf\351\nY=a\0b\nPOSTGRES_PASSWORD=pg\351tail9secret\n' > "$env_c"
    printf 'X=caf\351\nY=a\0b\nPOSTGRES_PASSWORD=<redacted>\n' > "$tmp/c.san.exp"
    printf 'db: auth with pg\351tail9secret failed\nGET /api/x?token=ab\351cd9tok HTTP/1.1\n' > "$tmp/c.log"
    printf 'db: auth with <redacted> failed\nGET /api/x?token=<redacted> HTTP/1.1\n' > "$tmp/c.log.exp"
    rc=0
    ( export LC_ALL=C.UTF-8
      sanitize_env "$env_c" > "$tmp/c.san"
      build_redaction_sedfile "$env_c" "$tmp/redact-c.sed"
      redact "$tmp/redact-c.sed" < "$tmp/c.log" > "$tmp/c.log.out" ) || rc=$?
    [ "$rc" = 0 ] || { echo "(c) the functions failed under C.UTF-8 (rc=$rc)" >&2; fail=1; }
    cmp -s "$tmp/c.san.exp" "$tmp/c.san" \
        || { echo "(c) sanitize_env under C.UTF-8: $(cat -v "$tmp/c.san" | tr '\n' ' ')" >&2; fail=1; }
    cmp -s "$tmp/c.log.exp" "$tmp/c.log.out" \
        || { echo "(c) log lines under C.UTF-8: $(cat -v "$tmp/c.log.out" | tr '\n' ' ')" >&2; fail=1; }
fi

# --- (e) main: report.txt and the logs in the bundle are redacted -----------------
# A docker stub on PATH answers what main asks; `compose ps` lands in report.txt,
# `compose logs` in logs/server.log, each with a secret of the .env and a token form.
work="$tmp/main"
mkdir -p "$work/bin" "$work/out" "$work/x"
printf 'services: {}\n' > "$work/docker-compose.yml"
printf 'SECRET_KEY=rep9secret\n' > "$work/.env"
cat > "$work/bin/docker" <<EOF
#!/usr/bin/env bash
case "\$*" in
    "compose ps --services") echo server ;;
    "compose ps") echo "server  up  rep9secret POST /api/hooks/trigger/$tok_hk" ;;
    "compose logs --no-color --tail 300 server") echo "GET /api/x?api_key=$tok_ng uses rep9secret" ;;
esac
exit 0
EOF
chmod +x "$work/bin/docker"
rc=0
( cd "$work" && PATH="$work/bin:$PATH" TMPDIR="$tmp" bash "$ROOT/scripts/diagnostics.sh" --output "$work/out" ) \
    > "$work/run.log" 2>&1 || rc=$?
bundles=("$work"/out/adminhelper-diagnostics-*.tar.gz)
if [ "$rc" != 0 ] || [ "${#bundles[@]}" != 1 ] || [ ! -f "${bundles[0]}" ]; then
    echo "(e) main: exit $rc, bundles: ${bundles[*]}" >&2; sed 's/^/    | /' "$work/run.log" >&2; fail=1
elif ! tar -xzf "${bundles[0]}" -C "$work/x"; then
    echo "(e) main: bundle does not extract" >&2; fail=1
else
    grep -qxF 'server  up  <redacted> POST /api/hooks/trigger/<redacted>' "$work/x/report.txt" \
        || { echo "(e) report.txt not redacted: $(cat "$work/x/report.txt")" >&2; fail=1; }
    grep -qxF 'GET /api/x?api_key=<redacted> uses <redacted>' "$work/x/logs/server.log" \
        || { echo "(e) logs/server.log not redacted: $(cat "$work/x/logs/server.log")" >&2; fail=1; }
    if grep -rq -e rep9secret -e 0123456789 "$work/x"; then
        echo "LEAK: (e) a secret or a token survived in the bundle" >&2
        fail=1
    fi
fi

if [ "$fail" != 0 ]; then
    echo "diagnostics_test: FAILED" >&2
    exit 1
fi
if [ -n "$LOCALE_SKIP" ]; then
    echo "SKIP: $LOCALE_SKIP"
    exit 75
fi
echo "diagnostics_test: OK"
