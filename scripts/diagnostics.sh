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
# It is masked at word edges only (a short user like admin must not eat into
# adminhelper), and like every value at every place (REDACT_AWK): a user that is a word
# of another secret cannot cut that secret in two, and a secret inside the user cannot
# cut the user.
SECRET_KEYS=(SECRET_KEY POSTGRES_PASSWORD SERVER_DB_PASSWORD SCHEDULER_DB_PASSWORD MONITOR_DB_PASSWORD CA_DB_PASSWORD
    MONITOR_API_KEY CA_ROOT_PASSPHRASE ADMIN_PASSWORD SMTP_PASSWORD SMTP_USER)

# The .env keys whose values name this installation: host names, addresses, networks
# and mail addresses. Masked only with --mask-hosts — a wrong domain or SAN is a
# frequent cause the bundle is meant to show.
HOST_KEYS=(DOMAIN EXTRA_SANS CA_FRPS_EXTRA_SANS ALLOWED_IPS FRP_SERVER_ADDR TRUSTED_PROXIES SMTP_HOST SMTP_FROM)

# mask_error : the message of a mask program that failed; the run then writes no bundle.
mask_error() {
    echo "[diagnostics] ERROR: the values of .env could not be read for the masking (see above) — no bundle written." >&2
}

# build_redaction_sedfile <envfile> <sedfile> [mask_hosts]
# Writes the rule file of redact: the .env secret values, one per line as a sed comment
# "#=<key> <value>" that awk reads in redact and sed passes over, and with mask_hosts=1
# the sed rules of host_rules behind them. Each value once; a value of SMTP_USER that is
# also one of another key is that key's, without word edges. A line of a value that is
# only whitespace (ENV_WS) is no value: it holds no secret, and would mask every blank of
# the logs.
build_redaction_sedfile() {
    local envfile="$1" sedfile="$2" mask_hosts="${3:-0}"
    : > "$sedfile"
    if [ -f "$envfile" ]; then
        local key list
        # The list is taken whole before it is written: a mask program that fails
        # (env_values, sed, awk, sort) fails the function, and the caller writes no
        # bundle. Call it as a command of its own, never under || or if: that turns
        # set -e off in it, and a rule that cannot be written would no longer stop the run.
        list="$(
            for key in "${SECRET_KEYS[@]}"; do
                env_values "$envfile" "$key" | LC_ALL=C sed -e "s/^/$key /" || exit 1
            done | LC_ALL=C awk -v ws="$ENV_WS" '
                # Skip whitespace only or the well-known placeholder (not a real secret).
                { v = substr($0, index($0, " ") + 1) }
                v !~ ("^" ws "*$") && v != "change-me-in-production" && (!(v in by) || by[v] == "SMTP_USER") {
                    by[v] = $1
                }
                END { for (v in by) print "#=" by[v] " " v }
            ' | LC_ALL=C sort
        )" || { mask_error; return 1; }
        [ -z "$list" ] || printf '%s\n' "$list" >> "$sedfile"
    fi
    if [ "$mask_hosts" = 1 ]; then
        host_rules "$envfile" >> "$sedfile" || { mask_error; return 1; }
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
    local envfile="$1" key form forms node name first rest
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
                # Taken whole first, as in build_redaction_sedfile: a failing mask
                # program fails the pipe, and host_rules with it.
                forms="$(
                    if [ "$key" = SMTP_FROM ]; then
                        env_values "$envfile" "$key" | LC_ALL=C sed -e 's/\\"\([^"\\]\|\\[^"]\)*\\"//g' \
                            -e 's/"\([^"\\]\|\\.\)*"//g' -e 's/[^,<]*<\([^>,]*\)>[^,]*/\1/g'
                    else
                        env_values "$envfile" "$key"
                    fi
                )" || exit 1
                [ -n "$forms" ] || continue
                while IFS= read -r form; do
                    IFS=$', \t<>' read -r -a parts <<< "$form"
                    printf '%s\n' "${parts[@]}"
                done < <(printf '%s\n' "$forms")
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

