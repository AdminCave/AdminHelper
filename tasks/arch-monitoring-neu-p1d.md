<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-neu-p1d — Task-Ledger
Status: bereit · Branch: feature/arch-monitoring-neu-p1d · Review: pro Task
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

### T1 — Regelform: `key`, `clear`, `when`, `rule_problems` (R-1638)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/tests/test_rule_form.py, apps/monitoring/tests/test_agent_plan.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @0f6859b01 2026-11-27T06:56:23+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1d/T1.verdict.json)
Änderung: `Condition` (field, op ∈ eq/ne/in/lt/le/gt/ge, value, check, max_age) und an `Rule` (`model.py:142`) die optionalen Felder `key` (Muster `_KEY`), `clear` und `when`; der Serializer (`:158`) lässt sie ungesetzt weg. `rule_key` (`<field>.<level>` ohne `key`) und `rule_problems(rules)` (Schlüssel doppelt); `clear` bei anderem Operator oder auf der falschen Seite, ein Bedingungswert, der nicht zum Operator passt, und `max_age` ohne `check` scheitern in `Rule`/`Condition`. `Check._consistent` (`:304`) verlangt `when.field` unter den eigenen `fields`, wenn `check` leer ist; `Module._consistent` (`:382`) meldet den ersten Fund von `rule_problems` (nicht `Check`: eine gespeicherte Probe-Config läuft im Agent-Plan als `Check` durch, eine von vor den Schlüsseln darf zwei gleiche haben, `test_agent_plan.py`) und verlangt für `when.check` einen anderen Probe-Check desselben Moduls mit `when.field` in seinen `fields`. Neue Testdatei (SPDX) mit Test-Modulen; der ganze Katalog bleibt gültig, kein Hash ändert sich.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_rule_form.py tests/test_catalog.py tests/test_check_configs.py tests/test_module_sync.py tests/test_rule_model_prototype.py tests/test_rule_model_differential.py tests/test_agent_plan.py
Doku: → T8

### T2 — Bewertung: Hysterese und Bedingung (R-1638)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/probe.py, apps/monitoring/tests/test_probe_checker.py, apps/monitoring/app/catalog/model.py, apps/monitoring/tests/test_rule_form.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @05aea311e 2026-11-27T07:00:44+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1d/T2.verdict.json)
Änderung: `_rating(rules, values, baseline, ts, *, firing, siblings, report_ts)` gibt Status, Meldungen, `firing` und `resting` zurück; `_rate` (`probe.py:168`) bleibt mit heutiger Signatur als Hülle. `clear`: Ein Schlüssel aus `firing` des Laufs davor hält, solange `op(wert, clear)` gilt, die Meldung nennt die Entwarnung. `when`: Die Regel ruht nur bei vorliegendem, frischem und nicht erfülltem Bedingungswert (eigenes Ergebnis oder `config["_siblings"][check]` mit `max_age`, sonst der Frischegrenze der Probe) und steht dann in `resting`. `evaluate` (`:215`) übernimmt `firing` aus `prev_details` in Läufe ohne Bewertung und für Regeln ohne Wert und schreibt `firing`/`resting` additiv in `_details`. Ein Probe-Fehler bleibt `critical`. Tests für Halten, Entwarnen, Lücke, Ruhen, fehlende, veraltete und unbrauchbare Bedingungswerte.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_probe_checker.py tests/test_rule_model_prototype.py tests/test_rule_model_differential.py tests/test_rule_form.py
Doku: → T8
Abhängt von: T1

