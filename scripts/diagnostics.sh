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
# Secrets and tokens are masked two ways: the exact values of the .env secrets
# and credentials (keys, passwords and SMTP_USER, read as compose reads them) are
# replaced everywhere, plus generic token forms: JWT, Bearer, the query
# parameters api_key, token and access_token, the token in a
# /hooks/trigger/<token> path and adminhelper_prov_ provisioning tokens.
# Host names and IP addresses stay in the bundle unless --mask-hosts is given.
# With it, IPv4 and IPv6 addresses become <ip> by their form, and every name and
# address set in DOMAIN, EXTRA_SANS, CA_FRPS_EXTRA_SANS, ALLOWED_IPS,
# FRP_SERVER_ADDR, TRUSTED_PROXIES, SMTP_HOST and SMTP_FROM (of a mailbox in
# SMTP_FROM with a display name, "Name <address>", only the address in
# angle brackets, not the name), and the name of this machine, also without its
# domain, become <host> —
# in report.txt, the logs and env.sanitized, which shows those keys as <masked>.
# A name with a dot matches in any case and takes the names under it along; a
# machine name without a dot only in its spelling and as a whole word, not as part
# of a service or image name.
# Other names, such as those of managed servers or webhook targets, stay.
# compose.yml stays a copy as it is.
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
        -h|--help) awk 'NR > 1 { if (!/^#/) exit; print }' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

# The secret-bearing .env keys whose VALUES must never leave the host. SMTP_PASSWORD is a
# regular .env key since the notification hub — without it the SMTP relay password would
# end up in cleartext in env.sanitized / the logs of a bundle advertised as issue-safe (3.7).
# SMTP_USER too: with some mail providers the user is itself an access token or a key ID.
# Its rule stops at word edges (a short user like admin must not eat into adminhelper),
# and it runs by its length like every value (build_redaction_sedfile): a user that is a
# word of another secret cannot cut that secret in two, and a secret inside the user
# cannot cut the user.
SECRET_KEYS=(SECRET_KEY POSTGRES_PASSWORD MONITOR_API_KEY CA_ROOT_PASSPHRASE ADMIN_PASSWORD SMTP_PASSWORD SMTP_USER)

# The .env keys whose values name this installation: host names, addresses, networks
# and mail addresses. Masked only with --mask-hosts — a wrong domain or SAN is a
# frequent cause the bundle is meant to show.
HOST_KEYS=(DOMAIN EXTRA_SANS CA_FRPS_EXTRA_SANS ALLOWED_IPS FRP_SERVER_ADDR TRUSTED_PROXIES SMTP_HOST SMTP_FROM)

# The whitespace of a .env line as compose reads it, EREs for LC_ALL=C awk with the
# bytes spelled out. ENV_WS is what Go's unicode.IsSpace calls whitespace: ASCII
# whitespace and the UTF-8 forms of NEL, NBSP, OGHAM SPACE MARK, EN QUAD to HAIR SPACE,
# LINE and PARAGRAPH SEPARATOR, NARROW NBSP, MEDIUM MATHEMATICAL SPACE and IDEOGRAPHIC
# SPACE; compose trims it from the end of an unquoted value. In front of a key it skips
# that and a BOM: ENV_SP (as the .env filter of backup.sh). Between key and separator,
# and between separator and value, it skips ASCII whitespace, NEL and NBSP: ENV_SEP.
ENV_WS="([[:space:]]|"$'\xc2[\x85\xa0]|\xe1\x9a\x80|\xe2\x80[\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89\x8a\xa8\xa9\xaf]|\xe2\x81\x9f|\xe3\x80\x80)'
ENV_SP="(${ENV_WS}|"$'\xef\xbb\xbf)'
ENV_SEP="([[:space:]]|"$'\xc2[\x85\xa0])'

