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
#       KEY: value) are found, in the logs and in sanitize_env; a key set twice
#       has both values masked (compose takes the last);
#   (c) a .env with a byte outside UTF-8 and a NUL byte, under the locale C.UTF-8:
#       sanitize_env masks the whole value and keeps every other byte, and the
#       value is masked in a log line, as is a query token with such a byte;
#   (d) no rule for ah_ keys any more: no token of the project carries that prefix,
#       (a) checks the forms they do take;
#   (e) main with a docker stub: report.txt and the logs in the bundle are redacted;
#       host names and addresses stay, and the closing message names --mask-hosts;
#       with --mask-hosts they are masked in report.txt and env.sanitized;
#   (f) --mask-hosts in the functions: IPv4 and IPv6 addresses become <ip>, one with
#       an IPv4 tail as a whole, the host values of the .env and the machine's name
#       <host>, env.sanitized shows those keys as <masked>; a time, a version number
#       and an image tag of four numbers stay;
#   (g) without the switch the same lines keep their names and addresses, the token
#       forms of (a) are masked;
#   (h) --help names --mask-hosts and says that of SMTP_FROM only the address in
#       angle brackets is masked, and ends with the usage line; an unknown
#       option still ends with 2;
#   (i) --mask-hosts, which values become <host> rules and how they match: the
#       longest first, at word edges; a name with a dot without regard to case and
#       with the names under it, one without a dot only in its spelling, as a whole
#       word (not in a service or image name) and with the domain behind it; of a
#       display name ("Name <address>") only the address, and no list part without
#       a letter or a digit; every part of a value, one in angle brackets and the
#       others, every mailbox of SMTP_FROM, and the first label of a machine name
#       with a dot unless it is digits only;
#   (j) SMTP_USER is masked like the passwords, with and without --mask-hosts, in
#       the logs and in sanitize_env, and only as a whole word;
#   (k) under the locale C.UTF-8, a key behind a BOM or Unicode whitespace and with
#       an NBSP before the separator is found, in the logs and in sanitize_env;
#       commented-out lines of a secret key are <redacted> in sanitize_env, of a host
#       key <masked> with --mask-hosts, and their values are no rules for the logs;
#   (l) .env values with escapes and over several lines, as compose reads them: in
#       the logs every line of such a value is masked, in both forms where the file
#       spells it otherwise, the longest value first (SMTP_USER too), a line of
#       whitespace only not at all (one of punctuation only is), and an assignment
#       of the key on a line a value runs on to as well; sanitize_env leaves out
#       the lines a value runs on to, to the end of the file without a closing
#       quote; under the locale C.UTF-8, an NBSP in front of a value and at the end
#       of an unquoted one is no part of it, one inside quotes is;
#   (m) main under umask 022: the bundle has mode 600, replaces a file under its
#       name instead of writing into it, and leaves no temp file, also when tar
#       fails, a link already holds the temp name (nothing is written through
#       it), the temp path leads out of the output dir through a linked dir or the
#       name turns into a dangling link just before the open (nothing is created); it
#       stays 0600 in a dir with a default ACL; no value of the .env stands in the
#       arguments of sed.
#
# Run: bash scripts/tests/diagnostics_test.sh   (needs bash, coreutils, tar, gzip
#      and the locale C.UTF-8: without it cases (c), (k) and the NBSP part of (l)
#      cannot run, and the test ends with 75)

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
# the .env the file form (pg$$9word). SECRET_KEY stands three times: compose takes
# the last line, an older value may still stand in a log, so every one is masked.
env_b="$tmp/.env-compose"
cat > "$env_b" <<'EOF'
SECRET_KEY=first9val
SMTP_PASSWORD='sq9pass'
POSTGRES_PASSWORD=pg$$9word
MONITOR_API_KEY="mon9key"
SECRET_KEY=sk9val #note
SECRET_KEY=last9val
EOF
sed_b="$tmp/redact-b.sed"
build_redaction_sedfile "$env_b" "$sed_b"
log_b="$(cat <<'EOF'
smtp: login to relay failed with sq9pass
db: connect user=adminhelper password=pg$9word
monitor: key mon9key rejected
app: signing with sk9val note
env: POSTGRES_PASSWORD=pg$$9word
app: old key first9val, new key last9val
EOF
)"
exp_b="$(cat <<'EOF'
smtp: login to relay failed with <redacted>
db: connect user=adminhelper password=<redacted>
monitor: key <redacted> rejected
app: signing with <redacted> note
env: POSTGRES_PASSWORD=<redacted>
app: old key <redacted>, new key <redacted>
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

# --- (f) --mask-hosts: names and addresses become <host> and <ip> -----------------
# The host values of the .env (a list split at ',', of a display name only the
# address in angle brackets) and the machine's name become <host>, every IPv4 and
# IPv6 address <ip>, one with an IPv4 tail as a whole; a time, a version, a MAC
# address and the tag of an image reference are no address. The token forms of (a)
# stay masked. uname is a function here, so the machine's name is known
# and cannot clash with the text.
# shellcheck disable=SC2317  # called by host_rules of the sourced script
uname() { if [ "${1:-}" = -n ]; then echo node9host; else command uname "$@"; fi; }
env_f="$tmp/.env-hosts"
cat > "$env_f" <<'EOF'
SECRET_KEY=hs9secret
DOMAIN=ah.example.com
EXTRA_SANS=alt.example.com,198.51.100.7
ALLOWED_IPS=203.0.113.0/24
SMTP_FROM="Ops9 <ops9@mail.example.com>"
# FRP_SERVER_ADDR=192.0.2.44
# old relay at 192.0.2.45
EOF
log_h="$(cat <<'EOF'
upstream [2001:db8::1]:8080
neighbour fe80::1 reachable
client 2001:db8:0:0:0:0:0:7 accepted, mac aa:bb:cc:dd:ee:ff
tls: certificate for ah.example.com and alt.example.com, peer 198.51.100.7
allow 203.0.113.0/24
10:00:00 nginx/1.27.3 ready
smtp: sending as ops9@mail.example.com on node9host
mapped ::ffff:192.0.2.1 seen
nat64 64:ff9b::198.51.100.7 seen
full 2001:db8:1:2:3:4:192.0.2.1 seen
long 0:0:0:0:0:ffff:203.0.113.5 seen
image myreg:5000/adminhelper/server:0.46.0.1 pulled
connect to 192.0.2.9:5432
EOF
)"
exp_f="$(cat <<'EOF'
<ip> - - [22/Oct/2026:10:00:00 +0000] "GET /api/connections?api_key=<redacted>&limit=50 HTTP/1.1" 200 512 "-" "curl/8.5.0"
INFO:     <ip>:51234 - "GET /api/connections?api_key=<redacted> HTTP/1.1" 200 OK
<ip> - - [22/Oct/2026:10:00:01 +0000] "POST /api/hooks/trigger/<redacted> HTTP/1.1" 202 18 "-" "curl/8.5.0"
INFO:     <ip>:51236 - "POST /api/hooks/trigger HTTP/1.1" 401 Unauthorized
<ip> - - [22/Oct/2026:10:00:02 +0000] "GET /api/sync?page_token=p2&ACCESS_TOKEN=<redacted> HTTP/1.1" 200 64 "https://<host>/x?token=<redacted>" "Mozilla/5.0"
provisioning: agent enrolled with adminhelper_prov_<redacted> from <ip>
upstream [<ip>]:8080
neighbour <ip> reachable
client <ip> accepted, mac aa:bb:cc:dd:ee:ff
tls: certificate for <host> and <host>, peer <ip>
allow <ip>
10:00:00 nginx/1.27.3 ready
smtp: sending as <host> on <host>
mapped <ip> seen
nat64 <ip> seen
full <ip> seen
long <ip> seen
image myreg:5000/adminhelper/server:0.46.0.1 pulled
connect to <ip>:5432
EOF
)"
sed_f="$tmp/redact-f.sed"
build_redaction_sedfile "$env_f" "$sed_f" 1
out_f="$(printf '%s\n%s\n' "$log_a" "$log_h" | redact "$sed_f")"
same "(f) --mask-hosts in the logs" "$exp_f" "$out_f" || fail=1
for leak in 203.0.113 192.0.2 198.51.100 2001:db8 fe80 example.com ops9 node9host 0123456789; do
    if has "$leak" "$out_f"; then
        echo "LEAK: (f) '$leak' survived --mask-hosts" >&2
        fail=1
    fi
