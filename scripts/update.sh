#!/usr/bin/env bash
#
# update.sh — release-bound update for an existing AdminHelper install.
#
# A release is a self-contained, versioned RUNTIME BUNDLE published as a GitHub
# release asset (adminhelper-runtime-vX.Y.Z.tar.gz: docker-compose.yml, .env.example,
# the ops scripts, a MANIFEST.sha256 and a VERSION marker). This script resolves a
# target release, downloads that one asset, verifies it against the release's
# SHA256SUMS, and swaps the runtime files into place atomically — so whatever a
# release changes (new/changed/removed scripts, a new compose) lands on the host.
# "Which files belong to release X" lives in the release, not in a list here.
#
# Modes:
#   ./scripts/update.sh                 move to the latest PUBLISHED release (skips
#                                       prereleases/drafts) if it is newer; refuses
#                                       a silent downgrade
#   ./scripts/update.sh --ref vX.Y.Z    pin to exactly that release (re-apply / down-
#                                       or upgrade explicitly)
#   ./scripts/update.sh --redeploy      no version move: just re-pull the pinned
#                                       images and recreate (self-heal)
#   ./scripts/update.sh --check         dry run: print installed vs. available, exit
#
# Flags: --skip-backup  --with-victoria  --no-rollback  --yes
#
# Safety: backs up first (data, incl. the CA crown jewel) and snapshots the current
# runtime files + .env before the swap; on a failed swap, .env migration, agent-repo
# refresh, image pull, recreate or health check it auto-rolls-back the runtime files
# + image pins (use --no-rollback to inspect the broken state). The updater updates
# ITSELF: if the release ships a newer update.sh it re-execs into it.
#
# Advanced overrides (mirrors / GitHub Enterprise / tests):
#   AH_API_BASE (default https://api.github.com), AH_DL_BASE (default https://github.com),
#   GITHUB_TOKEN (optional, raises the unauthenticated 60/h API rate limit).

set -euo pipefail

REPO="AdminCave/AdminHelper"
API_BASE="${AH_API_BASE:-https://api.github.com}"
DL_BASE="${AH_DL_BASE:-https://github.com}"
# minisign public key (the "RW..." line of minisign.pub) to verify the release
# SHA256SUMS signature — authenticity, not just transport integrity. Keep in
# sync with scripts/install.sh. Empty = not yet armed (warn + checksum-only);
# once set, a missing/invalid signature aborts the update.
MINISIGN_PUBKEY="RWTU2kEztd3UWTF8HW26S8MWWiTUe6oz38I7rTBBSOvmQ3SHmszo6llJ"

REF=""
REDEPLOY=0
CHECK=0
SKIP_BACKUP=0
NO_ROLLBACK=0
ASSUME_YES=0
BACKUP_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --ref) REF="${2:?}"; shift ;;
        --redeploy) REDEPLOY=1 ;;
        --check) CHECK=1 ;;
        --skip-backup) SKIP_BACKUP=1 ;;
        --with-victoria) BACKUP_ARGS+=(--with-victoria) ;;
        --no-rollback) NO_ROLLBACK=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

# Diagnostics go to stderr so functions can return a value on stdout via $(...).
log() { echo "[update] $*" >&2; }
die() { echo "FEHLER: $*" >&2; exit 1; }

# 0 if every '${' in $1 that is not part of a '$$' starts a placeholder compose
# accepts: ${NAME}, or ${NAME followed by :- - :? ? :+ or + and a closing '}' on
# the same line, nested ones included. The classes are spelled out: under
# de_DE.UTF-8 a range like [A-Z] in =~ matches umlauts too, and compose takes ASCII
# names only.
env_template_ok() {
    local s="$1" open=0
    local name='^[_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ][_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789]*'
    while [ -n "$s" ]; do
        case $s in
            '$$'*) s=${s:2} ;;
            "\${"*)
                s=${s:2}
                [[ $s =~ $name ]] || return 1
                s=${s:${#BASH_REMATCH[0]}}
                case $s in
                    '}'*) s=${s:1} ;;
                    ':-'*|':?'*|':+'*) open=$((open + 1)); s=${s:2} ;;
                    '-'*|'?'*|'+'*) open=$((open + 1)); s=${s:1} ;;
                    *) return 1 ;;
                esac ;;
            '}'*) [ "$open" -eq 0 ] || open=$((open - 1)); s=${s:1} ;;
            $'\n'*) [ "$open" -eq 0 ] || return 1; s=${s:1} ;;
            *) s=${s:1} ;;
        esac
    done
    [ "$open" -eq 0 ]
}

# A quoted value as compose reads it: $2 is the text after the opening quote $1. A
# backslash escapes the next character, and in double quotes \$ is a literal '$'
# (passed on as '$$'). Leaves the text up to the closing quote in QUOTED and the
# text after it in QUOTED_REST; returns 1 if $2 holds no closing quote.
read_quoted() {
    local q="$1" s="$2" c i=0
    QUOTED=""
    while [ "$i" -lt "${#s}" ]; do
        c=${s:i:1}
        if [ "$c" = "$q" ]; then QUOTED_REST=${s:i+1}; return 0; fi
        if [ "$c" = "\\" ]; then
            i=$((i + 1)); c=${s:i:1}
            case $c in
                '$') c='$$' ;;
                "\\"|"$q") ;;
                *) c="\\$c" ;;
            esac
        fi
        QUOTED+=$c; i=$((i + 1))
    done
    return 1
}

