<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-aio-status — Task-Ledger
Status: bereit · Branch: feature/arch-monitoring-aio-status · Review: pro Task
Spec: docs/features/arch-monitoring-aio-status.md (Roadmap R-1825)
Heavy: linux-full — geänderter Push-Pfad (`routers/agent.py`: Reihenfolge der Bewertung, Geschwister der Check-Bedingung) und neuer Katalog-Check; keine Migration, kein Server-, Gateway-, PKI-, Agent-, FRP- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@9704ac3f3`. Ein Katalog-Check kann als Ganzes ruhen (`Check.when` auf ein Feld eines anderen
Probe-Checks des Moduls) und einen festen Container der Installation ansprechen (`Target.container`); darauf baut der
`status.php`-Check von `nextcloud-aio` Version 2. Invariante über alle Tasks: Ohne `when` und `container` sind
Definitions-Hash, `config`, Status und Meldung jedes heutigen Checks Bit für Bit die heutigen. Neue Quelldateien
bekommen den SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`).
Risikopfad `app/routers/agent.py` (T3): `security` dazu. Belegte Fehler außerhalb des Auftrags werden Roadmap-Zeilen
(`roadmap.py add`).

### T1 — Katalog-Modell, Bindung und API-Sperre für `Check.when` und `Target.container` (R-1825)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/check_configs.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_check_when.py, apps/monitoring/tests/test_checks_crud.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @28501b24b 2026-11-27T12:11:48+01:00
Review: approve (.ah-out/review/arch-monitoring-aio-status/T1.verdict.json)
Änderung: `Check.when: Condition | None` (`model.py:291`): nur mit `when.check`, nicht an einem zentralen Check; der Serializer (`:314`) lässt es ungesetzt weg. `_sibling_fits` (`:464`) nimmt die Bedingung und die Ortsangabe statt der Regel (Meldungen der Regel-Form wörtlich gleich), `Module._consistent` (`:495`) prüft damit Regel- und Check-Bedingungen. `Target.container: str | None` (`:112`, Muster des Agents `^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$`): nur mit `kind == "container"`, nicht mit `service`, `image_fallback` oder `alternatives`; neuer Serializer lässt es ungesetzt weg. `ProbeConfig.when` (`check_configs.py:201`), weitergereicht an `Check.model_validate` (`:222`). `probe_config` (`module_sync.py:364`) bindet `t.container`, wenn der letzte Scan ihn sah (sonst „no container <name> on this host“), und schreibt `config["when"]` nur, wenn gesetzt. `"when"` in `_PROBE_MEASURE` (`routers/checks.py:138`): Ändern oder Weglassen wird mit 422 abgelehnt. Neue Testdatei (SPDX) mit Test-Modulen: Validierung (Meldungen), Dump ohne die Felder, Hash-Invariante über den ganzen Katalog (kein Check dumpt `when`/`container`), Bindung mit und ohne den Container, `when` in der Config; in `test_checks_crud.py` `when` in der Ablehnungsliste und ein PUT ohne `when` an einem Check mit `when`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_when.py tests/test_catalog.py tests/test_check_configs.py tests/test_module_sync.py tests/test_checks_crud.py tests/test_rule_form.py tests/test_agent_plan.py tests/test_rule_model_prototype.py
Doku: → T5

### T2 — Bewertung: der Check ruht als Ganzes (R-1825)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/probe.py, apps/monitoring/tests/test_probe_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @e3a2b9e2a 2026-11-27T12:15:21+01:00
Review: approve (.ah-out/review/arch-monitoring-aio-status/T2.verdict.json)
Änderung: `ProbeChecker.evaluate` (`probe.py:312`) prüft nach der Frische-Grenze und vor `status == "error"` (`:361`) `config["when"]`: Hält es bekannt nicht (`_condition_holds(when, {}, siblings, now, factor) is False`), ist der Check `ok`, `problems` und `firing` leer, `resting` je Regel `{"key", "when"}`, Meldung `Resting (<check>.<field> = <Wert>): Probe failed: <error>` bzw. `…: OK: <Werte>`; ein erfolgreicher Lauf speichert Werte und Baseline wie heute. Fehlender, veralteter oder unbrauchbarer Bedingungswert: Bewertung wie heute (Fehler bleibt `critical`). Nicht-gelaufen-Werte, unbekannter Status und Veraltung bleiben vor der Bedingung. Tests für Ruhen bei Fehler und bei Erfolg, Bewerten bei fehlendem, veraltetem (auch `max_age`) und erfülltem Bedingungswert, `firing` aus dem Lauf davor fällt beim Ruhen weg.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_probe_checker.py tests/test_rule_model_prototype.py tests/test_rule_model_differential.py
Doku: → T5
Abhängt von: T1