done
# env.sanitized: the host keys by key, commented out too, an address in another
# comment by its shape.
exp_fs="$(cat <<'EOF'
SECRET_KEY=<redacted>
DOMAIN=<masked>
EXTRA_SANS=<masked>
ALLOWED_IPS=<masked>
SMTP_FROM=<masked>
# FRP_SERVER_ADDR=<masked>
# old relay at <ip>
EOF
)"
same "(f) --mask-hosts in sanitize_env" "$exp_fs" "$(sanitize_env "$env_f" 1)" || fail=1

# --- (g) without the switch: names and addresses stay -------------------------------
sed_g="$tmp/redact-g.sed"
build_redaction_sedfile "$env_f" "$sed_g" 0
out_g="$(printf '%s\n%s\n' "$log_a" "$log_h" | redact "$sed_g")"
same "(g) the logs without --mask-hosts" "$(printf '%s\n%s\n' "$exp_a" "$log_h")" "$out_g" || fail=1
exp_gs="$(sed 's/^SECRET_KEY=.*/SECRET_KEY=<redacted>/' "$env_f")"
same "(g) sanitize_env without --mask-hosts" "$exp_gs" "$(sanitize_env "$env_f" 0)" || fail=1

# --- (i) --mask-hosts: which values become <host> rules, and how they match ---------
# The longest rule first: ah.example.com goes whole, not as ah.<host> through the
# shorter example.com inside it. A rule ends at a word edge: the machine's name
# node9host leaves node9hostname alone.
env_i="$tmp/.env-order"
printf 'DOMAIN=ah.example.com\nEXTRA_SANS=example.com\n' > "$env_i"
sed_i="$tmp/redact-i.sed"
build_redaction_sedfile "$env_i" "$sed_i" 1
out_i="$(printf '%s\n' 'GET https://ah.example.com/ via example.com' 'node9hostname up' | redact "$sed_i")"
exp_i="$(printf '%s\n' 'GET https://<host>/ via <host>' 'node9hostname up')"
same "(i) the longest rule first, at word edges" "$exp_i" "$out_i" || fail=1
# Of a display name ("Name <address>", as in SMTP_FROM) only the address is a host
# value, its words are none; a list part without a letter or a digit (the lone "-")
# is none either. Either would turn words or every "-" of the bundle into <host>.
# Host names ignore case, the rules too: AH.Example.com masks ah.example.com.
env_j="$tmp/.env-display"
cat > "$env_j" <<'EOF'
SMTP_FROM="AdminHelper - Alerts <alerts@mail.example.com>"
EXTRA_SANS=alt.example.com , - ,198.51.100.7
DOMAIN=AH.Example.com
COMPOSE_PROJECT_NAME=ah-prod
EOF
log_j="$(cat <<'EOF'
2026-10-22T10:00:00Z adminhelper-server-1 COMPOSE_PROJECT_NAME=ah-prod a|b&c*d
mail to alerts@mail.example.com
GET https://ah.example.com/
EOF
)"
exp_j="$(cat <<'EOF'
2026-10-22T10:00:00Z adminhelper-server-1 COMPOSE_PROJECT_NAME=ah-prod a|b&c*d
mail to <host>
GET https://<host>/
EOF
)"
sed_j="$tmp/redact-j.sed"
build_redaction_sedfile "$env_j" "$sed_j" 1
same "(i) display name, list parts, case in the logs" "$exp_j" "$(printf '%s\n' "$log_j" | redact "$sed_j")" \
    || fail=1
exp_js="$(cat <<'EOF'
SMTP_FROM=<masked>
EXTRA_SANS=<masked>
DOMAIN=<masked>
COMPOSE_PROJECT_NAME=ah-prod
EOF
)"
same "(i) display name, list parts, case in sanitize_env" "$exp_js" "$(sanitize_env "$env_j" 1)" || fail=1
# Every part of a host value is a rule: one in angle brackets takes none of the others
# with it. SMTP_FROM is a list of mailboxes: of each the address, in angle brackets
# or bare, the display name in quotes stays, also with a comma in it and where the
# .env escapes its quotes (\" in double quotes). A machine name with a dot gives its
# first label as well: a log may name the machine short.
env_ia="$tmp/.env-every"
cat > "$env_ia" <<'EOF'
EXTRA_SANS=alt9.example.com <inner9.example.com> tail9.example.com
SMTP_FROM='"Ops9 Team" <ops9@mail.example.com>, dev9@mail.example.com'
SMTP_FROM="\"Ops8, Team\" <ops8@mail.example.com>"
EOF
log_ia="$(cat <<'EOF'
tls: names alt9.example.com, inner9.example.com and tail9.example.com
mail from "Ops9 Team" <ops9@mail.example.com> cc dev9@mail.example.com
{"from": "\"Ops8, Team\" <ops8@mail.example.com>"}
node9 started on node9.corp.example.org
EOF
)"
exp_ia="$(cat <<'EOF'
tls: names <host>, <host> and <host>
mail from "Ops9 Team" <<host>> cc <host>
{"from": "\"Ops8, Team\" <<host>>"}
<host> started on <host>
EOF
)"
sed_ia="$tmp/redact-ia.sed"
(
    # shellcheck disable=SC2317  # called by host_rules of the sourced script
    uname() { if [ "${1:-}" = -n ]; then echo node9.corp.example.org; else command uname "$@"; fi; }
    build_redaction_sedfile "$env_ia" "$sed_ia" 1
)
same "(i) every part of a host value, every mailbox, the short machine name" "$exp_ia" \
    "$(printf '%s\n' "$log_ia" | redact "$sed_ia")" || fail=1
