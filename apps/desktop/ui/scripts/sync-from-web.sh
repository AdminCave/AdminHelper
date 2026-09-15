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
#   ./scripts/sync-from-web.sh --check  # Gate: Schnittmenge als Teilmenge
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
# --check ist die Gegenrichtung und maschinenlesbar. Geprueft wird die SCHNITT-
# MENGE: fuer jedes Symbol, das BEIDE Dateien exportieren, muss jede Zeile des
# Quell-Blocks auch im Ziel-Block stehen.
#
# Warum nicht byte-identisch, und warum nicht "jeder Quell-Export muss ins Ziel":
# die beiden Dateien sind laengst keine gemeinsame Datei mehr. Das Web-types.ts
# beschreibt die Admin-Panel-API (25 Exporte: User, ApiKey, Hook, Audit), das
# Desktop-types.ts die Client-API (58 Exporte: Connection, Monitoring,
# Notifications, Playbooks). Gemeinsam sind genau VIER Symbole - FrpConfig,
# FrpStatus, FrpStatusProxy, Server. Nur die sind doppelt gepflegt, nur die
# koennen driften.
#
# Teilmenge statt Gleichheit, weil dieselbe Server-Antwort links und rechts
# unterschiedlich weit projiziert wird: `Server` traegt im Desktop zusaetzlich
# `connections?: Connection[]`, und das ist richtig - `to_dict()` liefert das Feld
# (zusammen mit `createdAt` und `frpTunnels`, die KEINE der beiden Seiten
# deklariert), das Admin-Panel ignoriert es nur. Die Regel faengt den realen Fall:
# das Web zieht ein neues Server-Feld nach, das Desktop nicht.
#
# WO DER GUARD BLIND IST: die Loeschrichtung. Entfernt das Web ein Feld, bleibt
# die Teilmenge erfuellt - das Desktop behaelt die Leiche, und niemand meldet es.
# Das ist der Preis der Teilmengen-Regel und die einzige der sechs Drift-Formen,
# die sie nicht faengt (umbenannt, Typ geaendert, im Ziel entfernt: alle rot).
# Exit 1 bei Abweichung, Ausgabe je Symbol.

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
  awk -v name="$2" '
    # Ein interface endet an der schliessenden Klammer in Spalte 0. Ein type- oder
    # const-Alias endet an der ersten Zeile mit ";" - AUSSER die Deklaration
    # oeffnet einen Objekt- oder Array-Body (`= {`, `= [`), dann gilt wieder die
    # Klammer-Regel. Ohne diese Unterscheidung wuerde `export type X = {` nach der
    # ersten Feldzeile abbrechen, und zwar auf BEIDEN Seiten gleich - also nicht
    # falsch-rot, sondern falsch-gruen.
    !inblk && $0 ~ "^export interface " name "([^A-Za-z0-9_]|$)" { print; inblk = "brace"; next }
    !inblk && $0 ~ "^export (type|const) " name "([^A-Za-z0-9_]|$)" {
      print
      if ($0 ~ /;[ \t]*$/) exit
      inblk = ($0 ~ /[{[][ \t]*$/) ? "brace" : "semi"
      next
    }
    inblk == "brace" { print; if ($0 ~ /^[}\]]/) exit; next }
    inblk == "semi"  { print; if ($0 ~ /;[ \t]*$/) exit; next }
  ' "$1"
}

# --check: jede Zeile eines gemeinsamen Symbols muss auch im Ziel stehen.
#
# Die geteilte Menge steht hier NAMENTLICH, nicht als Mindestzahl. Ein blosser
# Zaehl-Boden greift erst, wenn mehrere Symbole auf einmal verschwinden - genau
# der unrealistische Fall. Der realistische ist der einzelne Refactor: ein Symbol
# umbenannt oder geloescht, und der Guard meldet weiter "keine Abweichung" fuer
# den Rest. Faellt eines dieser vier legitim weg, ist das eine bewusste Aenderung
# dieser Zeile - kein stilles Schrumpfen.
CHECK_SHARED=(FrpConfig FrpStatus FrpStatusProxy Server)

check_file() {
  local rel="$1" src="$2" dst="$3" sym shared=0 differing=0
  local absent=() gone=()
  # Ohne das meldet eine fehlende Zieldatei jedes einzelne Symbol als FEHLT und
  # verschuettet die eigentliche Ursache unter 25 awk-Fehlern.
  if [[ ! -f "${dst}" ]]; then
    echo "FEHLER: ${rel}: Ziel-Datei fehlt: ${dst}" >&2
    return 1
  fi
  for sym in $(exported_symbols "${src}"); do
    local a b missing
    b="$(symbol_block "${dst}" "${sym}")"
    if [[ -z "${b}" ]]; then
      absent+=("${sym}")
      continue
    fi
    shared=$((shared + 1))
    a="$(symbol_block "${src}" "${sym}")"
    missing="$(comm -23 <(printf '%s\n' "${a}" | sort) <(printf '%s\n' "${b}" | sort))"
    if [[ -n "${missing}" ]]; then
      echo "ABWEICHUNG: ${rel}: ${sym} - im Ziel fehlen Zeilen der Quelle:" >&2
      printf '%s\n' "${missing}" | sed 's/^/    /' >&2
      differing=$((differing + 1))
    fi
  done

  # Jedes erwartete gemeinsame Symbol muss auch wirklich gemeinsam sein.
  local expected
  for expected in "${CHECK_SHARED[@]}"; do
    if [[ -z "$(symbol_block "${dst}" "${expected}")" || -z "$(symbol_block "${src}" "${expected}")" ]]; then
      gone+=("${expected}")
    fi
  done

  # Nur eine Information: die beiden Dateien beschreiben verschiedene API-Flaechen,
  # ein Quell-Export ohne Gegenstueck ist der Normalfall, kein Fehler.
  if (( ${#absent[@]} > 0 )); then
    echo "=== ${rel}: ${#absent[@]} Quell-Exporte ohne Gegenstueck im Ziel (ok, getrennte Flaechen)"
    printf '    %s\n' "${absent[*]}"
  fi

  if (( ${#gone[@]} > 0 )); then
    echo "FEHLER: ${rel}: erwartete gemeinsame Symbole fehlen auf einer Seite: ${gone[*]}" >&2
    echo "  Wenn das Absicht ist, CHECK_SHARED in diesem Skript anpassen." >&2
    return 1
  fi
  if (( differing > 0 )); then
    echo "${rel}: ${differing} von ${shared} gemeinsamen Symbolen weichen ab" >&2
    return 1
  fi
  echo "=== ${rel}: ${shared} gemeinsame Symbole, keine Abweichung ==="
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
