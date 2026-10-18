#!/bin/sh
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# frps-supervisor.sh — runs frps only from a configuration that passed every check, and takes
# over changes to it.
#
#   frps-supervisor.sh          supervise frps (the image's entrypoint)
#   frps-supervisor.sh health   exit 0 while the state is waiting, running or stopped
#
# The supervisor runs as root, frps as FRPS_USER through su-exec (empty: as the supervisor,
# for tests without root; root refuses that). frps then holds no capability and owns no file
# it runs from. After every end of frps, before a new copy is swapped in and before every
# start, the supervisor KILLs every process of FRPS_USER, so that nothing frps forked outlives
# it; should one be left, frps does not start and no copy is left (waiting, processes_left).
#
# The input, frps.toml from the server and the TLS material from the ca-issuer, lives in
# volumes other containers write. Only regular files of at most 1 MiB are read from there,
# each within FRPS_READ_SECONDS; a symlink, any other kind of file or a larger one is invalid
# (input_unreadable), as is one that cannot be read. A candidate is copied into next/ of the
# supervisor's own working directory (FRPS_ACTIVE_DIR, mounted by frps alone), checked there
# while only the supervisor may read it, its TLS paths pointed at current/, and swapped in as
# current/, which frps reads and cannot write (FRPS_ACTIVE_DIR 0711, current/ 0755, its files
# 0644, all the supervisor's). frps always runs from current/, so a half-written or invalid
# input never reaches it. At the start, and after that whenever the input has changed and
# then stayed the same for two polls in a row (FRPS_POLL_SECONDS apart, one second while a
# start of frps is due; a file still being written is not taken for a new one):
#
#   valid                        frps (re)starts from the new current/      running
#   invalid, current/ exists     frps runs on from the last valid current/  degraded
#   invalid, no current/         nothing starts                             waiting
#   frps.toml missing or empty   frps stops, current/ is removed            stopped
#     (and no current/ to remove)                                           waiting
#
# An input that keeps changing for FRPS_UNSTABLE_SECONDS is not taken over: input_unstable,
# degraded while frps runs, waiting while it does not, until the input stays the same.
#
# Every start of frps, a restart after it exited included, first compares current/ with the
# copy the supervisor took over (a sha256 over frps.toml and the PEM files, kept in memory;
# a copy found at the start counts as taken over then), and checks current/frps.toml again
# (check_config). A copy that changed (event copy_changed) or fails starts nothing and is
# removed; before a restart the input is then taken over anew as at the start, so frps starts
# from a fresh copy of a valid input, and an invalid one leaves the state as without a valid
# copy.
#
# Events: started (frps started where none ran from a current/: at the start, or after
# waiting or stopped), applied (a change restarted frps; tokenChanged compares hashes of the
# token line), rejected (once per rejected input, and once per series of changes that made
# the input unstable), stopped, crashed (once per crash loop), copy_changed, start_refused
# (processes of FRPS_USER left).
# A valid input equal to the one frps runs from restarts nothing.
#
# frps exiting on its own is started again from current/ after 2, 4, 8 … FRPS_BACKOFF_MAX
# seconds; the third exit within FRPS_CRASH_WINDOW seconds makes the state crashloop, until
# frps has run that long again. TERM or INT stop frps (KILL after FRPS_STOP_SECONDS) and end
# the supervisor with 0.
#
# The state goes to $FRPS_STATE_DIR/status.json, rewritten at every poll as a heartbeat; its
# format is the contract the server reads, apps/server/app/modules/frp/supervisor_status.py.
# Log lines carry codes and paths, never the token.

set -u
export LC_ALL=C
umask 077