# A name without a dot is often a word or the name of a service: it counts only in
# the spelling of uname -n and as a whole word, not as part of a name joined by '-',
# '.' or '_' nor as a path segment behind a word (.../server:), and a domain behind it
# goes with it, also one that holds the name again (server.server.example.org); two
# names in a row (serverserver) are one word. A name with a dot takes the names under
# it along. Of a machine name with a dot, a first label of digits only is no rule: it
# would take that number wherever it stands (192 of 192.0.2.5).
env_ib="$tmp/.env-edges"
printf 'DOMAIN=ah.example.com\n' > "$env_ib"
log_ib="$(cat <<'EOF'
adminhelper-server-1 started
image ghcr.io/admincave/adminhelper/server:0.46.0 pulled
Server started
GET http://server:8443/
server up
server server, xserverserver serverserver server_x restarted server.
peer server.server.example.org:8443 up
push to registry.ah.example.com:5000 done
node9.corp.example.org:443 reachable
queue 192 items at 10:00:00 on 192.0.2.5
EOF
)"
exp_ib="$(cat <<'EOF'
adminhelper-server-1 started
image ghcr.io/admincave/adminhelper/server:0.46.0 pulled
Server started
GET http://<host>:8443/
<host> up
<host> <host>, xserverserver serverserver server_x restarted <host>.
peer <host>:8443 up
push to <host>:5000 done
node9.corp.example.org:443 reachable
queue 192 items at 10:00:00 on <ip>
EOF
)"
# The other machine names leave the server lines alone.
exp_id="$(printf '%s\n' "$log_ib" | sed -e 's/registry\.ah\.example\.com/<host>/' -e 's/192\.0\.2\.5/<ip>/')"
exp_ic="$(printf '%s\n' "$exp_id" | sed -e 's/^node9\.corp\.example\.org:443/<host>:443/')"
sed_ib="$tmp/redact-ib.sed"
sed_ic="$tmp/redact-ic.sed"
sed_id="$tmp/redact-id.sed"
(
    node_i=server
    # shellcheck disable=SC2317  # called by host_rules of the sourced script
    uname() { if [ "${1:-}" = -n ]; then echo "$node_i"; else command uname "$@"; fi; }
    build_redaction_sedfile "$env_ib" "$sed_ib" 1
    node_i=node9
    build_redaction_sedfile "$env_ib" "$sed_ic" 1
    node_i=192.0.2.5
    build_redaction_sedfile "$env_ib" "$sed_id" 1
)
same "(i) a name without a dot as a whole word, in its spelling (uname -n = server)" "$exp_ib" \
    "$(printf '%s\n' "$log_ib" | redact "$sed_ib")" || fail=1
same "(i) a name without a dot with the domain behind it (uname -n = node9)" "$exp_ic" \
    "$(printf '%s\n' "$log_ib" | redact "$sed_ic")" || fail=1
same "(i) no rule for a first label of digits only (uname -n = 192.0.2.5)" "$exp_id" \
    "$(printf '%s\n' "$log_ib" | redact "$sed_id")" || fail=1

# --- (j) SMTP_USER: always masked like the passwords, as a whole word ---------------
# With some mail providers the SMTP user is itself an access token or a key ID, so no
# switch keeps it; with --mask-hosts it stays <redacted>, not <masked>. Its rule ends
# at word edges: a short user like admin must not eat into adminhelper.
env_u="$tmp/.env-smtpuser"
printf 'SMTP_USER=relay9user@mail.example.com\nA=keep9\n' > "$env_u"
exp_us="$(printf 'SMTP_USER=<redacted>\nA=keep9')"
for mask in 0 1; do
    sed_u="$tmp/redact-u$mask.sed"
    build_redaction_sedfile "$env_u" "$sed_u" "$mask"
    same "(j) SMTP_USER in the logs, mask_hosts=$mask" 'auth as <redacted> ok' \
        "$(printf '%s\n' 'auth as relay9user@mail.example.com ok' | redact "$sed_u")" || fail=1
    same "(j) SMTP_USER in sanitize_env, mask_hosts=$mask" "$exp_us" "$(sanitize_env "$env_u" "$mask")" || fail=1
done
printf 'SMTP_USER=admin\n' > "$env_u"
sed_u="$tmp/redact-u-short.sed"
build_redaction_sedfile "$env_u" "$sed_u"
log_u="$(printf '%s\n' 'adminhelper-server-1 started' 'login admin failed')"
same "(j) a short SMTP_USER as a whole word" "$(printf '%s\n' 'adminhelper-server-1 started' 'login <redacted> failed')" \
    "$(printf '%s\n' "$log_u" | redact "$sed_u")" || fail=1

# --- (k) a key behind a BOM or Unicode whitespace, commented-out lines, under C.UTF-8
# Compose reads a key behind a BOM or Unicode whitespace (NBSP, EM SPACE) and with an
# NBSP between key and separator: such a value is masked in the logs and in
# env.sanitized, and the line keeps its form up to the value. A commented-out line of
# a secret key keeps its form with the value <redacted>, one of a host key with
# --mask-hosts <masked>; its value is no rule for the logs, a commented-out line is no
# configuration. Held byte for byte (cmp) against files written apart with printf.
if [ -n "$LOCALE_SKIP" ]; then
    LOCALE_SKIP="$LOCALE_SKIP, and neither can case (k) (BOM and Unicode whitespace in .env)"
    echo "SKIP case (k) (BOM and Unicode whitespace in .env) needs the locale C.UTF-8 as well"