# >>> dotenv tokenizer: diagnostics.sh and backup.sh hold the same text, a test keeps it so
# The whitespace of a .env line as compose reads it, EREs for LC_ALL=C awk with the
# bytes spelled out. ENV_WS is what Go's unicode.IsSpace calls whitespace: ASCII
# whitespace and the UTF-8 forms of NEL, NBSP, OGHAM SPACE MARK, EN QUAD to HAIR SPACE,
# LINE and PARAGRAPH SEPARATOR, NARROW NBSP, MEDIUM MATHEMATICAL SPACE and IDEOGRAPHIC
# SPACE; compose trims it from the end of an unquoted value. In front of a key it skips
# that and a BOM: ENV_SP. Between key and separator, and between separator and value,
# it skips ASCII whitespace, NEL and NBSP: ENV_SEP.
ENV_WS="([[:space:]]|"$'\xc2[\x85\xa0]|\xe1\x9a\x80|\xe2\x80[\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89\x8a\xa8\xa9\xaf]|\xe2\x81\x9f|\xe3\x80\x80)'
ENV_SP="(${ENV_WS}|"$'\xef\xbb\xbf)'
ENV_SEP="([[:space:]]|"$'\xc2[\x85\xa0])'

# ENV_TOK: awk functions that find the statements of a .env, for LC_ALL=C awk (byte
# for byte: a NUL byte or a byte outside UTF-8 passes). The program appends every line
# with a newline to S, defines want(k) (1 for a key whose values it needs) and
# hit(k, ks, vs, ve, q, closed, cs) (called for such a key only: a statement of k from
# ks, its value from vs to ve:
# q is its quote, "" for an unquoted value that ends before its newline; closed is 0
# for a quoted value without its closing quote; cs is the place of the "#" in front of
# a commented-out statement, 0 outside a comment), and calls tok_init(sp, sep,
# cmt) in BEGIN and tok_run() in END. A statement may be found more than once.
# tok_exact reads the file as compose does (compose-go dotenv: parse,
# getStatementStart, locateKeyName, extractVarValue): a quoted value runs on to its
# closing quote over any number of lines, whatever key it belongs to, and behind it
# the next statement begins. compose refuses a file with a key it cannot read; such a
# line is passed over here and the next one read. tok_alone then reads every line
# start and the place behind every quote as if it began a line, statements one behind
# the other while each quoted value closes on its line: the text may be a value of
# another key that only looks like an assignment, or a file compose refuses, and a
# secret there must still go. A quoted value of a wanted key runs on to its closing
# quote; with cmt also behind any "#" among the whitespace in front of a statement,
# and there over the commented-out lines that follow, to its closing quote or to the
# first line that is no comment.
ENV_TOK='
    function tok_init(sp, sep, cmt) {
        tsp = "^(" sp ")*"
        tspl = tok_nonl(sp)
        hs = tok_nonl(sep)
        tlead = "^(" tspl (cmt ? "|#" : "") ")*"
        tcre = "^(" tspl ")*#"
        tgre = "^(export(" tspl ")+)?[^[:space:]=:#\"\047]+(" hs ")*[=:]"
        tkey = "^(" hs "|[][A-Za-z0-9_.-]|[\200-\377])*"
        tcmt = cmt
    }
    # tok_nonl(re): re without the newline: a statement ends at its line.
    function tok_nonl(re) { gsub(/\[\[:space:\]\]/, "[ \t\v\f\r]", re); return re }
    # tok_eol(p): the place of the newline that ends the line of p.
    function tok_eol(p) { return p + index(substr(S, p), "\n") - 1 }
    # tok_close(s, c): the place of the quote c that closes a quoted value in s, 0
    # without one; a quote behind a backslash does not.
    function tok_close(s, c,    i, e, x) {
        for (i = 1; i <= length(s); i++) {
            x = substr(s, i, 1)
            if (e) e = 0
            else if (x == "\\") e = 1
            else if (x == c) return i
        }
        return 0
    }
    function tok_exact(    p, t, k, c, i, ks) {
        p = 1
        while (p <= N) {
            t = substr(S, p)
            match(t, tsp)
            p += RLENGTH
            if (p > N) return
            if (substr(S, p, 1) == "#") { p = tok_eol(p) + 1; continue }
            ks = p
            t = substr(S, p)
            if (match(t, "^export[ \t\f\r]")) { match(t, "^export(" hs ")*"); p += RLENGTH }
            match(substr(S, p), tkey)
            k = substr(S, p, RLENGTH)
            c = substr(S, p + RLENGTH, 1)
            p += RLENGTH + 1
            sub("(" hs ")+$", "", k)
            if (k == "" || index(k, " ") || (c != "=" && c != ":" && c != "\n")) { p = tok_eol(ks) + 1; continue }
            if (c == "\n") continue
            match(substr(S, p), "^(" hs ")*")
            p += RLENGTH
            c = substr(S, p, 1)
            if (c == "\"" || c == "\047") {
                i = tok_close(substr(S, p + 1), c)
                if (want(k)) hit(k, ks, p, i ? p + i : N, c, i > 0, 0)
                p = i ? p + i + 1 : N + 1
                continue
            }
            i = tok_eol(p)
            if (want(k)) hit(k, ks, p, i - 1, "", 1, 0)
            p = i + 1
        }
    }
    # tok_alone(p, h): the statements from p on as described above; h: p stands in a
    # commented-out line.
    function tok_alone(p, h,    t, k, c, i, j, e, ks, cs, x) {
        while (1) {
            t = substr(S, p)
            match(t, tlead)
            if (i = index(substr(t, 1, RLENGTH), "#")) { h = 1; if (!cs) cs = p + i - 1 }
            p += RLENGTH
            t = substr(S, p)
            if (!match(t, tgre)) return
            k = substr(t, 1, RLENGTH - 1)
            sub("^export(" tspl ")+", "", k)
            sub("(" hs ")+$", "", k)
            ks = p
            p += RLENGTH
            match(substr(S, p), "^(" hs ")*")
            p += RLENGTH
            c = substr(S, p, 1)
            e = tok_eol(p)
            if (c != "\"" && c != "\047") { if (want(k)) hit(k, ks, p, e - 1, "", 1, cs); return }
            i = tok_close(substr(S, p + 1), c)
            if (i && p + i < e) {
                if (want(k)) hit(k, ks, p, p + i, c, 1, cs)
                p += i + 1
                continue
            }
            if (!want(k)) return
            if (!(h && tcmt)) { hit(k, ks, p, i ? p + i : N, c, i > 0, cs); return }
            for (x = e + 1; x <= N && substr(S, x, tok_eol(x) - x) ~ tcre; x = tok_eol(x) + 1)
                if (j = tok_close(substr(S, x, tok_eol(x) - x), c)) { hit(k, ks, p, x + j - 1, c, 1, cs); return }
            hit(k, ks, p, x - 2, c, 0, cs)
            return
        }
    }
    function tok_run(    p, c, h) {
        N = length(S)
        tok_exact()
        for (p = 1; p <= N; p++) {
            if (p == 1 || substr(S, p - 1, 1) == "\n") {
                h = substr(S, p, tok_eol(p) - p) ~ tcre
                tok_alone(p, 0)
            }
            c = substr(S, p, 1)
            if (c == "\"" || c == "\047") tok_alone(p + 1, h)
        }
    }
