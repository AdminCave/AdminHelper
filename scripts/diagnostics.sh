#!/usr/bin/env bash
#
# diagnostics.sh — collect a REDACTED diagnostic bundle for a bug report.
#
# Gathers, into one timestamped tarball, everything a maintainer needs to debug
# a self-hosted AdminHelper stack — WITHOUT secrets:
#   - report.txt       versions, host OS, docker/compose versions, service status
#   - compose.yml      a copy of docker-compose.yml (uses ${VARS}, no secrets)
#   - env.sanitized    .env with all secret VALUES masked (<redacted>)
#   - logs/<svc>.log   recent per-service container logs, run through redaction
#
# Secrets and tokens are masked two ways: the exact secret values read from .env
# (as compose reads them) are replaced everywhere, plus generic token forms: JWT,
# Bearer, the query parameters api_key, token and access_token, the token in a
# /hooks/trigger/<token> path and adminhelper_prov_ provisioning tokens.
# Host names and IP addresses stay in the bundle unless --mask-hosts is given.
# With it, IPv4 and IPv6 addresses become <ip> by their form, and the names and
# addresses set in DOMAIN, EXTRA_SANS, CA_FRPS_EXTRA_SANS, ALLOWED_IPS,
# FRP_SERVER_ADDR, TRUSTED_PROXIES, SMTP_HOST, SMTP_USER and SMTP_FROM, and the
# name of this machine, become <host> — in report.txt, the logs and env.sanitized,
# which shows those keys as <masked>. Other names, such as those of managed
# servers or webhook targets, stay. compose.yml stays a copy as it is.
# ALWAYS skim the bundle before sending — redaction is best-effort, not a
# guarantee.
#
# Run from the repository root (where docker-compose.yml lives):
#   ./scripts/diagnostics.sh [--tail N] [--output DIR] [--mask-hosts]

set -euo pipefail

TAIL_LINES=300
OUT_DIR="."
MASK_HOSTS=0

while [ $# -gt 0 ]; do
    case "$1" in
        --tail) TAIL_LINES="${2:?--tail needs a number}"; shift ;;
        --output) OUT_DIR="${2:?--output needs a directory}"; shift ;;
        --mask-hosts) MASK_HOSTS=1 ;;
        -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

# The secret-bearing .env keys whose VALUES must never leave the host. SMTP_PASSWORD is a
# regular .env key since the notification hub — without it the SMTP relay password would
# end up in cleartext in env.sanitized / the logs of a bundle advertised as issue-safe (3.7).
SECRET_KEYS=(SECRET_KEY POSTGRES_PASSWORD MONITOR_API_KEY CA_ROOT_PASSPHRASE ADMIN_PASSWORD SMTP_PASSWORD)

# The .env keys whose values name this installation: host names, addresses, networks
# and mail addresses. Masked only with --mask-hosts — a wrong domain or SAN is a
# frequent cause the bundle is meant to show.
HOST_KEYS=(DOMAIN EXTRA_SANS CA_FRPS_EXTRA_SANS ALLOWED_IPS FRP_SERVER_ADDR TRUSTED_PROXIES SMTP_HOST SMTP_USER SMTP_FROM)

