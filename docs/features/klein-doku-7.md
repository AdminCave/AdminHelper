<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-7 — Spec

## Problem
- **R-1279:** `docs/admin/index.html` Z. 127 (EN Z. 89) sagt, bei gescheiterter Anmeldung frage *Neu verbinden* Benutzer
  und Passwort neu ab. Das gilt nur im Tab (`reconnectRdpTab` in `apps/desktop/ui/src/lib/stores/connectFlow.ts`,
  Z. 491–499): Ein abgedocktes Fenster mountet keinen `PasswordPrompt`, dort verbindet *Neu verbinden* ohne Rückfrage
  neu (Z. 494–495).
- **R-1282** (Monitoring-Seiten, 422 bei doppeltem Skalar-Query-Parameter) wandert in `klein-doku-8`: ein offener
  Branch (`feature/kern-monitoring-16`) ändert dieselben Dateien.

## Ziel / Nicht-Ziele
Die Doku gibt das Verhalten richtig wieder. Keine Verhaltensänderung, kein Code.

## Dateien
`docs/admin/index.html`, `docs/en/admin/index.html`.

## Datenmodell / API / Integrationen
Keine.

## Trade-offs
Keine; reine Prosa. Kein Changelog-Fragment (kein Nutzerverhalten ändert sich).

## Risiken & Rollback
Gering; ein Commit, zurücknehmbar.

## Doku-Impact
Die genannten Seiten DE+EN sind selbst der Inhalt.

## Offene Fragen
Keine.
