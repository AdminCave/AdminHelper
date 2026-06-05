#!/usr/bin/env bash
# Synchronisiert gemeinsam genutzte Datei-Blaetter aus dem Web-Frontend
# (apps/web/) in das Desktop-Projekt (apps/desktop/ui/).
#
# Hintergrund: Es gibt bewusst KEIN Monorepo / keine shared/-Pakete.
# Stattdessen werden reine Daten-Module (Types, i18n-Dictionaries) kopiert
# und bei Bedarf manuell per diff verglichen.
#
# Verwendung:
#   ./scripts/sync-from-web.sh          # zeigt diff vorher
#   ./scripts/sync-from-web.sh --apply  # kopiert tatsaechlich
#
# Die Dateien, die synchronisiert werden:
#   src/lib/api/types.ts         (Backend-API-Types)
#   src/lib/i18n/dictionaries.ts (Uebersetzungs-Strings, DE/EN)
#
# Alle anderen Module (client.ts, auth.ts, etc.) unterscheiden sich absichtlich
# zwischen Web und Desktop (localStorage vs Tauri-Store etc.) und werden NICHT
# synchronisiert.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="$(dirname "${SCRIPT_DIR}")"
REPO_ROOT="$(cd "${DESKTOP_ROOT}/../../.." && pwd)"
WEB_ROOT="${REPO_ROOT}/apps/web"

FILES=(
  "src/lib/api/types.ts"
  "src/lib/i18n/dictionaries.ts"
)

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
fi

for rel in "${FILES[@]}"; do
  src="${WEB_ROOT}/${rel}"
  dst="${DESKTOP_ROOT}/${rel}"
  if [[ ! -f "${src}" ]]; then
    echo "FEHLER: Quelldatei fehlt: ${src}" >&2
    exit 1
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
