<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-47 — Glocke: Vorfälle schließen und verlorene Meldungen nachholen — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-47 · Review: am Ende
Spec: docs/features/kern-monitoring-47.md (Roadmap R-1571, R-1572)
Heavy: none — nur Monitoring-Dienst (Router, Systemjob), kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Reihenfolge: T1 nach dem Merge von `feature/kern-monitoring-45` (#568, ändert `routers/checks.py`); T2 ist davon
unabhängig und darf vorher laufen (die Regel für abgeschaltete Checks gilt unabhängig von T1); T3 zuletzt.

## Tasks

### T1 — R-1571: Abschalten und Löschen schließen den Vorfall, Einschalten startet frisch  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_alerter_hub.py, apps/monitoring/tests/test_template_overrides.py, apps/monitoring/app/alerter.py, apps/monitoring/app/bell_catch_up.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/features/kern-monitoring-47.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @58697e36d 2026-11-18T23:44:24+01:00
Review: am Ende (Branch-Review)
Beweis: kern-monitoring-45 T9, rote Tests (~/.cache/ah-kern-monitoring-45/T9-r2.patch, lokal) · Dedup-Key: bug:monitoring:checks.py:toggle-leaves-incident
Änderung: zeigt die Glocke ein Problem (`hub_status` warning/critical), sendet `toggle_check` beim Abschalten und
`delete_check` nach dem Commit die Entwarnung auf der Stufe des Alarms; Abschalten setzt `notified_status` auf `ok`,
`hub_status` auf `ok`, wenn der Hub annahm. Einschalten setzt den Zustand frisch: `unknown`, Zähler 0, `since` jetzt,
alter Status wird nicht gemeldet. Erst die roten Tests aus dem Patch, dann der Fix.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter_hub.py tests/test_template_overrides.py tests/test_module_boundaries.py tests/test_bell_catch_up.py
Doku: → T3

### T2 — R-1572: Systemjob holt Glocken-Meldungen nach, höchstens 20 je Lauf  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/bell_catch_up.py, apps/monitoring/app/scheduler.py, apps/monitoring/app/main.py, apps/monitoring/tests/test_bell_catch_up.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @d3d70990f 2026-11-18T20:03:22+01:00
Review: am Ende (Branch-Review)
Beweis: kern-monitoring-45 T10, roter Test (~/.cache/ah-kern-monitoring-45/T10-redtest.patch, lokal) · Dedup-Key: bug:monitoring:alerter.py:hub-post-no-retry
Änderung: neues Modul (SPDX-Header) mit der Nachhol-Regel der Spec; `system:bell-catch-up` jede Minute,
`max_instances=1`, Deckel 20, älteste zuerst, `FOR UPDATE SKIP LOCKED`, Platz reservieren wie `process_alert`,
bei Fehlschlag zurückgeben; stumme Checks überspringen. Erst der rote Test (gescheiterter POST, nächster Lauf holt
nach), dann Deckel, Wartung, abgeschalteter Check, laufende Reservierung.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_bell_catch_up.py tests/test_alerter_hub.py
Doku: → T3

### T3 — Doku und CHANGELOG  [x]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-47.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @17af83b4c 2026-11-18T20:04:40+01:00
Review: am Ende (Branch-Review)
Änderung: Admin-Doku „Vorfälle in der Glocke“: Abschalten/Löschen schließt den Vorfall, Einschalten startet bei
`unknown`, nicht zugestellte Glocken-Meldungen holt der Dienst je Minute nach (höchstens 20). Entwickler-Doku beim
Alerter (Glocke): Nachhol-Job, Regel, Rennen mit der Sammelmeldung. Changelog-Fragment.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_bell_catch_up.py
Doku: docs/admin/monitoring.html DE+EN · docs/developer/monitoring.html DE+EN · changelog.d/kern-monitoring-47.md
Task-Review: am Ende
Abhängt von: T2

## Entscheidungen
- R-1569 (SMART `-n standby`) in kern-monitoring-48 verschoben: Beleg braucht eine echte HDD mit Standby.
- Nachhol-Job als eigenes Modul `bell_catch_up.py`, nicht in `alerter.py`: `feature/kern-notify-6` ändert
  `alerter.py` (Mail-Teil).
- T1 nimmt `tests/test_template_overrides.py` mit: T2 registriert `schedule_bell_catch_up` in `main.py`, die
  Start-Fixture dort kannte den Job nicht (4 Tests rot, nur im ganzen Monitoring-Lauf sichtbar); die Fixture fängt
  ihn jetzt ab, und `test_start_registers_the_system_jobs` verlangt ihn.
- T1 reserviert beim Abschalten den Glocken-Platz im selben Commit wie das Abschalten (wie `process_alert`), damit
  der Nachhol-Job die Entwarnung nicht parallel ein zweites Mal sendet; scheitert der POST, gibt `_release_hub_slot`
  ihn zurück und der Nachhol-Job holt sie nach. Einschalten lässt `notified_status` stehen: Regel-Kanäle (Mail)
  bekamen beim Abschalten keine Entwarnung.
- T1 macht `alerter._release_hub_slot` öffentlich (`release_hub_slot`) und gibt `alerter.subject_safe` dazu:
  `test_module_boundaries` verbietet private Namen über Modulgrenzen, und T2 las beide aus `bell_catch_up.py`.
  `_SUBJECT_TO_SPACE` bleibt privat, weil `feature/kern-notify-6` es in neuem Mail-Code nutzt; beide Änderungen
  liegen außerhalb seiner Hunks.
