<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-28 — Agent: Zugangsdaten unter Windows trotz kurz gesperrter Datei lesen

Roadmap: R-1823 (BUG), von Kevin am 2026-11-27 angenommen.

## Problem
`TestSetKeepsTheOtherSetsMadeAtTheSameTime` (`apps/agent/internal/credentials/store_test.go`) fiel im CI-Lauf
45893033754 (Attempt 1, Job „Go Agent (test, Windows)“) mit `open …\monitor\credentials.json: Access is denied.`;
Attempt 2 war grün, `internal/credentials` unverändert. Der Fehler kommt aus `readPrivate`
(`store_windows.go`), das `Load` unter der Sperre von `update` aufruft: das Öffnen scheitert, solange ein anderer
Prozess (Virenscanner, Indexer) die eben ersetzte Datei ohne Lese-Freigabe hält oder sie noch zum Löschen ansteht.
Welcher der beiden Fälle es auf dem Runner war, ist nicht belegt.

## Ziel & Nicht-Ziele
- Ziel: `readPrivate` öffnet unter Windows erneut, solange `ERROR_ACCESS_DENIED` oder `ERROR_SHARING_VIOLATION`
  kommt, bis `replaceWait` (2 s) vorbei ist, wie `replace` und Gos `cmd/internal/robustio`. Eine fehlende Datei
  bleibt sofort „keine Zugangsdaten“.
- Nicht-Ziel: Linux (kein solcher Zustand), andere Dateien des Agents.

## Betroffene Komponenten & Dateien
`apps/agent/internal/credentials/store_windows.go`, `store_windows_test.go`.

## Datenmodell / API / Migrationen
Keine.

## Trade-offs & Alternativen
Eine Datei, deren ACL den Agent wirklich aussperrt, meldet ihren Fehler erst nach 2 s statt sofort. Das ist
hingenommen: der Fall ist selten und endet mit demselben Fehler. Alternative: nur `ERROR_SHARING_VIOLATION`
wiederholen. Abgelehnt, weil der belegte Fehler `ERROR_ACCESS_DENIED` ist.

## Risiken & Rollback
Nur Windows. Rollback: den Task-Commit zurücknehmen.

## Tests
Zwei Windows-Tests im CI-Job `agent-windows`: ein Halter ohne Freigabe (`ERROR_SHARING_VIOLATION`) lässt nach
200 ms los, `Load` liest die Datei; eine zum Löschen anstehende Datei (`ERROR_ACCESS_DENIED`) verschwindet beim
Schließen, `Load` meldet keine Zugangsdaten statt eines Fehlers. Dauerlauf: ein Windows-only-Wackler ohne
Schleifenweg, „nicht verifiziert“ (`.claude/rules/testing.md`).

## Doku-Impact
Keine Doku-Seite beschreibt das Öffnen; ein Changelog-Eintrag unter „Fixed“.

## Offene Fragen
Keine.