### T3 — Geschwister-Ergebnisse im Push-Pfad (R-1638)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_probe_when.py, apps/monitoring/tests/test_probe_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f06a21303 2026-11-27T07:07:18+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1d/T3.verdict.json)
Änderung: `_evaluate_push_check` (`agent.py:437`) legt nur für eine Probe, deren Regeln `when.check` tragen, `config["_siblings"]` an: je `module_check_key` die gespeicherten `values`, `measured_ts` und `interval_s` der Probe-Checks derselben Instanz (`server_id`, `module_id`, `module_instance`), gelesen ohne Sperre; die Auswertungsreihenfolge nach ID (`_push_checks`, `:418`) bleibt. Neue Testdatei (SPDX): Report-Ende-zu-Ende mit einem Test-Modul aus zwei Probes, Regel ruht, bewertet bei fehlendem, veraltetem oder fremdem Geschwister (andere Instanz, anderer Server), keine Abfrage ohne `when.check`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_probe_when.py tests/test_probe_checker.py tests/test_agent_report.py tests/test_agent_report_v4.py
Doku: → T8
Abhängt von: T2

### T4 — Regel-Schicht: `effective`, Übersetzung, Drei-Wege-Merge (R-1638)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/rule_layer.py, apps/monitoring/tests/test_rule_layer.py, apps/monitoring/app/catalog/model.py, apps/monitoring/tests/test_rule_form.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @211e013a7 2026-11-27T07:20:07+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1d/T4.verdict.json)
Änderung: Neues Modul (SPDX) ohne DB-Zugriff: `effective(catalog, overrides)` (Katalog-Reihenfolge, `enabled: false` fällt heraus, eingefrorener Schlüssel als ausdrückliches `key`, `clear: null` nimmt die Entwarnung weg), `normalize` (dem Katalog gleiche Teile entfallen), `overrides_from(catalog, rules)` (Zuordnung über Schlüssel, sonst die einzige freie Regel mit gleichem `field`/`op`; feste Teile gleich; fehlende Regeln `enabled: false`; sonst `None` mit Grund) und `merge(old, new, overrides)` mit den Konflikten `both_changed`, `removed`, `redefined`, `clear_dropped` nach ADR §6.2. Neue Testdatei (SPDX): jede Zeile der Merge-Tabelle, Stufen-Änderung ohne `key`, Invariante „ohne Overrides gleich dem Katalog-Dump“ über den ganzen Katalog, Rundlauf `overrides_from(effective(…))`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_rule_layer.py tests/test_rule_form.py
Doku: → T8
Abhängt von: T1

### T5 — Spalte `rule_layer`, Migration, Anlegen und Umwandlung beim Start (R-1638)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/b6d8f0a2c4e6_rule_layer.py, apps/monitoring/app/rule_layer.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/main.py, apps/monitoring/tests/test_rule_layer_db.py, apps/monitoring/tests/test_migrations_smoke.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f2823d42b 2026-11-27T07:50:29+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1d/T5.verdict.json)
Änderung: `MonitorCheck.rule_layer` (Text, NULL; `models.py:118`, nicht in `to_dict`); Revision `b6d8f0a2c4e6` (SPDX) nach `f4b6d8a0c2e4`, nur Spalte an und ab. In `rule_layer.py` Lesen/Schreiben (`store_layer` schreibt Schicht, `config.rules` = `effective` und die Marke `config` genau bei bestehenden Overrides) und `record_rule_layers(db)`: Probe-Checks eines Moduls ohne Schicht; ohne Marke `catalog` = gespeicherte `config.rules`; mit Marke nur bei heutigem Hash, ausdrückbarem Unterschied und `effective` gleich `config.rules`, sonst eingefroren; Zählung im Log. `_create` (`module_sync.py:482`) schreibt die Schicht; `main.py` ruft `record_rule_layers` nach `reconcile_builtin_templates` (`:85`) vor `sync_catalog` (`:90`) im eigenen try/except. Neue Testdatei (SPDX): Umwandlung je Fall, Idempotenz, gleiche Bewertung vorher und nachher, neue Zeilen tragen die Schicht; Migrationstest auf und ab.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_rule_layer_db.py tests/test_rule_layer.py tests/test_module_sync.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py
Doku: → T8
Abhängt von: T4

