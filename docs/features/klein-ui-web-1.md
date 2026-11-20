<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-web-1

## Problem / Motivation
R-1658: `apps/web/public/logo.svg` ist kein wohlgeformtes XML (`xmllint --noout`: `AttValue: " or ' expected`). Ein
Kommentar im `<style>` enthaelt `<link rel=icon>`; ein Browser laedt ein SVG-Favicon als XML und verwirft die ganze
Datei beim ersten Parse-Fehler. Die Web-App hat dadurch kein Favicon. Gleicher Fehler wie R-1592 T2 im Desktop-UI.

## Ziel & Nicht-Ziele
Ziel: Kommentar ohne `<` (Wortlaut wie `apps/desktop/ui/public/logo.svg`), dazu ein Parse-Test in `apps/web`.
Nicht-Ziele: das Zeichen aendern, andere SVGs anfassen.

## Betroffene Komponenten & Dateien
`apps/web/public/logo.svg`, neu `apps/web/src/logo.test.ts` (Vorbild `apps/desktop/ui/src/logo.test.ts`).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Kommentar umformulieren statt `<` zu escapen: gleiche Loesung wie im Desktop, kein Verhaltensunterschied.

## Risiken & Rollback
Gering; Asset-Aenderung, per Revert zuruecknehmbar.

## Doku-Impact
Keine; nur Changelog-Fragment.

## Offene Fragen
Keine.
