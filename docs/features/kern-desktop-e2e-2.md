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
In `waitUntil` (Zeile 208) wirft der Helfer `invokeValue('tunnel_status')` bei einem abgelehnten Aufruf. `waitUntil`
bricht deshalb nicht beim ersten Wurf ab: wdio wiederholt eine werfende Bedingung im Intervall bis zum Timeout
(`Timer._checkCondition`) und lehnt dann mit dem zuletzt geworfenen Fehler ab, als `waitUntil condition failed with
the following reason: <Text>`; `timeoutMsg` gilt nur, wenn die Bedingung bis zuletzt `false` lieferte. Ein dauerhaft
abgelehntes `tunnel_status` ist ein Fehler, kein Zwischenzustand, und die Meldung trägt nun seinen Text. Belegt am
Quelltext von wdio 9.29.0 (lokal installiert); das Lockfile nennt 10.1.0, dessen Quelltext war hier nicht
installiert, die Logik ist dort nicht verifiziert.

## Risiken & Rollback
Gering; nur Testcode. Der Beweis läuft im nächtlichen Sammellauf (`desktop_e2e_tunnel`). Rollback: Revert.

## Doku-Impact
Keine (Testcode, kein dokumentiertes Verhalten).

## Offene Fragen
Keine.
