#!/usr/bin/env bash
#
# uninstall.sh — vollständige Deinstallation eines AdminHelper-Servers.
#
# Fragt INTERAKTIV pro Kategorie nach, was entfernt werden soll, und räumt dann
# auf, was install.sh/update.sh auf dem Host hinterlassen:
#   1. Stack stoppen        — Container + Netzwerk des Compose-Projekts
#   2. Daten-Volumes        — ALLE Named Volumes, inkl. ca-pki (die Root-CA!),
#                             postgres-data, victoria-data  (unwiederbringlich)
#   3. Host-Daten           — die Bind-Mounts ./data und ./certs (uid 10001)
#   4. Secrets              — .env (+ eine evtl. .env.restored aus einem Restore)
#   5. Backups              — ./backups/   (Default: BEHALTEN)
#   6. Docker-Images        — die Stack-Images   (Default: BEHALTEN)
#
# Erst werden alle Fragen gestellt, dann wird gelöscht (so kann keine Antwort
# eine andere blockieren — Volumes lassen sich erst nach dem Stack-Stop entfernen).
#
# Die Laufzeit-Dateien selbst (docker-compose.yml, .env.example, scripts/) werden
# NICHT angefasst — ein laufendes Skript löscht sein eigenes Verzeichnis nicht.
# Den exakten Aufräum-Befehl gibt das Skript am Ende aus.
#
# Aus dem Install-Verzeichnis ausführen (dort, wo die docker-compose.yml liegt):
#   ./scripts/uninstall.sh                 # interaktiv, fragt pro Kategorie
#   ./scripts/uninstall.sh --yes           # nicht-interaktiv: Stack+Volumes+Daten
#                                          # +.env weg, Backups/Images behalten
#   ./scripts/uninstall.sh --purge-backups # Backup-Frage auf JA vorbelegen
#                                          # (bzw. mit --yes: Backups mit löschen)
#   ./scripts/uninstall.sh --rmi           # Image-Frage auf JA vorbelegen
# Kombiniert "wirklich alles weg":
#   ./scripts/uninstall.sh --rmi --purge-backups --yes

set -euo pipefail

ASSUME_YES=0
PURGE_BACKUPS=0
REMOVE_IMAGES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --purge-backups) PURGE_BACKUPS=1 ;;
        --rmi) REMOVE_IMAGES=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

# --- Preflight --------------------------------------------------------------
[ -f docker-compose.yml ] || { echo "FEHLER: aus dem Install-Verzeichnis ausführen (docker-compose.yml fehlt)." >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "FEHLER: docker fehlt." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "FEHLER: 'docker compose' fehlt." >&2; exit 1; }

# Compose-Projektname (= Volume-/Netzwerk-Präfix bzw. -Label). Default ist der
# Verzeichnisname; identisch zu restore.sh, damit der Label-Sweep dieselben
# Ressourcen trifft, die `docker compose up` angelegt hat.
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9_-]//g')}"

# Rückfragen müssen vom kontrollierenden Terminal lesen (analog install.sh):
# unter `curl | bash` wäre stdin die Skript-Pipe. ACHTUNG: `[ -r /dev/tty ]`
# prüft nur das Datei-Bit, nicht ob sich /dev/tty wirklich ÖFFNEN lässt (ohne
# Controlling-Terminal — Pipe, </dev/null, cron — schlägt das open() fehl). Wir
# testen die echte Öffenbarkeit, sonst liefe jedes read auf EOF und würde
# fälschlich den Default ("ja, löschen") annehmen.
if (exec </dev/tty) 2>/dev/null; then TTY=/dev/tty; else TTY=""; fi
if [ "$ASSUME_YES" != 1 ] && [ -z "$TTY" ]; then
    echo "FEHLER: Kein nutzbares Terminal für die Rückfragen. Nutze --yes für einen nicht-interaktiven Lauf." >&2
    exit 1
fi

# Interaktive Ja/Nein-Frage mit Default ($2 = j|n). Im --yes-Modus wird nicht
# gefragt: das Ergebnis ist dann der Default. Liefert 0 = ja/löschen, 1 = nein.
ask() {
    local q="$1" def="$2" ans hint
    if [ "$ASSUME_YES" = 1 ]; then
        if [ "$def" = j ]; then return 0; else return 1; fi
    fi
    if [ "$def" = j ]; then hint="[J/n]"; else hint="[j/N]"; fi
    printf "  %s %s " "$q" "$hint"
    # Ein fehlgeschlagenes read (EOF/kein Terminal) darf NIEMALS still als Default
    # durchgehen — sonst würde aus "konnte nicht fragen" ein "ja, löschen".
    if ! read -r ans <"$TTY"; then
        echo >&2
        echo "FEHLER: Konnte nicht vom Terminal lesen — Abbruch (nichts wurde gelöscht)." >&2
        exit 1
    fi
    case "${ans:-}" in
        j|J|ja|JA|Ja|y|Y|yes|Yes) return 0 ;;
        n|N|nein|NEIN|Nein|no|No)  return 1 ;;
        *) if [ "$def" = j ]; then return 0; else return 1; fi ;;
    esac
}

