<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-47 — Glocke: Vorfälle schließen und verlorene Meldungen nachholen

Roadmap: R-1571, R-1572 (beide BUG). R-1569 (SMART ohne `-n standby`) fuhr geplant mit und ist in
`tasks/kern-monitoring-48.md` verschoben: sein Beleg braucht eine echte HDD mit Standby, die Pool-VMs haben nur
virtuelle Platten.

## Problem

- **R-1571:** Schaltet ein Admin einen Check ab oder löscht ihn, während die Glocke seinen Alarm zeigt, meldet
  niemand die Entwarnung: `toggle_check` und `delete_check` (`apps/monitoring/app/routers/checks.py:508`, `:529`)
  senden nichts, und ein abgeschalteter Check läuft nicht mehr. Der Vorfall im Hub bleibt offen. Rot belegt in
  kern-monitoring-45 T9 (Patch, vier Tests).
- **R-1572:** `process_alert` committet `notified_status` vor dem Hub-POST (`alerter.py:293`, at-most-once).
  Scheitert der POST, gibt `_notify_bell` nur den reservierten Glocken-Platz zurück (`alerter.py:342`); der nächste
  Lauf findet `notified_status == status` und meldet nichts. Der Alarm erreicht die Glocke nie. Rot belegt in
  kern-monitoring-45 T10.

## Ziel

- Abschalten schließt den Vorfall: die Glocke bekommt die Entwarnung auf der Stufe, mit der der Alarm sie erreichte;
  danach gilt der Check als entwarnt (`notified_status`/`hub_status` = `ok`). Löschen ebenso.
- Wiedereinschalten startet frisch (Kevin 2026-11-18): Status `unknown` bis zum ersten Ergebnis, Zähler auf 0; der
  alte Status wird nicht neu gemeldet. Ein Problem, das danach besteht, ist ein neuer Alarm.
- Was die Glocke nicht erreicht hat, holt ein Systemjob nach (Kevin 2026-11-18: Zwischenlösung, je Lauf gedeckelt):
  `system:bell-catch-up` jede Minute, höchstens 20 Checks je Lauf, älteste zuerst. Die Outbox R-1561 ersetzt ihn
  später.

## Nicht-Ziele

- Keine Outbox, kein Retry für Regel-Kanäle (Mail, Webhook): ihr at-most-once bleibt.
- Kein Nachholen der Entwarnung eines gelöschten Checks: die Zeile ist weg; scheitert der POST beim Löschen, bleibt
  der Vorfall offen (Restrisiko bis R-1561, im Log als Warnung).
- Keine Änderung am Hub (`apps/server`), an `ntf/service.py` oder an der Sammelmeldung.

## Betroffene Komponenten & Dateien

- `apps/monitoring/app/routers/checks.py` — `toggle_check`, `delete_check`.
- `apps/monitoring/app/bell_catch_up.py` (neu) — Auswahl und Nachmelden; nutzt `alerter.emit_to_hub`,
  `build_message`, `bell_severity`, `bell_record`, `hub_decision`, `muted_reason`, `release_hub_slot`.
  Eigenes Modul statt `alerter.py`: der offene Branch `feature/kern-notify-6` ändert `alerter.py` (Mail-Teil).
- `apps/monitoring/app/scheduler.py`, `apps/monitoring/app/main.py` — Job registrieren.
- Tests: `apps/monitoring/tests/test_alerter_hub.py` (T1), `apps/monitoring/tests/test_bell_catch_up.py` (neu, T2).

## Datenmodell / API / Migrationen

Keine Migration, keine API-Änderung. Gelesen und geschrieben werden die vorhandenen Spalten `monitor_states.status`,
`notified_status`, `hub_status`, `hub_sent_at`, `since`, `fail_count`, `ok_count`, `message`, `details`.

## Nachhol-Regel (T2)

Ein Check hinkt in der Glocke, wenn
- er eingeschaltet ist, `alert_status(status) == notified_status` gilt (keine neuere Meldung offen, die der normale
  Dispatch übernimmt), `hub_decision(hub_status, notified_status, severity) == "emit"` und
  `bell_record(notified_status, …)[0] != hub_status`; oder
- er abgeschaltet ist und die Glocke noch ein Problem zeigt (`hub_status` warning/critical): dann ist das Ziel die
  Entwarnung (ein gescheiterter Abschalt-POST aus T1).

Stumme Checks (`muted_reason`: Wartung, Host down) überspringt der Job. Er reserviert den Platz wie `process_alert`
(`hub_status`/`hub_sent_at` vor dem POST, Commit), sendet und gibt den Platz bei Fehlschlag mit `release_hub_slot`
zurück; die Auswahl sperrt mit `FOR UPDATE SKIP LOCKED`. Ein Dispatch, der zwischen Claim und POST steht, hat seinen
Platz schon reserviert und gilt nicht als hinkend. Die Sammelmeldung reserviert nicht vor dem POST: zwischen ihrem
Claim und ihrem POST (Sekunden) kann der Job dasselbe Ereignis ein zweites Mal senden; der Hub faltet es über
`incident_key` in denselben Vorfall.

## Trade-offs & Alternativen

- **Retry beim nächsten Check-Lauf** (in `execute_check`): kein Deckel je Lauf möglich, Push-Checks laufen über einen
  anderen Pfad, ein Hub-Ausfall kostete jeden Lauf jedes betroffenen Checks einen 5-s-Timeout. Verworfen.
- **Job mit Deckel 20 je Minute** (gewählt): bei Hub-Ausfall höchstens 20 POSTs je Minute, `max_instances=1`.
- **Outbox (R-1561):** die Dauerlösung, nicht in diesem Zug.

## Risiken & Rollback

- Doppelte Glocken-Ereignisse im Rennen mit der Sammelmeldung (oben): der Hub faltet sie.
- Ein Hub-Ausfall mit mehr als 20 hinkenden Checks braucht mehrere Minuten zum Nachholen.
- Rollback: Revert der Task-Commits; keine Daten- oder Schemaänderung.

## Doku-Impact

`docs/admin/monitoring.html` und `docs/en/admin/monitoring.html` (Vorfälle in der Glocke: Abschalten, Löschen,
Nachholen), `docs/developer/monitoring.html` DE+EN (Alerter: Glocke, Nachhol-Job), `changelog.d/kern-monitoring-47.md`.

## Offene Fragen

Keine: R-1571 und R-1572 hat Kevin am 2026-11-18 entschieden.