else
    env_uc="$tmp/.env-unicode"
    printf '\xef\xbb\xbfSECRET_KEY=bom9secret\n\xc2\xa0POSTGRES_PASSWORD=nbsp9secret\n\xe2\x80\x83MONITOR_API_KEY=em9secret\nADMIN_PASSWORD\xc2\xa0=sep9secret\n#ADMIN_PASSWORD=old9secret\n  # SMTP_PASSWORD = old9smtp\n#DOMAIN=old9.example.com\nA=keep9\n' > "$env_uc"
    printf '\xef\xbb\xbfSECRET_KEY=<redacted>\n\xc2\xa0POSTGRES_PASSWORD=<redacted>\n\xe2\x80\x83MONITOR_API_KEY=<redacted>\nADMIN_PASSWORD\xc2\xa0=<redacted>\n#ADMIN_PASSWORD=<redacted>\n  # SMTP_PASSWORD = <redacted>\n#DOMAIN=old9.example.com\nA=keep9\n' > "$tmp/k.san.exp"
    printf '\xef\xbb\xbfSECRET_KEY=<redacted>\n\xc2\xa0POSTGRES_PASSWORD=<redacted>\n\xe2\x80\x83MONITOR_API_KEY=<redacted>\nADMIN_PASSWORD\xc2\xa0=<redacted>\n#ADMIN_PASSWORD=<redacted>\n  # SMTP_PASSWORD = <redacted>\n#DOMAIN=<masked>\nA=keep9\n' > "$tmp/k.san1.exp"
    printf 'app: boot with bom9secret\ndb: auth nbsp9secret\nmonitor: key em9secret\nadmin: login sep9secret\nold: old9secret\n' > "$tmp/k.log"
    printf 'app: boot with <redacted>\ndb: auth <redacted>\nmonitor: key <redacted>\nadmin: login <redacted>\nold: old9secret\n' > "$tmp/k.log.exp"
    rc=0
    ( export LC_ALL=C.UTF-8
      sanitize_env "$env_uc" > "$tmp/k.san"
      sanitize_env "$env_uc" 1 > "$tmp/k.san1"
      build_redaction_sedfile "$env_uc" "$tmp/redact-k.sed"
      redact "$tmp/redact-k.sed" < "$tmp/k.log" > "$tmp/k.log.out" ) || rc=$?
    [ "$rc" = 0 ] || { echo "(k) the functions failed under C.UTF-8 (rc=$rc)" >&2; fail=1; }
    cmp -s "$tmp/k.san.exp" "$tmp/k.san" \
        || { echo "(k) sanitize_env under C.UTF-8: $(cat -v "$tmp/k.san" | tr '\n' ' ')" >&2; fail=1; }
    cmp -s "$tmp/k.san1.exp" "$tmp/k.san1" \
        || { echo "(k) sanitize_env --mask-hosts under C.UTF-8: $(cat -v "$tmp/k.san1" | tr '\n' ' ')" >&2; fail=1; }
    cmp -s "$tmp/k.log.exp" "$tmp/k.log.out" \
        || { echo "(k) log lines under C.UTF-8: $(cat -v "$tmp/k.log.out" | tr '\n' ' ')" >&2; fail=1; }
fi

# --- (l) values with escapes and over several lines, as compose reads them ---------
# In double quotes compose decodes \" \\ \n \t \$ and \0nnn, in single quotes \'; a
# quote behind a backslash does not end the value, and a value in quotes runs on over
# the lines to its closing quote. Every line of the value is a rule for the logs (a
# log line carries one line of it at most), and where the file spells the value
# otherwise, that form too: a copy of the .env in a log carries it. sanitize_env keeps
# the first line as KEY=<redacted> and leaves out the lines the value runs on to.
env_l="$tmp/.env-escapes"
cat > "$env_l" <<'EOF'
SECRET_KEY="ab\"cd9esc"
POSTGRES_PASSWORD="pq\\9bs"
MONITOR_API_KEY='sq\'9sq'
ADMIN_PASSWORD='ml9first
ml9second'
SMTP_PASSWORD="dq9first
dq9second"
CA_ROOT_PASSPHRASE="nl9first\nnl9second\ttab9\$dol9\0101oct9"
Z=after9
EOF
log_l="$(cat <<'EOF'
app: key ab"cd9esc
db: auth pq\9bs
monitor: key sq'9sq
admin: ml9first and ml9second
smtp: dq9first, dq9second
ca: nl9first
ca: nl9second<TAB>tab9$dol9Aoct9
env: SECRET_KEY="ab\"cd9esc" POSTGRES_PASSWORD="pq\\9bs" MONITOR_API_KEY='sq\'9sq'
env: CA_ROOT_PASSPHRASE="nl9first\nnl9second\ttab9\$dol9\0101oct9"
z: after9
EOF
)"
log_l="${log_l//<TAB>/$'\t'}"
exp_l="$(cat <<'EOF'
app: key <redacted>
db: auth <redacted>
monitor: key <redacted>
admin: <redacted> and <redacted>
smtp: <redacted>, <redacted>
ca: <redacted>
ca: <redacted>
env: SECRET_KEY="<redacted>" POSTGRES_PASSWORD="<redacted>" MONITOR_API_KEY='<redacted>'
env: CA_ROOT_PASSPHRASE="<redacted>"
z: after9
EOF
)"
sed_l="$tmp/redact-l.sed"
build_redaction_sedfile "$env_l" "$sed_l"
same "(l) escapes and lines of a value in the logs" "$exp_l" "$(printf '%s\n' "$log_l" | redact "$sed_l")" || fail=1
exp_ls="$(printf '%s\n' 'SECRET_KEY=<redacted>' 'POSTGRES_PASSWORD=<redacted>' 'MONITOR_API_KEY=<redacted>' \
    'ADMIN_PASSWORD=<redacted>' 'SMTP_PASSWORD=<redacted>' 'CA_ROOT_PASSPHRASE=<redacted>' 'Z=after9')"
same "(l) escapes and lines of a value in sanitize_env" "$exp_ls" "$(sanitize_env "$env_l")" || fail=1
# Without a closing quote the value runs on to the end of the file.
env_lo="$tmp/.env-open"
printf 'SECRET_KEY="open9first\nopen9second\n' > "$env_lo"
sed_lo="$tmp/redact-lo.sed"
build_redaction_sedfile "$env_lo" "$sed_lo"
same "(l) a value without its closing quote in the logs" "$(printf '%s\n' 'app: <redacted>' 'app: <redacted>')" \
    "$(printf '%s\n' 'app: open9first' 'app: open9second' | redact "$sed_lo")" || fail=1
same "(l) a value without its closing quote in sanitize_env" 'SECRET_KEY=<redacted>' "$(sanitize_env "$env_lo")" \
    || fail=1
