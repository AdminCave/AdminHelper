#!/bin/sh
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# frps-supervisor.sh — starts frps only from a configuration that passed every check.
#
# The input, frps.toml from the server and the TLS material from the ca-issuer, lives in
# volumes other containers write. A candidate is copied into next/ of the supervisor's own
# working directory (FRPS_ACTIVE_DIR, mounted by frps alone), checked there, its TLS paths
# pointed at current/, and swapped in as current/. frps always runs from current/, so a
# half-written or invalid input never reaches it:
#
#   valid                        frps starts from the new current/          running
#   invalid, current/ exists     frps starts from the last valid current/   degraded
#   invalid, no current/         nothing starts                             waiting
#   frps.toml missing or empty   current/ is removed, nothing starts        stopped
#     (and no current/ to remove)                                           waiting
#
# The state goes to $FRPS_STATE_DIR/status.json; its format is the contract the server reads,
# apps/server/app/modules/frp/supervisor_status.py. Log lines carry codes and paths, never
# the token.

set -u
export LC_ALL=C
umask 077

FRPS_CONFIG="${FRPS_CONFIG:-/etc/frp/frps.toml}"
FRPS_PKI_DIR="${FRPS_PKI_DIR:-/etc/frp-pki}"
FRPS_ACTIVE_DIR="${FRPS_ACTIVE_DIR:-/var/lib/frps-active}"
FRPS_STATE_DIR="${FRPS_STATE_DIR:-/var/lib/frps-state}"
FRPS_BIN="${FRPS_BIN:-frps}"

NEXT="$FRPS_ACTIVE_DIR/next"
CURRENT="$FRPS_ACTIVE_DIR/current"
PREV="$FRPS_ACTIVE_DIR/prev"
STATUS="$FRPS_STATE_DIR/status.json"
PEMS="frps.crt frps.key ca.crt"
# The only top-level keys frps gets: those config_generator.py writes, then a few for
# extra_config (frps 0.69.1 field names, none of them a listener).
TOP_KEYS="bindPort vhostHTTPSPort subDomainHost maxPortsPerClient detailedErrorsToClient
    webServer.addr webServer.port webServer.user webServer.password auth.method auth.token
    transport.maxPoolCount transport.tcpMux transport.tcpMuxKeepaliveInterval
    transport.heartbeatTimeout transport.tcpKeepalive userConnTimeout log.level log.maxDays"

log() { echo "[frps-supervisor] $*"; }

die() {
    log "error: $*" >&2
    exit 1
}

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

is_hash() { printf '%s' "$1" | grep -Eqx '[0-9a-f]{64}'; }

# content_hash <file>... — one sha256 over the contents of the files; a missing one counts too.
content_hash() {
    for file in "$@"; do
        if [ -f "$file" ]; then sha256sum < "$file"; else echo -; fi
    done | cut -d ' ' -f 1 | sha256sum | cut -d ' ' -f 1
}

# check_config <toml> — prints the first rule the file breaks as a reason code, or none.
#
# Only the layout the server generates passes (config_generator.py), so that frps reads the
# file exactly as these line checks do: every line is empty, the one table [transport.tls], or
# `key = value` with true, false, a number or a one-line string without quotes, backslashes
# or braces; every key once per table, in any case; no control characters. At top level only
# the keys in TOP_KEYS, compared exactly, and bindPort among them; webServer.port neither 443
# nor bindPort. Anything else is verify_failed. Then: at top level auth.method "token", a token
# of at least 16 characters and no other auth key, and a [transport.tls] table with nothing
# but force = true and the three files in FRPS_PKI_DIR.
check_config() {
    # NUL included, at which some awks split a line.
    if [ "$(tr -d '\n\040-\176\200-\377' < "$1" | wc -c)" -ne 0 ]; then
        echo verify_failed
        return
    fi
    PKI="$FRPS_PKI_DIR" TOP_KEYS="$TOP_KEYS" awk '
        BEGIN {
            n = split(ENVIRON["TOP_KEYS"], keys, " ")
            for (i = 1; i <= n; i++) top[keys[i]] = 1
        }
        $0 == "" { next }
        $0 == "[transport.tls]" {
            if (table != "") bad = 1
            table = $0
            next
        }
        index($0, "{") || index($0, "}") || index($0, "\\") ||
            $0 !~ /^[A-Za-z][A-Za-z0-9_.-]* = (true|false|[-+0-9.eE]+|"[^"]*")$/ {
            bad = 1
            next
        }
        {
            key = substr($0, 1, index($0, " = ") - 1)
            value = substr($0, length(key) + 4)
            if ((table, tolower(key)) in seen) bad = 1
            seen[table, tolower(key)] = 1
            if (table == "") {
                if (key == "auth.method") method = value
                else if (key == "auth.token") token = (value ~ /^"/ && length(value) - 2 >= 16)
                else if (key == "auth" || index(key, "auth.") == 1) other_auth = 1
                else if (!(key in top)) bad = 1
                if (key == "bindPort") bind_port = value
                if (key == "webServer.port") web_port = value
                next
            }
            pki = ENVIRON["PKI"]
            if (key == "force") forced = (value == "true")
            else if (key == "certFile") crt = (value == "\"" pki "/frps.crt\"")
            else if (key == "keyFile") pkey = (value == "\"" pki "/frps.key\"")
            else if (key == "trustedCaFile") ca = (value == "\"" pki "/ca.crt\"")
            else bad = 1
        }
        END {
            # Numbers, since frps reads +443.0 as 443 as well.
            if (bind_port == "") bad = 1
            if (web_port != "" && (web_port + 0 == 443 || web_port + 0 == bind_port + 0)) bad = 1
            if (bad) print "verify_failed"
            else if (method != "\"token\"" || !token || other_auth) print "token_invalid"
            else if (!forced) print "tls_not_forced"
            else if (!crt || !pkey || !ca) print "cert_paths"
            else print "none"
        }
    ' "$1"
}

