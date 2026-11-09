<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-bug-notifyprefs-1 — Desktop: Benachrichtigungs-Einstellungen, Ton, Incident-Typ

Zug `tasks/klein-bug-notifyprefs-1.md` mit R-1184, R-1183 und R-1150. Funde der Prüfung von `kern-notify-3`
(2026-11-07) und `arch-notify-incidents` (2026-11-05); beide Branches sind gemergt, die Stellen stehen auf `main`.
`overlap.sh` (2026-11-09): kein offener Branch ändert die Dateien dieser drei Zeilen.

## Problem / Motivation

- **R-1184 (BUG, Nutzerwirkung):** `NotificationPrefs.svelte` sendet beim Speichern immer
  `Intl.DateTimeFormat().resolvedOptions().timeZone` und die Ruhezeit-Felder, wie sie im Formular stehen. Liefert die
  Webview `Etc/Unknown` (der Server kennt die Zone nicht: `_check_timezone`, `schemas.py`) oder ist ein Zeitfeld
  geleert (`ClockTime` verlangt `HH:MM`), antwortet der Server 422 und die ganze Speicherung scheitert, auch für
  alle anderen Einstellungen.
- **R-1183 (BUG):** `sound.ts` legt den `AudioContext` an und spielt sofort. Startet er `suspended` (kein
  Nutzergeste seit Start), bleibt der Ton stumm.
- **R-1150 (REF):** `IncidentEntry.severity` (`types.ts:685`) kennt `ok` nicht, den der Hub bei Erholungen
  schreibt. Heute zeigt die UI den Wert nicht an; der Typ lügt.

## Ziel & Nicht-Ziele

Ziel: Speichern gelingt auch bei unbekannter Zone (die Zone wird dann nicht mitgesendet, der Server behält die
gespeicherte) und bei geleertem Zeitfeld (der zuletzt gespeicherte Wert gilt); der Ton versucht `resume()` auf
einem `suspended` Context; der Typ nennt `ok`. Nicht-Ziele: neue Fehlermeldungen im Formular, serverseitige
Änderungen, Anzeige von `ok`-Einträgen.

## Betroffene Komponenten & Dateien

Nur `desktop-ui`: `components/NotificationPrefs.svelte` (+ Test), `lib/sound.ts` (+ neuer Test `sound.test.ts`),
`lib/api/types.ts`.

## Datenmodell / API / Migrationen

Keine. Der Vertrag mit dem Server bleibt; `timezone` ist dort bereits optional.

## Trade-offs

R-1184: Alternative wäre eine Fehlermeldung bei leerem Zeitfeld. Das braucht einen neuen Text in
`dictionaries.ts`, die ein offener Branch (`feature/kern-ansible-1`) ändert; der stille Rückfall auf den
gespeicherten Wert braucht keinen, und das Formular zeigt nach dem Speichern den gespeicherten Wert.
Empfehlung: Rückfall.

## Zeile, die nicht mitfährt

**R-1185** (Hinweistext unter „Nicht stören“ nennt immer, Kritisches käme durch): die Korrektur ändert
`dictionaries.ts`, die `feature/kern-ansible-1` ebenfalls ändert; sie wandert in `tasks/klein-ui-desktop-1.md`.

## Risiken & Rollback

Gering, je Task einzeln zurücknehmbar. `resume()` ist best-effort wie der Rest von `playCriticalTone`.

## Doku-Impact

Keine (Fehlerbehebungen ohne dokumentiertes Verhalten; Typ intern).

## Offene Fragen

Keine.