# A host value over several lines, with --mask-hosts: each line gives its rules, and
# the line it runs on to goes from sanitize_env with the value.
env_lh="$tmp/.env-hostlines"
printf 'EXTRA_SANS="hl9a.example.com,\nhl9b.example.com"\nA=keep9\n' > "$env_lh"
sed_lh="$tmp/redact-lh.sed"
build_redaction_sedfile "$env_lh" "$sed_lh" 1
same "(l) a host value over several lines in the logs" 'san <host> <host>' \
    "$(printf '%s\n' 'san hl9a.example.com hl9b.example.com' | redact "$sed_lh")" || fail=1
same "(l) a host value over several lines in sanitize_env" "$(printf '%s\n' 'EXTRA_SANS=<masked>' 'A=keep9')" \
    "$(sanitize_env "$env_lh" 1)" || fail=1
# The rules run the longest value first and each value once: a line of a value (Pa,
# ml9) or the value of another key (pk9) inside a longer one does not cut it in two.
env_lr="$tmp/.env-order"
cat > "$env_lr" <<'EOF'
SECRET_KEY=pk9
ADMIN_PASSWORD="Pa\nPassphrase9Tail"
SMTP_PASSWORD="ml9
ml9-rest-of-secret"
POSTGRES_PASSWORD=pk9-db-secret
MONITOR_API_KEY=pk9-db-secret
EOF
sed_lr="$tmp/redact-lr.sed"
build_redaction_sedfile "$env_lr" "$sed_lr"
same "(l) the longest value first in the logs" \
    "$(printf '%s\n' 'auth: <redacted>' 'smtp: <redacted>' 'db: <redacted>' 'env: ADMIN_PASSWORD="<redacted>"')" \
    "$(printf '%s\n' 'auth: Passphrase9Tail' 'smtp: ml9-rest-of-secret' 'db: pk9-db-secret' \
        'env: ADMIN_PASSWORD="Pa\nPassphrase9Tail"' | redact "$sed_lr")" || fail=1
same "(l) each value one rule" "" "$(LC_ALL=C sort "$sed_lr" | LC_ALL=C uniq -d)" || fail=1
# SMTP_USER runs by its length as well: a secret inside the user (relay9) does not cut
# it in two. A value of SMTP_USER that is also one of another key is one rule, without
# word edges.
env_lu="$tmp/.env-userorder"
printf '%s\n' 'SECRET_KEY=relay9' 'SMTP_USER=dup9user' 'SMTP_USER=relay9user@mail.example.com' \
    'SMTP_PASSWORD=dup9user' > "$env_lu"
sed_lu="$tmp/redact-lu.sed"
build_redaction_sedfile "$env_lu" "$sed_lu"
same "(l) SMTP_USER by its length in the logs" \
    "$(printf '%s\n' 'auth as <redacted> ok' 'key <redacted>' 'smtp x<redacted>x')" \
    "$(printf '%s\n' 'auth as relay9user@mail.example.com ok' 'key relay9' 'smtp xdup9userx' | redact "$sed_lu")" \
    || fail=1
same "(l) a value of SMTP_USER and of another key one rule" 1 "$(grep -c dup9user "$sed_lu")" || fail=1
# A line of a value that is only whitespace (a space; a tab and an NBSP) is no rule: it
# holds no secret, and every blank of the logs would be masked. A value of punctuation
# only stays a rule.
env_lb="$tmp/.env-blank"
printf '%s\n' 'CA_ROOT_PASSPHRASE="first9part\n \nlast9part"' 'SMTP_PASSWORD="smtp9first' $'\t\xc2\xa0' \
    'smtp9last"' 'ADMIN_PASSWORD=!!!!!!!!' > "$env_lb"
sed_lb="$tmp/redact-lb.sed"
build_redaction_sedfile "$env_lb" "$sed_lb"
same "(l) a line of whitespace only in the logs" \
    "$(printf '%s\n' 'GET /x HTTP/1.1 Authorization: Bearer <redacted>' 'ca: <redacted>, <redacted>' \
        'smtp: <redacted> <redacted>' $'pad:\t\xc2\xa0end' 'admin: <redacted>')" \
    "$(printf '%s\n' 'GET /x HTTP/1.1 Authorization: Bearer abcdefgh12345678' 'ca: first9part, last9part' \
        'smtp: smtp9first smtp9last' $'pad:\t\xc2\xa0end' 'admin: !!!!!!!!' | redact "$sed_lb")" || fail=1
# Only the quotes of the key are followed: a line of the key may stand in the quoted
# value of another key (compose reads OTHER over three lines), and the value it opens
# runs on to a later assignment of the key; that assignment gives its value as well.
env_lq="$tmp/.env-otherquote"
printf '%s\n' "OTHER='line1" 'SECRET_KEY="fake' "line3'" 'SECRET_KEY=real9secret' > "$env_lq"
sed_lq="$tmp/redact-lq.sed"
build_redaction_sedfile "$env_lq" "$sed_lq"
same "(l) an assignment on a line a value runs on to in the logs" 'app: <redacted>' \
    "$(printf '%s\n' 'app: real9secret' | redact "$sed_lq")" || fail=1
same "(l) an assignment on a line a value runs on to in sanitize_env" \
    "$(printf '%s\n' "OTHER='line1" 'SECRET_KEY=<redacted>')" "$(sanitize_env "$env_lq")" || fail=1
# Under C.UTF-8: compose skips an NBSP between separator and value, and trims one
# from the end of an unquoted value; both values are masked without it. Inside quotes
# the NBSP is part of the value, and the rule masks it with the value. A value in
# quotes behind an NBSP runs on over the lines as well. Held byte for byte (cmp).
if [ -n "$LOCALE_SKIP" ]; then
    LOCALE_SKIP="$LOCALE_SKIP, and neither can the NBSP part of case (l)"
    echo "SKIP the NBSP part of case (l) needs the locale C.UTF-8 as well"
