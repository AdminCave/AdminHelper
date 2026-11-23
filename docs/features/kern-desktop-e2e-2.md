# kern-desktop-e2e-2 — settings-enroll.live.js: Ablehnungstext in der Fehlermeldung

Roadmap: R-0573 (REF, aus dem reviewer-Urteil desktop-fixes-2 T4).

## Problem
`apps/desktop/e2e/test/specs/settings-enroll.live.js` liest an zwei Stellen (Zeile 151 und 201) nur `.value` aus dem
Ergebnis von `invoke('tunnel_status')`. Lehnt das Backend den Befehl ab, kommt `{ rejected: "<Text>" }` zurück,
`.value` ist `undefined`, und die Spec scheitert an einer folgenden Erwartung oder läuft in den `waitUntil`-Timeout,
ohne den Ablehnungstext zu nennen. `tunnel-connect.live.js` hat dafür einen werfenden Helfer (`invoke`, Zeile 36–48:
`throw new Error(\`${cmd} failed: ${out.rejected}\`)`).

## Ziel & Nicht-Ziele
- **Ziel:** ein Helfer `invokeValue(cmd, args)` in `settings-enroll.live.js`, der wie in `tunnel-connect.live.js`
  bei `rejected` mit dem Text wirft und sonst `value` liefert; die zwei Stellen nutzen ihn. Die Stelle
  `expect(await invoke('device_identity')).toEqual({ value: null })` (Zeile 191) bleibt: `toEqual` zeigt einen
  Ablehnungstext schon im Diff.
- **Nicht-Ziele:** kein gemeinsames Helfer-Modul für alle Specs (YAGNI: zwei Dateien), keine Änderung am Ablauf der
  Spec.

## Betroffene Komponenten & Dateien
`apps/desktop/e2e/test/specs/settings-enroll.live.js` (Komponente `desktop-e2e`).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine (Tauri-Bridge unverändert).

## Trade-offs & Alternativen
In `waitUntil` (Zeile 201) wirft der Helfer beim ersten abgelehnten Aufruf statt bis zum Timeout zu warten. Das ist
gewollt: Ein abgelehntes `tunnel_status` ist kein Zwischenzustand, sondern ein Fehler, und die Meldung trägt nun
seinen Text.

## Risiken & Rollback
Gering; nur Testcode. Der Beweis läuft im nächtlichen Sammellauf (`desktop_e2e_tunnel`). Rollback: Revert.

## Doku-Impact
Keine (Testcode, kein dokumentiertes Verhalten).

## Offene Fragen
Keine.
