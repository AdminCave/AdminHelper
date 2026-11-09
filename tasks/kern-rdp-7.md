# Eingebettetes RDP: Live-Spec erwartet die falsche feste Größe — Task-Ledger
Status: aktiv · Branch: feature/kern-rdp-7 · Review: am Ende
Spec: docs/features/kern-rdp-7.md (Roadmap R-1205)
Heavy: linux-full — Fix eines REG aus dem Sammellauf; Beweis vor dem Merge: Schritt desktop_e2e_connect auf der Box der Lane (`iter.sh --cmd`, der `--step`-Name ist mehrdeutig, R-1206)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1205: Die Live-Spec erwartet die gespeicherte eigene Größe  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/rdp-embedded.live.js
Änderung: Der Prüfteil zur festen Größe wartet nach `chooseWindowMode('custom')` auf 1920x1080 statt 1280x720; der Kommentar nennt den Grund (der zuvor gespeicherte Einstellungsdialog legt seine Vorgabe 1920x1080 als eigene Größe ab).
Beweis: main@d5092bc55 · `env -u AH_REQUIRED bash scripts/vm/iter.sh --cmd 'AH_ALLOW_REAL=1 AH_CAPTURE=1 bash scripts/tests/desktop_e2e_connect.sh'` → `desktop_e2e_connect: 16 passed, 1 failed`, „the fixed desktop never had 1280x720“ (Sammellauf 2026-11-09 und dreimal auf der Box der Lane)
Dedup-Key: reg:desktop-e2e:rdp-embedded.live.js:fixed_1280x720
HEAD: cdd40c637
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (nur Testcode, kein dokumentiertes Verhalten)

## Entscheidungen
- Die Spec folgt der Vorgabe des Dialogs, statt die eigene Größe im Dialog zu setzen: kleinste Änderung, die den Fund behebt; die Angleichung der beiden Vorgaben ist Kevins Entscheidung und eine eigene Zeile.