# pem_intact <file> — the first certificate parses and no PEM block in the file is cut short.
pem_intact() {
    openssl x509 -noout -in "$1" >/dev/null 2>&1 &&
        openssl crl2pkcs7 -nocrl -certfile "$1" -out /dev/null >/dev/null 2>&1
}

# point_at_current <toml> — rewrites the three TLS paths of a checked file to current/.
point_at_current() {
    CUR="$CURRENT" awk '
        /^\[/ { table = $0 }
        table == "[transport.tls]" {
            cur = ENVIRON["CUR"]
            if (index($0, "certFile = ") == 1) $0 = "certFile = \"" cur "/frps.crt\""
            if (index($0, "keyFile = ") == 1) $0 = "keyFile = \"" cur "/frps.key\""
            if (index($0, "trustedCaFile = ") == 1) $0 = "trustedCaFile = \"" cur "/ca.crt\""
        }
        { print }
    ' "$1" > "$1.new" && mv -f "$1.new" "$1"
}

# stage — copies the input into next/ and checks the copy, so what is checked is what runs.
# Sets REASON (none, or the code of the first failed check) and CANDIDATE_HASH (over the
# copied input; empty without a frps.toml). A valid candidate is left in next/, ready for
# activate, with its TLS paths pointed at current/.
stage() {
    CANDIDATE_HASH=""
    rm -rf "$NEXT"
    mkdir "$NEXT" || die "cannot create $NEXT"
    if ! { [ -f "$FRPS_CONFIG" ] && cp "$FRPS_CONFIG" "$NEXT/frps.toml" 2>/dev/null; } \
        || [ ! -s "$NEXT/frps.toml" ]; then
        REASON=config_missing
        return
    fi
    for pem in $PEMS; do
        [ -f "$FRPS_PKI_DIR/$pem" ] && cp "$FRPS_PKI_DIR/$pem" "$NEXT/$pem" 2>/dev/null
    done
    CANDIDATE_HASH=$(content_hash "$NEXT/frps.toml" "$NEXT/frps.crt" "$NEXT/frps.key" "$NEXT/ca.crt")

    REASON=$(check_config "$NEXT/frps.toml") || die "cannot read $NEXT/frps.toml"
    [ "$REASON" = none ] || return
    for pem in $PEMS; do
        if [ ! -s "$NEXT/$pem" ]; then
            REASON=cert_missing
            return
        fi
    done
    if ! pem_intact "$NEXT/frps.crt" || ! pem_intact "$NEXT/ca.crt"; then
        REASON=cert_missing
        return
    fi
    if ! openssl x509 -checkend 0 -noout -in "$NEXT/frps.crt" >/dev/null 2>&1; then
        REASON=cert_expired
        return
    fi
    leaf_key=$(openssl x509 -noout -pubkey -in "$NEXT/frps.crt" 2>/dev/null)
    own_key=$(openssl pkey -pubout -passin pass: -in "$NEXT/frps.key" 2>/dev/null)
    if [ -z "$own_key" ] || [ "$leaf_key" != "$own_key" ]; then
        REASON=cert_key_mismatch
        return
    fi
    point_at_current "$NEXT/frps.toml" || die "cannot rewrite $NEXT/frps.toml"
    # frps verify passes an empty file and missing certificates, hence the checks above. Its
    # output is dropped: an error message may quote a value from the file.
    if ! "$FRPS_BIN" verify -c "$NEXT/frps.toml" >/dev/null 2>&1; then
        REASON=verify_failed
        return
    fi
    printf '%s\n' "$CANDIDATE_HASH" > "$NEXT/applied.sha256" || die "cannot write $NEXT"
}

# activate — swaps next/ in as current/. Two renames: a crash between them leaves prev/,
# which recover renames back on the next start.
activate() {
    rm -rf "$PREV"
    if [ -d "$CURRENT" ]; then
        mv "$CURRENT" "$PREV" || return 1
    fi
    if ! mv "$NEXT" "$CURRENT"; then
        [ -d "$PREV" ] && mv "$PREV" "$CURRENT"
        return 1
    fi
    rm -rf "$PREV"
}

recover() {
    if [ ! -d "$CURRENT" ] && [ -d "$PREV" ]; then
        mv "$PREV" "$CURRENT" || die "cannot restore $CURRENT"
    fi
    rm -rf "$PREV" "$NEXT"
}

applied_hash_of_current() {
    stored=$(cat "$CURRENT/applied.sha256" 2>/dev/null)
    if is_hash "$stored"; then printf '%s' "$stored"; fi
}

start_frps() {
    "$FRPS_BIN" -c "$CURRENT/frps.toml" &
    FRPS_PID=$!
    log "frps started from $CURRENT (pid $FRPS_PID)"
}

# set_state <state> <reason>
set_state() {
    if [ "$1" != "$STATE" ] || [ "$2" != "$STATE_REASON" ]; then
        SINCE=$(now)
        log "state $1 ($2)"
    fi
    STATE=$1
    STATE_REASON=$2
}

# add_event <event> <reason> <tokenChanged: true|false> — the ring keeps the last 8, oldest first.
add_event() {
    SEQ=$((SEQ + 1))
    EVENTS=$(printf '%s\n{"seq":%d,"event":"%s","at":"%s","reason":"%s","tokenChanged":%s}\n' \
        "$EVENTS" "$SEQ" "$1" "$(now)" "$2" "$3" | sed '/^$/d' | tail -n 8)
}

json_hash() {
    if [ -n "$1" ]; then printf '"%s"' "$1"; else printf 'null'; fi
}

# write_status — temp file and rename in the same directory: a reader sees the old or the new
# file, never a part. 0644, since the server reads it under another UID.
write_status() {
    events=$(printf '%s\n' "$EVENTS" | awk 'NF { printf "%s%s", sep, $0; sep = "," }')
    tmp="$FRPS_STATE_DIR/.status.json.tmp"
    if printf '{"v":1,"boot":"%s","heartbeat":"%s","state":"%s","reason":"%s","since":"%s","appliedHash":%s,"rejectedHash":%s,"events":[%s]}\n' \
        "$BOOT" "$(now)" "$STATE" "$STATE_REASON" "$SINCE" \
        "$(json_hash "$APPLIED_HASH")" "$(json_hash "$REJECTED_HASH")" "$events" > "$tmp" \
        && chmod 0644 "$tmp" && mv -f "$tmp" "$STATUS"; then
        return
    fi
    log "cannot write $STATUS" >&2
}

if ! { mkdir -p "$FRPS_ACTIVE_DIR" && chmod 0700 "$FRPS_ACTIVE_DIR"; }; then
    die "cannot set up $FRPS_ACTIVE_DIR"
fi
# The server and the scheduler read the status file under another UID.
if ! { mkdir -p "$FRPS_STATE_DIR" && chmod 0755 "$FRPS_STATE_DIR"; }; then
    log "cannot set up $FRPS_STATE_DIR" >&2
fi
recover

BOOT=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
SEQ=0
EVENTS=""
STATE=""
STATE_REASON=none
SINCE=""
APPLIED_HASH=$(applied_hash_of_current)
REJECTED_HASH=""
FRPS_PID=""

stage
if [ "$REASON" = none ]; then
    activate || die "cannot swap $NEXT in as $CURRENT"
    APPLIED_HASH=$CANDIDATE_HASH
    start_frps
    set_state running none
    add_event started none false
else
    rm -rf "$NEXT"
    if [ "$REASON" = config_missing ]; then
        if [ -d "$CURRENT" ]; then
            rm -rf "$CURRENT" || die "cannot remove $CURRENT"
            APPLIED_HASH=""
            set_state stopped config_missing
            add_event stopped config_missing false
        else
            set_state waiting config_missing
        fi
    else
        REJECTED_HASH=$CANDIDATE_HASH
        log "configuration rejected: $REASON"
        if [ -d "$CURRENT" ]; then
            start_frps
            set_state degraded "$REASON"
            add_event rejected "$REASON" false
        else
            set_state waiting "$REASON"
        fi
    fi
fi
write_status

if [ -n "$FRPS_PID" ]; then
    wait "$FRPS_PID"
    rc=$?
    log "frps exited ($rc)"
    exit "$rc"
fi
while :; do
    sleep 3600
done