### T3 — Push-Pfad: Geschwister der Check-Bedingung, Reihenfolge der Bewertung (R-1825)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_probe_when.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2040bd1fe 2026-11-27T12:18:02+01:00
Review: approve (.ah-out/review/arch-monitoring-aio-status/T3.verdict.json)
Änderung: Helfer `_sibling_names(config)` (Geschwister aus den Regeln und aus `config["when"]`); `_probe_siblings(db, check, config)` (`agent.py:525`) nutzt ihn. Der Push (`:161`) bewertet die Checks aus `_push_checks` (`:418`) stabil sortiert: erst Probe-Checks ohne Geschwister-Bedingung und alle übrigen Typen, dann die mit, in jeder Gruppe nach ID; eine Config, die kein JSON ist, zählt zur ersten Gruppe (die Bewertung meldet sie wie heute). Tests: Report-Ende-zu-Ende mit Test-Modul, Check-Bedingung ruht/bewertet, das Ergebnis des Geschwisters aus demselben Report zählt unabhängig von den IDs (ersetzt den Reihenfolge-Test), keine Abfrage ohne Geschwister-Bedingung.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_probe_when.py tests/test_probe_checker.py tests/test_agent_report.py tests/test_agent_report_v4.py
Doku: → T5
Abhängt von: T2
Test-Löschung: apps/monitoring/tests/test_probe_when.py::test_the_siblings_result_counts_in_the_evaluation_order — die Bewertung nach ID gilt nicht mehr (gewollte Verhaltensänderung); ersetzt im selben Commit durch einen Test, dass das Ergebnis des Geschwisters aus demselben Report unabhängig von den IDs zählt

### T4 — `nextcloud-aio` Version 2: Check `status` auf `status.php` (R-1825)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/nextcloud_aio.py, apps/monitoring/tests/test_catalog_nextcloud_aio.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @e29f2cc81 2026-11-27T12:22:49+01:00
Review: approve (.ah-out/review/arch-monitoring-aio-status/T4.verdict.json)
Änderung: Version 2, Check `status`: Sensor `http`, Ziel `{"kind": "container", "container": "nextcloud-aio-apache", "port_hint": 8000, "scheme": "http"}`, `GET /status.php` mit `Host: localhost`, Intervall 300 (wie `aio`, beide laufen im selben Agent-Zyklus), Felder und Regeln wie im Modul `nextcloud` (`status_code` ≠ 200 critical, Wartungsmodus und ausstehendes DB-Upgrade warning), `when` `{"check": "aio", "field": "backup", "op": "eq", "value": false}`. Karte um `("status", "data.versionstring", "Version")`, Docstring („Not covered“ ohne status.php, Ruhen im Backup). Tests: Modul lädt mit drei Checks, die Bindung gibt `status` den Apache-Container und lässt ihn ohne diesen Container mit Grund aus, Bewertung von `status` mit ruhendem und bewertendem Backup-Feld, Karte mit vier Einträgen; ein bestehender Instanz-Bestand bekommt den Check über `sync_catalog` still und den Fund „changed“.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_nextcloud_aio.py tests/test_catalog.py tests/test_module_sync.py tests/test_check_when.py
Doku: → T5
Abhängt von: T1, T2, T3

### T5 — Doku DE+EN, ADR-Nachtrag und CHANGELOG (R-1825)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/adr/0004-monitoring-neuordnung.md, changelog.d/arch-monitoring-aio-status.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7ebfafa3e 2026-11-27T12:28:38+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Admin-Doku Monitoring: Zeile `nextcloud-aio` (Check `status`, Ruhen im Backup, Hinweis zu `consecutive_fails` unter 3, der Apache-Port 8000 muss im Scan sichtbar sein) und der Absatz zu `when` (ein Check kann als Ganzes ruhen, Meldung `Resting (…)`). Entwickler-Doku Monitoring: Zeile `probe.py` (Check-Bedingung vor `error`, `_sibling_names`, Reihenfolge im Push statt „in der Reihenfolge nach ID“) und der Absatz zu `Rule`/`Condition` (`Check.when`, `Target.container`, Dump nur wenn gesetzt). ADR 0004 §6.4: Nachtrag, dass R-1825 die Empfehlung als Check-Bedingung umsetzt, weil ein Probe-Fehler vor den Regeln steht. Changelog-Fragment umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4

## Entscheidungen
- 2026-11-27 (Session): Ruhen gibt `ok`, nicht `unknown` (P1d-Verhalten ruhender Regeln, Dämpfung bleibt zurückgesetzt); `when` eines Checks setzt nur das Modul (API-Sperre wie Sensor und Ziel); keine Agent-Änderung nötig (der Agent löst Container über den Namen auf). Begründung in der Spec, „Trade-offs & Alternativen“.
- 2026-11-27 (Session, T3): Die Push-Reihenfolge hängt nur an den gespeicherten Configs; ändert ein Admin eine Config zwischen zwei gleichzeitigen Reports desselben Servers, können beide anders sortieren. Ein daraus folgender Deadlock bleibt im SAVEPOINT des einzelnen Checks (R-0635) und trifft nur diesen Server. Der Sortierschlüssel fängt `ValueError` und `RecursionError` aus `json.loads`, weil er vor der Isolation je Check läuft.
