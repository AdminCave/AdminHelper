#!/usr/bin/env bash
#
# restore.sh — restore an AdminHelper backup created by backup.sh (ADR 0001 §5).
#
# Restores the CA crown jewel (ca-pki), both databases, monitoring-data and —
# if present — victoria-data, then brings the stack back up. The restored CA
# means existing agents stay trusted (same Root + intermediates).
#
# Usage (from the repository root):
#   ./scripts/restore.sh <backup.tar.gz> [--yes]
#
# DESTRUCTIVE: replaces the contents of the ca-pki / monitoring-data /
# victoria-data volumes and both databases. The script stops the stack first.
#
# The compose project name (volume prefix) is the one docker compose uses:
# COMPOSE_PROJECT_NAME from the environment or .env, else the directory name.

set -euo pipefail

ARCHIVE="${1:?Usage: restore.sh <backup.tar.gz> [--yes]}"
ASSUME_YES=0
[ "${2:-}" = "--yes" ] && ASSUME_YES=1

if [ ! -f "$ARCHIVE" ]; then
    echo "[restore] FEHLER: Backup nicht gefunden: $ARCHIVE" >&2
    exit 1
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

# A backup is operator-supplied data. Before extracting it onto the host, reject
# a crafted archive that could escape $STAGE: absolute paths, ../ escapes, or
# sym/hardlink members (a symlink member can make tar write through it, out of
# $STAGE, on some tar versions). A genuine backup.sh archive has none of these.
# List to files (not a tar|grep pipeline, which pipefail+SIGPIPE could mask).
tar tzf  "$ARCHIVE" > "$STAGE/.names"
tar tzvf "$ARCHIVE" > "$STAGE/.verbose"
if grep -Eq '^/|(^|/)\.\.(/|$)' "$STAGE/.names"; then
    echo "[restore] FEHLER: Backup enthaelt absolute oder ../-Pfade — abgebrochen." >&2
    exit 1
fi
if grep -Eq '^[lh]' "$STAGE/.verbose"; then
    echo "[restore] FEHLER: Backup enthaelt Sym-/Hardlinks — abgebrochen." >&2
    exit 1
fi
rm -f "$STAGE/.names" "$STAGE/.verbose"
tar xzf "$ARCHIVE" -C "$STAGE" --no-same-owner --no-same-permissions

# cat -v: the MANIFEST comes from the backup; a control character in it must not
# reach the terminal before the question.
[ -f "$STAGE/MANIFEST.txt" ] && { echo "--- MANIFEST ---"; cat -v "$STAGE/MANIFEST.txt"; echo "----------------"; }

# >>> dotenv tokenizer: backup.sh, diagnostics.sh and restore.sh hold the same text, a test keeps it so
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
# the next statement begins. compose refuses a file with a key it cannot read (it sets
# tbad) and reads the value of an empty key like any other, then drops it; here a bad
# key's line is passed over and the next one read, an empty key read like any other.
# tok_alone then reads every line start and the place behind every quote as if it
# began a line, statements one behind the other while each quoted value closes on its
# line: the text may be a value of another key that only looks like an
# assignment, or a file compose refuses, and a secret there must still go.
# A quoted value of a wanted key runs on to its closing quote; with cmt also behind any
# "#" among the whitespace in front of a statement, and there over the commented-out
# lines that follow, to its closing quote or to the first line that is no comment.
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
            if (index(k, " ") || (c != "=" && c != ":" && c != "\n")) {
                tbad = 1
                p = tok_eol(ks) + 1; continue
            }
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

