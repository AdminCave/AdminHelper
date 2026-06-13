#!/usr/bin/env bash
#
# uninstall.sh — vollständige Deinstallation eines AdminHelper-Servers.
#
# Entfernt restlos, was install.sh/update.sh auf dem Host hinterlassen:
#   - alle Container des Compose-Projekts (server, gateway, ca-issuer, frps,
#     monitoring, victoria, postgres, redis, …)
#   - ALLE Named Volumes inkl. ca-pki (die Root-CA!), postgres-data, victoria-data
#   - das Compose-Netzwerk
#   - die Host-Bind-Mounts ./data und ./certs (gehören dem Container-User uid 10001)
#   - die Secrets-Datei .env (+ eine evtl. .env.restored aus einem Restore)
#
# Bewusst GESCHÜTZT (nur mit explizitem Flag):
#   - ./backups/  bleibt stehen (enthält CA + DB-Dumps)   -> --purge-backups
#   - Docker-Images bleiben liegen (Re-Pull ist billig)   -> --rmi
#
# Die Laufzeit-Dateien selbst (docker-compose.yml, .env.example, scripts/) werden
# NICHT automatisch gelöscht — ein laufendes Skript löscht sein eigenes Verzeichnis
# nicht. Den exakten Aufräum-Befehl gibt das Skript am Ende aus.
#
# DESTRUKTIV und NICHT umkehrbar (außer aus einem Backup). Aus dem
# Install-Verzeichnis ausführen (dort, wo die docker-compose.yml liegt):
#   ./scripts/uninstall.sh [--purge-backups] [--rmi] [--yes]

set -euo pipefail

ASSUME_YES=0
PURGE_BACKUPS=0
REMOVE_IMAGES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --purge-backups) PURGE_BACKUPS=1 ;;
        --rmi) REMOVE_IMAGES=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

# --- Preflight --------------------------------------------------------------
[ -f docker-compose.yml ] || { echo "FEHLER: aus dem Install-Verzeichnis ausführen (docker-compose.yml fehlt)." >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "FEHLER: docker fehlt." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "FEHLER: 'docker compose' fehlt." >&2; exit 1; }

# Compose-Projektname (= Volume-/Netzwerk-Präfix). Default ist der
# Verzeichnisname; identisch zu restore.sh, damit der Label-Fallback dieselben
# Ressourcen trifft, die `docker compose up` angelegt hat.
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9_-]//g')}"

# --- Inventur ---------------------------------------------------------------
CONTAINERS=$(docker compose ps --all --quiet 2>/dev/null | wc -l | tr -d ' ')

echo "============================================================================"
echo "  AdminHelper-Deinstallation"
echo "----------------------------------------------------------------------------"
echo "  Compose-Projekt:  $PROJECT  (${CONTAINERS} Container)"
echo "  Wird ENTFERNT:"
echo "    - alle Container + das Netzwerk des Projekts"
echo "    - alle Named Volumes  (inkl. ca-pki = Root-CA, postgres-data, victoria-data)"
echo "    - Host-Daten:  ./data  ./certs  .env"
[ -f .env.restored ] && echo "    - ./.env.restored"
echo "    - Docker-Images:   $([ "$REMOVE_IMAGES" = 1 ] && echo 'JA (--rmi)' || echo 'nein (behalten; --rmi zum Entfernen)')"
echo "    - ./backups/:      $([ "$PURGE_BACKUPS" = 1 ] && echo 'JA (--purge-backups)' || echo 'BLEIBT erhalten (--purge-backups zum Entfernen)')"
echo "============================================================================"

# Rückfrage muss vom kontrollierenden Terminal lesen (analog install.sh): unter
# `curl | bash` wäre stdin die Skript-Pipe.
if [ -r /dev/tty ]; then TTY=/dev/tty; else TTY=""; fi
if [ "$ASSUME_YES" != 1 ]; then
    [ -n "$TTY" ] || { echo "FEHLER: Kein Terminal für die Rückfrage. Übergib --yes für einen nicht-interaktiven Lauf." >&2; exit 1; }
    printf "Wirklich ALLES löschen? Tippe 'ja' zum Bestätigen: "
    read -r ans <"$TTY"
    case "$ans" in ja|JA|Ja|yes|y|Y) ;; *) echo "Abgebrochen — nichts wurde verändert."; exit 0 ;; esac