# build_redaction_sedfile <envfile> <sedfile> [mask_hosts]
# Writes a sed script that masks the .env secret values plus generic token forms,
# and with mask_hosts=1 the host names and addresses of host_rules as well.
build_redaction_sedfile() {
    local envfile="$1" sedfile="$2" mask_hosts="${3:-0}"
    : > "$sedfile"
    if [ -f "$envfile" ]; then
        local key val esc
        for key in "${SECRET_KEYS[@]}"; do
            while IFS= read -r val; do
                # Skip empty or the well-known placeholder (not a real secret).
                if [ -n "$val" ] && [ "$val" != "change-me-in-production" ]; then
                    esc="$(printf '%s' "$val" | LC_ALL=C sed -e 's/[][\\/.*^$]/\\&/g')"
                    printf 's/%s/<redacted>/g\n' "$esc" >> "$sedfile"
                fi
            done < <(env_values "$envfile" "$key")
        done
    fi
    # Generic token shapes that may appear in logs regardless of .env. The query
    # parameters stand in the request line of the gateway's and the server's access
    # logs (nginx combined, uvicorn); other query values stay readable.
    cat >> "$sedfile" <<'SED'
s/eyJ[A-Za-z0-9_-]\{6,\}\.[A-Za-z0-9_-]\{6,\}\.[A-Za-z0-9_-]*/<redacted-jwt>/g
s/[Bb]earer [A-Za-z0-9._-]\{8,\}/Bearer <redacted>/g
s/\([?&]\(api_key\|token\|access_token\)=\)[^&[:space:]"]\{1,\}/\1<redacted>/gI
s#/hooks/trigger/[^/?[:space:]"]\{8,\}#/hooks/trigger/<redacted>#g
s/adminhelper_prov_[A-Za-z0-9_-]\{8,\}/adminhelper_prov_<redacted>/g
SED
    if [ "$mask_hosts" = 1 ]; then
        host_rules "$envfile" >> "$sedfile"
    fi
}

# host_rules <envfile> : the sed script of --mask-hosts -> stdout. IPv4 addresses
# (optionally with /prefix) and IPv6 addresses with "::" or eight groups become
# <ip>; a time HH:MM:SS or a version a.b.c is no address. Then the values of the
# HOST_KEYS (read as for the secrets, lists split at ',' and whitespace) and this
# machine's name become <host>, the longest first, so a name is masked whole before
# a shorter one inside it (example.com in ah.example.com). Of a display name, as in
# SMTP_FROM="Name <a@b>", only the address in the angle brackets counts, and a part
# without an ASCII letter or digit (a lone "-") is dropped: either would turn plain
# words or every "-" of the bundle into <host>. \b on an edge that is a word
# character (letter, digit, _): a short name must not eat into longer words. The
# rules ignore case (sed's I), as host names do.
host_rules() {
    local envfile="$1" key form
    local -a parts
    cat <<'SED'
s#\b\(\(25[0-5]\|2[0-4][0-9]\|1[0-9][0-9]\|[1-9]\?[0-9]\)\.\)\{3\}\(25[0-5]\|2[0-4][0-9]\|1[0-9][0-9]\|[1-9]\?[0-9]\)\(/[0-9]\{1,3\}\)\?\b#<ip>#g
s#\b[0-9A-Fa-f]\{1,4\}\(:[0-9A-Fa-f]\{1,4\}\)\{7\}\(/[0-9]\{1,3\}\)\?\b#<ip>#g
s#\b\([0-9A-Fa-f]\{1,4\}:\)\{1,7\}\(:[0-9A-Fa-f]\{1,4\}\)\{1,7\}\(/[0-9]\{1,3\}\)\?\b#<ip>#g
s#\b\([0-9A-Fa-f]\{1,4\}:\)\{1,7\}:\(/[0-9]\{1,3\}\b\|\B\)#<ip>#g
s#\B::\([0-9A-Fa-f]\{1,4\}:\)\{0,6\}[0-9A-Fa-f]\{1,4\}\(/[0-9]\{1,3\}\)\?\b#<ip>#g
SED
    {
        if [ -f "$envfile" ]; then
            for key in "${HOST_KEYS[@]}"; do
                while IFS= read -r form; do
                    if [[ "$form" == *'<'*'>'* ]]; then
                        form="${form#*<}"
                        form="${form%%>*}"
                    fi
                    IFS=$', \t<>' read -r -a parts <<< "$form"
                    printf '%s\n' "${parts[@]}"
                done < <(env_values "$envfile" "$key")
            done
        fi
        uname -n 2>/dev/null || true
    } | LC_ALL=C awk '/[0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz]/ && !seen[tolower($0)]++ {
            print length($0) "\t" $0 }' \
      | LC_ALL=C sort -rn | cut -f2- \
      | LC_ALL=C sed -e 's/[][\\/.*^$]/\\&/g' -e 's/^[[:alnum:]_]/\\b&/' -e 's/[[:alnum:]_]$/&\\b/' \
            -e 's|.*|s/&/<host>/gI|'
}