# Without a .env (a fresh host) the backup's env.sanitized can become the .env,
# with an empty CA_ROOT_PASSPHRASE= (compose needs the line; the restored
# hierarchy does not need the value to start). Staged here, written after the
# confirmation and before postgres starts: postgres initialises a new volume with
# the POSTGRES_PASSWORD it finds then.
# env.new keeps the keys of the application only: every statement of a key that compose
# or the docker CLI read for themselves (COMPOSE_*, DOCKER_*, any case) goes, except
# COMPOSE_PROJECT_NAME (the volume prefix of the backed-up project). The statements as
# ENV_TOK finds them (as compose reads the file, and every line start and the place
# behind every quote read alone); cut as backup.sh cuts CA_ROOT_PASSPHRASE: a statement
# that starts inside the closed quoted value of another key keeps that closing quote,
# and a cut behind it that ends inside a statement compose reads takes that statement
# to its end, a changed line keeps the bytes outside those statements, a line left
# with whitespace only goes. Any awk error stops the restore before anything changes.
if [ -f "$STAGE/env.sanitized" ]; then
    # shellcheck disable=SC2016 # an awk program, $0 is awk's
    LC_ALL=C awk -v sp="$ENV_SP" -v sep="$ENV_SEP" "$ENV_TOK"'
        BEGIN { tok_init(sp, sep, 0) }
        function drop(k) { return toupper(k) ~ /^(COMPOSE|DOCKER)_/ && k != "COMPOSE_PROJECT_NAME" }
        function want(k) { return ex || drop(k) }
        function hit(k, ks, vs, ve, q, closed, cs) {
            if (!drop(k)) {
                if (ex && q != "" && closed) { m++; QS[m] = vs; QE[m] = ve }
                if (ex) { ne++; ES[ne] = ks; EE[ne] = ve }
                return
            }
            n++
            A[n] = ks
            B[n] = q == "" ? tok_eol(ve) - 1 : ve
        }
        { S = S $0 "\n" }
        END {
            N = length(S)
            ex = 1; tok_exact(); ex = 0
            tok_run()
            n0 = n
            for (j = 1; j <= n0; j++)
                for (i = 1; i <= m; i++)
                    if (QS[i] < A[j] && A[j] < QE[i] && B[j] >= QE[i]) {
                        if (B[j] > QE[i]) {
                            n++; A[n] = QE[i] + 1; B[n] = B[j]
                            do {
                                g = 0
                                for (r = 1; r <= ne; r++)
                                    if (ES[r] <= B[n] && EE[r] > B[n] && EE[r] >= A[n]) { B[n] = EE[r]; g = 1 }
                            } while (g)
                        }
                        B[j] = QE[i] - 1
                    }
            for (ls = 1; ls <= N; ls = le + 1) {
                le = tok_eol(ls)
                o = ""
                ch = 0
                p = ls
                while (p < le) {
                    c = 0
                    for (j = 1; j <= n; j++) if (A[j] <= p && B[j] >= p && (!c || B[j] > B[c])) c = j
                    if (c) { ch = 1; p = B[c] + 1; continue }
                    x = le
                    for (j = 1; j <= n; j++) if (A[j] > p && A[j] < x) x = A[j]
                    o = o substr(S, p, x - p)
                    p = x
                }
                if (!ch) print substr(S, ls, le - ls)
                else if (o !~ ("^(" sp ")*$")) {
                    sub("(" sp ")+$", "", o)
                    print o
                }
            }
            print "CA_ROOT_PASSPHRASE="
        }
    ' "$STAGE/env.sanitized" > "$STAGE/env.new" \
        || { echo "[restore] ERROR: could not read the .env of the backup; nothing was changed." >&2; exit 1; }
fi
NEW_ENV=""
[ -f .env ] || [ ! -f "$STAGE/env.new" ] || NEW_ENV="$STAGE/env.new"