FRPS_CONFIG="${FRPS_CONFIG:-/etc/frp/frps.toml}"
FRPS_PKI_DIR="${FRPS_PKI_DIR:-/etc/frp-pki}"
FRPS_ACTIVE_DIR="${FRPS_ACTIVE_DIR:-/var/lib/frps-active}"
FRPS_STATE_DIR="${FRPS_STATE_DIR:-/var/lib/frps-state}"
FRPS_BIN="${FRPS_BIN:-frps}"
# Set but empty switches su-exec off.
FRPS_USER="${FRPS_USER-frps}"
# Whole seconds, as POSIX sleep takes them.
FRPS_POLL_SECONDS="${FRPS_POLL_SECONDS:-5}"
FRPS_BACKOFF_MAX="${FRPS_BACKOFF_MAX:-60}"
FRPS_STOP_SECONDS="${FRPS_STOP_SECONDS:-10}"
FRPS_CRASH_WINDOW="${FRPS_CRASH_WINDOW:-60}"
FRPS_READ_SECONDS="${FRPS_READ_SECONDS:-5}"
# Seconds rather than polls: polls come one second apart while a start of frps is due.
FRPS_UNSTABLE_SECONDS="${FRPS_UNSTABLE_SECONDS:-30}"
# How long KILL goes on to processes of FRPS_USER that do not end (kill_left).
FRPS_KILL_SECONDS="${FRPS_KILL_SECONDS:-5}"
# Where kill_left finds the processes; for tests only.
FRPS_PROC_ROOT="${FRPS_PROC_ROOT:-/proc}"
# The host port compose publishes for frps; webServer.port must not take it.
FRP_BIND_PORT="${FRP_BIND_PORT:-}"

NEXT="$FRPS_ACTIVE_DIR/next"
CURRENT="$FRPS_ACTIVE_DIR/current"
PREV="$FRPS_ACTIVE_DIR/prev"
STATUS="$FRPS_STATE_DIR/status.json"
PEMS="frps.crt frps.key ca.crt"
# Bytes; the server's frps.toml and the PEM files are a few KiB.
INPUT_MAX=1048576
# The only top-level keys frps gets: those config_generator.py writes, then a few for
# extra_config (frps 0.69.1 field names, none of them a listener).
TOP_KEYS="bindPort vhostHTTPSPort subDomainHost maxPortsPerClient detailedErrorsToClient
    webServer.addr webServer.port webServer.user webServer.password auth.method auth.token
    transport.maxPoolCount transport.tcpMux transport.tcpMuxKeepaliveInterval
    transport.heartbeatTimeout transport.tcpKeepalive userConnTimeout log.level log.maxDays"

log() { echo "[frps-supervisor] $*"; }

die() {
    log "error: $*" >&2
    stop_frps
    exit 1
}

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# epoch — seconds since 1970, computed from fields every date prints rather than from %s.
epoch() {
    date -u '+%Y %m %d %H %M %S' | awk '{
        y = $1; m = $2
        if (m <= 2) { y--; m += 12 }
        days = 365 * y + int(y / 4) - int(y / 100) + int(y / 400) + int((153 * (m - 3) + 2) / 5) + $3
        print (days - 719469) * 86400 + $4 * 3600 + $5 * 60 + $6
    }'
}

is_hash() { printf '%s' "$1" | grep -Eqx '[0-9a-f]{64}'; }

# file_kind <file> — 0 for a regular file, 1 for none, 2 for a symlink or any other kind.
file_kind() {
    if [ -L "$1" ]; then return 2; fi
    [ -e "$1" ] || return 1
    [ -f "$1" ] || return 2
}

# Reads of a file below are bounded by FRPS_READ_SECONDS: one swapped for a FIFO after
# file_kind would block them for good.

# content_hash <file>... — one sha256 over the contents of the files, of each no more than
# take_input reads. A missing file counts too, and apart from that one that is no regular
# file or cannot be read.
content_hash() {
    for file in "$@"; do
        file_kind "$file"
        case $? in
        0)
            { timeout "$FRPS_READ_SECONDS" head -c $((INPUT_MAX + 1)) "$file" 2>/dev/null \
                || echo '!'; } | sha256sum
            ;;
        1) echo - ;;
        *) echo '!' ;;
        esac
    done | cut -d ' ' -f 1 | sha256sum | cut -d ' ' -f 1
}