'
# <<< dotenv tokenizer

# env_values <envfile> <key> : every value of <key> in the .env as compose reads it
# -> stdout, one line per line of the value, preceded by the value as the file
# spells it where the two differ. The logs carry the compose form, a copy of the .env
# the file form. Every value of the key, not the last only: compose takes the last
# one, an older one may still stand in a log. The statements as ENV_TOK finds them,
# not in a comment: .env.example carries example values there. Unquoted, a value ends
# before " #", loses the whitespace (ENV_WS) at its end, and $$ is $. In single quotes
# it is literal but for \' (a '). In double quotes compose decodes \a \b \f \n \r \t
# \v \$ \" \\ and \0 with three octal digits (to UTF-8; a \0 without them loses its 0),
# and $$ is $. A value without its closing quote runs to the end of the file. awk
# under LC_ALL=C reads the file byte for byte: grep took a line with a byte the
# caller's locale cannot decode (or a file with a NUL byte) for binary and left it out.
env_values() {
    LC_ALL=C awk -v key="$2" -v sp="$ENV_SP" -v ws="$ENV_WS" -v sep="$ENV_SEP" "$ENV_TOK"'
        BEGIN {
            tok_init(sp, sep, 0)
            dec["a"] = "\007"; dec["b"] = "\010"; dec["f"] = "\014"; dec["n"] = "\n"; dec["r"] = "\r"
            dec["t"] = "\t"; dec["v"] = "\013"; dec["$"] = "$$"; dec["\\"] = "\\"
        }
        function want(k) { return k == key }
        function hit(k, ks, vs, ve, q, closed, cs,    s, i, c, d, o, esc, val) {
            if (k != key) return
            if (q == "") {
                s = substr(S, vs, ve - vs + 1)
                if (i = index(s, " #")) s = substr(s, 1, i - 1)
                sub("(" ws ")+$", "", s)
                val = s
            } else {
                s = substr(S, vs + 1, ve - vs - closed)
                if (!closed) sub(/\n$/, "", s)
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
                    else val = val c
                }
                if (esc) val = val "\\"
            }
            if (q != "\047") gsub(/\$\$/, "$", val)
            if (s != val) print s
            print val
        }
        { S = S $0 "\n" }
        END { tok_run() }
    ' "$1"
}