else
    env_ln="$tmp/.env-nbsp"
    printf 'SECRET_KEY=\xc2\xa0nbsp9front\nPOSTGRES_PASSWORD=nbsp9end\xc2\xa0\nMONITOR_API_KEY="\xc2\xa0nbsp9in\xc2\xa0"\nSMTP_PASSWORD=\xc2\xa0"nbq9first\nnbq9second"\nA=keep9\n' > "$env_ln"
    printf 'SECRET_KEY=\xc2\xa0<redacted>\nPOSTGRES_PASSWORD=<redacted>\nMONITOR_API_KEY=<redacted>\nSMTP_PASSWORD=\xc2\xa0<redacted>\nA=keep9\n' > "$tmp/l.san.exp"
    printf 'app: boot with nbsp9front.\ndb: auth nbsp9end ok\nmonitor: key \xc2\xa0nbsp9in\xc2\xa0.\nsmtp: nbq9first nbq9second\n' > "$tmp/l.log"
    printf 'app: boot with <redacted>.\ndb: auth <redacted> ok\nmonitor: key <redacted>.\nsmtp: <redacted> <redacted>\n' > "$tmp/l.log.exp"
    rc=0
    ( export LC_ALL=C.UTF-8
      sanitize_env "$env_ln" > "$tmp/l.san"
      build_redaction_sedfile "$env_ln" "$tmp/redact-ln.sed"
      redact "$tmp/redact-ln.sed" < "$tmp/l.log" > "$tmp/l.log.out" ) || rc=$?
    [ "$rc" = 0 ] || { echo "(l) the functions failed under C.UTF-8 (rc=$rc)" >&2; fail=1; }
    cmp -s "$tmp/l.san.exp" "$tmp/l.san" \
        || { echo "(l) sanitize_env with NBSP under C.UTF-8: $(cat -v "$tmp/l.san" | tr '\n' ' ')" >&2; fail=1; }
    cmp -s "$tmp/l.log.exp" "$tmp/l.log.out" \
        || { echo "(l) log lines with NBSP under C.UTF-8: $(cat -v "$tmp/l.log.out" | tr '\n' ' ')" >&2; fail=1; }
fi
unset -f uname

# --- (e) main: report.txt and the logs in the bundle are redacted -----------------
# A docker stub on PATH answers what main asks; `compose ps` lands in report.txt,
# `compose logs` in logs/server.log, each with a secret of the .env and a token form.
# `compose ps` also names an address and DOMAIN, and a uname stub gives the
# machine's name to report.txt: without --mask-hosts they stay, with it they go.
work="$tmp/main"
mkdir -p "$work/bin" "$work/out" "$work/x" "$work/out-mask" "$work/x-mask"
printf 'services: {}\n' > "$work/docker-compose.yml"
printf 'SECRET_KEY=rep9secret\nDOMAIN=ah.example.com\n' > "$work/.env"
cat > "$work/bin/docker" <<EOF
#!/usr/bin/env bash
case "\$*" in
    "compose ps --services") echo server ;;
    "compose ps") echo "server  up  rep9secret POST /api/hooks/trigger/$tok_hk"
                  echo "gateway  up  198.51.100.20 ah.example.com" ;;
    "compose logs --no-color --tail 300 server") echo "GET /api/x?api_key=$tok_ng uses rep9secret" ;;
esac
exit 0
EOF
cat > "$work/bin/uname" <<'EOF'
#!/usr/bin/env bash
case "$*" in
    -n) echo node9host ;;
    -a) echo "Linux node9host 6.1.0-test #1 SMP x86_64 GNU/Linux" ;;
    *) exit 1 ;;
esac
EOF
chmod +x "$work/bin/docker" "$work/bin/uname"
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
    grep -qxF 'gateway  up  198.51.100.20 ah.example.com' "$work/x/report.txt" \
        || { echo "(e) report.txt lost a name or an address without --mask-hosts" >&2; fail=1; }
    grep -qxF 'Linux node9host 6.1.0-test #1 SMP x86_64 GNU/Linux' "$work/x/report.txt" \
        || { echo "(e) report.txt lost the machine's name without --mask-hosts" >&2; fail=1; }
    grep -qxF 'DOMAIN=ah.example.com' "$work/x/env.sanitized" \
        || { echo "(e) env.sanitized masked DOMAIN without --mask-hosts" >&2; fail=1; }
    grep -qF -e '--mask-hosts' "$work/run.log" \
        || { echo "(e) the closing message does not name --mask-hosts" >&2; fail=1; }
fi

# The same main with --mask-hosts: the address, DOMAIN and the machine's name go
# from report.txt and env.sanitized, and the closing message no longer names the
# switch.
rc=0
( cd "$work" && PATH="$work/bin:$PATH" TMPDIR="$tmp" bash "$ROOT/scripts/diagnostics.sh" --mask-hosts \
    --output "$work/out-mask" ) > "$work/run-mask.log" 2>&1 || rc=$?
bundles=("$work"/out-mask/adminhelper-diagnostics-*.tar.gz)
if [ "$rc" != 0 ] || [ "${#bundles[@]}" != 1 ] || [ ! -f "${bundles[0]}" ]; then
    echo "(e) main --mask-hosts: exit $rc, bundles: ${bundles[*]}" >&2; sed 's/^/    | /' "$work/run-mask.log" >&2
    fail=1
elif ! tar -xzf "${bundles[0]}" -C "$work/x-mask"; then
    echo "(e) main --mask-hosts: bundle does not extract" >&2; fail=1
else
    grep -qxF 'gateway  up  <ip> <host>' "$work/x-mask/report.txt" \
        || { echo "(e) --mask-hosts: report.txt: $(cat "$work/x-mask/report.txt")" >&2; fail=1; }
    grep -qxF 'Linux <host> 6.1.0-test #1 SMP x86_64 GNU/Linux' "$work/x-mask/report.txt" \
        || { echo "(e) --mask-hosts: the machine's name in report.txt" >&2; fail=1; }
    grep -qxF 'DOMAIN=<masked>' "$work/x-mask/env.sanitized" \
        || { echo "(e) --mask-hosts: env.sanitized: $(cat "$work/x-mask/env.sanitized")" >&2; fail=1; }
    if grep -rq -e rep9secret -e 0123456789 -e 198.51.100.20 -e ah.example.com -e node9host "$work/x-mask"; then
        echo "LEAK: (e) a secret, a token, a name or an address survived --mask-hosts" >&2
        fail=1
    fi
    if grep -qF -e '--mask-hosts' "$work/run-mask.log"; then
        echo "(e) the closing message names --mask-hosts although it was given" >&2
        fail=1
    fi
fi

# --- (m) main: the bundle is 0600 and under its name only when whole --------------
# The stubs of (e) in a dir of its own, under umask 022. A date stub fixes the name,
# and a bundle of an earlier run lies there with mode 644: it is replaced by one with
# mode 600, and no temp file stays. A sed wrapper logs its arguments: no value of the
# .env stands in them, an argument stands in the process list of the host. Then the
# temp name is taken by a link before the bundle is written (a mktemp stub sets it),
# to a file and to a FIFO outside the output dir: the run fails at once (timeout
# guards a hang), nothing reaches the link's target, the earlier bundle stays as it
# was, and the link goes. Last a tar that fails: the earlier bundle stays as it was,
# and its temp file goes.
m="$tmp/m"
mkdir -p "$m/bin" "$m/out" "$m/x"
cp "$work/docker-compose.yml" "$m/"
cp "$work/bin/docker" "$work/bin/uname" "$m/bin/"
printf 'SECRET_KEY=rep9secret\nDOMAIN=ah.example.com\nEXTRA_SANS=argv9.example.com\nADMIN_PASSWORD=argv9secret\n' \
    > "$m/.env"
