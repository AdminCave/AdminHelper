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

# --- Secrets (passphrase stripped) -----------------------------------------
if [ -f .env ]; then
    # Drops every statement that sets CA_ROOT_PASSPHRASE in a form compose reads,
    # and the commented-out ones: before the key any mix of whitespace, '#', a BOM
    # and the Unicode spaces compose skips (Go's unicode.IsSpace; their UTF-8 bytes
    # in sp), then an optional "export"; '=' or ':' separates, whitespace (NEL and
    # NBSP too) may stand before it. As in compose, a line holds statements one
    # behind the other while each quoted value closes; the passphrase may stand
    # there or behind any quote (that quote may close a value of another key begun
    # on an earlier line), and the other statements of the line stay. A quoted
    # value that does not close on its line runs on to its closing quote (a quote
    # after an odd number of backslashes does not close it), and without one to the
    # end of the file: those lines go too, in a comment the commented lines that
    # follow. In a comment the line goes from its '#' on; a line left with nothing
    # but whitespace goes. CA_ROOT_PASSPHRASE_OLD and the like are other keys and
    # stay. LC_ALL=C: awk reads bytes, so a NUL byte or a byte the caller's locale
    # cannot decode passes unchanged (grep took such a file for binary and left
    # lines out). Every other line is printed as is, the last with a newline; any
    # awk error (a write error too) aborts the backup.
    LC_ALL=C awk '
        BEGIN {
            sp = "([[:space:]]|\357\273\277|\302[\205\240]|\341\232\200|\342\200[\200\201\202\203\204\205\206\207\210\211\212\250\251\257]|\342\201\237|\343\200\200)"
            sep = "([[:space:]]|\302[\205\240])"
            kre = "^(export" sp "+)?CA_ROOT_PASSPHRASE" sep "*[=:]"
            gre = "^(export" sp "+)?[^[:space:]=:#\"\047]+" sep "*[=:]"
            lead = "^(" sp "|#)*"
            cre = "^" sp "*#"
        }
        # closeat(s, c): the place of the quote c that closes a quoted value in s, 0
        # without one; a quote behind a backslash does not.
        function closeat(s, c,    i, e, x) {
            for (i = 1; i <= length(s); i++) {
                x = substr(s, i, 1)
                if (e) e = 0
                else if (x == "\\") e = 1
                else if (x == c) return i
            }
            return 0
        }
        # walk(s): where in s a statement of the passphrase begins, s read as statements
        # one behind the other; a statement of another key is passed over when its
        # value is quoted and closes, anything else ends s. 0 without one. A "#" starts
        # a comment: wc = 1, the place is that of the "#", the statement wk bytes on.
        function walk(s,    n, c, i) {
            n = 0
            while (1) {
                match(s, lead)
                if (i = index(substr(s, 1, RLENGTH), "#")) {
                    wc = 1
                    wk = RLENGTH - i + 1
                    return substr(s, RLENGTH + 1) ~ kre ? n + i : 0
                }
                n += RLENGTH
                s = substr(s, RLENGTH + 1)
                wc = wk = 0
                if (s ~ kre) return n + 1
                if (!match(s, gre)) return 0
                n += RLENGTH
                s = substr(s, RLENGTH + 1)
                match(s, "^" sep "*")
                n += RLENGTH
                s = substr(s, RLENGTH + 1)
                c = substr(s, 1, 1)
                if ((c != "\"" && c != "\047") || !(i = closeat(substr(s, 2), c))) return 0
                n += i + 1
                s = substr(s, i + 2)
            }
        }
        # find(s): the first place where a statement of the passphrase begins in s, read
        # from its start and behind each of its quotes (any quote may close the value
        # of another key); 0 without one.
        # fc and fk are wc and wk of that place.
        function find(s,    p, i, c, w) {
            if (p = walk(s)) { fc = wc; fk = wk }
            for (i = 1; i <= length(s) && (!p || i < p); i++) {
                c = substr(s, i, 1)
                if ((c == "\"" || c == "\047") && (w = walk(substr(s, i + 1))) && (!p || i + w < p)) {
                    p = i + w
                    fc = wc
                    fk = wk
                }
            }
            return p
        }
        # cut(s): s without its passphrase statements; an unquoted value takes the rest
        # of s, a quoted one that runs on past s leaves q set (and cmt in a comment).
        # A comment that holds one goes from its "#" on.
        function cut(s,    out, p, v, c, i) {
            out = ""
            while (p = find(s)) {
                out = out substr(s, 1, p - 1)
                v = substr(s, p + fk)
                match(v, kre)
                v = substr(v, RLENGTH + 1)
                sub("^" sep "*", "", v)
                c = substr(v, 1, 1)
                if (c != "\"" && c != "\047") return out
                if (!(i = closeat(substr(v, 2), c))) { q = c; cmt = fc; return out }
                if (fc) return out
                s = substr(v, i + 2)
            }
            return out s
        }
        # keep(s): what is left of a line, unless only whitespace is.
        function keep(s) {
            if (s ~ ("^" sp "*$")) return
            sub("(" sp ")+$", "", s)
            print s
        }
        q != "" && cmt && $0 ~ cre { if (i = closeat($0, q)) { q = ""; cut(substr($0, i + 1)); cmt = 1 }; next }
        q != "" && cmt { q = "" }
        q != "" { if (i = closeat($0, q)) { q = ""; keep(cut(substr($0, i + 1))) }; next }
        $0 ~ cre {
            match($0, lead)
            s = substr($0, RLENGTH + 1)
            if (cut(s) == s) print
            else cmt = 1
            next
        }
        { cmt = 0; o = cut($0); if (o == $0) print; else keep(o) }
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
