<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-45 — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-45 · Review: pro Task
Spec: docs/features/kern-monitoring-45.md (Roadmap R-1525, R-1565, R-1566, R-1567, R-1568, R-0518, R-1570, R-1571, R-1572, R-1573)
Heavy: linux-full — `apps/agent` (SMART-Bericht) und der Server (Anfragegrenzen), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` zusätzlich zu `reviewer`, wenn `review.sh risk` es verlangt, und bei T1 und T10.
Reihenfolge: unabhängig, außer T6 nach T5 und T11 zuletzt. `check_configs.py` und `docs/admin/monitoring.html`
ändert auch das eigene `feature/kern-monitoring-18`; es merged vorher, der Basis-Merge löst das.

## Tasks

### T1 — R-1525: Anfrageprüfung des Servers wie im Monitoring  [x]
Komponente: server · Dateien: apps/server/app/core/bounds.py, apps/server/tests/test_bounds.py, apps/server/tests/test_hooks_webhook_payload.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @27a604a66 2026-11-18T12:35:11+01:00
Review: approve (.ah-out/review/kern-monitoring-45/T1.verdict.json)
Änderung: `_find_unstorable` des Servers übernimmt die Prüfung der Monitoring-Kopie (`MAX_DEPTH`); Tests für Grenze,
Ort und Fehlermeldung.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bounds.py tests/test_hooks_webhook_payload.py
Doku: → T11

### T2 — R-1566: Status-Zusammenfassung zählt nur aktive Checks  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_status_info.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @1ad575da2 2026-11-18T12:38:59+01:00
Review: approve (.ah-out/review/kern-monitoring-45/T2.verdict.json)
Änderung: `get_status_summary` zählt die Zustände über einen Join auf `MonitorCheck.enabled`. Test: ein
abgeschalteter Check mit Status `critical` fehlt in `critical` und `total` (rot vorher).
Beweis: Code-Lesung `routers/checks.py` `get_status_summary` (kein Filter auf `enabled`) · Dedup-Key: bug:monitoring:checks.py:summary-counts-disabled
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_info.py
Doku: → T11

### T3 — R-1565: Vorhersage bewertet volle Platten und folgt den Plattenregeln  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/forecast.py, apps/monitoring/app/check_engine.py, apps/monitoring/tests/test_checker_forecast.py, apps/monitoring/app/checkers/context.py, apps/monitoring/tests/test_check_engine_context.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @bbfcaa55d 2026-11-18T12:42:38+01:00
Review: approve (.ah-out/review/kern-monitoring-45/T3.verdict.json)
Änderung: Eine Platte ≥ 100 % ist `critical` („voll“), `hours_left` 0. Die Engine hängt der Vorhersage die
Plattenregeln der aktiven Ressourcen-Prüfung desselben Hosts an (`ignore_mounts`, `disk_overrides`,
`disk_min_free_gb`) und `free_gb` je Mount aus deren letztem Ergebnis; die Vorhersage überspringt ignorierte Mounts
und alarmiert nicht, solange mindestens `min_free_gb` frei ist. Tests: volle Platte critical (rot vorher),
ignorierter Mount, Override, Grenze, ohne Ressourcen-Prüfung wie bisher.
Beweis: Code-Lesung `forecast.py` Zweig `last_pct >= 100` · Dedup-Key: bug:monitoring:forecast.py:full-disk-stable
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checker_forecast.py tests/test_check_engine_context.py
Doku: → T11

### T4 — R-1567, R-1573: Modul-Sync wahrt eigene Regeln und eigene Schalter  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/app/routers/checks.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2bd76febb 2026-11-18T12:45:30+01:00
Review: approve (.ah-out/review/kern-monitoring-45/T4.verdict.json)
Änderung: `_update` überspringt einen Check mit eigenen Regeln des Admins und meldet den Grund in `skipped`.
`_adopt` schaltet bei `new` nur Checks ein, die der Admin nicht selbst abgeschaltet hat (`enabled` nicht in
`overridden_fields`). Tests je Zeile, rot vorher: geänderte Schwelle bleibt nach Katalog-Update; selbst
abgeschalteter Check bleibt nach gone → new aus, von gone abgeschalteter wird wieder an.
Beweis: Code-Lesung `module_sync.py` `_update` und `_adopt` · Dedup-Key: bug:monitoring:module_sync.py:_update-overwrites-rules, bug:monitoring:module_sync.py:gone-new-reenables
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: → T11

### T5 — R-0518: Agent lässt smart_passed ohne smart_status weg  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/smart.go, apps/agent/internal/monitor/smart_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @9d6f08207 2026-11-18T12:48:42+01:00
Review: approve (.ah-out/review/kern-monitoring-45/T5.verdict.json)
Änderung: `SmartDisk.Passed` wird `*bool` mit `omitempty`; ohne `smart_status` im JSON von smartctl fehlt das Feld.
Test: smartctl-JSON ohne `smart_status` (SMART abgeschaltet, Exit-Bit 2) ergibt kein `smart_passed` (rot vorher).
Beweis: Code-Lesung `smart.go` `querySmartDevice` (`Passed: raw.SmartStatus.Passed`) · Dedup-Key: bug:agent:smart.go:unknown-status-reads-failed
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T11

### T6 — R-1568: SMART-Prüfung dreiwertig  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py, apps/monitoring/tests/test_smart_checker.py
Änderung: `_absent_result` und die Plattenbewertung unterscheiden „nicht erhoben“ und „nicht lesbar“ nach Kevins
Stufen; eine Platte ohne `smart_passed` ist „nicht lesbar“, nicht „SMART FAILED“. Tests je Fall (rot vorher).
Beweis: Code-Lesung `smart.py` `_absent_result` · Dedup-Key: bug:monitoring:smart.py:tristate
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py
Doku: → T11
Abhängt von: T5

### T7 — R-1570: ZFS-Zustände, Scrub-Fehler und Scrub-Alter  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_plugin_checkers.py, apps/monitoring/tests/test_check_configs.py
Änderung: `SUSPENDED` und `REMOVED` sind kritisch; Scrub-Fehler ergeben `warning`; das Scrub-Alter kommt aus der
Konfiguration (`scrub_warn_days`, `scrub_crit_days`, Vorgabe 35/60). Tests je Fall (rot vorher).
Beweis: Code-Lesung `plugins.py` ZFS-Prüfung · Dedup-Key: bug:monitoring:plugins.py:zfs-states
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_plugin_checkers.py tests/test_check_configs.py
Doku: → T11

### T8 — R-1570: Desktop zeigt DEGRADED rot  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecZfs.svelte, apps/desktop/ui/src/components/monitoring/section/SecZfs.test.ts
Änderung: `healthClass` gibt für `DEGRADED` `crit`, wie die Bewertung. Test: `DEGRADED` trägt die kritische Klasse
(rot vorher).
Beweis: Code-Lesung `SecZfs.svelte` `healthClass` · Dedup-Key: bug:monitoring:plugins.py:zfs-states
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecZfs.test.ts
Doku: keine (Anzeige folgt der dokumentierten Bewertung)

### T9 — R-1571: Abschalten oder Löschen schließt den Hub-Vorfall  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_alerter_hub.py
Änderung: Zuerst ein Test: Check mit offenem Hub-Vorfall abschalten bzw. löschen → der Hub bekommt eine Meldung, die
den Vorfall schließt. Rot → `toggle_check` und `delete_check` melden das; grün → `[~] nicht reproduziert` mit dem
Test als Beleg.
Beweis: Code-Lesung `routers/checks.py` `toggle_check`, `delete_check` · Dedup-Key: bug:monitoring:checks.py:toggle-leaves-incident
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter_hub.py
Doku: → T11

### T10 — R-1572: gescheiterte Hub-Übergabe wird nachgeholt  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/tests/test_alerter_hub.py
Änderung: Zuerst ein Test: POST an den Hub scheitert → beim nächsten Lauf geht die Meldung erneut raus. Rot →
`hub_status` wird bei gescheitertem POST zurückgesetzt, sodass der nächste Lauf nachholt; grün → `[~] nicht
reproduziert` mit dem Test als Beleg.
Beweis: Code-Lesung `alerter.py` `_claim` · Dedup-Key: bug:monitoring:alerter.py:hub-post-no-retry
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter_hub.py
Doku: → T11

### T11 — Doku DE+EN und CHANGELOG  [ ]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-45.md
Änderung: Vorhersage (volle Platte, Plattenregeln), SMART-Stufen, ZFS-Zustände und Scrub-Konfiguration,
Status-Zusammenfassung, Modul-Sync (eigene Regeln, eigene Schalter), `smart_passed` optional; CHANGELOG-Fragment
(T1 neutral unter Changed).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_info.py
Doku: docs/admin/monitoring.html DE+EN · docs/developer/agent.html DE+EN · changelog.d/kern-monitoring-45.md
Task-Review: am Ende

## Entscheidungen
- 2026-11-18 Kevin (SMART-Stufen, T5/T6): „nicht erhoben“ = `info`, „nicht lesbar“ = `unknown`.
- 2026-11-18 T3: Eine Platte mit mindestens `min_free_gb` frei alarmiert nicht, auch wenn sie schnell vollläuft (der
  Alarm kommt erst unter der Grenze), wie Spec und R-1565 verlangen. Sie trägt in `_details` die Notiz „enough free
  space“ statt `hours_left` und zählt nicht in `disk_forecast_min_hours`.
- 2026-11-18 T4: Modul-Checks merken eigene Schalter und Regeln in `overridden_fields` (`enabled`, `config`), gesetzt
  von `toggle_check` und `update_check` über `mark_module_overrides`; `config` nur, wenn sich mehr als
  `interval_s`/`timeout_s`/`pair_check_id` ändert (das trägt `_update` ohnehin mit). Grenze: Änderungen vor diesem
  Stand sind nicht markiert. Die API liefert `overriddenFields` damit auch für Modul-Checks; der Desktop zeigt die
  Felder nur bei `templateId`.
  Die `config`-Markierung bleibt dauerhaft (`reset_check` verlangt `template_id`, Löschen legt einen Tombstone an):
  ein so geänderter Modul-Check bekommt kein Katalog-Update mehr; die Zwischenlösung der Spec, die Dauerlösung bringt
  die Neuordnung.
