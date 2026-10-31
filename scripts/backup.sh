#!/usr/bin/env bash
#
# backup.sh — full AdminHelper backup including the CA crown jewel (ADR 0001 §5).
#
# Bundles into one timestamped tarball:
#   - ca-pki              the unified PKI (Root + intermediates) — THE crown jewel
#   - postgres            pg_dump (custom format) of both DBs
#   - monitoring-data     the monitoring service's local state
#   - victoria-data       metric history (optional, large — pass --with-victoria)
#   - env.sanitized       .env WITHOUT CA_ROOT_PASSPHRASE (see below)
#
# Deliberately NOT backed up: gateway-certs / frps-certs (the ca-issuer
# re-provisions them from ca-pki on boot) and ./certs (obsolete since the
# gateway took over TLS).
#
# >>> CA_ROOT_PASSPHRASE is intentionally stripped from the backup <<<
# It encrypts the Root key, which IS in the backup — storing both together
# would defeat the encryption (ADR 0001 §5 / D7). Keep the passphrase
# separately (password manager). A restored stack runs WITHOUT it; the
# passphrase is only needed to rotate intermediates later.
#
# Run from the repository root with the stack up:
#   ./scripts/backup.sh [--with-victoria] [--output DIR]

set -euo pipefail
# Everything this script creates (a new output dir, the staging files, the archive)
# holds the PKI, both DB dumps or the .env: owner-only from the start.
umask 077

OUT_DIR="./backups"
WITH_VICTORIA=0

while [ $# -gt 0 ]; do
    case "$1" in
        --with-victoria) WITH_VICTORIA=1 ;;
        --output) OUT_DIR="${2:?--output needs a directory}"; shift ;;
        -h|--help) awk 'NR > 1 { if (!/^#/) exit; print }' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

if ! docker compose ps --status running --quiet postgres >/dev/null 2>&1 \
    || [ -z "$(docker compose ps --status running --quiet postgres)" ]; then
    echo "[backup] FEHLER: Der Stack (postgres/ca-issuer) muss laufen. 'docker compose up -d' zuerst." >&2
    exit 1
fi

TS=$(date +%Y-%m-%d_%H-%M-%S)
STAGE=$(mktemp -d)
PARTIAL=""
trap 'rm -rf "$STAGE"; [ -z "$PARTIAL" ] || rm -f -- "$PARTIAL"' EXIT

mkdir -p "$OUT_DIR"

# tar a service's mounted data dir to a staging file (uses the running container,
# so no compose-project volume-name guessing is needed).
dump_dir() {
    svc="$1"; src="$2"; out="$3"
    echo "[backup] $svc:$src -> $out"
    # tar over a live-written dir can exit 1 ("file changed as we read it"), which
    # would abort the whole backup under set -e though the archive is still usable.
    # Tolerate exit 1 (warn); a real error (exit 2) still aborts (4.120).
    rc=0
    docker compose exec -T "$svc" tar czf - -C "$src" . > "$STAGE/$out" || rc=$?
    if [ "$rc" -ne 0 ]; then
        [ "$rc" -eq 1 ] || { echo "[backup] FEHLER: tar $svc:$src exit $rc." >&2; return "$rc"; }
        echo "[backup] WARN: $svc:$src aenderte sich beim Lesen (tar exit 1) — Archiv ggf. inkonsistent." >&2
    fi
    # A docker-layer failure (service not running) also exits 1 but writes NOTHING to
    # stdout — and the preflight only checks postgres, so a stopped ca-issuer/monitoring
    # would otherwise slip through as a benign "file changed" tar warning and leave a
    # 0-byte crown-jewel archive that only surfaces at restore time. Require a non-empty
    # archive so a missing service fails the backup, not the disaster recovery.
    [ -s "$STAGE/$out" ] || { echo "[backup] FEHLER: $svc:$src ergab ein leeres Archiv (Service nicht laufend?)." >&2; return 1; }
}

dump_db() {
    db="$1"
    echo "[backup] pg_dump $db -> $db.dump"
    docker compose exec -T postgres sh -c \
        "PGPASSWORD=\$POSTGRES_PASSWORD pg_dump -h 127.0.0.1 -U adminhelper -Fc \"$db\"" \
        > "$STAGE/$db.dump"
}

# --- The crown jewel + service state ---------------------------------------
dump_dir ca-issuer  /app/data                 ca-pki.tar.gz
dump_dir monitoring /app/data                 monitoring-data.tar.gz
# ./data holds the server's auto-generated .secret_key (persisted when SECRET_KEY is
# the placeholder — the default for a bare `docker compose up` without init-secrets).
# Without it a fresh-host restore signs with a new key: all sessions invalid and any
# SECRET_KEY-encrypted data unreadable. It's tiny, so always include it (2.36).
dump_dir server     /app/data                 server-data.tar.gz
if [ "$WITH_VICTORIA" = 1 ]; then
    dump_dir victoria /victoria-metrics-data  victoria-data.tar.gz
fi

# --- Databases --------------------------------------------------------------
dump_db adminhelper
dump_db adminhelper_monitor

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

