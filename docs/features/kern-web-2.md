<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-web-2 — Idle-Abmeldung beim Laden: Zeitstempel aus der Zukunft

Roadmap: R-0890

## Problem / Motivation

Beim Laden einer aus dem Refresh-Cookie wiederhergestellten Sitzung vergleicht `watchIdle` (`apps/web/src/lib/idle.ts`)
die gespeicherte Zeit der letzten Bedienung mit der Uhr. Liegt sie in der Zukunft (Uhr zurückgestellt, Wert von Hand
gesetzt), ist die Differenz negativ, und die Sitzung bleibt, obwohl sich das Alter der letzten Bedienung nicht
bestimmen lässt.

## Ziel & Nicht-Ziele

- Ziel: Eine gespeicherte Zeit, die nach der aktuellen Uhr liegt, beendet die wiederhergestellte Sitzung beim Laden
  wie eine abgelaufene (Kevin 2026-10-30: fail-closed). Ohne Toleranz: dieselbe Uhr schreibt und liest.
- Unverändert: kein gespeicherter Wert oder blockierter Speicher (wie nach einem Login); die laufende Prüfung im Tab
  (sie überschreibt den Wert beim Start mit der aktuellen Zeit).
- Nicht-Ziel: eine serverseitige Sitzungsdauer (R-0887, eigenes Vorhaben).

## Betroffene Komponenten & Dateien

`apps/web/src/lib/idle.ts`, `apps/web/src/lib/idle.test.ts`; Doku `docs/admin/benutzer.html`,
`docs/en/admin/users.html`; `changelog.d/kern-web-2.md`.

## Datenmodell / API / Migrationen

Keine.

## Trade-offs & Alternativen

Eine Toleranz für kleine Uhrkorrekturen (NTP) wurde verworfen: Kevin hat fail-closed entschieden, und eine
Rückstellung um Sekunden trifft nur ein Neuladen in genau diesem Moment.

## Risiken & Rollback

Wer die Uhr zurückstellt und dann neu lädt, meldet sich neu an. Rollback: Revert.

## Doku-Impact

`docs/admin/benutzer.html` + EN (Abmeldung nach Inaktivität: auch eine Zeit in der Zukunft beendet die Sitzung beim
Laden), `changelog.d/kern-web-2.md`.

## Offene Fragen

Keine.