fi

# --- Container + Volumes + Netzwerk -----------------------------------------
DOWN_ARGS=(down --volumes --remove-orphans)
[ "$REMOVE_IMAGES" = 1 ] && DOWN_ARGS+=(--rmi all)

echo "[uninstall] Stoppe und entferne den Stack (Volumes inklusive)..."
if ! docker compose "${DOWN_ARGS[@]}"; then
    echo "[uninstall] WARN: 'docker compose down' schlug fehl — räume per Projekt-Label auf." >&2
fi

# Gürtel-und-Hosenträger: alles mit dem Projekt-Label einsammeln, was eine
# defekte/abweichende Compose-Datei stehengelassen haben könnte. Strikt auf
# DIESES Projekt gefiltert, damit keine fremden Stacks getroffen werden.
LABEL="com.docker.compose.project=$PROJECT"
docker ps -aq --filter "label=$LABEL" | xargs -r docker rm -f >/dev/null 2>&1 || true
docker volume ls -q --filter "label=$LABEL" | xargs -r docker volume rm >/dev/null 2>&1 || true
docker network ls -q --filter "label=$LABEL" | xargs -r docker network rm >/dev/null 2>&1 || true

# --- Host-Daten (gehören uid 10001 — als root im Container löschen) ----------
# Kein sudo voraussetzen: docker ist ohnehin Pflicht. Nur fest verdrahtete
# Pfadnamen (kein User-Input) im Repo-Root entfernen.
nuke_path() {
    local rel="$1"
    [ -e "$rel" ] || return 0
    rm -rf "$rel" 2>/dev/null || true
    if [ -e "$rel" ]; then
        docker run --rm -v "$PWD:/work" -w /work alpine rm -rf "$rel" >/dev/null 2>&1 || true
    fi
    if [ -e "$rel" ]; then
        echo "[uninstall] WARN: konnte '$rel' nicht vollständig entfernen — bitte manuell prüfen." >&2
    else
        echo "[uninstall] entfernt: $rel"
    fi
}

echo "[uninstall] Entferne Host-Daten + Secrets..."
nuke_path data
nuke_path certs
nuke_path .env
nuke_path .env.restored

# --- Backups (nur auf ausdrücklichen Wunsch) --------------------------------
if [ "$PURGE_BACKUPS" = 1 ]; then
    nuke_path backups
else
    [ -d backups ] && echo "[uninstall] ./backups/ bleibt erhalten ($(ls -1 backups 2>/dev/null | wc -l | tr -d ' ') Datei(en))."
fi

# --- Zusammenfassung --------------------------------------------------------
DIR_NAME=$(basename "$PWD")
cat <<EOF

============================================================================
  AdminHelper wurde entfernt: Container, Volumes (inkl. Root-CA), Netzwerk,
  ./data, ./certs und die .env-Secrets sind weg.
$([ "$REMOVE_IMAGES" != 1 ] && echo "
  Images noch vorhanden — entfernen mit:  ./scripts/uninstall.sh --rmi
  (oder gezielt: docker image rm <id>)")
$([ "$PURGE_BACKUPS" != 1 ] && [ -d backups ] && echo "
  Backups absichtlich behalten in ./backups/  (löschen: --purge-backups).")

  Rest des Install-Verzeichnisses (compose + scripts) entfernen:
      cd .. && rm -rf "$DIR_NAME"

  Erinnerung: Die separat aufbewahrte CA_ROOT_PASSPHRASE (Passwortmanager)
  wird ohne diese Installation nicht mehr gebraucht — du kannst sie löschen.
============================================================================
EOF
