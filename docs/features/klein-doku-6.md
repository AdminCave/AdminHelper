<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-6 — Spec

## Problem
- **R-1151:** `docs/developer/server.html` (Abschnitt Benachrichtigungen, EN gleich) sagt, dass das Detail eines Bündels
  Verlauf und Mitglieder nur für die eigenen Server zeigt. Es fehlt der Satz, dass die zusammengefassten Werte des
  Bündels (`count`, `severity`, `lastAt`, `state`, escalated/notified, `canAct`) für das ganze Bündel gelten und damit
  Aktivität auf nicht sichtbaren Servern verraten, Namen und Anzahl aber nicht (Trade-off 5 der Spec
  `arch-notify-incidents`; Code `apps/server/app/modules/notifications/incidents.py` ab Z. 248).
- **R-1154:** `docs/developer/cicd.html` Z. 43 (EN gleich) nennt bei `cargo audit (Desktop)` nicht, dass es Ausnahmen aus
  `apps/desktop/src-tauri/.cargo/audit.toml` liest (seit R-1097 T8, RUSTSEC-2023-0071).
- **R-1167:** `docs/admin/index.html` Z. 125 (EN Z. 87) sagt, der Desktop stelle die SSH-Tabs „nach der Anmeldung“
  wieder her; der Zeitpunkt ist das Öffnen des Workspace.

## Ziel / Nicht-Ziele
Die Doku gibt das Verhalten richtig wieder. Keine Verhaltensänderung, kein Code.

## Dateien
`docs/developer/server.html`, `docs/en/developer/server.html`, `docs/developer/cicd.html`,
`docs/en/developer/cicd.html`, `docs/admin/index.html`, `docs/en/admin/index.html`.

## Datenmodell / API / Integrationen
Keine.

## Trade-offs
Keine; reine Prosa. Kein Changelog-Fragment (kein Nutzerverhalten ändert sich, nur Entwickler-Doku und eine
Formulierung).

## Risiken & Rollback
Gering; ein Commit je Task zurücknehmbar.

## Doku-Impact
Die genannten Seiten DE+EN sind selbst der Inhalt.

## Offene Fragen
Keine.