# take_input <file> <copy> — copies an input file: 1 when it is missing, 2 when it is no
# regular file, cannot be read or is larger than INPUT_MAX. Of a larger one the copy gets a
# byte more than that, no matter how large it is.
take_input() {
    file_kind "$1" || return
    timeout "$FRPS_READ_SECONDS" head -c $((INPUT_MAX + 1)) "$1" > "$2" 2>/dev/null || return 2
    [ "$(wc -c < "$2")" -le "$INPUT_MAX" ] || return 2
}

input_hash() {
    content_hash "$FRPS_CONFIG" "$FRPS_PKI_DIR/frps.crt" "$FRPS_PKI_DIR/frps.key" "$FRPS_PKI_DIR/ca.crt"
}

# token_hash <toml> — a hash of the token line; the token itself stays in the file.
token_hash() { grep '^auth\.token = ' "$1" | sha256sum | cut -d ' ' -f 1; }

# check_config <toml> <tls dir> — prints the first rule the file breaks as a reason code, or
# none.
#
# Only the layout the server generates passes (config_generator.py), so that frps reads the
# file exactly as these line checks do: every line is empty, the one table [transport.tls], or
# `key = value` with true, false, a number or a one-line string without quotes, backslashes
# or braces; every key once per table, in any case; no control characters. At top level only
# the keys in TOP_KEYS, compared exactly, and bindPort among them; webServer.port neither 443
# nor bindPort nor FRP_BIND_PORT. Anything else is verify_failed. Then: at top level
# auth.method "token", a token of at least 16 characters and no other auth key, and a
# [transport.tls] table with nothing but force = true and the three files in <tls dir>.
check_config() {
    # NUL included, at which some awks split a line.
    if [ "$(tr -d '\n\040-\176\200-\377' < "$1" | wc -c)" -ne 0 ]; then
        echo verify_failed
        return
    fi
    PKI="$2" PUBLISHED="$FRP_BIND_PORT" TOP_KEYS="$TOP_KEYS" awk '
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
            published = ENVIRON["PUBLISHED"]
            if (web_port != "" && (web_port + 0 == 443 || web_port + 0 == bind_port + 0 ||
                (published != "" && web_port + 0 == published + 0))) bad = 1
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
# copied input; over the input as the poll saw it when a file of it cannot be read; empty
# without a frps.toml). A valid candidate is left in next/, ready for activate, with its TLS
# paths pointed at current/.
stage() {
    CANDIDATE_HASH=""
    rm -rf "$NEXT"
    mkdir "$NEXT" || die "cannot create $NEXT"
    take_input "$FRPS_CONFIG" "$NEXT/frps.toml"
    case $? in
    0) REASON=none ;;
    1) REASON=config_missing ;;
    *) REASON=input_unreadable ;;
    esac
    if [ "$REASON" = none ] && [ ! -s "$NEXT/frps.toml" ]; then REASON=config_missing; fi
    if [ "$REASON" = none ]; then
        for pem in $PEMS; do
            take_input "$FRPS_PKI_DIR/$pem" "$NEXT/$pem"
            [ $? -lt 2 ] || REASON=input_unreadable
        done
    fi
    case $REASON in
    config_missing) return ;;
    input_unreadable)
        CANDIDATE_HASH=$INPUT
        return
        ;;
    esac
    CANDIDATE_HASH=$(content_hash "$NEXT/frps.toml" "$NEXT/frps.crt" "$NEXT/frps.key" "$NEXT/ca.crt")

    REASON=$(check_config "$NEXT/frps.toml" "$FRPS_PKI_DIR") || die "cannot read $NEXT/frps.toml"
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