# Leaves $1 in TRIMMED without the white space compose skips in front of it: in
# front of a value (and after "export ") compose-go's isSpace, the ASCII blanks,
# U+0085 and U+00A0; in front of a statement ($2 = statement) Go's
# unicode.IsSpace, also U+1680, U+2000-U+200A, U+2028, U+2029, U+202F, U+205F and
# U+3000. Spelled out in UTF-8 bytes, so the caller's locale does not decide.
trim_blanks() {
    local s="$1" b blanks=(' ' $'\t' $'\v' $'\f' $'\r' $'\xc2\x85' $'\xc2\xa0')
    [ "$2" != statement ] || blanks+=($'\xe1\x9a\x80' $'\xe2\x80\x80' $'\xe2\x80\x81' $'\xe2\x80\x82'
        $'\xe2\x80\x83' $'\xe2\x80\x84' $'\xe2\x80\x85' $'\xe2\x80\x86' $'\xe2\x80\x87' $'\xe2\x80\x88'
        $'\xe2\x80\x89' $'\xe2\x80\x8a' $'\xe2\x80\xa8' $'\xe2\x80\xa9' $'\xe2\x80\xaf' $'\xe2\x81\x9f'
        $'\xe3\x80\x80')
    while :; do
        for b in "${blanks[@]}"; do
            case $s in "$b"*) s=${s#"$b"}; continue 2 ;; esac
        done
        break
    done
    TRIMMED=$s
}

# 0 if $1, the text in front of '=' or ':' or a line without either, is a key
# compose takes (compose-go dotenv, locateKeyName): letters, digits and _ . - [ ];
# blanks are skipped, but a space between two of its characters is an error ("key
# cannot contain a space"), unless $2 is 0: the last line of .env, without a line
# break and without '=' or ':', is a value to compose, not a key. Letters and
# digits beyond ASCII are told by [[:alpha:]] and [[:digit:]] under C.UTF-8, whose
# classes come close to Go's unicode.IsLetter and IsNumber (a '²' is a number to
# Go only). Without a UTF-8 locale such a character passes: better compose stop an
# update than this check stop one that compose would run.
env_key_ok() {
    local k="$1" spaced="$2" c n i=0 seen=0 gap=0 utf8=0 probe=$'\xc3\x84'
    local LC_ALL=C.UTF-8 2>/dev/null
    [ "${#probe}" -ne 1 ] || utf8=1
    while [ "$i" -lt "${#k}" ]; do
        c=${k:i:1}; i=$((i + 1))
        case $c in
            ' ') [ "$seen" -eq 0 ] || gap=$spaced; continue ;;
            $'\t'|$'\v'|$'\f'|$'\r') continue ;;
            []_.[-]|[0123456789]|[abcdefghijklmnopqrstuvwxyz]|[ABCDEFGHIJKLMNOPQRSTUVWXYZ]) ;;
            *)
                printf -v n '%d' "'$c"
                [ "$n" -ge 128 ] || return 1
                [ "$utf8" -eq 1 ] || continue
                # U+0085 and U+00A0 are blanks to compose.
                case $n in 133|160) continue ;; esac
                [[ $c == [[:alpha:][:digit:]] ]] || return 1 ;;
        esac
        [ "$gap" -eq 0 ] || return 1
        seen=1
    done
}

# compose reads the values in .env as templates, and a '${' that starts no valid
# placeholder ends EVERY compose call (pull, up, exec, config) with "Invalid
# template"; so do a quote that never closes and a key compose does not take
# (env_key_ok), text after a closing quote included. Checked before the first
# call, so such a .env stops the update before backup, swap and re-pin rather than
# after. Reads .env as compose does: a BOM at its start drops, blank and '#' lines
# drop, "export " may lead, '=' or ':' separates, a line without either is a key
# without a value; a quoted value runs to its closing quote, over several lines if
# need be, and is literal in single quotes, and the text after that quote is read
# as a line of its own; an unquoted value ends at " #". The message names the
# first key of the line or the line number, never a value or the line: either may
# hold a secret, and compose's own message quotes them. Not a later key of the
# line either: the text after a closing quote may be meant as part of the value.
check_env_templates() {
    local line key name val more q rest eol spaced n=0 QUOTED QUOTED_REST TRIMMED
    [ -f .env ] || return 0
    while :; do
        # eol=0: the line ends .env without a line break.
        eol=1; IFS= read -r line || { eol=0; [ -n "$line" ] || break; }
        n=$((n + 1)); name=""
        [ "$n" -gt 1 ] || line=${line#$'\xef\xbb\xbf'}
        # One assignment per pass: after a closing quote, compose reads on.
        while [ -n "$line" ]; do
            trim_blanks "$line" statement; line=$TRIMMED
            case $line in ''|'#'*) break ;; esac
            # compose's ^export\s+: RE2's \s is ASCII only and without \v.
            case $line in
                export[$' \t\f\r']*) trim_blanks "${line#export}" value; line=$TRIMMED ;;
            esac
            key=${line%%[=:]*}; spaced=1
            [ "$key" != "$line" ] || spaced=$eol
            if ! env_key_ok "$key" "$spaced"; then
                [ -z "$name" ] || die ".env: der Wert von ${name} hat hinter dem schliessenden Anfuehrungszeichen Text, den docker compose als Schluessel liest und nicht annimmt — compose bricht damit jeden Aufruf ab. Ein Anfuehrungszeichen im Wert als \\\" bzw. \\' schreiben oder den Text entfernen. Abbruch (nichts veraendert)."
                die ".env: der Eintrag in Zeile ${n} hat einen Schluessel, den docker compose nicht annimmt (erlaubt: Buchstaben, Ziffern und _ . - [ ], kein Leerzeichen) — compose bricht damit jeden Aufruf ab. Den Schluessel korrigieren oder die Zeile mit '#' auskommentieren. Abbruch (nichts veraendert)."
            fi
            [ "$key" != "$line" ] || break
            key=${key%"${key##*[![:space:]]}"}; name=${name:-$key}
            trim_blanks "${line#*[=:]}" value; val=$TRIMMED
            rest=""
            case $val in
                "'"*|'"'*)
                    # The lines up to the closing quote are part of this value, not
                    # keys of their own.
                    q=${val:0:1}; val=${val:1}
                    until read_quoted "$q" "$val"; do
                        IFS= read -r more || {
                            eol=0
                            [ -n "$more" ] || die ".env: der Wert von ${name} hat ein nicht geschlossenes Anfuehrungszeichen — docker compose bricht damit jeden Aufruf ab. Das Anfuehrungszeichen schliessen. Abbruch (nichts veraendert)."
                        }
                        n=$((n + 1)); val+=$'\n'$more
                    done
                    rest=$QUOTED_REST
                    if [ "$q" = '"' ]; then val=$QUOTED; else val=""; fi ;;
                *) val=${val%% #*} ;;
            esac
            env_template_ok "$val" \
                || die ".env: der Wert von ${name} enthaelt ein '\${' ohne gueltigen Platzhalter — docker compose bricht damit jeden Aufruf mit 'Invalid template' ab. '\$' als '\$\$' schreiben oder den Wert in einfache Anfuehrungszeichen setzen. Abbruch (nichts veraendert)."
            line=$rest
        done
    done < .env
}

