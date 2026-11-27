<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-neu-p1d — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-neu-p1d · Review: pro Task
Spec: docs/features/arch-monitoring-neu-p1d.md (Roadmap R-1638)
Heavy: linux-full — Monitoring-Migration (`monitor_checks.rule_layer`), geänderter Push-Pfad (`routers/agent.py`) und neue Monitoring-Route; kein Server-, Gateway-, PKI-, Agent-, FRP- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@12b9034e9`. P1d der Monitoring-Neuordnung (ADR 0004 §6, §10; Kevins Schnitt 2026-11-19,
Entscheidungen 2026-11-27 in der Spec): Regelform mit `key`, `clear` und `when`, Bewertung mit Hysterese und
Bedingung, Regel-Schicht je Probe-Check mit Drei-Wege-Merge, Umwandlung des Altbestands und die Regel-API.
Unverändert bleiben `MonitorCheckOut`, `ProbeConfig`, der Agent-Plan, `tests/rule_model_prototype.py` mit seinen
Tests, Desktop und Web. Invariante über alle Tasks: Ohne Overrides und ohne `clear`/`when` sind `config.rules`,
Definitions-Hash, Status und Meldung jedes Probe-Checks Bit für Bit die heutigen. Neue Quelldateien bekommen den
SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`). Postgres-Tests
(`tests/test_migrations_smoke.py`) laufen ohne Postgres in `DATABASE_URL` als test-skip; die Task mit Migration fährt
sie zusätzlich gegen die Test-DB des Worktrees und nennt die Summary-Zeile im Commit-Body, die PR-CI fährt sie mit
Postgres. Risikopfade (`app/routers/agent.py`, `alembic/versions/*`, `app/schemas.py`): `security` je Task dazu.
Alembic-Kopf: vor jedem Push `origin/main` hereinmergen und `scripts/dev/overlap.sh` fahren; wer als Zweiter auf
`f4b6d8a0c2e4` aufsetzt, hängt seine Revision um. Belegte Fehler außerhalb des Auftrags werden Roadmap-Zeilen
(`roadmap.py add`).

### T1 — Regelform: `key`, `clear`, `when`, `rule_problems` (R-1638)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/tests/test_rule_form.py
Änderung: `Condition` (field, op ∈ eq/ne/in/lt/le/gt/ge, value, check, max_age) und an `Rule` (`model.py:142`) die optionalen Felder `key` (Muster `_KEY`), `clear` und `when`; der Serializer (`:158`) lässt sie ungesetzt weg. `rule_key` (`<field>.<level>` ohne `key`) und `rule_problems(rules)` (Schlüssel doppelt, `clear` bei anderem Operator oder auf der falschen Seite, Bedingungswert passt nicht zum Operator, `max_age` ohne `check`); `Check._consistent` (`:304`) meldet den ersten Fund und verlangt `when.field` unter den eigenen `fields`, wenn `check` leer ist; `Module._consistent` (`:382`) verlangt für `when.check` einen anderen Probe-Check desselben Moduls mit `when.field` in seinen `fields`. Neue Testdatei (SPDX) mit Test-Modulen; der ganze Katalog bleibt gültig, kein Hash ändert sich.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_rule_form.py tests/test_catalog.py tests/test_check_configs.py tests/test_module_sync.py tests/test_rule_model_prototype.py tests/test_rule_model_differential.py
Doku: → T8

### T2 — Bewertung: Hysterese und Bedingung (R-1638)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/probe.py, apps/monitoring/tests/test_probe_checker.py
Änderung: `_rating(rules, values, baseline, ts, *, firing, siblings, report_ts)` gibt Status, Meldungen, `firing` und `resting` zurück; `_rate` (`probe.py:168`) bleibt mit heutiger Signatur als Hülle. `clear`: Ein Schlüssel aus `firing` des Laufs davor hält, solange `op(wert, clear)` gilt, die Meldung nennt die Entwarnung. `when`: Die Regel ruht nur bei vorliegendem, frischem und nicht erfülltem Bedingungswert (eigenes Ergebnis oder `config["_siblings"][check]` mit `max_age`, sonst der Frischegrenze der Probe) und steht dann in `resting`. `evaluate` (`:215`) übernimmt `firing` aus `prev_details` in Läufe ohne Bewertung und für Regeln ohne Wert und schreibt `firing`/`resting` additiv in `_details`. Ein Probe-Fehler bleibt `critical`. Tests für Halten, Entwarnen, Lücke, Ruhen, fehlende, veraltete und unbrauchbare Bedingungswerte.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_probe_checker.py tests/test_rule_model_prototype.py tests/test_rule_model_differential.py tests/test_rule_form.py
Doku: → T8
Abhängt von: T1