# The databases go back as the service roles that own them (db-init sets them up from
# these passwords), never as the superuser. Read them the way compose interpolates
# ${VAR}: the environment first, then the env file compose will read (.env, or the
# staged one above). Checked before the stack is stopped.
# In the file the last statement of the key counts, in every form compose reads
# (ENV_TOK): an unquoted value up to a " #" without the whitespace at its end, a quoted
# one between its quotes. A value restore cannot take as compose does (a quote left
# open, a line break, a backslash inside quotes, a "$" outside single quotes: compose
# would expand them) stops the restore with the key named, never its value.
ENV_FILE=.env
[ -z "$NEW_ENV" ] || ENV_FILE="$NEW_ENV"
role_password() {
    local key="$1" value="${!1:-}" rc=0
    if [ -z "$value" ] && [ -f "$ENV_FILE" ]; then
        # shellcheck disable=SC2016 # an awk program, $0 is awk's
        value=$(LC_ALL=C awk -v sp="$ENV_SP" -v sep="$ENV_SEP" -v ws="$ENV_WS" -v key="$key" "$ENV_TOK"'
            BEGIN { tok_init(sp, sep, 0) }
            function want(k) { return k == key }
            function hit(k, ks, vs, ve, q, closed, cs) {
                F = 1; Q = q; C = closed
                V = q == "" ? substr(S, vs, ve - vs + 1) : substr(S, vs + 1, ve - vs - 1)
            }
            { S = S $0 "\n" }
            END {
                N = length(S)
                tok_exact()
                if (!F) exit 0
                if (Q == "") {
                    if (i = index(V, " #")) V = substr(V, 1, i - 1)
                    sub("(" ws ")+$", "", V)
                }
                if (!C || index(V, "\n") || (Q != "" && index(V, "\\")) || (Q != "\047" && index(V, "$"))) exit 3
                printf "%s", V
            }
        ' "$ENV_FILE") || rc=$?
        if [ "$rc" = 3 ]; then
            echo "[restore] ERROR: ${key} in ${ENV_FILE} is no plain value (a quote left open, a line break, a backslash inside quotes or a \$ outside single quotes); restore cannot read it as compose does. Nothing was changed." >&2
            exit 1
        fi
        [ "$rc" = 0 ] || { echo "[restore] ERROR: could not read ${key} from ${ENV_FILE}; nothing was changed." >&2; exit 1; }
    fi
    printf '%s' "$value"
}
check_role_passwords() {
    local key value missing=()
    for key in SERVER_DB_PASSWORD SCHEDULER_DB_PASSWORD MONITOR_DB_PASSWORD CA_DB_PASSWORD; do
        value=$(role_password "$key") || exit 1
        [ -n "$value" ] || missing+=("$key")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        if [ "$ENV_FILE" = .env ]; then
            echo "[restore] ERROR: .env lacks ${missing[*]} — run ./scripts/init-secrets.sh first. The stack keeps running unchanged." >&2
        else
            echo "[restore] ERROR: the .env of the backup lacks ${missing[*]} (a backup from before the per-service roles) — set them in the environment or create .env with ./scripts/init-secrets.sh first. Nothing was changed." >&2
        fi
        exit 1
    fi
}
check_role_passwords

# Compose alone knows the project name (the volume prefix: it reads
# COMPOSE_PROJECT_NAME from .env too) and the pinned postgres image, which the
# helper containers below use instead of an unpinned alpine.
compose_names() {
    local compose_cfg
    if ! compose_cfg=$(docker compose "$@" config </dev/null 2>"$STAGE/.compose-err"); then
        echo "[restore] ERROR: docker compose config failed; nothing was changed:" >&2
        cat -v "$STAGE/.compose-err" >&2
        exit 1
    fi
    PROJECT=$(sed -n '1s/^name: //p' <<<"$compose_cfg")
    HELPER_IMAGE=$(docker compose "$@" config --images postgres </dev/null 2>"$STAGE/.compose-err") || HELPER_IMAGE=""
    if [ -z "$PROJECT" ] || [ -z "$HELPER_IMAGE" ]; then
        echo "[restore] ERROR: docker compose names no project or no postgres image; nothing was changed." >&2
        cat -v "$STAGE/.compose-err" >&2
        exit 1
    fi
    rm -f "$STAGE/.compose-err"
}
# postgres18-data is the volume of PostgreSQL 18; postgres-data, the volume of 17,
# stays after update.sh migrated it, as its rollback, and still marks an installation.
pg_volume_exists() { docker volume inspect "${PROJECT}_postgres18-data" </dev/null >/dev/null 2>&1; }
any_pg_volume_exists() {
    pg_volume_exists || docker volume inspect "${PROJECT}_postgres-data" </dev/null >/dev/null 2>&1
}

# The staged .env counts only where its project has no database volume yet;
# otherwise everything runs as today, against the environment and the .env.
FRESH=0
if [ -n "$NEW_ENV" ]; then
    compose_names --env-file "$NEW_ENV"
    any_pg_volume_exists || FRESH=1
fi
# The images the stack starts with the .env of the backup, named before the question,
# one per service. A value of the backup reaches the terminal here, so each must be one
# line of a plain image reference; control characters or a line break could make the
# list show other images than start. cat -v: compose's message may quote such values.
# Each image comes from the service's own key in compose's canonical YAML (service at
# indent 2, image at 4): `config --images <svc>` names the images of the service's
# dependencies too, in no fixed order (db-init depends on postgres). A value YAML
# quotes or writes as a block fails the check below; a service without an image key
# gets compose's default name <project>-<svc>.
compose_fail() {
    echo "[restore] ERROR: docker compose $1 failed; nothing was changed:" >&2
    cat -v "$STAGE/.compose-err" >&2
    exit 1
}
IMAGES=""
if [ "$FRESH" = 1 ]; then
    SERVICES=$(docker compose --env-file "$NEW_ENV" config --services </dev/null 2>"$STAGE/.compose-err") \
        || compose_fail "config --services"
    NEW_CFG=$(docker compose --env-file "$NEW_ENV" config </dev/null 2>"$STAGE/.compose-err") \
        || compose_fail "config"
    for svc in $SERVICES; do
        img=$(awk -v svc="$svc" '
            /^[^ ]/ { in_svc = ($0 == "services:"); cur = ""; next }
            in_svc && /^  [^ ]/ { cur = substr($0, 3); sub(/:$/, "", cur); next }
            in_svc && cur == svc && /^    image:/ { print substr($0, 12); found = 1 }
            END { if (!found) exit 3 }
        ' <<<"$NEW_CFG") || img="${PROJECT}-${svc}"
        if [ "$img" != "${img%%$'\n'*}" ] || ! LC_ALL=C grep -qxE '[A-Za-z0-9][A-Za-z0-9._/:@+-]*' <<<"$img"; then
            echo "[restore] ERROR: the image of service ${svc} in the .env of the backup is not one plain image reference (letters, digits and ._/:@+- on one line); nothing was changed." >&2
            exit 1
        fi
        IMAGES+="${svc}: ${img}"$'\n'
    done
fi
if [ "$FRESH" = 0 ]; then
    if [ "$ENV_FILE" != .env ]; then ENV_FILE=.env; check_role_passwords; fi
    compose_names
    PGVOL=0; pg_volume_exists && PGVOL=1
    # Without a volume postgres initialises one with POSTGRES_PASSWORD, from the
    # environment (backup_restore_test.sh exports it) or from .env.
    PG_PW=$(role_password POSTGRES_PASSWORD) || exit 1
    if [ "$PGVOL" = 0 ] && [ ! -f .env ] && [ -z "$PG_PW" ]; then
        if [ -n "$NEW_ENV" ]; then
            echo "[restore] ERROR: no .env here and no POSTGRES_PASSWORD in the environment; the .env of the backup belongs to a project whose database volume exists, not to ${PROJECT}. Nothing was changed." >&2
        else
            echo "[restore] ERROR: no .env here, no POSTGRES_PASSWORD in the environment and no env.sanitized in the backup: postgres cannot initialise a new volume; nothing was changed." >&2
        fi
        exit 1
    fi
    if [ "$PGVOL" = 1 ] && [ -z "$PG_PW" ]; then
        echo "[restore] ERROR: the volume ${PROJECT}_postgres18-data exists, but POSTGRES_PASSWORD is set neither in the environment nor in .env; pg_restore could not log in. Nothing was changed." >&2
        exit 1
    fi
fi
SERVER_PW=$(role_password SERVER_DB_PASSWORD) || exit 1
MONITOR_PW=$(role_password MONITOR_DB_PASSWORD) || exit 1

echo "[restore] Ziel-Compose-Projekt: $PROJECT"
[ "$FRESH" = 0 ] || echo "[restore] No .env and no database volume here: the .env of the backup becomes .env before postgres starts."
if [ "$FRESH" = 1 ]; then
    echo "[restore] With it the stack starts these images:"
    printf '%s' "$IMAGES" | sed 's/^/[restore]   /'
fi
echo "[restore] DIES ÜBERSCHREIBT ca-pki, monitoring-data, victoria-data und beide DBs."
if [ "$ASSUME_YES" != 1 ]; then
    printf "Fortfahren? [y/N] "
    read -r ans
    case "$ans" in y|Y|yes|j|J) ;; *) echo "Abgebrochen."; exit 0 ;; esac
