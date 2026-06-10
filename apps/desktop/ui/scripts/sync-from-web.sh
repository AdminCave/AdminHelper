#!/usr/bin/env bash
# Synchronisiert gemeinsam genutzte Datei-Blaetter aus dem Web-Frontend
# (apps/web/) in das Desktop-Projekt (apps/desktop/ui/).
#
# Hintergrund: Es gibt bewusst KEIN Monorepo / keine shared/-Pakete.
# Stattdessen werden reine Daten-Module kopiert und bei Bedarf manuell
# per diff verglichen.
#
# Verwendung:
#   ./scripts/sync-from-web.sh          # zeigt diff vorher
#   ./scripts/sync-from-web.sh --apply  # kopiert tatsaechlich
#
# Die Dateien, die synchronisiert werden:
#   src/lib/api/types.ts (Backend-API-Types)
#
# Die i18n-Dictionaries (src/lib/i18n/dictionaries.ts) sind BEWUSST getrennt:
# Web und Desktop pflegen eigene Uebersetzungen und werden NICHT synchronisiert.
# Alle anderen Module (client.ts, auth.ts, etc.) unterscheiden sich ebenfalls
# absichtlich zwischen Web und Desktop (localStorage vs Tauri-Store etc.).
#
# Schutz: Enthaelt die Ziel-Datei exportierte Symbole, die in der Quelle
# fehlen, bricht das Skript ab statt sie still zu ueberschreiben.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="$(dirname "${SCRIPT_DIR}")"
REPO_ROOT="$(cd "${DESKTOP_ROOT}/../../.." && pwd)"
WEB_ROOT="${REPO_ROOT}/apps/web"

FILES=(
  "src/lib/api/types.ts"
)

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
fi

# Listet exportierte Top-Level-Symbole (interface/type/const) einer TS-Datei.
exported_symbols() {
  grep -oE '^export (interface|type|const) [A-Za-z0-9_]+' "$1" | awk '{print $3}' | sort -u
}

for rel in "${FILES[@]}"; do
  src="${WEB_ROOT}/${rel}"
  dst="${DESKTOP_ROOT}/${rel}"
  if [[ ! -f "${src}" ]]; then
    echo "FEHLER: Quelldatei fehlt: ${src}" >&2
    exit 1
  fi
  if [[ -f "${dst}" ]]; then
    missing="$(comm -23 <(exported_symbols "${dst}") <(exported_symbols "${src}"))"
    if [[ -n "${missing}" ]]; then
      echo "FEHLER: ${rel}: Ziel-Datei enthaelt Exporte, die in der Quelle fehlen:" >&2
      echo "${missing}" | sed 's/^/  - /' >&2
      echo "Abbruch — erst die Quelle (apps/web) nachziehen, dann erneut synchronisieren." >&2
      exit 1
    fi
  fi
  if ! diff -q "${src}" "${dst}" >/dev/null 2>&1; then
    echo "=== Unterschied: ${rel} ==="
    diff -u "${dst}" "${src}" || true
    if [[ ${APPLY} -eq 1 ]]; then
      cp "${src}" "${dst}"
      echo "-> uebernommen"
    fi
  else
    echo "=== ${rel}: identisch ==="
  fi
done

if [[ ${APPLY} -eq 0 ]]; then
  echo
  echo "Hinweis: Nur diff angezeigt. Mit --apply werden die Dateien tatsaechlich kopiert."
fi