# --- Preflight --------------------------------------------------------------
[ -f docker-compose.yml ] || die "aus dem Install-Verzeichnis ausfuehren (docker-compose.yml fehlt)."
# The services run as UID 10001 (app) and Postgres as UID/GID 70: a host account that has
# one of these IDs reaches the data of the containers. The install directory is closed to
# others (at most 0750, the owner stays who installs), and such an account is named, not refused.
# Tighten only: g-w,o-rwx turns 0755/0775 into 0750 and leaves a stricter 0700 alone.
close_install_dir() {
    chmod g-w,o-rwx . 2>/dev/null \
        || echo "WARNING: could not close $(pwd) to other accounts; they may read the install directory." >&2
    return 0
}
warn_host_uids() {
    command -v getent >/dev/null 2>&1 || return 0
    local uid name
    for uid in 10001 70; do
        # getent ends with 2 for no such account; under pipefail that must not end the run.
        name=$(getent passwd "$uid" 2>/dev/null | cut -d: -f1) || name=""
        [ -z "$name" ] || echo "WARNING: host account '$name' has UID $uid, which a container uses; it can read the data of the services (see docs/admin/betrieb.html)." >&2
    done
    return 0
}
warn_host_uids
check_env_templates
command -v docker >/dev/null 2>&1 || die "docker fehlt."
docker compose version >/dev/null 2>&1 || die "'docker compose' fehlt."
command -v curl >/dev/null 2>&1 || die "curl fehlt."
# After the checks that stop with "nothing changed"; --check changes nothing, the mode included.
[ "$CHECK" = 1 ] || close_install_dir

# Set or replace KEY=value in .env (idempotent), un-commenting if needed. Returns 1,
# with .env unchanged, if the new file cannot be written.
upsert_env() {
    local key="$1" value="$2" tmp
    # Reject a value with newlines: it would inject extra .env lines (3.79).
    case $value in
        *[$'\n\r']*) die "ungueltiger Wert fuer ${key} (Zeilenumbruch)." ;;
    esac
    # Delete any existing (possibly commented) line for the key, then append the
    # literal value. No sed replacement, so |, & or \1 in the value aren't
    # interpreted (3.79). grep -v exits 1 when it filters every line, which is
    # fine; 2 is an error (a write error too). The copy sits next to .env (mktemp:
    # 0600, same file system, so mv is a rename) and replaces it only once both
    # steps worked: a full disk must not leave a cut-down .env in its place.
    # LC_ALL=C grep -a, on every read of .env: grep takes a file with a NUL byte or
    # a byte the caller's locale cannot decode for binary and leaves lines out,
    # which would drop them from .env or hide its SERVER_IMAGE. mv -f, here, in the
    # swap and in both rollbacks: without it, mv asks before it replaces a file it
    # may not write when stdin is a terminal, and waits for an answer that a
    # wrapper collecting the output never shows.
    tmp=$(mktemp .env.ah-XXXXXX) || return 1
    { { LC_ALL=C grep -a -vE "^#?[[:space:]]*${key}=" .env || [ $? -eq 1 ]; } > "$tmp" \
        && printf '%s=%s\n' "$key" "$value" >> "$tmp" \
        && mv -f "$tmp" .env; } \
        || { rm -f "$tmp"; return 1; }
}

# Currently installed version = the tag pinned on SERVER_IMAGE in .env (X.Y.Z),
# or "unknown" for a floating tag (:latest/:main) where a semver compare is moot.
installed_version() {
    local tag=""
    [ -f .env ] && tag=$(LC_ALL=C grep -a -E '^SERVER_IMAGE=' .env | head -1 | sed 's/.*://')
    case "$tag" in
        [0-9]*.[0-9]*.[0-9]*) printf '%s' "$tag" ;;
        *) printf 'unknown' ;;
    esac
}