# env_values <envfile> <key> : every value of <key> in the .env, in the forms
# env_value_forms gives -> stdout, one per line. LC_ALL=C grep -a: grep takes a
# line with a byte the caller's locale cannot decode (or a file with a NUL byte)
# for binary and leaves it out, and its value would stay in the logs. Every line
# of the key, not the first: compose takes the last one. The key as compose reads
# it: an "export" may lead, '=' or ':' separates, whitespace may stand around it.
env_values() {
    local line re="^[[:space:]]*(export[[:space:]]+)?${2}[[:space:]]*[=:]"
    while IFS= read -r line; do
        env_value_forms "$line"
    done < <(LC_ALL=C grep -a -E "$re" "$1" 2>/dev/null)
}

# env_value_forms <line> : the value of a .env line whose key env_values matched,
# as compose reads it -> stdout, one per line, preceded by the value as the
# file spells it where the two differ (the longer one first, so a sed rule masks it
# whole). The value starts behind the first '=' or ':' (the key holds neither).
# Compose takes a value in single quotes literally; in double quotes and unquoted
# it turns $$ into $, and an unquoted value ends before " #" and loses the
# whitespace at its ends. The logs carry the compose form, a copy of the .env the
# file form.
env_value_forms() {
    local v="${1#*[=:]}" file
    v="${v#"${v%%[![:space:]]*}"}"  # ltrim
    case "$v" in
        \'*\'*) file="${v#\'}"; printf '%s\n' "${file%%\'*}"; return ;;
        \"*\"*) file="${v#\"}"; file="${file%%\"*}" ;;
        *)
            file="${v%% \#*}"
            file="${file%"${file##*[![:space:]]}"}"  # rtrim
            ;;
    esac
    [ "${file//\$\$/\$}" = "$file" ] || printf '%s\n' "$file"
    printf '%s\n' "${file//\$\$/\$}"
}

# redact <sedfile> : filter stdin -> stdout through the redaction sed script.
# LC_ALL=C: byte for byte. Under UTF-8, `[^…]` stops in front of a byte outside
# UTF-8, and the rest of a token would stay.
redact() {
    LC_ALL=C sed -f "$1"
}

# sanitize_env <envfile> [mask_hosts] : mask secret VALUES by key line, for
# env.sanitized -> stdout. The second, independent redaction path —
# build_redaction_sedfile redacts by value, this redacts by key, so a secret is
# masked even if its value never appeared in a log. The key as compose reads it (as
# in env_values); the line keeps its form up to the value. LC_ALL=C: under UTF-8,
# `.*` stops in front of a byte outside UTF-8, and the rest of the value would stay.
# With mask_hosts=1 the values of the HOST_KEYS become <masked> as well, and the
# rest of the file runs through host_rules: an address or a name may also stand in
# a comment or in another key.
sanitize_env() {
    local envfile="$1" mask_hosts="${2:-0}" pat re rules
    pat="$(IFS='|'; printf '%s' "${SECRET_KEYS[*]}")"
    re="^([[:space:]]*(export[[:space:]]+)?(${pat})[[:space:]]*[=:][[:space:]]*).*"
    if [ "$mask_hosts" != 1 ]; then
        LC_ALL=C sed -E "s/${re}/\1<redacted>/" "$envfile"
        return
    fi
    rules="$(host_rules "$envfile")"
    pat="$(IFS='|'; printf '%s' "${HOST_KEYS[*]}")"
    LC_ALL=C sed -E -e "s/${re}/\1<redacted>/" \
        -e "s/^([[:space:]]*(export[[:space:]]+)?(${pat})[[:space:]]*[=:][[:space:]]*).*/\1<masked>/" "$envfile" \
        | LC_ALL=C sed -e "$rules"
}

main() {
    if [ ! -f docker-compose.yml ]; then
        echo "Fehler: docker-compose.yml nicht gefunden. Bitte im Repo-Root ausfuehren." >&2
        exit 1
    fi

    # `stage` is intentionally global, not local: the EXIT trap runs in the
    # global scope after main returns, where a local would be unbound under set -u.
    local ts sedfile
    ts="$(date -u +%Y%m%dT%H%M%SZ)"
    stage="$(mktemp -d)"
    trap 'rm -rf "$stage"' EXIT
    mkdir -p "$stage/logs"
    sedfile="$stage/.redact.sed"
    build_redaction_sedfile ".env" "$sedfile" "$MASK_HOSTS"

    # --- report.txt (redacted like the logs) ------------------------------
    {
        echo "AdminHelper diagnostics — $ts"
        echo "======================================================================"
        echo
        echo "## Version"
        if [ -f VERSION ]; then cat VERSION; else echo "(no VERSION file)"; fi
        echo
        echo "## Host"
        uname -a 2>/dev/null || true
        [ -f /etc/os-release ] && grep -E '^(PRETTY_NAME|VERSION)=' /etc/os-release || true
        echo
        echo "## Docker"
        docker --version 2>/dev/null || echo "docker: n/a"
        docker compose version 2>/dev/null || echo "docker compose: n/a"
        echo
        echo "## Service status"
        docker compose ps 2>&1 || echo "(docker compose ps failed)"
        echo
        echo "## Images"
        docker compose config --images 2>/dev/null || echo "(could not list images)"
    } 2>&1 | redact "$sedfile" > "$stage/report.txt"

    # --- compose.yml (no secrets: uses ${VARS}) ---------------------------
    cp docker-compose.yml "$stage/compose.yml"

    # --- env.sanitized (mask secret VALUES) -------------------------------
    if [ -f .env ]; then
        sanitize_env .env "$MASK_HOSTS" > "$stage/env.sanitized"
    fi

    # --- per-service logs (redacted) --------------------------------------
    local services svc
    services="$(docker compose ps --services 2>/dev/null || true)"
    if [ -n "$services" ]; then
        while IFS= read -r svc; do
            [ -n "$svc" ] || continue
            docker compose logs --no-color --tail "$TAIL_LINES" "$svc" 2>&1 \
                | redact "$sedfile" > "$stage/logs/${svc}.log" || true
        done <<< "$services"
    else
        echo "(no running services / docker compose unavailable)" > "$stage/logs/_none.txt"
    fi

    # --- pack -------------------------------------------------------------
    rm -f "$sedfile"  # the redaction script itself must not ship in the bundle
    local archive
    archive="${OUT_DIR%/}/adminhelper-diagnostics-${ts}.tar.gz"
    tar -czf "$archive" -C "$stage" .

    echo "[diagnostics] Bundle erstellt: $archive"
    echo "[diagnostics] Inhalt: report.txt, compose.yml, env.sanitized, logs/"
    echo "[diagnostics] WICHTIG: vor dem Senden kurz durchsehen (Redaction ist Best-effort)."
    if [ "$MASK_HOSTS" != 1 ]; then
        echo "[diagnostics] Host names and IP addresses are not masked. With --mask-hosts, IP addresses, the names in"
        echo "[diagnostics] the .env host settings (see --help) and this machine's name are masked; other names stay."
    fi
    echo "[diagnostics] Dann an ein GitHub-Issue anhaengen: https://github.com/AdminCave/AdminHelper/issues/new/choose"
}

# Only run main when executed directly — sourcing (e.g. the test) just loads the
# functions.
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
    main "$@"
fi