### T3 — Geschwister-Ergebnisse im Push-Pfad (R-1638)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_probe_when.py
Änderung: `_evaluate_push_check` (`agent.py:437`) legt nur für eine Probe, deren Regeln `when.check` tragen, `config["_siblings"]` an: je `module_check_key` die gespeicherten `values`, `measured_ts` und `interval_s` der Probe-Checks derselben Instanz (`server_id`, `module_id`, `module_instance`), gelesen ohne Sperre; die Auswertungsreihenfolge nach ID (`_push_checks`, `:418`) bleibt. Neue Testdatei (SPDX): Report-Ende-zu-Ende mit einem Test-Modul aus zwei Probes, Regel ruht, bewertet bei fehlendem, veraltetem oder fremdem Geschwister (andere Instanz, anderer Server), keine Abfrage ohne `when.check`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_probe_when.py tests/test_probe_checker.py tests/test_agent_report.py tests/test_agent_report_v4.py
Doku: → T8
Abhängt von: T2

### T4 — Regel-Schicht: `effective`, Übersetzung, Drei-Wege-Merge (R-1638)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/rule_layer.py, apps/monitoring/tests/test_rule_layer.py
Änderung: Neues Modul (SPDX) ohne DB-Zugriff: `effective(catalog, overrides)` (Katalog-Reihenfolge, `enabled: false` fällt heraus, eingefrorener Schlüssel als ausdrückliches `key`, `clear: null` nimmt die Entwarnung weg), `normalize` (dem Katalog gleiche Teile entfallen), `overrides_from(catalog, rules)` (Zuordnung über Schlüssel, sonst die einzige freie Regel mit gleichem `field`/`op`; feste Teile gleich; fehlende Regeln `enabled: false`; sonst `None` mit Grund) und `merge(old, new, overrides)` mit den Konflikten `both_changed`, `removed`, `redefined`, `clear_dropped` nach ADR §6.2. Neue Testdatei (SPDX): jede Zeile der Merge-Tabelle, Stufen-Änderung ohne `key`, Invariante „ohne Overrides gleich dem Katalog-Dump“ über den ganzen Katalog, Rundlauf `overrides_from(effective(…))`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_rule_layer.py tests/test_rule_form.py
Doku: → T8
Abhängt von: T1

### T5 — Spalte `rule_layer`, Migration, Anlegen und Umwandlung beim Start (R-1638)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/b6d8f0a2c4e6_rule_layer.py, apps/monitoring/app/rule_layer.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/main.py, apps/monitoring/tests/test_rule_layer_db.py, apps/monitoring/tests/test_migrations_smoke.py
Änderung: `MonitorCheck.rule_layer` (Text, NULL; `models.py:118`, nicht in `to_dict`); Revision `b6d8f0a2c4e6` (SPDX) nach `f4b6d8a0c2e4`, nur Spalte an und ab. In `rule_layer.py` Lesen/Schreiben (`store_layer` schreibt Schicht, `config.rules` = `effective` und die Marke `config` genau bei bestehenden Overrides) und `record_rule_layers(db)`: Probe-Checks eines Moduls ohne Schicht; ohne Marke `catalog` = gespeicherte `config.rules`; mit Marke nur bei heutigem Hash, ausdrückbarem Unterschied und `effective` gleich `config.rules`, sonst eingefroren; Zählung im Log. `_create` (`module_sync.py:482`) schreibt die Schicht; `main.py` ruft `record_rule_layers` nach `reconcile_builtin_templates` (`:85`) vor `sync_catalog` (`:90`) im eigenen try/except. Neue Testdatei (SPDX): Umwandlung je Fall, Idempotenz, gleiche Bewertung vorher und nachher, neue Zeilen tragen die Schicht; Migrationstest auf und ab.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_rule_layer_db.py tests/test_rule_layer.py tests/test_module_sync.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py
Doku: → T8
Abhängt von: T4