# The installed state as messages name it: the version, or else what follows the
# image name in SERVER_IMAGE (a floating ":main", a digest "@sha256:…"; without a
# tag or without the line ":latest", the default), never "unknown".
installed_label() {
    local ver ref="" tag
    ver=$(installed_version)
    if [ "$ver" != unknown ]; then printf '%s' "$ver"; return 0; fi
    [ -f .env ] && ref=$(LC_ALL=C grep -a -E '^SERVER_IMAGE=' .env | head -1)
    ref="${ref#SERVER_IMAGE=}"; ref="${ref##*/}"
    tag="${ref#"${ref%%[:@]*}"}"
    printf '%s' "${tag:-:latest}"
}

# Resolve the latest published, non-prerelease, non-draft release tag via the API.
# (releases/latest excludes prereleases and drafts by definition.) No jq on hosts.
gh_curl() {
    # Add an optional GITHUB_TOKEN as an Authorization header via a curl config on
    # stdin (--config -), never argv: on a multi-user host argv is readable from ps /
    # /proc/<pid>/cmdline while the request runs, and stdin keeps it off disk too (3.86).
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        printf 'header = "Authorization: Bearer %s"\n' "$GITHUB_TOKEN" | curl --config - "$@"
    else
        curl "$@"
    fi
}

resolve_latest_tag() {
    local json tag
    json=$(gh_curl -fsSL -H "Accept: application/vnd.github+json" \
        "${API_BASE}/repos/${REPO}/releases/latest" 2>/dev/null) \
        || die "Konnte das neueste Release nicht abfragen (Netz/Rate-Limit?). Nutze --ref vX.Y.Z."
    tag=$(printf '%s' "$json" | grep -o '"tag_name":[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\1/')
    [ -n "$tag" ] || die "Kein tag_name in der Release-Antwort gefunden."
    printf '%s' "$tag"
}

# True if $1 (version) is strictly greater than $2, via `sort -V`.
semver_gt() {
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ]
}

# Verify the SHA256SUMS minisign signature against the pinned public key. Unset
# MINISIGN_PUBKEY = not yet armed -> warn + checksum-only (no regression). Once
# armed, a missing minisign binary or a bad/absent signature aborts. Fail closed.
# Writes only to stderr (fetch_bundle returns the extract dir on stdout).
verify_sums_signature() {
    local tmp="$1" dl="$2"
    if [ -z "$MINISIGN_PUBKEY" ]; then
        log "WARNUNG: Release-Signatur nicht konfiguriert — nur Transport-Integritaet (Checksumme)."
        return 0
    fi
    # Don't silently sudo apt-get install minisign — abort with a clear instruction
    # rather than escalating + touching the host's package set unasked (3.78).
    command -v minisign >/dev/null 2>&1 \
        || die "minisign fehlt — Signatur nicht pruefbar. Bitte installieren (z.B. 'sudo apt-get install minisign' bzw. das Paket der Distribution) und erneut ausfuehren."
    curl -fsSL --retry 3 -o "${tmp}/SHA256SUMS.minisig" "${dl}/SHA256SUMS.minisig" \
        || die "Release-Signatur (SHA256SUMS.minisig) fehlt."
    minisign -Vm "${tmp}/SHA256SUMS" -P "$MINISIGN_PUBKEY" -x "${tmp}/SHA256SUMS.minisig" >/dev/null 2>&1 \
        || die "Release-Signatur ungueltig — Abbruch (moegliche Manipulation)."
    log "Release-Signatur verifiziert (minisign)."
}

# Download the runtime bundle for TAG into $1, verify against SHA256SUMS + the
# in-bundle MANIFEST.sha256, and assert the bundle's VERSION matches TAG. Echoes
# the extract dir on success.
fetch_bundle() {
    local tag="$1" tmp="$2" asset dl expected ver
    asset="adminhelper-runtime-${tag}.tar.gz"
    dl="${DL_BASE}/${REPO}/releases/download/${tag}"
    log "Lade Runtime-Bundle ${asset} ..."
    curl -fsSL --retry 3 --retry-connrefused -o "${tmp}/${asset}" "${dl}/${asset}" \
        || die "Bundle ${asset} nicht ladbar (Release veroeffentlicht? Tag korrekt?)."
    curl -fsSL --retry 3 -o "${tmp}/SHA256SUMS" "${dl}/SHA256SUMS" \
        || die "SHA256SUMS fuer ${tag} nicht ladbar."
    verify_sums_signature "$tmp" "$dl"
    # --fail catches HTTP errors but NOT a truncated 200 — the checksum does.
    expected=$(awk -v a="$asset" '$2==a {print $1; exit}' "${tmp}/SHA256SUMS")
    [ -n "$expected" ] || die "Keine Checksumme fuer ${asset} in SHA256SUMS."
    echo "${expected}  ${tmp}/${asset}" | sha256sum -c - >/dev/null 2>&1 \
        || die "Checksumme des Bundles stimmt nicht — Abbruch (nichts veraendert)."
    mkdir -p "${tmp}/extract"
    tar xzf "${tmp}/${asset}" -C "${tmp}/extract"
    ( cd "${tmp}/extract" && sha256sum -c MANIFEST.sha256 >/dev/null 2>&1 ) \
        || die "Manifest-Verifikation des Bundles fehlgeschlagen."
    ver=$(cat "${tmp}/extract/VERSION" 2>/dev/null || true)
    [ "$ver" = "$tag" ] || die "Bundle-Version (${ver:-?}) passt nicht zum Ziel (${tag})."
    printf '%s' "${tmp}/extract"
}

