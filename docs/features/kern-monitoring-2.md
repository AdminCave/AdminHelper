<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Maske als SMTP-Passwort beim Anlegen eines Templates

Zug `kern-monitoring-2` (Roadmap R-0968). Stand des Codes: `origin/main@0c474527`.

## Problem / Motivation

`POST /templates` (`apps/monitoring/app/routers/templates.py:214`) ruft `_keep_smtp_password(..., None)`: Eine
Alert-Definition mit `smtp_password: "***"` wird angelegt, das Passwort aber still verworfen (kein gespeichertes,
das die Maske meinen könnte). `POST /alerts` (`apps/monitoring/app/routers/alerts.py:59-60`) lehnt dieselbe Eingabe
mit 422 ab. Der Aufrufer merkt beim Template nicht, dass kein Passwort gespeichert ist; Mails über den Relay
scheitern erst später an der Anmeldung.

## Ziel & Nicht-Ziele

- Ziel: `POST /templates` antwortet auf `smtp_password: "***"` in einer Alert-Definition mit 422 und demselben
  Text wie `POST /alerts`; nichts wird angelegt. Ein leeres Passwort bleibt erlaubt (keins gespeichert).
- Nicht-Ziel: `PUT /templates/{id}` mit der Maske an einer neuen Definition (heute ebenfalls still verworfen,
  `test_template_put_with_the_mask_on_a_new_definition_stores_no_password`) und `PUT /alerts/{id}` ohne
  gespeichertes Passwort bleiben, wie sie sind; das Editieren sendet gelesene Definitionen zurück.

## Betroffene Komponenten & Dateien

`apps/monitoring/app/routers/templates.py` (`create_template`), `apps/monitoring/tests/test_alert_secrets.py`,
`docs/admin/monitoring.html` + `docs/en/admin/monitoring.html`, `changelog.d/kern-monitoring-2.md`.

## Datenmodell / API / Migrationen

Keine Migration. API: `POST /templates` 201 → 422 nur für die Maske als Passwort. Aufrufer: Desktop
`saveTemplate` (`apps/desktop/ui/src/lib/stores/monitoring.ts:398`) legt Templates nur aus dem Formular an, nie
aus einer gelesenen Definition; der Server-Proxy reicht den Status durch.

## Trade-offs & Alternativen

Empfehlung: 422 wie bei `POST /alerts` (Fehler sichtbar, eine Regel für beide Wege). Alternative: Warnung in der
Antwort — kein bestehendes Muster dafür.

## Risiken & Rollback

Ein Skript, das heute Templates mit `***` anlegt, bekommt 422 statt eines Templates ohne Passwort. Rollback: Revert.

## Doku-Impact

`docs/admin/monitoring.html` + EN: der Satz „beim Anlegen einer Regel lehnt sie `***` … mit 422 ab“ nennt auch das
Anlegen eines Templates. CHANGELOG über `changelog.d/kern-monitoring-2.md`.

## Offene Fragen

Keine.