fi

if [ "$FRESH" = 1 ]; then
    env_tmp=$(mktemp ./.env.restore.XXXXXX)
    cat "$NEW_ENV" > "$env_tmp"
    mv -f "$env_tmp" .env
    echo "[restore] .env created from the backup (CA_ROOT_PASSPHRASE= empty)."
fi

# Restore a volume from a staged tarball: wipe then extract, with the stack down.
# `docker run` creates the volume if it does not exist (fresh-host DR works).
# The helpers run as root (the files keep their owners) with sh, not the
# postgres entrypoint, and without a network.
restore_volume() {
    vol="$1"; tarball="$2"
    [ -f "$STAGE/$tarball" ] || { echo "[restore] $tarball nicht im Backup — überspringe $vol"; return; }
    echo "[restore] Volume ${PROJECT}_${vol} <- $tarball"
    docker run --rm --network none --entrypoint sh -v "${PROJECT}_${vol}:/dst" -v "$STAGE:/src:ro" "$HELPER_IMAGE" \
        -c 'find /dst -mindepth 1 -delete 2>/dev/null || true; tar xzf "/src/'"$tarball"'" -C /dst'
}

echo "[restore] Stoppe den Stack (Volumes bleiben erhalten)..."
docker compose down

restore_volume ca-pki          ca-pki.tar.gz
restore_volume monitoring-data monitoring-data.tar.gz
restore_volume victoria-data   victoria-data.tar.gz