# Refresh the host ./repo (the gateway's apt/rpm repo mount) from this release's
# agent-repo asset. Best-effort: a release WITHOUT the asset (signing key not
# configured, or a pre-repo release) leaves ./repo untouched and never fails the
# update — but an asset that IS present and cannot be fetched, verified (tampering)
# or unpacked returns 1, and the caller rolls the update back. The caller tests the
# status, which turns set -e off in here: every step that can fail returns 1 itself,
# except on purpose a missing asset (404/000) or checksum line (skip, return 0) and
# the clean-up before the copy (find -delete), which may leave files behind.
# Reuses the already-downloaded, signature-verified ${tmp}/SHA256SUMS. Updates the
# tree IN PLACE (keeps the dir inode) so the gateway's live bind mount stays valid.
update_agent_repo() {
    local tag="$1" tmp="$2" asset dl expected
    asset="adminhelper-agent-repo-${tag}.tar.gz"
    dl="${DL_BASE}/${REPO}/releases/download/${tag}"
    local code rc=0
    code=$(curl -fsSL --retry 3 --retry-connrefused -o "${tmp}/${asset}" -w '%{http_code}' "${dl}/${asset}" 2>/dev/null) || rc=$?
    if [ "$rc" -ne 0 ]; then
        # 404 (asset genuinely absent) or 000 (file:// tests / no HTTP layer) → skip;
        # a 5xx or other failure means the asset may exist but the fetch failed —
        # that must NOT be mistaken for "no asset" (4.58).
        case "$code" in
            404|000) log "Kein Agent-Repo-Asset in ${tag} — ueberspringe Repo-Update (Paket-Repo unveraendert)."; return 0 ;;
            *) log "Agent-Repo-Asset ${asset} nicht ladbar (HTTP ${code})."; return 1 ;;
        esac
    fi
    expected=$(awk -v a="$asset" '$2==a {print $1; exit}' "${tmp}/SHA256SUMS" 2>/dev/null || true)
    [ -n "$expected" ] || { log "Keine Checksumme fuer ${asset} — ueberspringe Repo-Update."; return 0; }
    echo "${expected}  ${tmp}/${asset}" | sha256sum -c - >/dev/null 2>&1 \
        || { log "Checksumme des Agent-Repo-Assets stimmt nicht (moegliche Manipulation)."; return 1; }
    log "Aktualisiere Paket-Repo unter ./repo ..."
    # Unpack into staging FIRST: a tar failure returns before ./repo is touched,
    # so a corrupt asset can't leave the gateway serving an empty repo. The
    # dir inode is kept (content swapped in place) so the live bind mount stays valid (4.59).
    local staging; staging=$(mktemp -d "${tmp}/repo.XXXXXX") || return 1
    tar xzf "${tmp}/${asset}" -C "$staging" \
        || { log "Agent-Repo-Asset ${asset} nicht entpackbar."; return 1; }
    mkdir -p repo || return 1
    find repo -mindepth 1 -delete 2>/dev/null || true
    cp -a "$staging"/. repo/ || return 1
}

# Wait until the server accepts connections (migrations done, uvicorn up).
# Retries/interval are tunable (default 120×2s = 240s) for slow hosts and tests.
wait_for_server() {
    local attempt=0 max="${AH_HEALTH_RETRIES:-120}" iv="${AH_HEALTH_INTERVAL:-2}"
    log "Warte auf den Server (Alembic laeuft beim Start)..."
    until docker compose exec -T server \
            python -c "import socket; socket.create_connection(('127.0.0.1', 8080), 2).close()" >/dev/null 2>&1; do
        attempt=$((attempt + 1))
        [ "$attempt" -ge "$max" ] && return 1
        sleep "$iv"
    done
    return 0
}

# ---------------------------------------------------------------------------
# Self-heal: re-pull the already-pinned images and recreate. No version move,
# no file swap — the old bare-update behaviour, now behind an explicit flag.
# ---------------------------------------------------------------------------
if [ "$REDEPLOY" = 1 ]; then
    if [ "$SKIP_BACKUP" != 1 ]; then log "Backup-first..."; ./scripts/backup.sh "${BACKUP_ARGS[@]}"; fi
    log "Ziehe die gepinnten Images neu..."
    docker compose pull || die "Ziehen der Images fehlgeschlagen (Netz/Rate-Limit?) — Re-Deploy abgebrochen, Container unveraendert."
    log "Starte den Stack neu..."
    docker compose up -d
    wait_for_server || die "Server nicht rechtzeitig bereit. Restore: ./scripts/restore.sh ./backups/<neuestes>.tar.gz"
    log "Re-Deploy fertig (Version unveraendert: $(installed_label))."
    exit 0
fi

# --- Resolve target + guard rails -------------------------------------------
INSTALLED=$(installed_version)
INSTALLED_LABEL=$(installed_label)
if [ -n "$REF" ]; then
    TARGET="$REF"
else
    TARGET=$(resolve_latest_tag)
fi
TARGET_VER="${TARGET#v}"

# Compare only for the bare (latest) path; --ref is an explicit, unconditional move.
if [ -z "$REF" ]; then
    if [ "$INSTALLED" != "unknown" ] && [ "$TARGET_VER" = "$INSTALLED" ]; then
        log "Bereits auf der neuesten Version ${INSTALLED}. (--redeploy zum Neuziehen, --ref ${TARGET} zum erneuten Anwenden.)"
        exit 0
    fi
    if [ "$INSTALLED" != "unknown" ] && semver_gt "$INSTALLED" "$TARGET_VER"; then
        die "Installiert ist ${INSTALLED}, neuestes Release ist ${TARGET_VER} — kein stiller Downgrade. Explizit: --ref ${TARGET}."
    fi