cat > "$m/bin/date" <<EOF
#!/usr/bin/env bash
[ "\$*" = '-u +%Y%m%dT%H%M%SZ' ] && { echo 20261022T100000Z; exit 0; }
exec "$(type -P date)" "\$@"
EOF
cat > "$m/bin/sed" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$m/sed-args.log"
exec "$(type -P sed)" "\$@"
EOF
chmod +x "$m/bin/date" "$m/bin/sed"
m_bundle="$m/out/adminhelper-diagnostics-20261022T100000Z.tar.gz"
printf 'old\n' > "$m_bundle"
chmod 644 "$m_bundle"
rc=0
( umask 022 && cd "$m" && PATH="$m/bin:$PATH" TMPDIR="$tmp" bash "$ROOT/scripts/diagnostics.sh" --mask-hosts \
    --output "$m/out" ) > "$m/run.log" 2>&1 || rc=$?
if [ "$rc" != 0 ]; then
    echo "(m) main: exit $rc" >&2; sed 's/^/    | /' "$m/run.log" >&2; fail=1
else
    m_mode="$(stat -c %a "$m_bundle")"
    [ "$m_mode" = 600 ] || { echo "(m) the bundle has mode $m_mode, expected 600" >&2; fail=1; }
    { tar -xzf "$m_bundle" -C "$m/x" && [ -f "$m/x/report.txt" ]; } 2>/dev/null \
        || { echo "(m) the bundle is no archive with report.txt" >&2; fail=1; }
    # The files in it were the running user's alone too (umask 077 in main).
    m_open="$(tar -tvzf "$m_bundle" 2>&1 | awk '$1 != "-rw-------" && $1 != "drwx------"')" || true
    [ -z "$m_open" ] || { echo "(m) entries of the bundle open to others: $m_open" >&2; fail=1; }
    m_left="$(ls -A "$m/out")"
    [ "$m_left" = "${m_bundle##*/}" ] || { echo "(m) the output dir holds: $(tr '\n' ' ' <<<"$m_left")" >&2; fail=1; }
fi
# The wrapper ran (else the search below proves nothing), and saw no value. The search
# is for argv9, the start of both values: a rule carries a name escaped
# (argv9\.example\.com), which a search for the name itself misses.
[ -s "$m/sed-args.log" ] || { echo "(m) the sed wrapper logged no call" >&2; fail=1; }
if grep -qF argv9 "$m/sed-args.log"; then
    echo "LEAK: (m) a value of the .env stood in the arguments of sed: $(grep -F argv9 "$m/sed-args.log")" >&2
    fail=1
fi

# cksum only on a regular file: a link to the FIFO under the bundle's name would block.
m_same() { [ ! -L "$m_bundle" ] && [ -f "$m_bundle" ] && [ "$(cksum < "$m_bundle")" = "$m_sum" ]; }
m_sum="$(cksum < "$m_bundle")"
mkdir -p "$m/bin-link" "$m/bin-tar"
cat > "$m/bin-link/mktemp" <<EOF
#!/usr/bin/env bash
case "\${!#}" in
    */.adminhelper-diagnostics-*)
        name="\$("$(type -P mktemp)" -u -- "\${!#}")" || exit 1
        ln -s -- "\$LINK_TO" "\$name" || exit 1
        printf '%s\n' "\$name" ;;
    *) exec "$(type -P mktemp)" "\$@" ;;
esac
EOF
chmod +x "$m/bin-link/mktemp"
: > "$m/outside"
mkfifo "$m/fifo"
for m_to in outside fifo; do
    rc=0
    ( umask 022 && cd "$m" && LINK_TO="$m/$m_to" PATH="$m/bin-link:$m/bin:$PATH" TMPDIR="$tmp" \
        timeout 30 bash "$ROOT/scripts/diagnostics.sh" --output "$m/out" ) > "$m/run-$m_to.log" 2>&1 || rc=$?
    case "$rc" in
        0) echo "(m) a link to the $m_to under the temp name: exit 0" >&2; fail=1 ;;
        124) echo "(m) a link to the $m_to under the temp name: the run hung" >&2; fail=1 ;;
    esac
    m_same || { echo "(m) a link to the $m_to under the temp name changed the earlier bundle" >&2; fail=1; }
    m_left="$(ls -A "$m/out")"
    [ "$m_left" = "${m_bundle##*/}" ] \
        || { echo "(m) a link to the $m_to left in the output dir: $(tr '\n' ' ' <<<"$m_left")" >&2; fail=1; }
done
[ ! -s "$m/outside" ] || { echo "(m) the bundle went into the target of a link under the temp name" >&2; fail=1; }

# A temp path that leads out of the output dir through a linked dir part: the file
# mktemp made there passes every check on the descriptor, so the run must stop on the
# dir itself. The stub's own link stays; nothing else may.
mkdir -p "$m/bin-dirlink" "$m/elsewhere"
ln -s -- "$m/elsewhere" "$m/out/.lnk"
cat > "$m/bin-dirlink/mktemp" <<EOF
#!/usr/bin/env bash
case "\${!#}" in
    */.adminhelper-diagnostics-*)
        base="\${!#}"; base="\${base##*/}"
        "$(type -P mktemp)" -- "$m/out/.lnk/\$base" ;;
    *) exec "$(type -P mktemp)" "\$@" ;;
esac
EOF
chmod +x "$m/bin-dirlink/mktemp"
rc=0
( umask 022 && cd "$m" && PATH="$m/bin-dirlink:$m/bin:$PATH" TMPDIR="$tmp" \
    timeout 30 bash "$ROOT/scripts/diagnostics.sh" --output "$m/out" ) > "$m/run-dirlink.log" 2>&1 || rc=$?
case "$rc" in
    0) echo "(m) a temp path through a linked dir: exit 0" >&2; fail=1 ;;
    124) echo "(m) a temp path through a linked dir: the run hung" >&2; fail=1 ;;
esac
grep -q '^\[diagnostics\] ERROR: ' "$m/run-dirlink.log" \
    || { echo "(m) a temp path through a linked dir: no ERROR line" >&2; fail=1; }
m_same || { echo "(m) a temp path through a linked dir changed the earlier bundle" >&2; fail=1; }
m_else="$(find "$m/elsewhere" -type f -size +0 | head -1)"
[ -z "$m_else" ] || { echo "(m) the bundle went through the linked dir: $m_else" >&2; fail=1; }
m_left="$(ls -A "$m/out" | LC_ALL=C sort | tr '\n' ' ')"
[ "$m_left" = ".lnk ${m_bundle##*/} " ] \
    || { echo "(m) a temp path through a linked dir left in the output dir: $m_left" >&2; fail=1; }
