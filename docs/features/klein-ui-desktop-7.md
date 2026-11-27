# klein-ui-desktop-7 — Desktop-UI: Enter-Doppelausloesung und Fehler-Banner

Roadmap R-0439 (BUG), R-0783 (IDEE).

## Problem
- **R-0439:** In `MonCheckLine.svelte` tragen die Aktions-Buttons (Bearbeiten, Jetzt pruefen, Aktivieren) einen
  `onkeydown`-Handler, der bei Enter die Aktion ausfuehrt. Der Handler ruft kein `preventDefault`, der Browser
  synthetisiert fuer Enter auf einem `<button>` zusaetzlich den Klick: die Aktion laeuft doppelt, der Toggle hebt sich
  auf. Der Handler auf der Zeile braucht den Schutz, dass Enter eines Buttons nicht bis zur Zeile durchschlaegt.
- **R-0783:** `reloadForMode` in `connections.ts` setzt zu Beginn jedes Abrufs `error: null`. Faellt der Sync im Takt
  aus, verschwindet das Banner je Abruf kurz und wird per `role=alert` erneut angesagt.

## Ziel & Nicht-Ziele
- Enter auf einem Aktions-Button loest genau einmal aus und expandiert die Zeile nicht; Enter auf der Zeile expandiert.
- `error` bleibt waehrend eines Abrufs stehen und wird erst bei Erfolg geloescht (oder durch den neuen Fehler ersetzt).
- Nicht-Ziel: `load()` (ohne Modus) und andere Zeilen mit demselben Muster.

## Betroffene Dateien
`apps/desktop/ui/src/components/monitoring/section/MonCheckLine.svelte` (+ neuer Test `MonCheckLine.test.ts`),
`apps/desktop/ui/src/lib/stores/connections.ts` (+ `connections.reload.test.ts`).

## Datenmodell / API
Keine. Kein Vertrag, keine Migration.

## Trade-offs
Reset-Button nutzt schon das Muster "Enter nur nicht zur Zeile durchlassen". Gewaehlt: die Zeile ignoriert Tasten,
die nicht von ihr selbst stammen (`e.target === e.currentTarget`), die Button-Handler entfallen. Eine Stelle statt
vier.

## Risiken & Rollback
Gering, rein UI; je Task einzeln zuruecknehmbar. Das WebView-Verhalten ist nicht verifiziert (kein Display), der
Komponententest belegt den Handler-Pfad in jsdom.

## Doku-Impact
Keine (kein dokumentiertes Verhalten betroffen); CHANGELOG ueber `changelog.d/klein-ui-desktop-7.md`.

## Offene Fragen
Keine.