# --- Inventur ---------------------------------------------------------------
CONTAINERS=$(docker compose ps --all --quiet 2>/dev/null | wc -l | tr -d ' ')
echo "============================================================================"
echo "  AdminHelper-Deinstallation   (Compose-Projekt: $PROJECT, ${CONTAINERS} Container)"
echo "  Du wirst für jede Kategorie einzeln gefragt — gelöscht wird erst danach."
echo "============================================================================"

# --- Fragen sammeln ---------------------------------------------------------
# Backup-/Image-Default folgt dem jeweiligen Flag (Vorbelegung der Frage).
BK_DEFAULT=$([ "$PURGE_BACKUPS" = 1 ] && echo j || echo n)
IM_DEFAULT=$([ "$REMOVE_IMAGES" = 1 ] && echo j || echo n)

if ! ask "1) Stack stoppen — Container + Netzwerk entfernen?" j; then
    echo "Abgebrochen — nichts wurde verändert."
    exit 0
fi
DEL_VOLUMES=0;  if ask "2) Daten-Volumes löschen (DB, Root-CA, Metriken — UNWIEDERBRINGLICH)?" j; then DEL_VOLUMES=1; fi
DEL_HOSTDATA=0; if ask "3) Host-Daten ./data + ./certs löschen?" j; then DEL_HOSTDATA=1; fi
DEL_ENV=0;      if ask "4) Secrets-Datei .env löschen?" j; then DEL_ENV=1; fi
DEL_BACKUPS=0;  if [ -d backups ] && ask "5) Backups ./backups/ löschen?" "$BK_DEFAULT"; then DEL_BACKUPS=1; fi
DEL_IMAGES=0;   if ask "6) Docker-Images des Stacks löschen?" "$IM_DEFAULT"; then DEL_IMAGES=1; fi

# --- Stack runterfahren (Container + Netzwerk; Volumes/Images bedingt) -------
DOWN_ARGS=(down --remove-orphans)
[ "$DEL_VOLUMES" = 1 ] && DOWN_ARGS+=(--volumes)
[ "$DEL_IMAGES" = 1 ] && DOWN_ARGS+=(--rmi all)

echo "[uninstall] Stoppe und entferne den Stack..."
if ! docker compose "${DOWN_ARGS[@]}"; then
    echo "[uninstall] WARN: 'docker compose down' schlug fehl — räume per Projekt-Label auf." >&2
fi

# Gürtel-und-Hosenträger: Reste, die eine defekte/abweichende Compose-Datei
# stehengelassen haben könnte, per Projekt-Label einsammeln. Strikt auf DIESES
# Projekt gefiltert, damit keine fremden Stacks getroffen werden.
LABEL="com.docker.compose.project=$PROJECT"
docker ps -aq --filter "label=$LABEL" | xargs -r docker rm -f >/dev/null 2>&1 || true
docker network ls -q --filter "label=$LABEL" | xargs -r docker network rm >/dev/null 2>&1 || true
if [ "$DEL_VOLUMES" = 1 ]; then
    docker volume ls -q --filter "label=$LABEL" | xargs -r docker volume rm >/dev/null 2>&1 || true
fi

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

if [ "$DEL_HOSTDATA" = 1 ]; then nuke_path data; nuke_path certs; fi
if [ "$DEL_ENV" = 1 ]; then nuke_path .env; nuke_path .env.restored; fi
if [ "$DEL_BACKUPS" = 1 ]; then nuke_path backups; fi

# --- Zusammenfassung --------------------------------------------------------
DIR_NAME=$(basename "$PWD")
echo
echo "============================================================================"
echo "  Deinstallation abgeschlossen."
echo "  Entfernt:   Container + Netzwerk"
if [ "$DEL_VOLUMES" = 1 ];  then echo "              Named Volumes (inkl. Root-CA, DB, Metriken)"; else echo "              [behalten] Named Volumes — Daten bleiben erhalten"; fi
if [ "$DEL_HOSTDATA" = 1 ]; then echo "              ./data + ./certs"; else echo "              [behalten] ./data + ./certs"; fi
if [ "$DEL_ENV" = 1 ];      then echo "              .env (Secrets)"; else echo "              [behalten] .env (Secrets)"; fi
if [ "$DEL_BACKUPS" = 1 ];  then echo "              ./backups/"; elif [ -d backups ]; then echo "              [behalten] ./backups/  (löschen: --purge-backups)"; fi
if [ "$DEL_IMAGES" = 1 ];   then echo "              Docker-Images"; else echo "              [behalten] Docker-Images  (löschen: --rmi)"; fi
echo "----------------------------------------------------------------------------"
echo "  Rest des Install-Verzeichnisses (compose + scripts) entfernen:"
echo "      cd .. && rm -rf \"$DIR_NAME\""
if [ "$DEL_VOLUMES" = 1 ]; then
    echo
    echo "  Hinweis: Mit ca-pki ist die Root-CA weg — enrollte Agenten/Clients"
    echo "  werden nicht mehr vertraut. Die separat aufbewahrte CA_ROOT_PASSPHRASE"
    echo "  (Passwortmanager) wird nicht mehr gebraucht und kann gelöscht werden."
fi
echo "============================================================================"