# activate — opens next/ to frps for reading and swaps it in as current/; COPY_HASH is then
# the hash of the copy frps runs from. Two renames: a crash between them leaves prev/, which
# recover renames back on the next start.
activate() {
    for file in frps.toml applied.sha256 $PEMS; do
        chmod 0644 "$NEXT/$file" || return 1
    done
    chmod 0755 "$NEXT" || return 1
    rm -rf "$PREV"
    if [ -d "$CURRENT" ]; then
        mv "$CURRENT" "$PREV" || return 1
    fi
    if ! mv "$NEXT" "$CURRENT"; then
        [ -d "$PREV" ] && mv "$PREV" "$CURRENT"
        return 1
    fi
    rm -rf "$PREV"
    COPY_HASH=$(copy_hash)
}

# copy_hash — the sha256 over the copy in current/, as content_hash makes it.
copy_hash() {
    content_hash "$CURRENT/frps.toml" "$CURRENT/frps.crt" "$CURRENT/frps.key" "$CURRENT/ca.crt"
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

# start_frps — starts frps from current/ as FRPS_USER, as long as current/ is still the copy
# the supervisor took over (COPY_HASH), current/frps.toml passes check_config again and no
# process of FRPS_USER is left (kill_left). A copy that changed (event copy_changed) or fails
# starts nothing and is removed (drop_copy), and start_frps returns 1; with processes left, 2
# (refuse_start).
start_frps() {
    file_kind "$CURRENT/frps.toml"
    case $? in
    0)
        reason=$(check_config "$CURRENT/frps.toml" "$CURRENT" 2>/dev/null) \
            || reason=input_unreadable
        ;;
    1) reason=config_missing ;;
    *) reason=input_unreadable ;;
    esac
    if [ "$(copy_hash)" != "$COPY_HASH" ]; then
        log "frps not started, the copy in $CURRENT changed since it was taken over and goes"
        add_event copy_changed none false
    elif [ "$reason" != none ]; then
        log "frps not started, the copy in $CURRENT fails the check and goes: $reason"
    elif ! kill_left; then
        refuse_start
        return 2
    else
        if [ -n "$FRPS_USER" ]; then
            su-exec "$FRPS_USER" "$FRPS_BIN" -c "$CURRENT/frps.toml" &
        else
            "$FRPS_BIN" -c "$CURRENT/frps.toml" &
        fi
        FRPS_PID=$!
        STARTED_AT=$(epoch)
        log "frps started from $CURRENT (pid $FRPS_PID)"
        return 0
    fi
    drop_copy "$reason"
    return 1
}

# drop_copy <reason> — removes current/; the state is set as an invalid input without a valid
# copy would (waiting).
drop_copy() {
    rm -rf "$CURRENT" || die "cannot remove $CURRENT"
    APPLIED_HASH=""
    COPY_HASH=""
    end_series
    set_config waiting "$1"
}

# refuse_start — processes of FRPS_USER are left: frps does not start, and no copy is left for
# them to read (event start_refused), until the input changes or the container starts anew.
refuse_start() {
    log "frps not started, processes of $FRPS_USER are left; the copy in $CURRENT goes"
    rm -rf "$NEXT"
    drop_copy processes_left
    add_event start_refused processes_left false
}

# stop_frps — TERM, KILL after FRPS_STOP_SECONDS; either way frps is waited for.
stop_frps() {
    [ -n "${FRPS_PID:-}" ] || return 0
    kill -TERM "$FRPS_PID" 2>/dev/null
    waited=0
    # The shell reaps an ended child while it runs the next foreground command, the sleep;
    # kill -0 fails from then on.
    while kill -0 "$FRPS_PID" 2>/dev/null; do
        if [ "$waited" -ge "$FRPS_STOP_SECONDS" ]; then
            log "frps did not stop within ${FRPS_STOP_SECONDS}s, killing it"
            kill -KILL "$FRPS_PID" 2>/dev/null
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done
    wait "$FRPS_PID" 2>/dev/null
    kill_left
    log "frps stopped"
    FRPS_PID=""
}