# REDACT_AWK: the awk program of redact. It finds on each line every place of a value of
# the rule file (of SMTP_USER at word edges only) and every generic token form that may
# appear in logs regardless of .env. The query parameters stand in the request line of
# the gateway's and the server's access logs (nginx combined, uvicorn); other query
# values stay readable. All places are found on the line as it came, and places that
# overlap are masked as one: a value inside a token, a token inside a value or the two
# side by side without a separator leave no rest of either (masked one after the other,
# the first cut the second, and its rest no longer matched). Such a run begins with its
# leftmost place, the longest of those: a token form keeps its name (Bearer, the query
# parameter, /hooks/trigger/, adminhelper_prov_) unless a value overlaps it, a JWT
# becomes <redacted-jwt>, all else <redacted>. Repetitions are spelled out: older mawk
# knows no {n,}.
REDACT_AWK='
    function rep(c, k,    s) { s = ""; while (k-- > 0) s = s c; return s }
    # tok(re, s, kind, pre): every match of re in s, one behind the other; pre is the
    # length of the name the match begins with. gsub marks each match with a newline,
    # which no line holds, and split cuts there: one pass, however many matches.
    function tok(re, s, kind, pre,    t, P, k, i, q) {
        t = s
        if (!gsub(re, "\n&", t)) return
        k = split(t, P, "\n")
        q = length(P[1]) + 1
        for (i = 2; i <= k; i++) {
            match(P[i], "^(" re ")")
            n++; A[n] = q; B[n] = q + RLENGTH - 1; K[n] = kind
            L[n] = kind == "query" ? index(substr(P[i], 1, RLENGTH), "=") : pre
            q += length(P[i])
        }
    }
    # mark(s, f): what the run that begins with place f becomes.
    function mark(s, f,    y) {
        if (K[f] == "jwt") return "<redacted-jwt>"
        for (y = A[f]; y < A[f] + L[f]; y++) if (y in VS) return "<redacted>"
        return L[f] ? (K[f] == "bearer" ? "Bearer " : substr(s, A[f], L[f])) "<redacted>" : "<redacted>"
    }
    BEGIN {
        w = "[A-Za-z0-9_-]"; b = "[A-Za-z0-9._-]"; h = "[^/?[:space:]\"]"
        re_jwt = "eyJ" rep(w, 6) w "*[.]" rep(w, 6) w "*[.]" w "*"
        re_bearer = "[Bb]earer " rep(b, 8) b "*"
        re_query = "[?&](api_key|token|access_token)=[^&[:space:]\"]+"
        re_hook = "/hooks/trigger/" rep(h, 8) h "*"
        re_prov = "adminhelper_prov_" rep(w, 8) w "*"
        while ((getline l < rf) > 0)
            if (substr(l, 1, 2) == "#=") {
                nv++
                V[nv] = substr(l, index(l, " ") + 1)
                U[nv] = substr(l, 3, index(l, " ") - 3) == "SMTP_USER"
            }
        close(rf)
    }
    {
        s = $0
        n = 0
        tok(re_jwt, s, "jwt", 0)
        tok(re_bearer, s, "bearer", 7)
        tok(re_query, tolower(s), "query", 0)
        tok(re_hook, s, "hook", 15)
        tok(re_prov, s, "prov", 17)
        for (i = 1; i <= nv; i++)
            for (p = 1; j = index(substr(s, p), V[i]); p = q + 1) {
                q = p + j - 1
                e = q + length(V[i]) - 1
                if (U[i] && ((substr(V[i], 1, 1) ~ /[A-Za-z0-9_]/ && substr(s, q - 1, 1) ~ /[A-Za-z0-9_]/) \
                    || (substr(V[i], length(V[i])) ~ /[A-Za-z0-9_]/ && substr(s, e + 1, 1) ~ /[A-Za-z0-9_]/)))
                    continue
                n++; A[n] = q; B[n] = e; K[n] = "value"; L[n] = 0
            }
        if (!n) { print s; next }
        # By start: the longest place there (the first of equals), and where values begin.
        delete E; delete F; delete VS
        for (j = 1; j <= n; j++) {
            if (!(A[j] in E) || B[j] > E[A[j]]) { E[A[j]] = B[j]; F[A[j]] = j }
            if (K[j] == "value") VS[A[j]] = 1
        }
        p = 1; f = 0; ls = length(s)
        for (x = 1; x <= ls; x++) {
            if (!(x in E)) continue
            if (f && x <= e) { if (E[x] > e) e = E[x]; continue }
            if (f) { printf "%s%s", substr(s, p, A[f] - p), mark(s, f); p = e + 1 }
            f = F[x]; e = E[x]
        }
        printf "%s%s%s\n", substr(s, p, A[f] - p), mark(s, f), substr(s, e + 1)
    }