fi

if [ "$CHECK" = 1 ]; then
    log "Installiert: ${INSTALLED_LABEL}   Ziel: ${TARGET_VER} (${TARGET})"
    if [ "$INSTALLED" = "$TARGET_VER" ]; then log "Aktuell — kein Update noetig."; else log "Update verfuegbar."; fi
    exit 0
fi

# Without .env there is no installed state to roll back to; checked before the
# backup and the snapshot, so a broken install dir gets neither.
[ -f .env ] || die ".env fehlt im Install-Verzeichnis — kein Stand zum Zurueckrollen. Abbruch (nichts veraendert)."

log "Update ${INSTALLED_LABEL} -> ${TARGET_VER}"

# --- Fetch + verify the bundle (before touching anything) -------------------
TMP=$(mktemp -d)
# A re-exec'd updater also removes the TMP of the run that handed off to it (its
# exec skipped its own EXIT trap), but only when it runs from exactly that dir: the
# variable alone never makes this script delete a directory.
PARENT_TMP=""
if [ -n "${AH_UPDATE_PARENT_TMP:-}" ] && [ "$0" = "${AH_UPDATE_PARENT_TMP}/update-new.sh" ]; then
    PARENT_TMP="$AH_UPDATE_PARENT_TMP"
fi
trap 'rm -rf -- "$TMP" ${PARENT_TMP:+"$PARENT_TMP"}' EXIT
EXTRACT=$(fetch_bundle "$TARGET" "$TMP")

