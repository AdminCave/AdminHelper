<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-7 — strictSelectors der Desktop-E2E einschalten

Zug `tasks/klein-tests-desktop-7.md` mit R-1135. `overlap.sh` (2026-11-24): kein offener Branch ändert
`apps/desktop/e2e`. Kevin 2026-11-24: die Zeile ist frei für die Klein-Session, die Desktop-Box ist frei
(`warm.env` vom Nachtlauf), der GUI-Lauf geht auf eine frische Box.

## Problem / Motivation
WebdriverIO 10 lässt `$` bei mehr als einem Treffer werfen (`strictSelectors`). Die Specs unter
`apps/desktop/e2e/test/specs/` (rund 4300 Zeilen) sind gegen das First-Match-`$` von wdio 9 geschrieben;
`wdio.conf.js` hält das Altverhalten mit `strictSelectors: false`, bis ein GUI-Lauf zeigt, welche Selektoren
mehrdeutig sind (kern-deps-3 T3, 2026-11-05). Solange das aus ist, trifft ein Spec bei einer UI-Änderung still das
erste von mehreren Elementen und kann das falsche anklicken.

## Ziel & Nicht-Ziele
Ziel: `strictSelectors: true` in `wdio.conf.js` (die Workspaces-Konfig übernimmt `base.strictSelectors`), jeder
mehrdeutige Selektor ist eingegrenzt, der GUI-Lauf ist grün. Nicht-Ziele: neue Specs, andere Selektor-Umbauten,
Änderung der UI (ein fehlendes `data-testid` ist erlaubt, wenn der Selektor sonst nicht eindeutig wird; dann
gehört es in die Task und in `apps/desktop/ui`).

## Betroffene Komponenten & Dateien
`apps/desktop/e2e/wdio.conf.js`, `apps/desktop/e2e/test/lib/*.js`, die Specs, in denen der Lauf Mehrdeutigkeit
zeigt (Dateiliste per `ledger.sh set-files` nachgezogen). Keine API, kein Datenmodell, keine Migration.

## Vorgehen
Mit `strictSelectors: true` die GUI-Läufe (`scripts/tests/desktop_e2e_*.sh`, Teil `gui`) auf einer frischen
Desktop-Box fahren (`/vm`, `iter`), je roten Spec den Fehler „multiple elements" lesen, den Selektor eingrenzen
(Rolle, Text, `data-testid`, Elternbereich), erneut fahren, bis alle grün sind. Die Specs, die der Lauf nicht
erreicht (Multibox-Stufe: Provisioning, RDP embedded), fallen unter denselben Schalter und laufen im Capstone;
ein dort roter Spec wird eine Roadmap-Zeile.

## Trade-offs & Alternativen
Alternative: `strictSelectors` aus lassen und nur dokumentieren. Verworfen: die Zeile verlangt das Einschalten,
und first-match ist genau die Fehlerklasse, die ein Selektor-Test nicht fangen soll. Empfehlung: einschalten.

## Risiken & Rollback
Ein im Lauf nicht erreichter Spec kann erst im Capstone rot werden; Rollback ist `strictSelectors: false` und
ein Revert der Task. Die Box läuft nur im Pool `adminhelper-ci` (Lane des Vorhabens), danach `vm.py list` sauber.

## Doku-Impact
Keine: interne Test-Konfiguration ohne dokumentiertes Verhalten.

## Offene Fragen
Keine.