'

# redact <rulefile> : filter stdin -> stdout through the rule file of
# build_redaction_sedfile: REDACT_AWK, then the sed rules of --mask-hosts. LC_ALL=C:
# byte for byte. Under UTF-8, `[^…]` stops in front of a byte outside UTF-8, and the
# rest of a token would stay.
redact() {
    LC_ALL=C awk -v rf="$1" "$REDACT_AWK" | LC_ALL=C sed -f "$1"
}

# sanitize_env <envfile> [mask_hosts] : mask secret VALUES by key, for env.sanitized
# -> stdout. The second, independent redaction path — build_redaction_sedfile redacts
# by value, this redacts by key, so a secret is masked even if its value never
# appeared in a log. The statements as ENV_TOK finds them, commented out as well (any
# '#' among the whitespace in front of a statement): an old value there may still be
# valid. A line keeps its form up to the first such value, then <redacted>, and the
# rest of the line goes; so do the lines a value runs on to. The line that closes a
# value goes too, unless another such value begins behind its closing quote: then the
# line is printed from behind the quote up to that value. awk under LC_ALL=C: byte for
# byte, a byte outside UTF-8 or a NUL byte passes unchanged; every line is printed with
# a newline. With mask_hosts=1 the values of the HOST_KEYS become <masked> as well, and
# the rest of the file runs through host_rules: an address or a name may also stand in
# a comment or in another key.
sanitize_env() {
    local envfile="$1" mask_hosts="${2:-0}" secrets hosts="" rules prog
    secrets="${SECRET_KEYS[*]}"
    # shellcheck disable=SC2016 # an awk program, $0 is awk's
    prog="$ENV_TOK"'
        BEGIN {
            tok_init(sp, sep, 1)
            split(secrets, a, " "); for (i in a) sec[a[i]] = 1
            split(hosts, a, " "); for (i in a) hst[a[i]] = 1
        }
        function want(k) { return (k in sec) || (k in hst) }
        function hit(k, ks, vs, ve, q, closed, cs) {
            n++
            A[n] = vs; B[n] = ve; M[n] = (k in sec) ? "<redacted>" : "<masked>"
        }
        { S = S $0 "\n" }
        END {
            tok_run()
            for (ls = 1; ls <= N; ls = le + 1) {
                le = tok_eol(ls)
                # from: the first byte of the line behind every value that covers it
                from = ls
                do {
                    more = 0
                    for (j = 1; j <= n; j++) if (A[j] < from && B[j] >= from) { from = B[j] + 1; more = 1 }
                } while (more)
                best = 0
                for (j = 1; j <= n; j++) if (A[j] >= from && A[j] < le && (!best || A[j] < A[best])) best = j
                if (best) print substr(S, from, A[best] - from) M[best]
                else if (from == ls) print substr(S, ls, le - ls)
            }
        }
    '
    if [ "$mask_hosts" != 1 ]; then
        LC_ALL=C awk -v sp="$ENV_SP" -v sep="$ENV_SEP" -v secrets="$secrets" -v hosts= "$prog" "$envfile"
        return
    fi
    rules="$(host_rules "$envfile")" || return 1
    hosts="${HOST_KEYS[*]}"
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
        sanitize_env .env "$MASK_HOSTS" > "$stage/env.sanitized" || {
            echo "[diagnostics] ERROR: .env could not be masked for env.sanitized (see above) — no bundle written." >&2
            exit 1
        }
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