# frps_left — the pids of the processes of FRPS_USER that have not ended (a zombie has), from
# FRPS_PROC_ROOT; never PID 1 or this shell.
frps_left() {
    for status in "$FRPS_PROC_ROOT"/[0-9]*/status; do
        pid=${status%/status}
        pid=${pid##*/}
        case $pid in 1 | "$$") continue ;; esac
        state=""
        uid=""
        # A process that ended in the meantime has no file left to read.
        {
            while read -r key value _; do
                case $key in
                State:) state=$value ;;
                Uid:)
                    uid=$value
                    break
                    ;;
                esac
            done < "$status"
        } 2>/dev/null
        if [ "$uid" = "$FRPS_UID" ] && [ "$state" != Z ]; then echo "$pid"; fi
    done
}

# kill_left — KILL to every process of FRPS_USER: one frps forked would outlive it and could
# read the copy of the next start. The supervisor sends it as root, so that none of them can
# fend it off, and to them alone. Again a tenth of a second later (busybox and GNU sleep take
# fractions) while one is left, for FRPS_KILL_SECONDS at the most; 1 if one is left then. The
# shell reaps those that fall to PID 1.
kill_left() {
    [ -n "$FRPS_USER" ] || return 0
    rounds=0
    deadline=$(($(epoch) + FRPS_KILL_SECONDS))
    while left=$(frps_left) && [ -n "$left" ]; do
        if [ "$rounds" -ge $((FRPS_KILL_SECONDS * 10)) ] || [ "$(epoch)" -ge "$deadline" ]; then
            log "processes of $FRPS_USER left: $(printf '%s' "$left" | tr '\n' ' ')"
            return 1
        fi
        # shellcheck disable=SC2086 # one pid a word
        kill -KILL $left 2>/dev/null
        rounds=$((rounds + 1))
        sleep 0.1
    done
    return 0
}

# end_series — forgets the exits of frps so far: the next one waits 2 s again.
end_series() {
    BACKOFF=0
    CRASHLOOP=0
    EXIT_1=""
    EXIT_2=""
    RESTART_AT=""
}

# check_frps — notices frps ending on its own and schedules its next start from current/.
check_frps() {
    [ -n "$FRPS_PID" ] || return 0
    if kill -0 "$FRPS_PID" 2>/dev/null; then
        if [ "$BACKOFF" -gt 0 ] && [ $(($(epoch) - STARTED_AT)) -ge "$FRPS_CRASH_WINDOW" ]; then
            log "frps has run for ${FRPS_CRASH_WINDOW}s again"
            end_series
        fi
        return 0
    fi
    wait "$FRPS_PID"
    rc=$?
    kill_left
    FRPS_PID=""
    t=$(epoch)
    if [ "$BACKOFF" -eq 0 ]; then BACKOFF=2; else BACKOFF=$((BACKOFF * 2)); fi
    if [ "$BACKOFF" -gt "$FRPS_BACKOFF_MAX" ]; then BACKOFF=$FRPS_BACKOFF_MAX; fi
    RESTART_AT=$((t + BACKOFF))
    log "frps exited ($rc), restarting it in ${BACKOFF}s"
    # EXIT_1 and EXIT_2: the two exits before this one.
    if [ "$CRASHLOOP" = 0 ] && [ -n "$EXIT_1" ] && [ $((t - EXIT_1)) -lt "$FRPS_CRASH_WINDOW" ]; then
        CRASHLOOP=1
        add_event crashed none false
    fi
    EXIT_1=$EXIT_2
    EXIT_2=$t
}

# restart_due — starts frps again once its delay is over. Should current/ fail its check and
# be gone, the input this poll saw is taken over at once, as at the start; should processes of
# FRPS_USER be left, nothing starts.
restart_due() {
    if [ -n "$RESTART_AT" ] && [ "$(epoch)" -ge "$RESTART_AT" ]; then
        RESTART_AT=""
        started=0
        start_frps || started=$?
        if [ "$started" -eq 1 ]; then take_over start; fi
    fi
}