### T6 — Katalog-Update führt zusammen statt zu überspringen (R-1638)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/app/rule_layer.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_rule_layer_db.py, apps/monitoring/app/models.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @a81a5729e 2026-11-27T08:02:03+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1d/T6.verdict.json)
Änderung: `_update` (`module_sync.py:517`) überspringt nur Zeilen mit Marke `config` und ohne Schicht (Grund `:531` bleibt); Zeilen mit Schicht bekommen die neue Definition mit `merge(layer.catalog, neue Regeln, overrides)`, `catalog` = neuer Stand, Konflikte in der Schicht (die des letzten Merges) und als Warnung im Log mit Check-ID, Schlüssel und Art. (Die Marke über `store_layer` in `mark_module_overrides` ist nach T7 verschoben, Entscheidung T6.) Tests: Übernehmen mit Override behält die Admin-Grenze und nimmt die neue Regel auf, jede Konfliktart über `_adopt`, eingefrorene Zeile bleibt wie heute, zentrale Checks unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_rule_layer_db.py tests/test_findings_api.py tests/test_rule_layer.py
Doku: → T8
Abhängt von: T5

### T7 — Regel-API und Übersetzung in `PUT /checks/{id}` (R-1638)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/schemas.py, apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_check_rules_api.py, apps/monitoring/tests/test_checks_crud.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/app/rule_layer.py, apps/monitoring/tests/test_rule_layer_db.py, apps/monitoring/tests/test_response_shapes.py, docs/features/arch-monitoring-neu-p1d.md, apps/monitoring/tests/test_module_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @015fc7bf6 2026-11-27T08:35:14+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1d/T7.verdict.json)
Änderung: `GET /checks/{id}/rules` und `PUT /checks/{id}/rules` (`require_internal`, Schemas `RuleOverride`, `RuleConflict`, `CheckRulesOut`, `CheckRulesInput`; 404 ohne Regelsatz, 409 eingefroren, 422 nach `rule_problems` und unbekanntem Schlüssel; Zeile `FOR UPDATE`, eine Transaktion). `update_check` (`checks.py:418`) übersetzt bei einer Probe mit Schicht geänderte `config.rules` über `overrides_from` und speichert `effective`; nicht ausdrückbar heißt 422 mit Verweis auf `/rules`; eingefrorene und zentrale Checks wie heute (`mark_module_overrides`-Aufruf `:503`). `mark_module_overrides` (`module_sync.py:148`) setzt bei Zeilen mit Schicht die Marke nicht aus dem Config-Vergleich, sondern über `store_layer` (aus T6, Entscheidung T6). Neue Testdatei (SPDX); `test_checks_crud.py` für die 422 und den Rundlauf eines alten Clients; OpenAPI-Snapshot neu.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_rules_api.py tests/test_checks_crud.py tests/test_openapi_snapshot.py tests/test_openapi_integer_bounds.py tests/test_response_shapes.py tests/test_module_sync.py tests/test_rule_layer_db.py tests/test_rule_layer.py
Doku: → T8
Abhängt von: T6

