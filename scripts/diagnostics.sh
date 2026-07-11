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
# Secrets are masked two ways: the exact secret values read from .env are
# replaced everywhere, plus generic token patterns (JWT, Bearer, ah_ API keys).
# ALWAYS skim the bundle before sending — redaction is best-effort, not a
# guarantee. The bundle is safe to attach to a GitHub issue.
#
# Run from the repository root (where docker-compose.yml lives):
#   ./scripts/diagnostics.sh [--tail N] [--output DIR]

set -euo pipefail

TAIL_LINES=300
OUT_DIR="."

while [ $# -gt 0 ]; do
    case "$1" in
        --tail) TAIL_LINES="${2:?--tail needs a number}"; shift ;;
        --output) OUT_DIR="${2:?--output needs a directory}"; shift ;;
        -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

# The secret-bearing .env keys whose VALUES must never leave the host. SMTP_PASSWORD is a
# regular .env key since the notification hub — without it the SMTP relay password would
# end up in cleartext in env.sanitized / the logs of a bundle advertised as issue-safe (3.7).
SECRET_KEYS=(SECRET_KEY POSTGRES_PASSWORD MONITOR_API_KEY CA_ROOT_PASSPHRASE ADMIN_PASSWORD SMTP_PASSWORD)

# build_redaction_sedfile <envfile> <sedfile>
# Writes a sed script that masks the .env secret values plus generic token forms.
build_redaction_sedfile() {
    local envfile="$1" sedfile="$2"
    : > "$sedfile"
    if [ -f "$envfile" ]; then
        local key val esc
        for key in "${SECRET_KEYS[@]}"; do
            # `|| true`: a missing key (grep rc 1) must not trip set -e/pipefail.
            val="$(grep -E "^[[:space:]]*${key}=" "$envfile" 2>/dev/null | head -n1 | cut -d= -f2- || true)"
            val="${val%\"}"
            val="${val#\"}"
            val="${val#"${val%%[![:space:]]*}"}"  # ltrim
            val="${val%"${val##*[![:space:]]}"}"  # rtrim
            # Skip empty or the well-known placeholder (not a real secret).
            if [ -n "$val" ] && [ "$val" != "change-me-in-production" ]; then
                esc="$(printf '%s' "$val" | sed -e 's/[][\\/.*^$]/\\&/g')"
                printf 's/%s/<redacted>/g\n' "$esc" >> "$sedfile"
            fi
        done
    fi
    # Generic token shapes that may appear in logs regardless of .env.
    cat >> "$sedfile" <<'SED'
s/eyJ[A-Za-z0-9_-]\{6,\}\.[A-Za-z0-9_-]\{6,\}\.[A-Za-z0-9_-]*/<redacted-jwt>/g
s/[Bb]earer [A-Za-z0-9._-]\{8,\}/Bearer <redacted>/g
s/ah_[A-Za-z0-9_-]\{8,\}/ah_<redacted>/g
SED
}

# redact <sedfile> : filter stdin -> stdout through the redaction sed script.
redact() {
    sed -f "$1"
}

# sanitize_env <envfile> : mask secret VALUES by key line, for env.sanitized -> stdout.
# The second, independent redaction path — build_redaction_sedfile redacts by value,
# this redacts by key, so a secret is masked even if its value never appeared in a log.
sanitize_env() {
    local envfile="$1" pat
    pat="$(IFS='|'; printf '%s' "${SECRET_KEYS[*]}")"
    sed -E "s/^([[:space:]]*(${pat}))=.*/\1=<redacted>/" "$envfile"
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
    build_redaction_sedfile ".env" "$sedfile"

    # --- report.txt -------------------------------------------------------
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
    } > "$stage/report.txt" 2>&1

    # --- compose.yml (no secrets: uses ${VARS}) ---------------------------
    cp docker-compose.yml "$stage/compose.yml"

    # --- env.sanitized (mask secret VALUES) -------------------------------
    if [ -f .env ]; then
        sanitize_env .env > "$stage/env.sanitized"
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
    echo "[diagnostics] Dann an ein GitHub-Issue anhaengen: https://github.com/AdminCave/AdminHelper/issues/new/choose"
}

# Only run main when executed directly — sourcing (e.g. the test) just loads the
# functions.
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
    main "$@"
fi
