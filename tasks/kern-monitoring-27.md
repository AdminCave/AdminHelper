<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: gespeicherte Texte und Dienste-Fehlerzeilen nachziehen — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-27 · Review: pro Task
Spec: docs/features/kern-monitoring-27.md (Roadmap R-1372, R-1373, R-1415)
Heavy: none — Monitoring-Dienst und ein Desktop-Helfer; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Speicherbare Zeichen im Alert-Log und beim Lesen alter Zeilen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/bounds.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/alerter.py, apps/monitoring/app/models.py, apps/monitoring/tests/test_alerter_dispatch.py, apps/monitoring/tests/test_stored_json_numbers.py, changelog.d/kern-monitoring-27.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @9dda9c8cc 2026-11-14T07:56:09+01:00
Review: approve (.ah-out/review/kern-monitoring-27/T1.verdict.json)
Änderung: R-1372, R-1373. `_UNSTORABLE`/`_storable` aus `check_engine.py:53,254` als `storable()` nach
`app/core/bounds.py`; `send_to_rule` (`alerter.py:140`) speichert `error` durch `storable()`. `loads_readable`
(`models.py:45`) ersetzt einzelne Surrogate in Strings und Schlüsseln durch U+FFFD. Tests zuerst rot: Kanal-Fehler mit
NUL und Surrogat wird gespeichert; Altzeile mit `"\ud800"` in `details` liefert 200.
Beweis: feature/arch-monitoring-module-2@5ce886191 (security-Randnotiz T16) · Dedup-Key: bug:monitoring:app/alerter.py:MonitorAlertLog.error, bug:monitoring:app/core/bounds.py:loads_readable
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter_dispatch.py tests/test_stored_json_numbers.py tests/test_check_engine.py
Doku: changelog.d/kern-monitoring-27.md (### Fixed)

### T2 — Dienste-Routen und Fehlerzeilen nachhärten  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/service_inventory.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_service_inventory.py, apps/monitoring/tests/test_service_inventory_api.py, changelog.d/kern-monitoring-27.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @357f642e4 2026-11-14T08:11:52+01:00
Review: approve (.ah-out/review/kern-monitoring-27/T2.verdict.json)
Änderung: R-1415 (Einzelheiten privat). Negativtests ohne interne Berechtigung für GET
`/status/server/{id}/services` und PUT `.../services/options` (`checks.py:710`); Zeilensperre auf dem Inventar in
`store_service_report` (`service_inventory.py:172`) und in der PUT-Route, Test dazu; der feste Budget-Test
`test_a_hostile_report_is_redacted_within_its_budget` (`tests/test_service_inventory.py:267`) wird ein Zeitvergleich
über zwei Längen für alle Regeln.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_inventory.py tests/test_service_inventory_api.py
Doku: changelog.d/kern-monitoring-27.md (neutral)
Test-Löschung: apps/monitoring/tests/test_service_inventory.py::test_a_hostile_report_is_redacted_within_its_budget — ersetzt durch einen Zeitvergleich über zwei Längen (gleichwertig, schärfer)
Abhängt von: T1

### T3 — Desktop „Mehr Log“: Unit-Prüfung enger  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/ssh.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @bd2e6ecc3 2026-11-14T08:21:12+01:00
Review: approve (.ah-out/review/kern-monitoring-27/T3.verdict.json)
Änderung: R-1415. `build_journal_args` (`ssh.rs:116`) lehnt eine Unit mit `\` am Ende ab, Test bei den
Journal-Tests (`ssh.rs:729`); der Kommentar in `base_args` (`ssh.rs:216`) nennt `terminal_open_ssh_journal` als
validierenden Aufrufer.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- journal
Doku: keine (interne Prüfung, kein dokumentiertes Verhalten)

## Entscheidungen
- Gate 2026-11-14: R-1406 (nach 0.47.0) in `tasks/kern-monitoring-21.md`, R-1400 (Abhilfe ist Kevins Wahl) in
  `tasks/kern-monitoring-34.md`.
- `Review: pro Task` trotz drei Tasks: SEC-Zeile, `security` je Task.
- T2: der Sperr-Test prüft das für postgresql kompilierte SQL (`FOR UPDATE`), weil sqlite die Klausel verwirft;
  ein Server ohne Inventarzeile hat nichts zu sperren, dort verbirgt `_services_out` die Zeilen bei ausgeschaltetem
  Schalter. Der Laufzeit-Test (Faktor < 24 bei 8-facher Länge) fiel in der Gegenprobe mit `[a-z]*authorization` (Faktor ~62).
- T2, Prüfer-Nit `populate_existing` am gesperrten `get`: nicht übernommen. `_known_server` hält keine Referenz auf die
  Inventarzeile, die schwache Identity-Map gibt sie frei, der gesperrte `get` lädt frisch; ein Test mit gleichzeitigem
  Schreiber vor der Sperre blieb ohne Änderung grün.