# ./data is a host bind mount, not a named volume, so restore it directly (it carries
# the server's .secret_key). Stack is down here, matching restore_volume (2.36).
if [ -f "$STAGE/server-data.tar.gz" ]; then
    echo "[restore] ./data <- server-data.tar.gz"
    # Same escape guard as the outer archive above: this inner tarball is unpacked
    # with the host tar directly into the repo (NOT container-jailed like the volume
    # restores), so a crafted symlink/../ member could otherwise write out of ./data.
    tar tzf  "$STAGE/server-data.tar.gz" > "$STAGE/.dnames"
    tar tzvf "$STAGE/server-data.tar.gz" > "$STAGE/.dverbose"
    if grep -Eq '^/|(^|/)\.\.(/|$)' "$STAGE/.dnames" || grep -Eq '^[lh]' "$STAGE/.dverbose"; then
        echo "[restore] FEHLER: server-data.tar.gz enthaelt absolute/../-Pfade oder Sym-/Hardlinks — abgebrochen." >&2
        exit 1
    fi
    rm -f "$STAGE/.dnames" "$STAGE/.dverbose"
    mkdir -p data
    # Wipe + extract as container-root, symmetric to how backup.sh captured this
    # dir (dump_dir tars /app/data INSIDE the server container) and to
    # restore_volume above. The server container owns these files as root, so a
    # host-side tar run by the invoking user cannot clean up or write into the
    # dir at all — that failed silently (find) and then died confusingly
    # ("Cannot utime" / "Cannot mkdir: Permission denied"), breaking DR exactly
    # when it is needed. The escape guard above still applies (defense in
    # depth); the extraction is now jailed to /dst as well.
    docker run --rm --network none --entrypoint sh -v "$PWD/data:/dst" -v "$STAGE:/src:ro" "$HELPER_IMAGE" \
        -c 'find /dst -mindepth 1 -delete 2>/dev/null || true; tar xzf /src/server-data.tar.gz -C /dst' \
        || { echo "[restore] FEHLER: ./data konnte nicht wiederhergestellt werden." >&2; exit 1; }