# --- Self-update: hand off to the release's update.sh if it differs ----------
# A running bash script must not overwrite its own on-disk file, so we re-exec the
# new updater from a temp copy (it then performs the actual swap). The marker
# prevents an exec loop; we pass --ref TARGET so the hand-off is deterministic.
if [ "${AH_UPDATE_REEXECED:-0}" != 1 ] && ! cmp -s "${EXTRACT}/scripts/update.sh" ./scripts/update.sh; then
    log "Release bringt eine neuere update.sh — uebergebe an die neue Version..."
    cp "${EXTRACT}/scripts/update.sh" "${TMP}/update-new.sh"; chmod +x "${TMP}/update-new.sh"
    pass=(--ref "$TARGET")
    [ "$SKIP_BACKUP" = 1 ] && pass+=(--skip-backup)
    [ "$NO_ROLLBACK" = 1 ] && pass+=(--no-rollback)
    [ "$ASSUME_YES" = 1 ] && pass+=(--yes)
    [ ${#BACKUP_ARGS[@]} -gt 0 ] && pass+=("${BACKUP_ARGS[@]}")
    # exec replaces this process: the EXIT trap won't fire, so $TMP survives for
    # the new updater to run from; AH_UPDATE_PARENT_TMP has it remove $TMP at its end.
    exec env AH_UPDATE_REEXECED=1 AH_UPDATE_PARENT_TMP="$TMP" bash "${TMP}/update-new.sh" "${pass[@]}"
fi

# --- Backup-first (data) + snapshot the current runtime files ---------------
if [ "$SKIP_BACKUP" != 1 ]; then
    log "Backup-first..."
    ./scripts/backup.sh "${BACKUP_ARGS[@]}"
else
    log "Backup uebersprungen (--skip-backup)."
fi

mkdir -p backups
SNAP="backups/runtime-prev-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
SNAP_FILES=(docker-compose.yml .env.example scripts)
# Include ./repo so a rollback restores the old agent package repo too — not just
# compose + scripts (else a rolled-back update keeps the new version's repo) (4.129).
[ -d repo ] && SNAP_FILES+=(repo)
# The snapshot is the auto-rollback's ONLY basis, so a failure here (full disk,
# backups/ perms) must abort — nothing is swapped yet, so aborting is clean. A
# best-effort snapshot would let a later health-fail rollback restore nothing while
# claiming success, leaving old images + new compose (2.41).
tar czf "$SNAP" "${SNAP_FILES[@]}" || die "Laufzeit-Snapshot fehlgeschlagen — Abbruch (noch nichts veraendert)."
chmod 600 "$SNAP" 2>/dev/null || true
log "Laufzeit-Snapshot: ${SNAP}"
# .env as it was, for both rollbacks below: all of it goes back while no container
# has been touched, only its image pins once containers may have started. Kept in $TMP
# (0700, removed on exit), not in the snapshot, which both restore in whole.
cp -p .env "${TMP}/env.prev" || die "Kopie der .env fehlgeschlagen — Abbruch (noch nichts veraendert)."

# --- Both rollbacks: the runtime files as the snapshot holds them -----------
# tar only adds and overwrites, so the paths the swap added go first, and ./repo is
# emptied IN PLACE (the dir inode stays, so the gateway's live bind mount stays
# valid): afterwards ./repo holds exactly the snapshot's tree, or stays empty if the
# update created it. Every step runs; returns 1 if any of them failed.
restore_snapshot() {
    local rel rc=0
    while IFS= read -r rel; do
        [ -n "$rel" ] || continue
        rm -f "$rel" || rc=1
    done <<< "$ADDED_PATHS"
    if [ -d repo ]; then find repo -mindepth 1 -delete || rc=1; fi
    tar xzf "$SNAP" || rc=1
    return "$rc"
}

# --- Rollback while no container has been touched yet ------------------------
# A failed swap, .env migration, agent-repo refresh or pull (registry down, rate
# limit, an image the release did not publish) comes before the recreate, so
# nothing of the new version ever ran: the installed state is the snapshot plus the
# old .env as a whole, pins of a floating tag included. No recreate needed. $1 says
# what failed, $2 is the way on that --no-rollback names: once .env is pinned on
# the target, a bare re-run would call the install current. $3 replaces what
# --no-rollback says stays: a failed swap comes before the re-pin.
rollback_before_deploy() {
    if [ "$NO_ROLLBACK" = 1 ]; then
        die "$1. --no-rollback gesetzt: ${3:-neue Laufzeit-Dateien + Image-Pins bleiben stehen}, Container unveraendert. $2"
    fi
    local incomplete=0
    echo >&2
    log "Rolle Laufzeit-Dateien + .env auf ${INSTALLED_LABEL} zurueck (Snapshot ${SNAP})..."
    restore_snapshot || { log "WARN: Snapshot-Restore fehlgeschlagen — Rollback UNVOLLSTAENDIG, bitte manuell pruefen."; incomplete=1; }
    # Copy next to .env, then rename: an interrupted restore leaves no half .env.
    # -T: a directory .env.ah-new in the way fails the restore, it takes no copy.
    { cp -pT "${TMP}/env.prev" .env.ah-new && mv -fT .env.ah-new .env; } \
        || { log "WARN: .env-Restore fehlgeschlagen — Rollback UNVOLLSTAENDIG, bitte manuell pruefen."; incomplete=1; }
    [ "$incomplete" = 0 ] \
        || die "$1 — Rollback auf ${INSTALLED_LABEL} UNVOLLSTAENDIG (siehe WARN), Container unveraendert. Bitte manuell pruefen."
    die "$1 — zurueckgerollt auf ${INSTALLED_LABEL}, Container unveraendert. Update danach erneut ausfuehren."
}

# --- Atomic-ish swap: place every manifest file, drop obsolete ops scripts ---
# Paths come from the bundle's MANIFEST.sha256 (col 2). Each file is copied next to
# its place from the already-verified extract dir and renamed over it; scripts/*
# get the exec bit. A path that does not exist yet is noted in ADDED_PATHS first:
# the snapshot cannot bring back its absence, so a rollback removes it
# (restore_snapshot). One step, like migrate_env: the caller tests the status,
# which turns set -e off in here, so every part that can fail returns 1 itself, a
# copy left half written goes, and the caller rolls back. -T: a directory
# <path>.ah-new in the way fails the copy, it takes no file.
MANIFEST_PATHS=$(awk '{print $2}' "${EXTRACT}/MANIFEST.sha256")
ADDED_PATHS=""
swap_runtime_files() {
    local rel f
    while IFS= read -r rel; do
        [ -n "$rel" ] || continue
        rel="${rel#./}"
        [ -e "$rel" ] || [ -L "$rel" ] || ADDED_PATHS+="${rel}"$'\n'
        mkdir -p "$(dirname "$rel")" || return 1
        { cp -T "${EXTRACT}/${rel}" "${rel}.ah-new" && mv -fT "${rel}.ah-new" "$rel"; } \
            || { rm -f "${rel}.ah-new"; return 1; }
        case "$rel" in scripts/*.sh) chmod +x "$rel" || return 1 ;; esac
    done <<< "$MANIFEST_PATHS"

    # Remove ops scripts that this release no longer ships (managed set only: our
    # scripts/*.sh that are absent from the manifest). Never touches non-script files.
    for f in scripts/*.sh; do
        [ -e "$f" ] || continue
        if ! printf '%s\n' "$MANIFEST_PATHS" | grep -qx "./$f" && \
           ! printf '%s\n' "$MANIFEST_PATHS" | grep -qx "$f"; then
            log "Entferne nicht mehr ausgelieferte Datei: $f"
            rm -f "$f" || return 1
        fi
    done
}
swap_runtime_files || rollback_before_deploy "Tausch der Laufzeit-Dateien fehlgeschlagen" \
    "Weiter mit ./scripts/update.sh --ref ${TARGET} (Release erneut anwenden)." \
    "teils getauschte Laufzeit-Dateien bleiben stehen, .env unveraendert"

# --- .env migration: add new keys, fill new secrets, re-pin images ----------
# One step: the caller tests the status, which turns set -e off in here, so every
# part that can fail returns 1 itself, and the caller rolls the whole .env back.
# Additive only: append active KEY=value from the new .env.example that .env is
# missing — never overwrite an existing value (no clobbering of secrets/config).
migrate_env() {
    local line key rc
    if [ -f .env.example ]; then
        while IFS= read -r line; do
            case "$line" in
                [A-Z_]*=*)
                    key="${line%%=*}"
                    rc=0; LC_ALL=C grep -a -qE "^#?[[:space:]]*${key}=" .env || rc=$?
                    case $rc in
                        0) ;;
                        1) printf '%s\n' "$line" >> .env || return 1; log ".env: neuen Key ${key} ergaenzt" ;;
                        *) return 1 ;;
                    esac
                    ;;
            esac
        done < .env.example || return 1
    fi
    # Fill any newly-added empty secrets (idempotent — leaves set values alone).
    ./scripts/init-secrets.sh >/dev/null || return 1

    # Re-pin the image tags to the target version (vX.Y.Z -> :X.Y.Z).
    upsert_env SERVER_IMAGE     "ghcr.io/admincave/adminhelper/server:${TARGET_VER}" || return 1
    upsert_env GATEWAY_IMAGE    "ghcr.io/admincave/adminhelper/gateway:${TARGET_VER}" || return 1
    upsert_env FRPS_IMAGE       "ghcr.io/admincave/adminhelper/frps:${TARGET_VER}" || return 1
    upsert_env CA_ISSUER_IMAGE  "ghcr.io/admincave/adminhelper/ca-issuer:${TARGET_VER}" || return 1
    upsert_env MONITORING_IMAGE "ghcr.io/admincave/adminhelper/monitoring:${TARGET_VER}" || return 1
    chmod 600 .env 2>/dev/null || true
    log "Images gepinnt auf :${TARGET_VER}"
}
migrate_env || rollback_before_deploy ".env-Migration fehlgeschlagen" \
    ".env kann halb migriert sein. Weiter mit ./scripts/update.sh --ref ${TARGET} (Release erneut anwenden)."

# --- Refresh the gateway's agent package repo --------------------------------
# --redeploy never calls update_agent_repo, so only --ref re-applies the repo.
update_agent_repo "$TARGET" "$TMP" \
    || rollback_before_deploy "Paket-Repo-Update fehlgeschlagen" \
        "./repo kann halb gefuellt sein. Weiter mit ./scripts/update.sh --ref ${TARGET} (Release samt Paket-Repo erneut anwenden)."

# --- Rollback once containers may have started -------------------------------
# A failed recreate or health check: parts of the new version may have run. $1
# says what failed. With --no-rollback, .env stays pinned on the target and a bare
# re-run would call the install current; --ref is never stopped by the downgrade
# guard, but it pins a release, so a floating tag only comes back by hand.
rollback_after_deploy() {
    if [ "$NO_ROLLBACK" = 1 ]; then
        local back="zurueck mit ./scripts/update.sh --ref v${INSTALLED}"
        [ "$INSTALLED" != "unknown" ] || back="zurueck auf den vorigen Floating-Tag nur von Hand (Image-Pins in .env)"
        die "$1. --no-rollback gesetzt: kaputter Stand bleibt zum Debuggen stehen, .env auf ${TARGET_VER} gepinnt. Danach: ./scripts/update.sh --redeploy (gepinnte Images neu starten); ${back}. Alembic kann die Datenbank beim Start schon migriert haben; Daten-Restore bei Bedarf: ./scripts/restore.sh ./backups/<neuestes>.tar.gz"
    fi
    local incomplete=0
    echo >&2
    log "Rolle Laufzeit-Dateien + Image-Pins auf ${INSTALLED_LABEL} zurueck (Snapshot ${SNAP})..." >&2
    # If the snapshot restore fails, the rollback is INCOMPLETE (new runtime files
    # stay in place) — say so loudly rather than claiming a clean rollback (4.60).
    restore_snapshot || { log "WARN: Snapshot-Restore fehlgeschlagen — Rollback UNVOLLSTAENDIG, bitte manuell pruefen."; incomplete=1; }
    # The containers ran, so only the pin lines of the old .env go back: a key the
    # migration added or a secret init-secrets.sh filled (CA_ROOT_PASSPHRASE) may
    # be in use already. Taken from env.prev, not rebuilt from INSTALLED, which is
    # "unknown" for a floating tag (:latest/:main): pins left on the target make
    # the next run call the install current. A pin the old .env lacked stays
    # absent. grep exits 1 for "no line selected", which is fine on either side.
    # LC_ALL=C grep -a, as in upsert_env: a file grep takes for binary loses lines.
    local pins='^#?[[:space:]]*(SERVER|GATEWAY|FRPS|CA_ISSUER|MONITORING)_IMAGE='
    { ( umask 077
        { LC_ALL=C grep -a -vE "$pins" .env || [ $? -eq 1 ]; } > .env.ah-new \
            && { LC_ALL=C grep -a -E "$pins" "${TMP}/env.prev" || [ $? -eq 1 ]; } >> .env.ah-new
      ) && mv -fT .env.ah-new .env; } \
        || { log "WARN: Image-Pin-Restore fehlgeschlagen — Rollback UNVOLLSTAENDIG, bitte manuell pruefen."; incomplete=1; }
    docker compose up -d >/dev/null \
        || { log "WARN: Start des Stands ${INSTALLED_LABEL} fehlgeschlagen — Rollback UNVOLLSTAENDIG, bitte manuell pruefen."; incomplete=1; }
    [ "$incomplete" = 0 ] \
        || die "$1 — Rollback auf ${INSTALLED_LABEL} UNVOLLSTAENDIG (siehe WARN), bitte manuell pruefen. Daten-Restore bei Bedarf: ./scripts/restore.sh ./backups/<neuestes>.tar.gz"
    die "$1 — zurueckgerollt auf ${INSTALLED_LABEL}. Daten-Restore bei Bedarf: ./scripts/restore.sh ./backups/<neuestes>.tar.gz"
}

# --- Deploy + health check, with automatic rollback on failure --------------
log "Ziehe die Images..."
docker compose pull \
    || rollback_before_deploy "Ziehen der Images fehlgeschlagen (Netz/Rate-Limit/Image nicht veroeffentlicht?)" \
        "Weiter mit ./scripts/update.sh --redeploy (gepinnte Images erneut ziehen und starten) oder --ref ${TARGET} (Release erneut anwenden)."
log "Starte den Stack neu..."
docker compose up -d || rollback_after_deploy "Stack-Neustart fehlgeschlagen"

if wait_for_server; then
    log "Fertig. Jetzt auf ${TARGET_VER}. Bei Problemen: ./scripts/restore.sh ./backups/<neuestes>.tar.gz"
else
    rollback_after_deploy "Server nicht rechtzeitig bereit"
fi