### T8 — Doku DE+EN und CHANGELOG (R-1638)  [x]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-monitoring-neu-p1d.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @38943eb93 2026-11-27T08:49:49+01:00
Review: am Ende (nur Doku, Branch-Review)
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
- 2026-11-27 T1: Die Prüfungen je Regel (`clear` auf der sicheren Seite, Bedingungswert zum Operator, `max_age` nur mit `check`) sitzen in den Validatoren von `Rule` und `Condition`, damit jede wirksame Regel sie beim Bauen trägt; `rule_problems` prüft den Regelsatz (doppelte Schlüssel), nur im Katalog (`Module`) und in den Schreibpfaden der Regel-Schicht (T7): Altzeilen mit zwei Regeln gleichen Felds und Levels bleiben im Agent-Plan (Prüfer-Fund T1) und werden in T5 eingefroren; damit keine Hysterese über einen geteilten Schlüssel läuft, lehnt `Check` in T2 `clear` an einer Regel ab, deren Schlüssel ein zweites Mal vorkommt (keine gespeicherte Zeile trägt `clear` vor P1d, Prüfer-Nit T1). `clear_fits` ist öffentlich für den Merge (T4). `max_age` ist auf eine Woche begrenzt (Integer-Grenzen der OpenAPI).
- 2026-11-27 T2: `_rating` nimmt zusätzlich `factor` (Probe-Faktor des Reports), damit ein Geschwister dieselbe Frischegrenze bekommt wie die eigene Probe (`_stale_after`, gemeinsam für beide). Eine ruhende Regel trägt ihren Schlüssel nicht in `firing` weiter: ruht sie, endet ihre Hysterese, und nach dem Ruhen zählt wieder der Grenzwert. Die Meldung nennt `clears at` nur, solange die Hysterese die Regel hält. `Check` lehnt `clear` an einem geteilten Schlüssel ab (Nit T1, `model.py`).
- 2026-11-27 T3: `_probe_siblings` liest die Geschwister in einer Abfrage (Check samt Zustand, ohne Sperre) und nur für Regeln mit `when.check`; ein Check ohne `module_id` hat keine Geschwister. Ausgeschaltete Geschwister filtert es nicht: ihr Ergebnis veraltet und lässt die Regel dann bewerten. Gibt es einen Schlüssel an derselben Instanz zweimal, gilt der Check mit der kleinsten ID. Der Prüfer-Nit aus T2 (Parameter `"200x"`) ist hier als eigener Test behoben (`test_probe_checker.py`).
- 2026-11-27 T4: Der eingefrorene Schlüssel einer Stufen-Änderung hat die Form `<feld>.<stufe>`; ein Schlüssel mit Punkt ist deshalb erlaubt, aber nur als eigenes Feld mit einer Stufe (`Rule`), so trifft er nie den abgeleiteten Schlüssel einer anderen Regel; der T1-Test „Punkt wird abgewiesen“ wird dazu enger (anderes Feld, andere Endung) statt gelöscht. Teile vergleicht die Schicht als JSON-Werte (`true` ≠ `1`, `90` = `90.0`, auch in `when`/`unless`). `overrides_from` ordnet erst unveränderte Regeln über ihren Schlüssel zu, dann geänderte (ein abgeleiteter Schlüssel nur bei gleichem `op`), zuletzt eine Regel ohne eigenen Schlüssel der einzigen freien Katalog-Regel gleichen Felds und Operators; zwei mögliche sind mehrdeutig und werden abgewiesen. `clear_dropped` setzt das Override `clear` auf `null` (die Regel rechnet dann ohne Entwarnung). Konflikte tragen hier `key`, `kind`, `part`; den Zeitstempel `at` setzt T6 beim Speichern.
- 2026-11-27 T5: `record_rule_layers` steht in `module_sync.py` neben `sync_catalog`, weil es `definition_hash` und den Katalog braucht (`module_sync` importiert `rule_layer`, umgekehrt wäre es zyklisch); `rule_layer.py` bekommt `convert`, `read_layer`, `store_layer`. `sync_catalog` gibt einer Zeile mit Marke `config` und ohne Schicht keinen Hash mehr, sonst wandelte ein späterer Start ihre Regeln gegen die heutige Definition um, obwohl nichts zeigt, woraus der Admin sie geändert hat. Eine Zeile ohne Marke, deren Regeln nicht lesbar sind oder `rule_problems` verletzen, bekommt keine Schicht (Warnung, nicht gezählt) und wird bei jedem Start neu angesehen; eine eingefrorene zählt `frozen`, ihr Grund steht auf Debug. Gespeicherte Regeln zählen in der Form, in der der Katalog sie ausgibt (`model_dump`: ein Teil `null` ist kein Teil). Ein zentraler Check (Typ `central`) bekommt keine Schicht; eine markierte Zeile, deren Katalog-Check inzwischen zentral ist, bleibt über den Hash eingefroren (die Prüfung „kein zentraler Check“ in der Umwandlung wäre doppelt).
- 2026-11-27 T6: `_update` bekommt `now` aus `_adopt` für das `at` der Konflikte (ISO-Zeit, naiv UTC wie `now`); geprüft wird die Config mit den wirksamen Regeln, ein Override, der nicht mehr passt (nur über eine von Hand geschriebene Schicht erreichbar), lässt die alte Zeile laufen mit dem bisherigen Grund „the updated check does not hold“. Eine Probe-Zeile ohne Schicht und ohne Marke bekommt beim Update eine (Katalog = neuer Stand, keine Overrides). Verschiebt der Katalog den Check zum Monitoring-Dienst, lehnt `_update` wie bisher ab, die Schicht bleibt. Die Marke über `store_layer` in `mark_module_overrides` kommt mit T7, zusammen mit der Übersetzung in `update_check`: allein ließe sie einen `PUT` mit geänderten Regeln ohne Marke (`test_the_api_marks_the_admins_switch_and_rules_on_a_module_check` rot). Bis T7 verliert ein `PUT` mit geänderten Regeln an einer Zeile mit Schicht sie beim nächsten Update; der Branch wird nur als Ganzes gemergt. `test_a_catalog_update_keeps_the_rules_the_admin_changed` fährt deshalb mit einer Zeile ohne Schicht (eingefroren), der Fall mit Schicht steht in `test_rule_layer_db.py`.
- 2026-11-27 T7: `CheckRulesOut` trägt `checkId` (camelCase wie die übrigen Out-Schemas, Spec nachgezogen). Beide `PUT` lassen die Konflikte stehen; sie zeigen, wo das letzte Update ein Override traf, und erst das nächste Update ersetzt sie. `at` schreibt `_update` jetzt als `iso_utc` mit `Z` (ändert T6 und seinen Test), wie die übrigen Zeitangaben der API. `RuleOverride` typisiert `value` und `clear` wie `Rule` (strikt, ganze Zahlen mit BIGINT-Grenze für die OpenAPI-Prüfung); eine ganze Zahl über der Grenze nimmt pydantic als float an (strikt erlaubt int → float), harmlos, weil die Regel als JSON-Text liegt; `null` nur für `clear`. `effective` nennt bei einem Override, das die Regel bricht, deren Schlüssel; `PUT /rules` antwortet damit 422. `PUT /rules` prüft nur die Regeln (`effective`), nicht die ganze Config: Feld, Operator und Schlüssel bleiben fest, also kann ein Override die Prüfungen des Checks (Feld in `fields`, `when`/`unless`, eindeutige Schlüssel mit `clear`) nicht verletzen, und eine Prüfung der ganzen Config sperrte nur Altzeilen. `PUT /checks/{id}` vergleicht gesendete mit gespeicherten `config.rules`: unverändert → die gespeicherten Overrides bleiben (alter Client ändert nur das Intervall), sonst `overrides_from`. Sperre: beide `PUT` lesen die Zeile `FOR UPDATE`, `_adopt` sperrt die Checks der Instanz über `instance_checks(lock=True)` in fester Reihenfolge (`created_at`, `id`); die API hält nur eine Zeile, also kein Deadlock; `sync_catalog` und `findings.py` lesen weiter ohne Sperre (sie schreiben keine Schicht). `mark_module_overrides` setzt `config` aus dem Config-Vergleich nur noch für Zeilen ohne Schicht; mit Schicht setzt `store_layer` die Marke genau bei bestehenden Overrides (Probe-Configs ändern sonst nur `interval_s`/`timeout_s`, die ein Update behält); `test_only_a_change_the_update_would_lose_marks_the_config` fährt deshalb mit einer Zeile ohne Schicht, der Fall mit Schicht ist ein eigener Test. Ein manueller Check und eine zentrale Modul-Zeile antworten auf `/rules` mit 404. Die Proxy-Allowlist des Servers deckt `/checks/{id}/rules` über das Präfix.
