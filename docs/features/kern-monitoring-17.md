<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Check-Status `info`: Hinweis ohne Alarm (R-1280)

## Problem / Motivation
Ein Check kennt heute `ok`, `warning`, `critical`, `unknown` (und `pending` vor dem ersten Ergebnis). Manche Befunde
sind kein Problem, sollen aber auffallen: bei OPNsense „Update verfügbar“ (mit `update_reboot`) und der
CARP-Wartungsmodus. Der Katalogvertrag aus R-1223 kennt als Regelstufe nur `warning`/`critical`
(`apps/monitoring/app/catalog/model.py:141`); darum hat das Modul `opnsense` dafür keine Regel, die Werte stehen nur
auf der Karte und der Status bleibt `ok` (Kevin 2026-11-10, Frage 5 und 6 in `tasks/arch-opnsense-plugin.md`).

## Ziel & Nicht-Ziele
Ziel: eine Regelstufe und ein Check-Status `info`, „Hinweis ohne Alarm: kein Gelb, keine Glocke, keine Mail“
(Roadmap-Titel). Kevin 2026-11-15:
- Der Desktop zeigt einen info-Check im blauen Info-Ton; die Übersicht zählt „Hinweis“ getrennt; für die Ampel von
  Host und Gruppe zählt `info` wie `ok` (ein Host mit nur Hinweisen bleibt grün).
- Fällt ein gemeldeter Check von `warning`/`critical` auf `info`, geht die übliche Entwarnung raus wie bei `ok`.
  `ok → info` und `info → ok` bleiben still; `info → warning/critical` alarmiert wie bisher.

Erster Nutzer: `opnsense` (Version 2) mit `info`-Regeln für `update_available`, `update_reboot` und CARP
`maintenance`.

Nicht-Ziele: `info` für die eingebauten Check-Typen (CPU, Platte, HTTP …) und Vorlagen; eine Alert-Regel, die auf
`info` benachrichtigt; eine eigene Glocken-Stufe; Web-Frontend (hat keine Monitoring-Ansicht).

## Betroffene Komponenten & Dateien
- **Monitoring:**
  - `app/catalog/model.py:141` `Rule.level` um `info`.
  - `app/checkers/probe.py:49` `_LEVELS`/`_rate`: die schlimmste gehaltene Regel bestimmt den Status, nur info-Regeln
    ergeben `info`.
  - `app/check_engine.py:88–152`: `info` zählt für `next_fail_count`, `is_suppressed`, `next_ok_count` und
    `holds_recovery` wie `ok` (eine Entwarnung über `info` hält `consecutive_oks` ein).
  - `app/alerter.py:84` `resolve_notification` und `_claim_transition`: für die Benachrichtigung gilt `info` als
    `ok` (Entwarnung, `silent_ack`, `reported_status`). Damit sieht der Versand (Regeln, Glocke, Bündel) nie `info`.
  - `app/core/victoria.py:262`: `monitor_check_status` 4 für `info` (0–3 bleiben).
  - `app/routers/checks.py:765` und `app/schemas.py:351` `StatusSummaryOut`: Feld `info`.
  - `app/catalog/modules/opnsense.py`: Version 2 mit den drei Regeln.
- **Desktop-UI:** `src/lib/api/types.ts:89` `MonStatus` und `:574` `MonitoringStatusSummary`;
  `src/lib/models/monitoring.ts:19` `STATUS_PRIORITY` (info 0 wie ok) und `:200` `MonitoringSummary`/`computeSummary`;
  `MonSummaryCards.svelte` (Karte „Hinweis“), `MonStatusTimeline.svelte` (Wert 4 blau), `charts/TimeChart.svelte`
  `statusColor`, `card/MonCard.svelte` (`data-status`), `src/lib/i18n/dictionaries.ts` (`monitoring.status.info`).

## Datenmodell / API / Migrationen
`MonitorState.status` ist ein freier String (`app/models.py:185`): keine Migration. API: `GET /status/summary` bekommt
das Feld `info` (additiv; OpenAPI-Snapshot und der Desktop-Vertragstest ziehen mit). Check-Status in Antworten kann
`info` sein. Agent unverändert: die Regeln wertet der Monitoring-Dienst aus.

## Externe Integrationen
VictoriaMetrics: nur ein neuer Zahlenwert in einer bestehenden Reihe, kein Formatwechsel.

## Trade-offs & Alternativen
- `info` als Merkmal neben `ok` (etwa `details.hint`) statt als Status: kein neuer Status, aber Übersicht, Farbe und
  Verlauf bräuchten eine zweite Quelle. Verworfen; Kevin hat Farbe und Zählung als Status entschieden.
- Normalisierung `info → ok` an einer Stelle im Alerter statt in jedem Versandweg: ein Ort, Glocke und Bündel bleiben
  unverändert. Empfohlen.
- VictoriaMetrics `info` = 0 (wie ok) statt 4: die Zeitleiste könnte `info` dann nicht blau zeigen. 4 gewählt.

## Risiken & Rollback
Ein vergessener `== "ok"`-Leser behandelt `info` als Problem (etwa Fehlerzähler). Gegenmittel: Tests je Pfad (Zähler,
Hold, Entwarnung, stille Wechsel). Rollback: Revert; gespeicherte `info`-Zustände werden beim nächsten Lauf neu
bewertet, die Opnsense-Version 2 bleibt als angebotene Katalog-Aktualisierung (R-1264) liegen.

## Doku-Impact
`docs/admin/monitoring.html` (Status-Abschnitt, Alert-Regeln, Tabelle OPNsense) und
`docs/developer/monitoring.html` (Werte von `monitor_check_status`), je DE+EN; `changelog.d/kern-monitoring-17.md`.

## Offene Fragen
Keine (Kevin 2026-11-15).