### T6 — Katalog-Update führt zusammen statt zu überspringen (R-1638)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/app/rule_layer.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_rule_layer_db.py
Änderung: `_update` (`module_sync.py:517`) überspringt nur Zeilen mit Marke `config` und ohne Schicht (Grund `:531` bleibt); Zeilen mit Schicht bekommen die neue Definition mit `merge(layer.catalog, neue Regeln, overrides)`, `catalog` = neuer Stand, Konflikte in der Schicht (die des letzten Merges) und als Warnung im Log mit Check-ID, Schlüssel und Art. `mark_module_overrides` (`:147`) setzt bei Zeilen mit Schicht die Marke nicht aus dem Config-Vergleich, sondern über `store_layer`. Tests: Übernehmen mit Override behält die Admin-Grenze und nimmt die neue Regel auf, jede Konfliktart über `_adopt`, eingefrorene Zeile bleibt wie heute, zentrale Checks unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_rule_layer_db.py tests/test_findings_api.py tests/test_rule_layer.py
Doku: → T8
Abhängt von: T5

### T7 — Regel-API und Übersetzung in `PUT /checks/{id}` (R-1638)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/schemas.py, apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_check_rules_api.py, apps/monitoring/tests/test_checks_crud.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: `GET /checks/{id}/rules` und `PUT /checks/{id}/rules` (`require_internal`, Schemas `RuleOverride`, `RuleConflict`, `CheckRulesOut`, `CheckRulesInput`; 404 ohne Regelsatz, 409 eingefroren, 422 nach `rule_problems` und unbekanntem Schlüssel; Zeile `FOR UPDATE`, eine Transaktion). `update_check` (`checks.py:418`) übersetzt bei einer Probe mit Schicht geänderte `config.rules` über `overrides_from` und speichert `effective`; nicht ausdrückbar heißt 422 mit Verweis auf `/rules`; eingefrorene und zentrale Checks wie heute (`mark_module_overrides`-Aufruf `:503`). Neue Testdatei (SPDX); `test_checks_crud.py` für die 422 und den Rundlauf eines alten Clients; OpenAPI-Snapshot neu.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_rules_api.py tests/test_checks_crud.py tests/test_openapi_snapshot.py tests/test_openapi_integer_bounds.py tests/test_response_shapes.py tests/test_module_sync.py
Doku: → T8
Abhängt von: T6

### T8 — Doku DE+EN und CHANGELOG (R-1638)  [ ]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-monitoring-neu-p1d.md
Änderung: Entwickler-Doku Monitoring: Modul-Modell (`key`, `clear`, `when`, `rule_problems`), Katalog-Updates mit Regel-Schicht und Merge, `rule_layer`, `record_rule_layers`, Marke `config`, `_siblings`, `firing`/`resting` in `_details`. API-Referenz: `GET/PUT /checks/{id}/rules`, die 422 von `PUT /checks/{id}`. Admin-Doku Monitoring: `#probe-status` (Entwarnung, ruhende Regel), Fund `changed` und „Geänderte Definitionen“ (geänderte Grenzen bleiben über ein Update, Konflikte, eingefrorene Altzeilen). Changelog-Fragment umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4, T5, T6, T7

## Entscheidungen
- Kevin 2026-11-27: Regel-API als neue Route `GET/PUT /checks/{id}/rules`, `PUT /checks/{id}` übersetzt, nicht Ausdrückbares 422 mit Verweis; `MonitorCheckOut` bleibt (Spec, Entscheidung 1).
- Kevin 2026-11-27: Altbestand nur umwandeln, wo es exakt geht (heutige Katalog-Version, als Overrides ausdrückbar, gleiche Bewertung); sonst eingefroren, Anzahl im Log (Entscheidung 2).
- Kevin 2026-11-27: `status.php` von `nextcloud-aio` eigene FEAT-Zeile nach P1d (R-1825); P1d belegt `when` mit Test-Modulen (Entscheidung 3).
- Kevin 2026-11-27: Konflikte über `GET /checks/{id}/rules` und Log, ruhende Regeln additiv in `_details`, Oberfläche in P2 (Entscheidung 4).
- 2026-11-27 Plan: Wirksame Regeln bleiben in `config.rules` materialisiert; die Schicht hält den gebundenen Katalog-Stand, weil der Merge den alten Regelsatz braucht (Spec, Trade-offs).
- 2026-11-27 Plan: Die Ausnahme mit Geltung „Regel“ (P1b hatte sie P1d zugeordnet) braucht die Wirkung „prüfen, nicht bewerten“ aus P1c und wird R-1826 (`neu`); P1d liefert Schlüssel und Override `enabled`.