# set_config <state> <reason> — the state as the input makes it; a crash loop shows over it.
set_config() {
    CONFIG_STATE=$1
    CONFIG_REASON=$2
}

# take_over <start|change> — checks the input and acts on the outcome (see the table above).
take_over() {
    HANDLED=$INPUT
    stage
    case $REASON in
    none)
        if [ "$1" = change ] && [ "$CANDIDATE_HASH" = "$APPLIED_HASH" ] \
            && { [ -n "$FRPS_PID" ] || [ -n "$RESTART_AT" ]; }; then
            rm -rf "$NEXT"
        else
            event=started
            token_changed=false
            if [ "$1" = change ] && [ -d "$CURRENT" ]; then
                event=applied
                if [ "$(token_hash "$CURRENT/frps.toml")" != "$(token_hash "$NEXT/frps.toml")" ]; then
                    token_changed=true
                fi
                log "configuration changed, restarting frps"
            fi
            stop_frps
            # Nothing of FRPS_USER may see the new copy before the new frps does.
            if ! kill_left; then
                refuse_start
                REJECTED_HASH=""
                return
            fi
            activate || die "cannot swap $NEXT in as $CURRENT"
            APPLIED_HASH=$CANDIDATE_HASH
            end_series
            start_frps || return
            add_event "$event" none "$token_changed"
        fi
        REJECTED_HASH=""
        set_config running none
        ;;
    config_missing)
        rm -rf "$NEXT"
        REJECTED_HASH=""
        if [ -d "$CURRENT" ]; then
            stop_frps
            end_series
            rm -rf "$CURRENT" || die "cannot remove $CURRENT"
            APPLIED_HASH=""
            COPY_HASH=""
            set_config stopped config_missing
            add_event stopped config_missing false
        elif [ "$CONFIG_STATE" != stopped ]; then
            set_config waiting config_missing
        fi
        ;;
    *)
        rm -rf "$NEXT"
        log "configuration rejected: $REASON"
        started=0
        if [ -d "$CURRENT" ] && [ -z "$FRPS_PID" ] && [ -z "$RESTART_AT" ]; then
            start_frps || started=$?
        fi
        if [ "$started" -eq 0 ] && [ -d "$CURRENT" ]; then
            set_config degraded "$REASON"
            if [ "$CANDIDATE_HASH" != "$REJECTED_HASH" ]; then
                add_event rejected "$REASON" false
            fi
        elif [ "$started" -ne 2 ]; then
            # 2: refuse_start has set the state, processes_left.
            set_config waiting "$REASON"
        fi
        REJECTED_HASH=$CANDIDATE_HASH
        ;;
    esac
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

report() {
    if [ "$CRASHLOOP" = 1 ]; then
        set_state crashloop none
    elif [ "$UNSTABLE" = 1 ]; then
        if [ -n "$FRPS_PID" ] || [ -n "$RESTART_AT" ]; then
            set_state degraded input_unstable
        else
            set_state waiting input_unstable
        fi
    else
        set_state "$CONFIG_STATE" "$CONFIG_REASON"
    fi
    write_status
}

# poll — one round of the loop. An input that differs from the one the last poll saw is only
# noted; the next poll that finds it unchanged takes it over. CHANGING_SINCE: when the polls
# began to see the input change, logged once; after FRPS_UNSTABLE_SECONDS of that the input
# counts as unstable, with one rejected event for the series.
poll() {
    check_frps
    INPUT=$(input_hash)
    if [ "$INPUT" != "$SEEN" ]; then
        SEEN=$INPUT
        t=$(epoch)
        if [ -z "$CHANGING_SINCE" ]; then
            CHANGING_SINCE=$t
            log "input changed, taking it over once it stays the same"
        elif [ "$UNSTABLE" = 0 ] && [ $((t - CHANGING_SINCE)) -ge "$FRPS_UNSTABLE_SECONDS" ]; then
            UNSTABLE=1
            add_event rejected input_unstable false
        fi
    else
        CHANGING_SINCE=""
        UNSTABLE=0
        if [ "$INPUT" != "$HANDLED" ]; then
            take_over change
        fi
    fi
    restart_due
    report
}