rm -f -- "$m/out/.lnk"

# The temp name swapped for a link to a path that does not exist, between the check
# that it is no link and its open (a function named [ under BASH_ENV): the open must
# not create that path, and the run stops.
cat > "$m/swap-env.sh" <<'EOF'
#!/usr/bin/env bash
# Sourced through BASH_ENV: right after the script's check that the temp name is no
# link, the name becomes a link to a path that does not exist yet (once).
[() {
  builtin [ "$@"; local rc=$?
  if [[ -n "${AH_TEST_SWAP_TO:-}" && $# -eq 4 && "$1" == '!' && "$2" == -L \
      && "$3" == */.adminhelper-* && ! -e "$AH_TEST_SWAP_MARK" ]]; then
    : > "$AH_TEST_SWAP_MARK"
    rm -f -- "$3" && ln -s -- "$AH_TEST_SWAP_TO" "$3"
  fi
  return $rc
}
EOF
rc=0
( umask 022 && cd "$m" && BASH_ENV="$m/swap-env.sh" AH_TEST_SWAP_TO="$m/created" AH_TEST_SWAP_MARK="$m/swapped" \
    PATH="$m/bin:$PATH" TMPDIR="$tmp" timeout 30 bash "$ROOT/scripts/diagnostics.sh" --output "$m/out" ) \
    > "$m/run-swap.log" 2>&1 || rc=$?
case "$rc" in
    0) echo "(m) a name swapped before the open: exit 0" >&2; fail=1 ;;
    124) echo "(m) a name swapped before the open: the run hung" >&2; fail=1 ;;
esac
[ -e "$m/swapped" ] || { echo "(m) a name swapped before the open: the swap did not happen" >&2; fail=1; }
{ [ ! -e "$m/created" ] && [ ! -L "$m/created" ]; } \
    || { echo "(m) the open created the target of a link swapped in before it" >&2; fail=1; }
m_same || { echo "(m) a name swapped before the open changed the earlier bundle" >&2; fail=1; }
m_left="$(ls -A "$m/out")"
[ "$m_left" = "${m_bundle##*/}" ] \
    || { echo "(m) a name swapped before the open left in the output dir: $(tr '\n' ' ' <<<"$m_left")" >&2; fail=1; }

# A default ACL on the output dir: the bundle is still 0600, its mode comes from
# mktemp. Without setfacl or ACL support the case says so and checks the mode alone.
mkdir -p "$m/acl"
m_acl_note=""
if ! command -v setfacl >/dev/null 2>&1; then
    m_acl_note="setfacl not installed"
elif ! m_acl_err="$(setfacl -d -m g::rwx,o::rwx "$m/acl" 2>&1)"; then
    m_acl_note="no ACL on $(df -T "$m/acl" | awk 'NR==2 {print $2}'): $m_acl_err"
fi
[ -z "$m_acl_note" ] || echo "NOTE: (m) the ACL case ran WITHOUT a default ACL ($m_acl_note); only the mode is checked"
rc=0
( umask 022 && cd "$m" && PATH="$m/bin:$PATH" TMPDIR="$tmp" bash "$ROOT/scripts/diagnostics.sh" \
    --output "$m/acl" ) > "$m/run-acl.log" 2>&1 || rc=$?
m_acl_bundle="$m/acl/${m_bundle##*/}"
[ "$rc" = 0 ] || { echo "(m) main into a dir with a default ACL: exit $rc" >&2; fail=1; }
[ "$(stat -c '%a' "$m_acl_bundle" 2>&1)" = 600 ] \
    || { echo "(m) the bundle in a dir with a default ACL has mode $(stat -c '%a' "$m_acl_bundle" 2>&1)" >&2; fail=1; }
[ -n "$m_acl_note" ] || getfacl -p "$m/acl" 2>/dev/null | grep -qx 'default:group::rwx' \
    || { echo "(m) the default ACL was not set on the output dir" >&2; fail=1; }

cat > "$m/bin-tar/tar" <<'EOF'
#!/usr/bin/env bash
printf 'part\n'
exit 1
EOF
chmod +x "$m/bin-tar/tar"
rc=0
( umask 022 && cd "$m" && PATH="$m/bin-tar:$m/bin:$PATH" TMPDIR="$tmp" bash "$ROOT/scripts/diagnostics.sh" \
    --output "$m/out" ) > "$m/run-tar.log" 2>&1 || rc=$?
[ "$rc" != 0 ] || { echo "(m) main with a failing tar: exit 0" >&2; fail=1; }
m_same || { echo "(m) a failing tar changed the earlier bundle" >&2; fail=1; }
m_left="$(ls -A "$m/out")"
[ "$m_left" = "${m_bundle##*/}" ] \
    || { echo "(m) a failing tar left in the output dir: $(tr '\n' ' ' <<<"$m_left")" >&2; fail=1; }

# --- (h) the switch in the usage ----------------------------------------------------
# The usage line is the last line --help prints: a range that ends too early loses it,
# one that ends too late prints code. Of SMTP_FROM with a display name only the address
# in angle brackets is masked, and the header says so (R-0804).
rc=0
help_out="$(bash "$ROOT/scripts/diagnostics.sh" --help 2>&1)" || rc=$?
[ "$rc" = 0 ] || { echo "(h) --help: exit $rc" >&2; fail=1; }
has '\[--mask-hosts\]' "$help_out" || { echo "(h) --help does not name --mask-hosts: $help_out" >&2; fail=1; }
has 'angle brackets' "$help_out" \
    || { echo "(h) --help does not say what of SMTP_FROM is masked: $help_out" >&2; fail=1; }
help_last="${help_out##*$'\n'}"
[ "$help_last" = '#   ./scripts/diagnostics.sh [--tail N] [--output DIR] [--mask-hosts]' ] \
    || { echo "(h) --help ends with: $help_last" >&2; fail=1; }
rc=0
bash "$ROOT/scripts/diagnostics.sh" --bogus > /dev/null 2>&1 || rc=$?
[ "$rc" = 2 ] || { echo "(h) --bogus: exit $rc, expected 2" >&2; fail=1; }

if [ "$fail" != 0 ]; then
    echo "diagnostics_test: FAILED" >&2
    exit 1
fi
if [ -n "$LOCALE_SKIP" ]; then
    echo "SKIP: $LOCALE_SKIP"
    exit 75
fi
echo "diagnostics_test: OK"
