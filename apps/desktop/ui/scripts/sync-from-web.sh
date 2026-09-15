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
#   ./scripts/sync-from-web.sh --check  # Gate: jeder Web-Export byte-identisch
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
#
# --check ist die Gegenrichtung und maschinenlesbar: fuer jedes
# `export interface|type|const` der QUELLE muss der gleichnamige Block im ZIEL
# byte-identisch vorhanden sein. Volle Datei-Identitaet ist kein erreichbares
# Ziel mehr (das Desktop-types.ts hat eigene Exporte, die das Web nicht kennt);
# die gemeinsame Teilmenge ist das reale Risiko: der Server-Typ aendert sich,
# das Web zieht nach, das Desktop nicht. Exit 1 bei Abweichung, Ausgabe je Symbol.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="$(dirname "${SCRIPT_DIR}")"
REPO_ROOT="$(cd "${DESKTOP_ROOT}/../../.." && pwd)"
WEB_ROOT="${REPO_ROOT}/apps/web"

FILES=(
  "src/lib/api/types.ts"
)

APPLY=0
CHECK=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  --check) CHECK=1 ;;
  "") ;;
  *) echo "Unbekannte Option: ${1}" >&2; exit 2 ;;
esac

# Listet exportierte Top-Level-Symbole (interface/type/const) einer TS-Datei.
exported_symbols() {
  grep -oE '^export (interface|type|const) [A-Za-z0-9_]+' "$1" | awk '{print $3}' | sort -u
}

# Gibt den Deklarationsblock EINES Symbols aus: von der export-Zeile bis zur
# schliessenden Klammer in Spalte 0 — oder nur die eine Zeile, wenn die
# Deklaration dort schon mit ';' endet (type-Aliase, const). Nur Spalte 0 zaehlt
# als Ende: ein Feld wie `  id: number;` beendet den Block sonst sofort.
symbol_block() {
  awk -v start="^export (interface|type|const) $2([^A-Za-z0-9_]|\$)" '
    !inblk && $0 ~ start { print; if ($0 ~ /;[ \t]*$/) exit; inblk = 1; next }
    inblk { print; if ($0 ~ /^}/) exit }
  ' "$1"
}

# --check: jeder Export der Quelle muss im Ziel byte-identisch stehen.
check_file() {
  local rel="$1" src="$2" dst="$3" sym missing=0 differing=0
  for sym in $(exported_symbols "${src}"); do
    local a b
    a="$(symbol_block "${src}" "${sym}")"
    b="$(symbol_block "${dst}" "${sym}")"
    if [[ -z "${b}" ]]; then
      echo "FEHLT:      ${rel}: ${sym}" >&2
      missing=$((missing + 1))
    elif [[ "${a}" != "${b}" ]]; then
      echo "ABWEICHUNG: ${rel}: ${sym}" >&2
      diff -u <(printf '%s\n' "${b}") <(printf '%s\n' "${a}") \
        --label "desktop/${sym}" --label "web/${sym}" | sed 's/^/  /' >&2
      differing=$((differing + 1))
    fi
  done
  if (( missing + differing > 0 )); then
    echo "${rel}: ${missing} fehlend, ${differing} abweichend" >&2
    return 1
  fi
  echo "=== ${rel}: alle $(exported_symbols "${src}" | wc -l) Web-Exporte identisch ==="
}

CHECK_FAILED=0
for rel in "${FILES[@]}"; do
  src="${WEB_ROOT}/${rel}"
  dst="${DESKTOP_ROOT}/${rel}"
  if [[ ! -f "${src}" ]]; then
    echo "FEHLER: Quelldatei fehlt: ${src}" >&2
    exit 1
  fi
  # --check kopiert nichts, also greift der Ueberschreib-Schutz unten nicht: er
  # bewacht --apply. Wuerde er hier zuerst abbrechen, meldete das Gate immer nur
  # "Ziel hat eigene Exporte" — und genau die sind erlaubt (Teilmengen-Paritaet).
  if (( CHECK == 1 )); then
    check_file "${rel}" "${src}" "${dst}" || CHECK_FAILED=1
    continue
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

if (( CHECK == 1 )); then
  exit "${CHECK_FAILED}"
fi

if [[ ${APPLY} -eq 0 ]]; then
  echo
  echo "Hinweis: Nur diff angezeigt. Mit --apply werden die Dateien tatsaechlich kopiert."
fi