# pause <seconds> — a sleep that TERM and INT cut short: a trapped signal ends wait at once.
pause() {
    sleep "$1" &
    PAUSE_PID=$!
    wait "$PAUSE_PID" && PAUSE_PID=""
}

on_signal() {
    trap '' TERM INT
    log "stopping"
    if [ -n "$PAUSE_PID" ]; then
        kill "$PAUSE_PID" 2>/dev/null
        wait "$PAUSE_PID" 2>/dev/null
    fi
    stop_frps
    exit 0
}

# health — the container's health check; reads the status file and nothing else.
health() {
    state=$(sed -n 's/.*"state": *"\([a-z]*\)".*/\1/p' "$STATUS" 2>/dev/null)
    echo "${state:-no status}"
    case $state in
    waiting | running | stopped) exit 0 ;;
    esac
    exit 1
}

if [ "${1:-}" = health ]; then
    health
fi

# whole_seconds <name> <value> — anything else would make the loop spin or the shell's
# arithmetic fail (a leading 0 reads as octal).
whole_seconds() {
    case $2 in
    0* | *[!0-9]*) die "$1 must be a whole number of seconds above 0" ;;
    esac
}
whole_seconds FRPS_POLL_SECONDS "$FRPS_POLL_SECONDS"
whole_seconds FRPS_BACKOFF_MAX "$FRPS_BACKOFF_MAX"
whole_seconds FRPS_STOP_SECONDS "$FRPS_STOP_SECONDS"
whole_seconds FRPS_CRASH_WINDOW "$FRPS_CRASH_WINDOW"
whole_seconds FRPS_READ_SECONDS "$FRPS_READ_SECONDS"
whole_seconds FRPS_UNSTABLE_SECONDS "$FRPS_UNSTABLE_SECONDS"
whole_seconds FRPS_KILL_SECONDS "$FRPS_KILL_SECONDS"
# Unset or a port: anything else would compare as some other number.
case $FRP_BIND_PORT in
'') ;;
0* | *[!0-9]* | ??????*) die "FRP_BIND_PORT must be a port number" ;;
*) [ "$FRP_BIND_PORT" -le 65535 ] || die "FRP_BIND_PORT must be a port number" ;;
esac
FRPS_UID=""
if [ -n "$FRPS_USER" ]; then
    FRPS_UID=$(id -u "$FRPS_USER" 2>/dev/null) || die "FRPS_USER $FRPS_USER is no user"
    # kill_left would hit root's processes, the health check's among them.
    [ "$FRPS_UID" != 0 ] || die "FRPS_USER must not be root"
elif [ "$(id -u)" -eq 0 ]; then
    die "FRPS_USER must name the user frps runs as, not be empty under root"
fi

# frps passes through to current/ and lists nothing.
if ! { mkdir -p "$FRPS_ACTIVE_DIR" && chmod 0711 "$FRPS_ACTIVE_DIR"; }; then
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
CONFIG_STATE=""
CONFIG_REASON=none
APPLIED_HASH=$(applied_hash_of_current)
# A copy left from an earlier run counts as taken over now.
COPY_HASH=""
if [ -d "$CURRENT" ]; then COPY_HASH=$(copy_hash); fi
REJECTED_HASH=""
FRPS_PID=""
STARTED_AT=0
PAUSE_PID=""
CHANGING_SINCE=""
UNSTABLE=0
end_series
trap on_signal TERM INT

INPUT=$(input_hash)
SEEN=$INPUT
take_over start
report

while :; do
    # While a start of frps is due, every second, so that its delay holds.
    if [ -n "$RESTART_AT" ]; then pause 1; else pause "$FRPS_POLL_SECONDS"; fi
    poll
done