# --- Secrets (passphrase stripped) -----------------------------------------
if [ -f .env ]; then
    # Drops every statement of CA_ROOT_PASSPHRASE that ENV_TOK finds (as compose reads
    # the file, and every line start and the place behind every quote read alone), the
    # commented-out ones too: in a comment from its '#' to the end of the line its value
    # ends on. A changed line keeps the bytes outside those statements without the
    # whitespace at its end; a commented-out line or one left with whitespace only goes.
    # CA_ROOT_PASSPHRASE_OLD and the like are other keys and stay. LC_ALL=C: awk reads
    # bytes, so a NUL byte or a byte the caller's locale cannot decode passes unchanged
    # (grep took such a file for binary and left lines out). Every other line is printed
    # as is, the last with a newline; any awk error (a write error too) aborts the
    # backup.
    # shellcheck disable=SC2016 # an awk program, $0 is awk's
    LC_ALL=C awk -v sp="$ENV_SP" -v sep="$ENV_SEP" "$ENV_TOK"'
        BEGIN { tok_init(sp, sep, 1) }
        function want(k) { return k == "CA_ROOT_PASSPHRASE" }
        function hit(k, ks, vs, ve, q, closed, cs) {
            n++
            A[n] = cs ? cs : ks
            B[n] = (cs || q == "") ? tok_eol(ve) - 1 : ve
        }
        { S = S $0 "\n" }
        END {
            tok_run()
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
                else if (substr(S, ls, le - ls) !~ tcre && o !~ ("^(" sp ")*$")) {
                    sub("(" sp ")+$", "", o)
                    print o
                }
            }
        }
    ' .env > "$STAGE/env.sanitized" \
        || { echo "[backup] ERROR: could not copy .env without CA_ROOT_PASSPHRASE — backup aborted." >&2; exit 1; }
    echo "[backup] .env gesichert (CA_ROOT_PASSPHRASE entfernt — getrennt aufbewahren!)"
fi

# --- Manifest ---------------------------------------------------------------
cat > "$STAGE/MANIFEST.txt" <<EOF
AdminHelper backup
created:        $TS
victoria-data:  $([ "$WITH_VICTORIA" = 1 ] && echo "included" || echo "skipped (--with-victoria)")

Restore:  ./scripts/restore.sh adminhelper-backup-$TS.tar.gz

CA_ROOT_PASSPHRASE is NOT in this archive (it encrypts the Root key, which is).
Keep it separately. A restored stack runs without it; it is only needed to
rotate intermediates.
EOF

ARCHIVE="$OUT_DIR/adminhelper-backup-$TS.tar.gz"
# Write to a hidden temp file in the output dir, then rename: mktemp creates it 0600
# whatever the umask, so the archive is never readable by others, not even while tar
# writes it; and a failed or aborted write (disk full, Ctrl-C) leaves no truncated
# archive under a name that restore.sh and the docs treat as valid. A rename within
# the dir is atomic and keeps the mode (as in pg-backup.sh). -T: a directory under the
# archive name fails the rename instead of taking the archive in, and a symlink there
# (to a directory too) is replaced, its target left alone (as in update.sh). The
# rename can reach the disk before the data does, and a power loss would then leave
# the name on an empty or truncated file: sync the file before the rename and the
# dir (its new entry) after it; only these two, a bare sync flushes every filesystem.
#
# tar writes only into the file mktemp created: it lies in the output dir itself, the
# name is opened for reading only (no O_CREAT, so nothing new appears through a link
# put there in between) and that same open file again for appending, without
# truncating it, and the open descriptor is checked before the first byte (a
# regular file of ours, 0600, one link, still empty, the same file as the name, which
# is no link).
# Anything else under that name (a link to a file or a FIFO elsewhere) aborts the
# backup instead of taking the archive. The mode comes from mktemp and stays 0600 in a
# dir with a default ACL; a target without Unix owner and mode fails the check.
PARTIAL=$(mktemp "${OUT_DIR%/}/.adminhelper-backup-$TS.XXXXXX")
archive_fd_ok() {
    [ "${PARTIAL%/*}" = "${OUT_DIR%/}" ] && [ -f "$PARTIAL" ] && [ ! -L "$PARTIAL" ] || return 1
    exec 4<"$PARTIAL" || return 1
    exec 3>>/dev/fd/4 || return 1
    # One comparison of the descriptor's inode with the name's own (lstat, no link
    # followed): a link under the name has an inode of its own, so a name swapped
    # between two separate tests cannot pass. With one link, the name is the file's
    # only one.
    [ "$(stat -L -c '%u %a %h %s' /dev/fd/3)" = "$(id -u) 600 1 0" ] \
        && [ "$(stat -L -c '%d %i' /dev/fd/3)" = "$(stat -c '%d %i' -- "$PARTIAL")" ]
}
archive_fd_ok || {
    echo "[backup] ERROR: $PARTIAL is not a file of its own that only you can read (owner, mode 600, one link, empty) — backup aborted." >&2
    echo "[backup] A target that does not keep Unix owner and mode (as a CIFS, vfat or NTFS mount often does not) cannot hold the archive safely: back up to a local directory and copy the archive from there." >&2
    exit 1
}
tar czf - -C "$STAGE" . >&3
exec 3>&- 4<&-
sync -- "$PARTIAL" \
    || { echo "[backup] ERROR: could not flush the archive to disk — backup aborted." >&2; exit 1; }
mv -fT -- "$PARTIAL" "$ARCHIVE" \
    || { echo "[backup] ERROR: could not move the archive to $ARCHIVE (is a directory in the way?) — backup aborted." >&2; exit 1; }
PARTIAL=""
sync -- "$OUT_DIR" \
    || { echo "[backup] ERROR: could not flush $OUT_DIR to disk — $ARCHIVE is written, but its name may not survive a power loss." >&2; exit 1; }

echo "[backup] OK -> $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
echo "[backup] Erinnerung: CA_ROOT_PASSPHRASE separat sichern (nicht im Tarball)."