# build_redaction_sedfile <envfile> <sedfile> [mask_hosts]
# Writes a sed script that masks the .env secret values plus generic token forms,
# and with mask_hosts=1 the host names and addresses of host_rules as well. Each
# value once and the longest first: a value is masked whole before a shorter one
# inside it (another line of a value over several lines, the value of another key)
# can cut it in two. A value of SMTP_USER that is also one of another key keeps that
# key's rule, without word edges. A line of a value that is only whitespace (ENV_WS)
# is no rule: it holds no secret, and its rule would mask every blank of the logs.
build_redaction_sedfile() {
    local envfile="$1" sedfile="$2" mask_hosts="${3:-0}"
    : > "$sedfile"
    if [ -f "$envfile" ]; then
        local key line val esc
        while IFS= read -r line; do
            key="${line%% *}"
            val="${line#* }"
            esc="$(printf '%s' "$val" | LC_ALL=C sed -e 's/[][\\/.*^$]/\\&/g')"
            if [ "$key" = SMTP_USER ]; then
                esc="$(printf '%s' "$esc" | LC_ALL=C sed -e 's/^[[:alnum:]_]/\\b&/' -e 's/[[:alnum:]_]$/&\\b/')"
            fi
            printf 's/%s/<redacted>/g\n' "$esc" >> "$sedfile"
        done < <(
            for key in "${SECRET_KEYS[@]}"; do
                env_values "$envfile" "$key" | LC_ALL=C sed -e "s/^/$key /"
            done | LC_ALL=C awk -v ws="$ENV_WS" '
                # Skip whitespace only or the well-known placeholder (not a real secret).
                { v = substr($0, index($0, " ") + 1) }
                v !~ ("^" ws "*$") && v != "change-me-in-production" && (!(v in by) || by[v] == "SMTP_USER") {
                    by[v] = $1
                }
                END { for (v in by) print length(v) "\t" by[v] " " v }
            ' | LC_ALL=C sort -t "$(printf '\t')" -k1,1rn | cut -f2-
        )
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
# <ip>, one with an IPv4 tail (::ffff:192.0.2.1, six groups or fewer with "::")
# whole; a time HH:MM:SS or a version a.b.c is no address, nor is a number run
# right behind <path>/<name>: (an image tag, .../server:1.2.3.4). sed cannot look
# behind: the dots of such a tag become newlines, which a line in sed never holds,
# during the IPv4 rule and dots again after it. Then the values of the
# HOST_KEYS (read as for the secrets) and this machine's name become <host>, the
# longest first, so a name is masked whole before a shorter one inside it
# (example.com in ah.example.com). A value is split at ',', whitespace, '<' and '>',
# and every part counts. SMTP_FROM is a list of mailboxes: a display name in quotes
# goes (in the file form of a value in double quotes its quotes are \"), then of a
# mailbox with angle brackets only the address in them counts, of one without the
# mailbox itself, and a part without an ASCII letter or digit (a lone "-") is
# dropped: the words of a display name or every "-" of the bundle would turn into
# <host>. Of a machine name with a dot its first label counts as well
# (node9 of node9.example.org): a log may name the machine short. \b on an edge that
# is a word character (letter, digit, _): a short name must not eat into longer
# words. A name with a dot ignores case (sed's I), as host names do, and takes a
# chain of labels before it along (registry.ah.example.com). A name without a dot is
# often a word or a service: it counts only in its spelling and as a whole word, not
# behind a word character, '.', '-' or a path segment (<word>/), nor before a word
# character or '-'; a domain behind it goes with it. sed has no look-behind: such an
# occurrence gets its first letter turned into a newline, which a line never holds,
# and back after the rule.
host_rules() {
    local envfile="$1" key form node name first rest
    local w=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_
    local -a parts
    cat <<'SED'
s#\(\b\([0-9A-Fa-f]\{1,4\}:\)\{6\}\|\b\([0-9A-Fa-f]\{1,4\}:\)\{1,5\}\(:[0-9A-Fa-f]\{1,4\}\)\{0,4\}:\|\B::\([0-9A-Fa-f]\{1,4\}:\)\{0,5\}\)\(\(25[0-5]\|2[0-4][0-9]\|1[0-9][0-9]\|[1-9]\?[0-9]\)\.\)\{3\}\(25[0-5]\|2[0-4][0-9]\|1[0-9][0-9]\|[1-9]\?[0-9]\)\(/[0-9]\{1,3\}\)\?\b#<ip>#g
s#\(/[[:alnum:]_.-]\{1,\}:[0-9]\{1,\}\)\.\([0-9]\{1,\}\)\.\([0-9]\{1,\}\)\.\([0-9]\{1,\}\)#\1\n\2\n\3\n\4#g
s#\b\(\(25[0-5]\|2[0-4][0-9]\|1[0-9][0-9]\|[1-9]\?[0-9]\)\.\)\{3\}\(25[0-5]\|2[0-4][0-9]\|1[0-9][0-9]\|[1-9]\?[0-9]\)\(/[0-9]\{1,3\}\)\?\b#<ip>#g
s#\n#.#g
s#\b[0-9A-Fa-f]\{1,4\}\(:[0-9A-Fa-f]\{1,4\}\)\{7\}\(/[0-9]\{1,3\}\)\?\b#<ip>#g
s#\b\([0-9A-Fa-f]\{1,4\}:\)\{1,7\}\(:[0-9A-Fa-f]\{1,4\}\)\{1,7\}\(/[0-9]\{1,3\}\)\?\b#<ip>#g
s#\b\([0-9A-Fa-f]\{1,4\}:\)\{1,7\}:\(/[0-9]\{1,3\}\b\|\B\)#<ip>#g
s#\B::\([0-9A-Fa-f]\{1,4\}:\)\{0,6\}[0-9A-Fa-f]\{1,4\}\(/[0-9]\{1,3\}\)\?\b#<ip>#g
SED
    {
        if [ -f "$envfile" ]; then
            for key in "${HOST_KEYS[@]}"; do
                while IFS= read -r form; do
                    IFS=$', \t<>' read -r -a parts <<< "$form"
                    printf '%s\n' "${parts[@]}"
                done < <(
                    if [ "$key" = SMTP_FROM ]; then
                        env_values "$envfile" "$key" | LC_ALL=C sed -e 's/\\"\([^"\\]\|\\[^"]\)*\\"//g' \
                            -e 's/"\([^"\\]\|\\.\)*"//g' -e 's/[^,<]*<\([^>,]*\)>[^,]*/\1/g'
                    else
                        env_values "$envfile" "$key"
                    fi
                )
            done
        fi
        node="$(uname -n 2>/dev/null)" || true
        printf '%s\n' "$node"
        if [[ "$node" == *.* && "${node%%.*}" == *[!0123456789]* ]]; then
            printf '%s\n' "${node%%.*}"
        fi
    } | LC_ALL=C awk '/[0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz]/ &&
            !seen[index($0, ".") ? tolower($0) : $0]++ { print length($0) "\t" $0 }' \
      | LC_ALL=C sort -rn | cut -f2- \
      | while IFS= read -r name; do
            if [[ "$name" == *.* ]]; then
                printf 's/\\([%s-]\\{1,\\}\\.\\)*%s/<host>/gI\n' "$w" "$(printf '%s' "$name" \
                    | LC_ALL=C sed -e 's/[][\\/.*^$]/\\&/g' -e 's/^[[:alnum:]_]/\\b&/' -e 's/[[:alnum:]_]$/&\\b/')"
                continue
            fi
            first="$(printf '%s' "${name:0:1}" | LC_ALL=C sed -e 's/[][\\/.*^$]/\\&/g')"
            rest="$(printf '%s' "${name:1}" | LC_ALL=C sed -e 's/[][\\/.*^$]/\\&/g')"
            for _ in 1 2; do
                printf 's/\\([%s.\\n-]\\|[%s\\n]\\/\\)%s\\(%s\\)/\\1\\n\\2/g\n' "$w" "$w" "$first" "$rest"
                printf 's/%s\\(%s[%s\\n-]\\)/\\n\\1/g\n' "$first" "$rest" "$w"
            done
            printf 's/%s%s\\(\\.[%s\\n-]\\{1,\\}\\)*/<host>/g\n' "$first" "$rest" "$w"
            printf 's/\\n/%s/g\n' "$(printf '%s' "${name:0:1}" | LC_ALL=C sed -e 's/[\\&/]/\\&/g')"
        done
}

# env_values <envfile> <key> : every value of <key> in the .env as compose reads it
# -> stdout, one line per line of the value, preceded by the value as the file
# spells it where the two differ. The logs carry the compose form, a copy of the .env
# the file form. Every value of the key, not the last only: compose takes the last
# one, an older one may still stand in a log. The key as compose reads it: behind
# whitespace (ENV_SP), an "export" may lead, '=' or ':' separates, whitespace
# (ENV_SEP) may stand before it. Not a commented-out line: it is no configuration,
# and .env.example carries example values there. The value begins behind the
# separator and the whitespace (ENV_SEP) after it. Unquoted, it ends before " #",
# loses the whitespace (ENV_WS) at its end, and $$ is $. In single quotes it is
# literal but for \' (a '). In double quotes compose decodes \a \b \f \n \r \t \v \$
# \" \\ and \0 with three octal digits (to UTF-8; a \0 without them loses its 0), and
# $$ is $. A quote behind an odd number of backslashes does not end the value, and a
# value that does not end on its line runs on to its closing quote, without one to
# the end of the file. Only the quotes of <key> are followed: the line that opened a
# value may stand in a quoted value of another key, and a line it runs on to be an
# assignment of <key>; such a line gives its own value as well, read as that line
# alone. awk under LC_ALL=C reads the file byte for byte: grep took a line with a
# byte the caller's locale cannot decode (or a file with a NUL byte) for binary and
# left it out.
env_values() {
    LC_ALL=C awk -v key="$2" -v sp="$ENV_SP" -v ws="$ENV_WS" -v sep="$ENV_SEP" '
        BEGIN {
            re = "^" sp "*(export" sp "+)?" key sep "*[=:]"
            dec["a"] = "\007"; dec["b"] = "\010"; dec["f"] = "\014"; dec["n"] = "\n"; dec["r"] = "\r"
            dec["t"] = "\t"; dec["v"] = "\013"; dec["$"] = "$$"; dec["\\"] = "\\"
        }
        function emit() {
            if (q != "\047") gsub(/\$\$/, "$", val)
            if (file != val) print file
            print val
            q = ""
        }
        # take(s): s is a line of a quoted value, behind its opening quote or one the
        # value runs on to; file gets it as spelled, val as compose reads it.
        function take(s,    i, c, d, o) {
            for (i = 1; i <= length(s); i++) {
                c = substr(s, i, 1)
                if (esc) {
                    esc = 0
                    if (c == q) val = val c
                    else if (q == "\047") val = val "\\" c
                    else if (c in dec) val = val dec[c]
                    else if (c == "0") {
                        d = substr(s, i + 1, 3)
                        sub(/[^0123456789].*/, "", d)
                        i += length(d)
                        if (d !~ /^[0123][01234567][01234567]$/) { val = val "\\" d; continue }
                        o = substr(d, 1, 1) * 64 + substr(d, 2, 1) * 8 + substr(d, 3, 1)
                        val = val (o < 128 ? sprintf("%c", o) : sprintf("%c%c", 192 + int(o / 64), 128 + o % 64))
                    } else val = val "\\" c
                } else if (c == "\\") esc = 1
                else if (c == q) { file = file substr(s, 1, i - 1); emit(); return }
                else val = val c
            }
            file = file s "\n"
            if (esc) { val = val "\\"; esc = 0 }
            val = val "\n"
        }
        # start(v): v is a line of key behind its separator; its value begins.
        function start(v,    i) {
            sub("^" sep "*", "", v)
            file = val = ""
            q = substr(v, 1, 1)
            if (q == "\"" || q == "\047") { take(substr(v, 2)); return }
            q = ""
            if (i = index(v, " #")) v = substr(v, 1, i - 1)
            sub("(" ws ")+$", "", v)
            file = val = v
            emit()
        }
        # finish(): a quoted value without its closing quote ends here.
        function finish() { sub(/\n$/, "", file); sub(/\n$/, "", val); emit() }
        q != "" && match($0, re) {
            qq = q; qfile = file; qval = val
            start(substr($0, RLENGTH + 1))
            if (q != "") finish()
            q = qq; file = qfile; val = qval
        }
        q != "" { take($0); next }
        match($0, re) { start(substr($0, RLENGTH + 1)); next }
        END { if (q != "") finish() }
    ' "$1" 2>/dev/null
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
# in env_values), and commented out as well (any '#' among the whitespace in front):
# an old value there may still be valid. The line keeps its form up to the value. A
# value in quotes that does not end on its line runs on to its closing quote (as in
# env_values; not in a commented-out line, compose skips it whole), and the lines it
# runs on to go. awk under LC_ALL=C: byte for byte, a byte outside UTF-8 or a NUL
# byte passes unchanged; every line is printed with a newline. With mask_hosts=1 the
# values of the HOST_KEYS become <masked> as well, and the rest of the file runs
# through host_rules: an address or a name may also stand in a comment or in another
# key.
sanitize_env() {
    local envfile="$1" mask_hosts="${2:-0}" secrets hosts rules prog
    secrets="$(IFS='|'; printf '%s' "${SECRET_KEYS[*]}")"
    # shellcheck disable=SC2016 # an awk program, $0 is awk's
    prog='
        BEGIN {
            lead = "^(" sp "|#)*(export" sp "+)?"
            sre = lead "(" secrets ")" sep "*[=:]" sep "*"
            if (hosts != "") hre = lead "(" hosts ")" sep "*[=:]" sep "*"
        }
        function closes(s,    i, c, esc) {
            for (i = 1; i <= length(s); i++) {
                c = substr(s, i, 1)
                if (esc) esc = 0
                else if (c == "\\") esc = 1
                else if (c == q) return 1
            }
            return 0
        }
        # mask(m): the line up to its value, then m; a quoted value that runs on
        # leaves q set, and the lines up to its closing quote go.
        function mask(m,    v) {
            print substr($0, 1, RLENGTH) m
            if (index(substr($0, 1, RLENGTH), "#")) return
            v = substr($0, RLENGTH + 1)
            q = substr(v, 1, 1)
            if ((q != "\"" && q != "\047") || closes(substr(v, 2))) q = ""
        }
        q != "" { if (closes($0)) q = ""; next }
        match($0, sre) { mask("<redacted>"); next }
        hre != "" && match($0, hre) { mask("<masked>"); next }
        { print }
    '
    if [ "$mask_hosts" != 1 ]; then
        LC_ALL=C awk -v sp="$ENV_SP" -v sep="$ENV_SEP" -v secrets="$secrets" -v hosts= "$prog" "$envfile"
        return
    fi
    rules="$(host_rules "$envfile")"
    hosts="$(IFS='|'; printf '%s' "${HOST_KEYS[*]}")"
    # The rules reach sed through a pipe, not as an argument: the arguments of a process
    # stand in the process list for every user of the host, and the rules carry the
    # names and addresses --mask-hosts is to hide.
    LC_ALL=C awk -v sp="$ENV_SP" -v sep="$ENV_SEP" -v secrets="$secrets" -v hosts="$hosts" "$prog" "$envfile" \
        | LC_ALL=C sed -f <(printf '%s\n' "$rules")
}

main() {
    # Stage, rule file and bundle belong to the running user alone. Here, not at the
    # top: the test sources the script for its functions.
    umask 077
    if [ ! -f docker-compose.yml ]; then
        echo "Fehler: docker-compose.yml nicht gefunden. Bitte im Repo-Root ausfuehren." >&2
        exit 1
    fi

    # `stage` and `partial` are intentionally global, not local: the EXIT trap runs in
    # the global scope after main returns, where a local would be unbound under set -u.
    local ts sedfile
    ts="$(date -u +%Y%m%dT%H%M%SZ)"
    partial=""
    stage="$(mktemp -d)"
    trap 'rm -rf "$stage"; [ -z "$partial" ] || rm -f -- "$partial"' EXIT
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
    # Write to a hidden temp file in the output dir, then rename: a file already under
    # the name is replaced instead of written into with its mode and owner, and a
    # failed run leaves no half-written bundle under the name. As in backup.sh, tar
    # writes only into the file mktemp created (0600 whatever the umask or a default
    # ACL): it lies in the output dir itself, its name is opened for reading only (no
    # O_CREAT, so nothing new appears through a link put there in between) and that
    # same open file again for appending, and the open descriptor is checked before the
    # first byte (a regular file of ours, 0600, one link, still empty, the same inode as
    # the name without following a link); anything else stops the run. pipefail is not
    # needed: tar writes to the descriptor itself. -T: a directory under the name fails
    # the rename instead of taking the bundle in.
    partial="$(mktemp -- "${OUT_DIR%/}/.adminhelper-diagnostics-${ts}.XXXXXX")"
    bundle_fd_ok() {
        [ "${partial%/*}" = "${OUT_DIR%/}" ] && [ -f "$partial" ] && [ ! -L "$partial" ] || return 1
        exec 4<"$partial" || return 1
        exec 3>>/dev/fd/4 || return 1
        [ "$(stat -L -c '%u %a %h %s' /dev/fd/3)" = "$(id -u) 600 1 0" ] \
            && [ "$(stat -L -c '%d %i' /dev/fd/3)" = "$(stat -c '%d %i' -- "$partial")" ]
    }
    bundle_fd_ok || {
        echo "[diagnostics] ERROR: $partial is not a file of its own that only you can read (owner, mode 600, one link, empty) — no bundle written." >&2
        echo "[diagnostics] A target that does not keep Unix owner and mode (as a CIFS, vfat or NTFS mount often does not) cannot hold the bundle safely: write it to a local directory and copy it from there." >&2
        exit 1
    }
    tar -czf - -C "$stage" . >&3
    exec 3>&- 4<&-
    mv -fT -- "$partial" "$archive"
    partial=""

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