else
    echo "[restore] server-data.tar.gz nicht im Backup — überspringe ./data"
fi

echo "[restore] Starte postgres für den DB-Restore..."
docker compose up -d postgres
# Wait for postgres to accept connections — over TCP, the way restore_db connects.
# On a fresh volume the image's init server listens on the socket only, so a
# socket probe says ready while 127.0.0.1 still refuses until the restart.
ready=0
for _ in $(seq 1 60); do
    if docker compose exec -T postgres pg_isready -h 127.0.0.1 -U adminhelper >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
# The loop just falling through on timeout would let restore_db run against a
# not-ready postgres and fail confusingly mid-restore — abort clearly (4.54).
[ "$ready" = 1 ] || { echo "[restore] FEHLER: postgres nach 60s nicht bereit — Abbruch." >&2; exit 1; }

# db-init creates the roles and, on a fresh host, adminhelper_monitor, and hands the
# schema with everything already in it to its role: only the owner may drop what
# --clean drops, and a restore as the superuser would leave objects the service
# roles cannot touch.
echo "[restore] db-init: roles, monitoring DB, ownership..."
docker compose run --rm -T db-init

# restore_db <db> <role> <password>: the password goes in through the environment of
# docker compose (-e without a value), never through an argv.
restore_db() {
    db="$1"; role="$2"
    [ -f "$STAGE/$db.dump" ] || { echo "[restore] $db.dump nicht im Backup — überspringe"; return; }
    echo "[restore] pg_restore $db as $role"
    PGPASSWORD="$3" docker compose exec -T -e PGPASSWORD postgres \
        pg_restore -h 127.0.0.1 -U "$role" --clean --if-exists --no-owner --no-privileges -d "$db" \
        < "$STAGE/$db.dump"
}

# The certificate register (R-0224) admits only the certificates it recorded, and the
# restored copy lacks those issued or renewed since the backup. Moving its install
# time to now reopens the transition: they are taken over at first contact, for 90
# days from here. Without the table (a backup from before the register), the server's
# migration writes the time itself when it starts.
reopen_register_transition() {
    [ -f "$STAGE/adminhelper.dump" ] || return 0
    echo "[restore] certificate register: transition reopened as of now (90 days)"
    PGPASSWORD="$SERVER_PW" docker compose exec -T -e PGPASSWORD postgres \
        psql -h 127.0.0.1 -U ah_server -d adminhelper -v ON_ERROR_STOP=1 -q \
        <<'SQL'
DO $$
BEGIN
    IF to_regclass('public.certificate_register_state') IS NOT NULL THEN
        UPDATE certificate_register_state SET installed_at = timezone('UTC', now());
    END IF;
END
$$;
SQL
}

restore_db adminhelper ah_server "$SERVER_PW"
reopen_register_transition
restore_db adminhelper_monitor ah_monitor "$MONITOR_PW"

echo "[restore] Starte den kompletten Stack..."
docker compose up -d

# .env: never clobber an existing one (it may hold the live CA_ROOT_PASSPHRASE).
if [ "$FRESH" = 0 ] && [ -f "$STAGE/env.sanitized" ]; then
    ( umask 077; cat "$STAGE/env.new" > ./.env.restored )
    chmod 600 ./.env.restored
    echo "[restore] .env aus dem Backup nach ./.env.restored geschrieben (mit leerer Zeile CA_ROOT_PASSPHRASE=)."
    if [ "$PGVOL" = 0 ]; then
        echo "[restore]   -> the database volume was initialised with POSTGRES_PASSWORD of the current .env:"
        echo "[restore]      keep that one when you take values over from .env.restored."
    fi
fi

echo "[restore] Fertig. Der ca-issuer lädt die wiederhergestellte Hierarchie — Agenten bleiben vertraut."
