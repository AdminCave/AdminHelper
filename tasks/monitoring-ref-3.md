<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Alarm-Protokoll einmal, Typ-Tabellen gepinnt, Scheduler-Job nach dem Commit, Modulgrenzen, lange Funktionen — Task-Ledger
Status: erledigt · Branch: feature/monitoring-ref-3 · Review: pro Task
Spec: docs/features/monitoring-ref-3.md (Roadmap R-0693, R-0694, R-0695, R-0696, R-0697, R-0728)
Heavy: none — nur Interna von `apps/monitoring` (Alarm-Pfad, Push-Handler, Reihenfolge Commit/Scheduler, Typ-Tabellen, Modulgrenzen); keine Route, kein Request- oder Response-Schema, keine OpenAPI-Änderung (T1: `regex=` und `pattern=` ergeben dasselbe Schema, Probe in der Spec), kein Alembic, kein Agent-, Gateway-, Compose-, PKI-, FRP- oder Install-Pfad (die `linux-full`-Liste in `/feature-plan` §3 und CLAUDE.md §5 nennt `apps/monitoring` nicht). Die FOR-UPDATE-Tests (`tests/test_check_engine_concurrency.py`) fährt die PR-CI gegen Postgres (`ci.yml`, Job `monitoring`, `DATABASE_URL`)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: monitoring-io (`tasks/monitoring-io.md` auf `feature/monitoring-io`), smtp-hardening (`tasks/smtp-hardening.md` auf `feature/smtp-hardening`) — gebaut wird erst nach dem Merge beider; sie ändern `alerter.py`, `check_engine.py`, `routers/agent.py`, `routers/checks.py`, `checkers/agent.py`, `models.py`, `routers/templates.py` und `docs/developer/monitoring.html`.

Bündel `/feature-plan --bundle monitoring`: die sechs `geplant`-REF-Zeilen der Komponente Monitoring (R-0728 nur
mit seinem Monitoring-Teil; `hooks/script_runner.py` und `provisioning/router.py` gehören zum Server). Zeilenangaben:
`origin/main@237b450a`. Die Tasks beschreiben den Endstand nach monitoring-io und smtp-hardening (beide Branches
konfliktfrei auf `origin/main` zusammengeführt, `git merge-tree`); der builder zieht vor T1 `origin/main` nach und
greppt jede Zeile neu.

Für alle Tasks:
- Reihenfolge von oben nach unten. Echte Abhängigkeiten: T4 → T3 (Testdatei), T6 → T5, T10 → T5, T6, T7, T9 (sonst
  ist der Wächter rot), T11 → T4, T9, T10. Sonst ordnet die gemeinsame Datei: `routers/checks.py` (T1, T2, T3),
  `routers/agent.py` (T4, T9, T10, T11), `alerter.py`/`alert_bundle.py` (T5, T6, T9), `check_engine.py` (T9, T14),
  `checkers/smart.py` (T4, T13), `tests/test_module_boundaries.py` (T7, T10), `tests/test_check_type_parity.py`
  (T3, T4), `tests/test_check_engine_concurrency.py` (T6, T9), `docs/developer/monitoring.html` (T4, T6, T8, T9).
- Refactor (alle außer T2) nach Beweisklasse B (`tasks/README.md`): die Testdateien des `Verify:` vor und nach dem
  Diff grün (beide Summary-Zeilen in den Commit-Body), Coverage der geänderten App-Dateien mit pytest-cov (im Venv)
  nicht gesunken (Zahlen in den Commit-Body), die Mutations-Stichprobe aus `Orakel:` in einer Kopie im eigenen
  Scratch-Verzeichnis, nie im Bau-Worktree. Längen als `end_lineno - lineno + 1` über `ast` (Python 3.13.5), vorher
  und nachher in den Commit-Body. Keine Verhaltensänderung: Antworten, Statuscodes, Meldungen, Alert-Log-Gründe,
  Commit- und Flush-Punkte bleiben. T2 ist eine Verhaltensänderung nach Klasse A: der neue Test zuerst rot auf HEAD,
  dreimal identisch.
- Auf `scripts/dev/review-risk.txt`: `apps/monitoring/app/alerter.py` (T5, T6), `apps/monitoring/app/routers/agent.py`
  (T4, T9, T10, T11), `apps/monitoring/app/check_engine.py` (T9, T14) — diese Tasks bekommen zusätzlich `security`.
- Die Monitoring-Suite läuft auf SQLite. `tests/test_check_engine_concurrency.py` überspringt sich ohne
  Postgres-`DATABASE_URL` (von `scripts/tests/run.sh` erlaubt); die PR-CI fährt ihn gegen Postgres. Eine Task, die
  ihn ändert, sagt das im Commit-Body. Kein neuer Test, der nur mit Postgres läuft.
- Tests patchen Namen in `app.alerter`, `app.routers.checks`, `app.template_sync` und `app.routers.agent`
  (`monkeypatch.setattr(alerter, "_dispatch", …)` u. a.). Ein Helfer ruft solche Namen über sein eigenes Modul, damit
  die Patches weiter greifen; wo ein Name sich ändert, zieht das Patch-Ziel im selben Commit mit (ein vergessenes
  scheitert laut, `raising=True`).
- Neue Code-Strings (Log-Zeilen) englisch; bestehende deutsche bleiben. Docstrings von FastAPI-Routen nicht ändern
  (OpenAPI-`description`).
- Doku-Tasks fahren zusätzlich `python3 scripts/dev/doc-smoke.py --paths --env --strict` (Exit 0, Ergebnis in den
  Commit-Body). CHANGELOG: unter `## [Unreleased]`, umlautfrei.

### T1 — Metrik-Endpunkt: Query(pattern=) statt regex= (R-0697)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_checks_metrics.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2bcb4c0c 2026-10-29T11:43:53+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T1.verdict.json)
Änderung: In `get_check_metrics` (`apps/monitoring/app/routers/checks.py:427-…`) wird der Parameter `period` (`:429`) `Query("1h", pattern="^(1h|6h|24h|7d)$")`; sonst nichts. Tests in `tests/test_checks_metrics.py`: (a) ein `ast`-Scan über `apps/monitoring/app/**/*.py` (Pfad wie `tests/test_architecture_transitions.py:20`): kein Aufruf trägt das Schlüsselwort `regex`; Nicht-leer-Wächter: der Scan liest mindestens 30 Module und findet mindestens einen Aufruf mit `pattern=`; (b) `GET /checks/{id}/metrics?period=2h` → 422 mit `string_pattern_mismatch` im `detail`, `period=7d` → 200 (Fake-`query_range` wie in der Datei). Zuerst rot: (a) auf HEAD. `tests/test_openapi_snapshot.py` bleibt ohne Neuaufnahme grün.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checks_metrics.py tests/test_openapi_snapshot.py
Doku: keine (intern; Schema unverändert)
Beweis: origin/main@237b450a · `routers/checks.py:429` `Query("1h", regex=…)`; Probe (FastAPI 0.141.1 und 0.159.1, dreimal gleich): `regex=` warnt beim Import `FastAPIDeprecationWarning: \`regex\` has been deprecated, please use \`pattern\` instead`, `pattern=` nicht; OpenAPI beider Varianten gleich (wie `tests/openapi.snapshot.json:1444`); `period=2h` → 422 `string_pattern_mismatch` in beiden
Orakel: contract — kein `regex=` in `app/`, OpenAPI-Snapshot unverändert, 422 für einen Wert außerhalb der Liste
Dedup-Key: ref:monitoring:routers/checks.py:query-regex-deprecated
HEAD: 237b450a

### T2 — Scheduler-Job erst nach dem Commit, auch beim Löschen (R-0695)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_scheduler_after_commit.py, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6c224eaa 2026-10-29T11:46:15+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T2.verdict.json)
Änderung: `delete_check` (`apps/monitoring/app/routers/checks.py:278-287`): Tombstone, Löschen, `db.commit()`, danach `remove_check(check_id)` mit der ID aus dem Pfad (nicht über das gelöschte Objekt). `delete_template` (`apps/monitoring/app/routers/templates.py:230-244`): die IDs der Checks merken, Checks, Regeln und Template löschen, `db.commit()`, danach `remove_check` je gemerkter ID. Je Stelle ein Satz Kommentar zum Warum (scheitert der Commit, muss der Job bleiben; wie `template_sync._apply_scheduler_actions`, `apps/monitoring/app/template_sync.py:52-60`). Im Checks-Router ein Helfer (etwa `_schedule(check)`: eingeschaltet `add_check(check.id, check.interval, check.check_type)`, sonst `remove_check(check.id)`), den `create_check` (`:180-181`; für einen abgeschalteten neuen Check ist `remove_check` ein No-op, `apps/monitoring/app/scheduler.py:99-107`), `update_check` (`:264-267`), `toggle_check` (`:301-304`) und `reset_check` (`:331-334`) nach ihrem Commit rufen; er ruft die im Router importierten `add_check`/`remove_check`, damit die Patches greifen (`tests/test_templates_router.py:61`, `:292`, `tests/test_template_sync.py:97-98`, `tests/test_tag_sync.py:40-41`). Neue Testdatei `tests/test_scheduler_after_commit.py` (SPDX-Header wie die anderen Testdateien, Modul-Docstring mit dem Warum) mit `client_db` (`tests/conftest.py:39-77`): eine Ereignisliste aus einem `after_commit`-Listener auf der Session-Fabrik des Fixtures (`sqlalchemy.event.listen(factory, "after_commit", …)`) und Recordern für `app.routers.checks.remove_check` und `app.routers.templates.remove_check`; (a) `DELETE /checks/{id}` eines eingeschalteten `ping`-Checks → `["commit", "remove:<id>"]`; (b) ein `before_commit`-Listener wirft `RuntimeError`, Client mit `raise_server_exceptions=False` → 500, kein `remove`, der Check steht noch in der DB; (c) `DELETE /templates/{id}` mit zwei Checks des Templates → `["commit", "remove:<a>", "remove:<b>"]`; (d) wie (b) für das Template: kein `remove`, Template und Checks stehen; (e) Gegenprobe über den Helfer: `POST /checks/{id}/toggle` auf einem eingeschalteten Check → `["commit", "remove:<id>"]`. Zuerst rot: (a)–(d) auf HEAD (dort `remove` vor `commit` bzw. trotz gescheitertem Commit), dreimal identisch.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_scheduler_after_commit.py tests/test_checks_crud.py tests/test_templates_router.py tests/test_template_sync.py tests/test_tag_sync.py
Doku: CHANGELOG.md (Fixed, umlautfrei: scheitert im Monitoring das Loeschen eines Checks oder Templates beim Speichern, bleibt der Check eingeplant; vorher lief er bis zum Neustart des Dienstes nicht mehr)
Beweis: origin/main@237b450a · Code-Lesung `routers/checks.py:284-287` (`remove_check` vor `db.commit()`), `routers/templates.py:236-244` (ebenso je Check); ein Job entsteht nur beim Start neu (`scheduler.py:110-135`). Der Beweis ist (a)–(d) rot auf HEAD, dreimal identisch (Summary in den Commit-Body)
Orakel: contract — der Scheduler ändert sich erst nach einem erfolgreichen Commit
Dedup-Key: ref:monitoring:routers/checks.py:job-removed-before-commit
HEAD: 237b450a
Semantik: keine Stelle in docs/ (gesucht: „Scheduler“, „APScheduler“, „remove_check“, „DELETE /checks“ in `docs/developer/monitoring.html` und `docs/admin/monitoring.html`); Vorbild im Code `apps/monitoring/app/template_sync.py:52-60` — „Apply collected scheduler mutations AFTER the DB commit succeeded. Mutating the running APScheduler before the rows are persisted (the old behaviour) meant a failed/rolled-back commit left ghost jobs firing execute_check for checks that never existed, or silently unscheduled checks.“; die Roadmap-Zeile R-0695 (Kevin angenommen) legt das Verhalten fest

### T3 — Paritätstest der Typ-Tabellen gegen CHECK_TYPES (R-0694)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_types.py, apps/monitoring/tests/test_check_type_parity.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @3b901d9a 2026-10-29T11:48:25+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T3.verdict.json)
Änderung: Die funktionslokale Menge `agent_types` in `get_check_metrics` (`apps/monitoring/app/routers/checks.py:444-451`) wird die Modulkonstante `SERVER_METRIC_TYPES: frozenset[str]` neben `CHECK_TYPE_METRICS` (`:72`), mit dem bisherigen Kommentar; Inhalt und Abfragen bleiben (nicht aus `PUSH_ONLY_TYPES` abgeleitet: `agent_ping` gehört hinein, `smart_health` nicht — Spec, Nicht-Ziele). Der Modul-Docstring von `apps/monitoring/app/check_types.py` (`:5-14`) sagt danach, was stimmt: Typen und `push_only` leben hier, die Tabellen je Typ bei ihren Verwendern, `tests/test_check_type_parity.py` hält sie gleich. Neue Testdatei `tests/test_check_type_parity.py` (SPDX-Header, Modul-Docstring mit dem Warum: ein Typ, der in einer Tabelle fehlt, fällt sonst erst zur Laufzeit auf — `ValueError` in `get_checker`, eine ungeprüfte Config, eine Abfrage nach `monitor_check_duration_ms`): (a) `set(_REGISTRY)` (`app.checkers`), `set(CONFIG_MODELS)` (`app.check_configs`) und `set(CHECK_TYPE_METRICS)` (`app.routers.checks`) je gleich `VALID_CHECK_TYPES`; die Meldung nennt je Tabelle die fehlenden und die überzähligen Typen; (b) `_DYNAMIC_METRIC_PATTERNS` und `SERVER_METRIC_TYPES` sind Teilmengen von `VALID_CHECK_TYPES`; (c) Nicht-leer-Wächter: `VALID_CHECK_TYPES` hat mindestens 12 Einträge, `PUSH_ONLY_TYPES` ist eine nicht leere echte Teilmenge. Der Test ist auf HEAD grün (die Tabellen stimmen heute); was er kann, zeigt die Mutations-Stichprobe.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_type_parity.py tests/test_checks_metrics.py tests/test_push_only_ui_sync.py tests/test_check_configs.py
Doku: keine (intern; der Docstring von `check_types.py` wird richtig)
Beweis: origin/main@237b450a · Probe (Endstand, Python 3.13.5, dreimal gleich): `_REGISTRY`, `CONFIG_MODELS` und `CHECK_TYPE_METRICS` haben je genau die 12 Typen aus `CHECK_TYPES`, `_DYNAMIC_METRIC_PATTERNS` ist Teilmenge; kein Test vergleicht sie (`grep -rn "CONFIG_MODELS\|_REGISTRY\|CHECK_TYPE_METRICS" apps/monitoring/tests` trifft nur Einzelzugriffe in `test_check_configs.py` und einen Kommentar in `test_agent_report.py`)
Orakel: contract — jede Tabelle kennt genau die Typen aus `CHECK_TYPES`; Mutations-Stichprobe: `"system_state"` aus `CHECK_TYPE_METRICS` entfernt bzw. ein 13. Typ nur in `CHECK_TYPES` → (a) rot und nennt die Tabelle (Ergebnis in den Commit-Body)
Dedup-Key: ref:monitoring:check_types.py:seven-type-tables
HEAD: 237b450a

### T4 — Push-Checker: ein Protocol, prev_details für jeden (R-0694)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/__init__.py, apps/monitoring/app/checkers/plugins.py, apps/monitoring/app/checkers/smart.py, apps/monitoring/app/checkers/system.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_check_type_parity.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4a47717a 2026-10-29T11:54:32+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T4.verdict.json)
Änderung: In `apps/monitoring/app/checkers/__init__.py` neben `Checker` (`:19-26`) `class PushChecker(Checker, Protocol)` mit `evaluate(self, config: dict, report: dict, prev_details: dict | None = None) -> tuple[str, str, dict | None]` (Docstring: `prev_details` sind die vorigen `_details` des Checks oder `None`; wer sie nicht braucht, liest sie nicht). `ProxmoxBackupChecker.evaluate` und `ZfsHealthChecker.evaluate` (`apps/monitoring/app/checkers/plugins.py:62`, `:184`), `SmartHealthChecker.evaluate` (`apps/monitoring/app/checkers/smart.py:87`) und `SystemStateChecker.evaluate` (`apps/monitoring/app/checkers/system.py:56`) bekommen den Parameter `prev_details: dict | None = None`, unbenutzt, Bewertung unverändert. In `apps/monitoring/app/routers/agent.py` entfällt `_PREV_DETAILS_TYPES` (`:64`); der Rumpf je Check (`:240-…`, im Endstand in `with db.begin_nested():`) liest die vorigen `_details` für jeden Push-Check wie heute für die drei (ungültiges JSON oder kein Objekt → `None`) und ruft `checker.evaluate(config, report, prev_details)`; der Kommentar über dem State-Lock (welche Checker den Vorwert lesen und warum) bleibt sinngemäß. Tests in `tests/test_check_type_parity.py`: (a) für jeden Typ in `PUSH_ONLY_TYPES` hat `get_checker(t).evaluate` genau die Parameter `config`, `report`, `prev_details`, dieser mit Default `None` (`inspect.signature`); Nicht-leer: mindestens 7 Push-Typen geprüft; (b) jeder andere Typ hat einen Checker mit `run`. Zuerst rot: (a) auf HEAD (`proxmox_backup`, `smart_health`, `system_state`, `zfs_health`). Die Router-Fälle mit Vorwert (`docker_health` Neustart-Zähler, `agent_resources` Hysterese, `service_process` Listen-Modus) bleiben in den bestehenden Suiten grün.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_type_parity.py tests/test_agent_report.py tests/test_plugin_checkers.py tests/test_smart_checker.py tests/test_system_state_checker.py tests/test_service_process_checker.py tests/test_agent_resources_checker.py
Doku: docs/developer/monitoring.html + docs/en/developer/monitoring.html, Abschnitt `docker_health` (`:188`): statt „(`evaluate(config, report, prev_details)`, `_PREV_DETAILS_TYPES` in `routers/agent.py`)“ — jeder Push-Checker nimmt `evaluate(config, report, prev_details)` (`PushChecker` in `checkers/__init__.py`), den Vorwert lesen `agent_resources`, `service_process` und `docker_health`; doc-smoke
Abhängt von: T3
Beweis: origin/main@237b450a · Code-Lesung `routers/agent.py:64`, `:240` (die Liste steht im Router), `checkers/__init__.py:19-26` (Protocol nur `run`); Probe (Endstand, `inspect.signature`): `proxmox_backup`, `smart_health`, `system_state`, `zfs_health` nehmen `(config, report)`
Orakel: contract — jeder Push-Checker nimmt `prev_details`; eine Signatur ohne macht (a) rot
Dedup-Key: ref:monitoring:check_types.py:seven-type-tables
HEAD: 237b450a

### T5 — Alarm: ein Regel-Pfad für Einzel- und Sammelmeldung (R-0693)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/app/alert_bundle.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @3ad36203 2026-10-29T11:59:51+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T5.verdict.json)
Änderung: Neu und öffentlich in `apps/monitoring/app/alerter.py`, von beiden Pfaden gerufen: `enabled_rules(db) -> list[MonitorAlertRule]` (die Abfrage `alerter.py:149` = `apps/monitoring/app/alert_bundle.py:356`); `reported_status(notified: str | None) -> str` (`alerter.py:157` = `_reported`, `alert_bundle.py:323-326`, das entfällt); `rule_applies(db, rule, check, *, is_recovery: bool) -> bool` = `_rule_matches` und, außer bei einer Entwarnung, nicht `_is_in_cooldown` (`alerter.py:195-201` = `alert_bundle.py:357-363`; die DEBUG-Zeile zum Cooldown wandert mit); `send_to_rule(db, rule, members: Sequence[tuple[MonitorCheck, str]], msg: dict, new_status: str, sent_at: datetime | None = None) -> None`: ein Versand über `_dispatch` mit dem ersten Mitglied als Check, isoliert (Ausnahme → `logger.exception("Alert dispatch failed for rule %s", rule.id)`, Ergebnis `(False, f"Dispatch failed ({type(exc).__name__})")`), danach je Mitglied eine `MonitorAlertLog`-Zeile mit dessen `old_status`, `sent_at` bzw. ohne `sent_at` `utcnow_naive()` nach dem Versand wie heute (`alerter.py:203-222` = `_send_rules`/`_dispatch_isolated`, `alert_bundle.py:369-396`; `_dispatch_isolated` entfällt). `process_alert` liest die Regeln weiter vor dem Claim-Commit und ruft je Regel `rule_applies` und `send_to_rule(db, rule, [(check, reported_old)], msg, new_status)`; `_send_rules` ruft dieselben mit `sent_at=now`. `_rule_matches`, `_is_in_cooldown` und `_dispatch` bleiben privat und werden im Modul gerufen, die Patches der Tests greifen weiter. Kein neuer Test (Refactor): die Suiten beider Pfade vor und nach dem Diff grün; der Alert-Log-Grund `Dispatch failed (ValueError)` (`tests/test_alerter.py:431`, `tests/test_alert_bundle.py:381`) bleibt; der Text der Service-Log-Zeile wird einer für beide Pfade (Spec, Trade-off 1).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter.py tests/test_alert_bundle.py tests/test_alerter_hub.py tests/test_alerter_sent_state.py tests/test_alerter_dispatch.py tests/test_architecture_transitions.py
Doku: keine (intern; die Entwickler-Doku nennt die geänderten Namen erst in T6)
Beweis: origin/main@237b450a · Code-Lesung `alerter.py:149`, `:157`, `:195-222` gegen `alert_bundle.py:323-326`, `:356-396`
Orakel: mutation-sample — `send_to_rule` schreibt die Log-Zeile nur für das erste Mitglied bzw. `rule_applies` lässt `is_recovery` außer Acht → je mindestens ein Test der Suiten rot (Ergebnis in den Commit-Body); eine Stichprobe, kein Beweis der Äquivalenz
Metrik: Zugriffe von `alert_bundle.py` auf private Namen von `alerter` (AST, Python 3.13.5, Endstand) 12 → 9 (`_rule_matches`, `_is_in_cooldown`, `_dispatch` entfallen); Regel-Schleife und Isolation je einmal statt zweimal
Dedup-Key: ref:monitoring:alert_bundle.py:duplicated-alert-protocol
HEAD: 237b450a

### T6 — Alarm: Glocke und Nachricht öffentlich, process_alert in benannte Schritte (R-0693, R-0728)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/app/alert_bundle.py, apps/monitoring/tests/test_alerter.py, apps/monitoring/tests/test_check_engine_concurrency.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, apps/monitoring/tests/test_alerter_hub.py, apps/monitoring/tests/_helpers.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @a7d5d7f4 2026-10-29T12:09:06+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T6.verdict.json)
Änderung: (1) Umbenannt, weil beide Pfade sie rufen: `_build_message` → `build_message` (`apps/monitoring/app/alerter.py:486`), `_emit_to_hub` → `emit_to_hub` (`:378`), `_post_hub_event` → `post_hub_event` (`:418`). (2) Neu und öffentlich: `bell_severity(hub_status, old_status, new_status, severity) -> str` (Entwarnung: `hub_status`, sonst `_hub_severity(old_status, new_status, severity)`; ersetzt `alerter.py:235` und `_bell_severity`, `apps/monitoring/app/alert_bundle.py:494-499`); `bell_record(status, severity, sent_at, now) -> tuple[str | None, datetime | None]` = (`_capped_status(status, severity)`, bei `ok` `sent_at`, sonst `now`) (ersetzt `hub_reserved`, `alerter.py:174-177`, und `_record_bell`, `alert_bundle.py:515-520`); `highest_severity(severities) -> str` und `capped_label(status, severity) -> str` (der Deckel des Betreffs aus `build_message` und `_bundle_message`, `alert_bundle.py:404-408`, `:419`). `process_alert` gibt `emit_to_hub` die Stufe immer aus `bell_severity`; der Zweig `severity is None` in `emit_to_hub` entfällt, wenn ihn kein Aufrufer mehr nutzt. `_severity_level`, `_STATUS_LEVEL`, `_LEVEL_SEVERITY`, `_hub_severity`, `_capped_status`, `_release_hub_slot` bleiben privat; danach greift `alert_bundle.py` auf keinen privaten Namen von `alerter` mehr zu (nur noch `check_engine._dispatch_alert_bg`, T9). (3) R-0728: `process_alert` (`alerter.py:90-238`, 149 Zeilen) in benannte Schritte, etwa `_claim_transition` (Lock, aktueller Status, Entscheidung, `silent_ack`, Stummschaltung, Regeln lesen, Glocken-Entscheidung und Reservierung, Claim-Commit; gibt ein kleines `NamedTuple` oder `None` zurück), `_notify_rules` und `_notify_bell` (Emit, bei Fehlschlag `_release_hub_slot`). Reihenfolge, Commit- und Flush-Punkte bleiben: Regeln vor dem Claim-Commit, Nachricht einmal nach dem Commit, Versand, `db.flush()`, Glocke. `process_alert` höchstens 60 Zeilen samt Docstring, keine neue Funktion über 60. (4) Tests: Patch-Ziele und Direktaufrufe folgen den neuen Namen (`tests/test_alerter.py`: `_build_message`, `_emit_to_hub`, `_post_hub_event`; `tests/test_check_engine_concurrency.py`: `_emit_to_hub`), Aussagen unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter.py tests/test_alert_bundle.py tests/test_alerter_hub.py tests/test_alerter_sent_state.py tests/test_alerter_dispatch.py tests/test_check_engine_concurrency.py tests/test_architecture_transitions.py
Doku: docs/developer/monitoring.html + docs/en/developer/monitoring.html: `:247` `_emit_to_hub` → `emit_to_hub`, `:253` `_post_hub_event` → `post_hub_event`, `:255` „eine Nachricht über `_dispatch`“ → „über `send_to_rule`“; doc-smoke
Abhängt von: T5
Beweis: origin/main@237b450a · Code-Lesung `alerter.py:174-177`, `:235` gegen `alert_bundle.py:494-520`; `alert_bundle.py:313`, `:404-419`, `:485-488`, `:499`, `:518` greifen auf `_build_message`, `_severity_level`, `_STATUS_LEVEL`, `_LEVEL_SEVERITY`, `_emit_to_hub`, `_post_hub_event`, `_hub_severity`, `_capped_status` zu
Orakel: mutation-sample — `bell_record` setzt bei `ok` `now` statt `sent_at` bzw. `bell_severity` nimmt für eine Entwarnung die Severity des Checks → je mindestens ein Test der Suiten rot (Ergebnis in den Commit-Body); eine Stichprobe, kein Beweis der Äquivalenz
Metrik: AST (Python 3.13.5): `process_alert` 149 → ≤ 60 Zeilen, längste neue Funktion ≤ 60; Zugriffe von `alert_bundle.py` auf private Namen von `alerter` 9 → 0
Dedup-Key: ref:monitoring:alert_bundle.py:duplicated-alert-protocol
HEAD: 237b450a

### T7 — MonitorTemplate.to_dict ohne Domänen-Import (R-0696)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_alert_secrets.py, apps/monitoring/tests/test_module_boundaries.py, apps/monitoring/tests/test_seed.py, apps/monitoring/tests/test_models_timestamps.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5c57644d 2026-10-29T12:21:03+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T7.verdict.json)
Änderung: `MonitorTemplate.to_dict` (`apps/monitoring/app/models.py:232-…`) bekommt die zwei Flags als Schlüsselwort-Parameter ohne Default, `builtin_edited: bool` und `builtin_update_available: bool`, und schreibt sie an dieselbe Stelle wie heute (`builtinEdited`, `builtinUpdateAvailable` nach `builtinVersion`); der funktionslokale Import (`:234`) entfällt. In `apps/monitoring/app/routers/templates.py` ein Helfer (etwa `_template_dict(template, **kw)`), der `builtin_edited(template)` und `builtin_update_available(template)` aus `app.builtin_templates` rechnet (das Modul importiert der Router schon, `:18`) und `to_dict` ruft; die fünf Aufrufer (`:88`, `:162`, `:181`, `:220`, `:321`) nutzen ihn. Antworten unverändert: Schlüssel, Werte, Reihenfolge. `tests/test_alert_secrets.py::test_template_to_dict_masks_only_a_set_password` (aus smtp-hardening T2) ruft `to_dict(builtin_edited=False, builtin_update_available=False)`, Aussagen unverändert. Neue Testdatei `tests/test_module_boundaries.py` (SPDX-Header, Modul-Docstring mit dem Warum, Muster wie `tests/test_architecture_transitions.py`: ein `ast`-Scan, weil ein Abhängigkeitszyklus in keinem Verhaltenstest auffällt): (a) jedes `import`/`from … import` in `app/models.py`, auch in Funktionen, das ein Modul unter `app` nennt, nennt eins unter `app.core`; Nicht-leer: der Scan findet mindestens einen solchen Import. Zuerst rot: (a) auf HEAD (`models.py:234`).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_boundaries.py tests/test_templates_router.py tests/test_alert_secrets.py tests/test_seed.py tests/test_template_overrides.py tests/test_openapi_snapshot.py
Doku: keine (intern)
Beweis: origin/main@237b450a · Code-Lesung `models.py:234` (funktionslokaler Import aus `builtin_templates`), `builtin_templates.py:37-39` (importiert `models` und `template_sync`), `template_sync.py:42` (`scheduler`), `scheduler.py:21-22` (`alert_bundle`, `check_engine`)
Orakel: contract — `models.py` hängt in `app` nur von `app.core` ab; Template-Antworten unverändert
Dedup-Key: ref:monitoring:models.py:model-imports-domain
HEAD: 237b450a

### T8 — cleanup_server in eigenes Modul (R-0696)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/server_cleanup.py, apps/monitoring/app/template_sync.py, apps/monitoring/app/routers/admin.py, apps/monitoring/tests/test_template_sync.py, apps/monitoring/tests/test_template_suggestions.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, apps/monitoring/tests/test_scheduler_after_commit.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @873ae458 2026-10-29T12:25:21+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T8.verdict.json)
Änderung: `cleanup_server` (`apps/monitoring/app/template_sync.py:701-743`) zieht unverändert in das neue Modul `apps/monitoring/app/server_cleanup.py` (SPDX-Header per `reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`, Modul-Docstring: was beim Löschen eines Servers geht und warum ohne Fremdschlüssel). Den Scheduler bedient es weiter über die gesammelten Aktionen nach dem Commit: `_apply_scheduler_actions` (`template_sync.py:52-65`) wird öffentlich `apply_scheduler_actions` (die Aufrufer in `template_sync.py` ziehen mit), `server_cleanup` importiert es und `SchedulerAction` aus `template_sync`; so greifen die Patches `template_sync.add_check`/`remove_check` der Tests weiter. Die Zeile im Modul-Docstring von `template_sync` (`:13`) entfällt. `apps/monitoring/app/routers/admin.py:18` importiert aus `app.server_cleanup`. Tests: nur die Imports (`tests/test_template_sync.py:36`, `tests/test_template_suggestions.py:29`) zeigen auf das neue Modul, Aussagen unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_sync.py tests/test_template_suggestions.py tests/test_admin_router.py tests/test_tag_sync.py tests/test_module_boundaries.py
Doku: docs/developer/monitoring.html + docs/en/developer/monitoring.html, Modulübersicht (`:62-79`): eine Zeile `server_cleanup.py` (Aufräumen beim Löschen eines Servers, `cleanup_server()`); dabei die dort fehlenden `alert_bundle.py` (Sammelmeldung der Heartbeats) und `check_types.py` (Check-Typen, `push_only`) nachtragen; doc-smoke
Beweis: origin/main@237b450a · Code-Lesung `template_sync.py:701-743` (räumt Checks, Regeln, Zuweisungen, Tombstones, Agent-Schlüssel, Wartungsfenster, Liveness, Host-Fakten und Ablehnungen eines Servers ab — keine Template-Synchronisation), einziger Aufrufer in `app/` ist `routers/admin.py:61`
Orakel: contract — dieselben Tests von `cleanup_server` grün über den neuen Import
Metrik: `template_sync.py` 743 Zeilen → etwa 700, eine Zuständigkeit weniger
Dedup-Key: ref:monitoring:models.py:model-imports-domain
HEAD: 237b450a

### T9 — dispatch_alert_bg öffentlich (R-0696)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/routers/agent.py, apps/monitoring/app/alert_bundle.py, apps/monitoring/tests/test_architecture_transitions.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_check_engine_concurrency.py, apps/monitoring/tests/test_service_process_checker.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, apps/monitoring/tests/_helpers.py, apps/monitoring/tests/test_alerter_hub.py, apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_alerter_sent_state.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @8c0f6ae0 2026-10-29T12:31:47+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T9.verdict.json)
Änderung: `_dispatch_alert_bg` (`apps/monitoring/app/check_engine.py:44`) heißt `dispatch_alert_bg`: der eine Versandweg für Scheduler, Push-Pfad und Sammelmeldung (so sagt es sein Docstring schon). Aufrufer `check_engine.py:364` (Pool), `apps/monitoring/app/routers/agent.py:18`, `:314`, `apps/monitoring/app/alert_bundle.py:149`; Docstrings und Kommentare mit dem Namen ziehen mit (`check_engine.py:33`, `:357`, `alert_bundle.py:125`, `:131`, `tests/test_service_process_checker.py:803`). Tests: `tests/test_architecture_transitions.py:105-113` sucht `^def dispatch_alert_bg\(` (Aussage „genau einmal, in check_engine.py“ bleibt), `tests/test_check_engine.py:283`, `:337` und `tests/test_check_engine_concurrency.py` (Imports und Aufrufe) folgen dem Namen. Danach ist `grep -rn "_dispatch_alert_bg" apps/monitoring docs` leer.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine.py tests/test_architecture_transitions.py tests/test_check_engine_concurrency.py tests/test_alert_bundle.py tests/test_agent_report.py tests/test_service_process_checker.py tests/test_execute_check.py
Doku: docs/developer/monitoring.html + docs/en/developer/monitoring.html `:255` („gehen dann einzeln über `_dispatch_alert_bg`“ → `dispatch_alert_bg`); doc-smoke
Beweis: origin/main@237b450a · `routers/agent.py:18` und `alert_bundle.py:149` nehmen `check_engine._dispatch_alert_bg`
Orakel: contract — `test_alert_dispatch_is_defined_once` findet die eine Definition unter dem neuen Namen
Metrik: Zugriffe auf private Namen über Modulgrenzen in `app/` (AST, Python 3.13.5) nach T6: 3 → 1 (es bleibt `_find_nul`, T10)
Dedup-Key: ref:monitoring:models.py:model-imports-domain
HEAD: 237b450a

### T10 — find_nul öffentlich, Wächter gegen private Namen über Modulgrenzen (R-0696)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/bounds.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_module_boundaries.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @fb44af33 2026-10-29T12:35:42+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T10.verdict.json)
Änderung: `_find_nul` (`apps/monitoring/app/core/bounds.py:43`, Aufrufer `:73`, `apps/monitoring/app/routers/agent.py:23`, `:101`) heißt `find_nul`. In `tests/test_module_boundaries.py` (aus T7) ein zweiter Wächter: (b) kein Modul unter `app/` importiert aus einem anderen Modul unter `app` einen Namen, der mit `_` beginnt (ohne `__…__`; `from app.x import _y`, auch relativ), und keins greift über einen importierten App-Modulnamen auf einen solchen Namen zu (`alerter._y`, `check_engine._y`); Tests bleiben außen vor (sie dürfen private Namen patchen). Die Meldung nennt Datei, Zeile und Namen. Nicht-leer: der Scan liest mindestens 30 Module und findet mindestens 50 Importe aus `app`. Zuerst rot: (b) auf HEAD nach T5, T6, T9 (`_find_nul` in `routers/agent.py`).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_boundaries.py tests/test_nul.py tests/test_agent_report.py tests/test_architecture_transitions.py
Doku: keine (intern; die Doku nennt `_find_nul` nicht)
Abhängt von: T5, T6, T7, T9
Beweis: origin/main@237b450a · AST-Zählung (Python 3.13.5, `from app.x import _y` und `<app-Modul>._y` außerhalb des definierenden Moduls, Tests ausgenommen): 16 Zugriffe; Endstand 15 (13 in `alert_bundle.py`, `_dispatch_alert_bg` und `_find_nul` in `routers/agent.py`)
Orakel: contract — kein privater Name kreuzt eine Modulgrenze; Mutations-Stichprobe: `from app.core.bounds import _find_nul` zurück → (b) rot
Metrik: 15 → 0 Zugriffe (dasselbe AST-Kriterium)
Dedup-Key: ref:monitoring:models.py:model-imports-domain
HEAD: 237b450a

### T11 — agent_report in benannte Schritte (R-0728)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ae1aca70 2026-10-29T12:41:30+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T11.verdict.json)
Änderung: `agent_report` (`apps/monitoring/app/routers/agent.py:74-316`) ruft private Schritte in der heutigen Reihenfolge: Liveness mit eigenem Commit (ab `:87`), NUL-Prüfung (ab `:101`, `RequestValidationError` wie bisher), Host-Fakten (`:121`), Metrik-Zeilen aus `resources` und `uptime_seconds` mit dem breiten `except` als letzter Sicherung und `victoria.write` (`:181`), Push-Checks laden (Filter, Reihenfolge nach `id`, `:188-…`), je Check die Auswertung im Savepoint (Endstand: `with db.begin_nested():`, `except Exception` mit `logger.exception` und `continue` außerhalb; Zeilen, Alert und Zähler eines Checks erst nach dem Block übernommen), Commit mit 500 „Failed to save the check evaluation“ (`:297-…`), Check-Zeilen schreiben, Alerts per `BackgroundTasks` (`:314`). Etwa `_record_liveness`, `_refuse_nul`, `_report_lines`, `_push_checks`, `_evaluate_push_check` (gibt die Zeilen und den Alert oder `None` zurück), `_prev_details`. Antwort, Log-Texte, Statuscodes und die Namen, die Tests in `app.routers.agent` patchen (`apply_result`, `get_checker`, `victoria`, `store_host_facts`, `record_agent_report`, `dispatch_alert_bg`), bleiben; der Docstring der Route bleibt wörtlich (OpenAPI-`description`). `agent_report` höchstens 60 Zeilen samt Docstring, keine neue Funktion über 60.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_service_process_checker.py tests/test_system_state_checker.py tests/test_nul.py tests/test_require_agent.py tests/test_victoria_injection.py tests/test_openapi_snapshot.py
Doku: keine (intern)
Abhängt von: T4, T9, T10
Beweis: origin/main@237b450a · AST (Python 3.13.5): `agent_report` 243 Zeilen (Endstand nach monitoring-io 237)
Orakel: mutation-sample — die Zeilen eines Checks auch nach einer Ausnahme im Savepoint übernommen bzw. Liveness erst nach der NUL-Prüfung → je mindestens ein Test der Suiten rot (Ergebnis in den Commit-Body); eine Stichprobe, kein Beweis der Äquivalenz
Metrik: `agent_report` 237 → ≤ 60 Zeilen, längste Funktion in `routers/agent.py` ≤ 60 (AST, Python 3.13.5)
Dedup-Key: ref:cross:python:long-functions
HEAD: 237b450a

### T12 — AgentResourcesChecker.evaluate in benannte Schritte (R-0728)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f281f24a 2026-10-29T12:46:27+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T12.verdict.json)
Änderung: `AgentResourcesChecker.evaluate` (`apps/monitoring/app/checkers/agent.py:314-…`, 215 Zeilen, Endstand 216) ruft private Schritte: die Hysterese-Bewertung (heute die Closure `grade`, `:339-…`, etwa als kleine Klasse oder Funktion mit dem Vorwert), CPU/RAM/Swap, Last je CPU (samt der Regel „im Container nicht bewertet“), Platten mit Inodes und `min_free_gb`, Temperaturen, Ergebnis (Status, Meldung, `metrics`, `_details` samt `problems`). Reihenfolge der Probleme in der Meldung, Schlüssel und Werte von `metrics` und `_details`, Defaults der Config und die Kommentare zum Warum (keine CPU/RAM- und Platten-Metrik hier, R-0633; Hysterese je Metrik) bleiben. `evaluate` höchstens 60 Zeilen samt Docstring, keine neue Funktion über 60. Die übrigen Klassen der Datei bleiben unberührt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_resources_checker.py tests/test_checker_messages.py tests/test_agent_report.py
Doku: keine (intern)
Beweis: origin/main@237b450a · AST (Python 3.13.5): `AgentResourcesChecker.evaluate` 215 Zeilen (Endstand 216), Datei 834 Zeilen
Orakel: mutation-sample — die Hysterese nimmt den Vorwert nicht mehr (`prev_level` immer `None`) bzw. die Inode-Prüfung fällt weg → je mindestens ein Test in `test_agent_resources_checker.py` rot (Ergebnis in den Commit-Body); eine Stichprobe, kein Beweis der Äquivalenz
Metrik: `evaluate` 216 → ≤ 60 Zeilen, längste neue Funktion ≤ 60 (AST, Python 3.13.5)
Dedup-Key: ref:cross:python:long-functions
HEAD: 237b450a

### T13 — SmartHealthChecker.evaluate in benannte Schritte (R-0728)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @eac2a46e 2026-10-29T12:48:57+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T13.verdict.json)
Änderung: `SmartHealthChecker.evaluate` (`apps/monitoring/app/checkers/smart.py:87-257`, 171 Zeilen) ruft private Schritte: kein Gerät (`smart_absent`), Schwellen aus der Config (`:101-117`), Bewertung je Platte (allgemeine Prüfungen, Exit-Code-Bits, Temperatur je Klasse, dann `_check_ata`/`_check_nvme`, `:260`, `:301`), Metriken je Platte (`:234-…`), Ergebnis (`:248-257`). Meldungen, Reihenfolge der Probleme, Metrik-Namen (`safe_metric_part`), `_details` und die Kommentare zum Warum bleiben. `evaluate` höchstens 60 Zeilen samt Docstring, keine neue Funktion über 60.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py tests/test_checker_messages.py tests/test_agent_report.py
Doku: keine (intern)
Abhängt von: T4
Beweis: origin/main@237b450a · AST (Python 3.13.5): `SmartHealthChecker.evaluate` 171 Zeilen
Orakel: mutation-sample — Bit `0x10` des Exit-Codes nicht mehr `critical` bzw. `ignore_devices` ignoriert → je mindestens ein Test in `test_smart_checker.py` rot (Ergebnis in den Commit-Body); eine Stichprobe, kein Beweis der Äquivalenz
Metrik: `evaluate` 171 → ≤ 60 Zeilen, längste neue Funktion ≤ 60 (AST, Python 3.13.5)
Dedup-Key: ref:cross:python:long-functions
HEAD: 237b450a

### T14 — apply_result in benannte Schritte (R-0728)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @573ed519 2026-10-29T12:51:56+01:00
Review: approve (.ah-out/review/monitoring-ref-3/T14.verdict.json)
Änderung: `apply_result` (`apps/monitoring/app/check_engine.py:167-272`, 106 Zeilen, davon 22 Zeilen Docstring und 11 Signatur) ruft zwei private Schritte: die Dämpfung (Zähler `next_fail_count`/`next_ok_count`, `effective_status`, `holds_recovery`, Kürzung auf `MAX_MESSAGE` vor dem Suffix, Suffix „(failure n/m)“ bzw. „(recovery n/m)“) und das Schreiben des States (neu anlegen oder aktualisieren samt INFO-Zeile `"Check '%s': %s -> %s (%s)"` und der Regel für `keep_previous_details_when_absent`); die Sent-State-Entscheidung (`resolve_notification`, `silent_ack`) bleibt im Rumpf. Docstring, Rückgabe und die Tokens, die `tests/test_architecture_transitions.py:25-32` in `check_engine.py` verlangt, bleiben. `apply_result` höchstens 70 Zeilen samt Docstring, keine neue Funktion über 60.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine.py tests/test_architecture_transitions.py tests/test_execute_check.py tests/test_agent_report.py tests/test_check_engine_concurrency.py
Doku: keine (intern)
Beweis: origin/main@237b450a · AST (Python 3.13.5): `apply_result` 106 Zeilen
Orakel: mutation-sample — Kürzung nach statt vor dem Suffix bzw. `held` ohne Übernahme von `notified_status` → je mindestens ein Test in `test_check_engine.py` rot (Ergebnis in den Commit-Body); eine Stichprobe, kein Beweis der Äquivalenz
Metrik: `apply_result` 106 → ≤ 70 Zeilen, längste neue Funktion ≤ 60 (AST, Python 3.13.5)
Dedup-Key: ref:cross:python:long-functions
HEAD: 237b450a

## Entscheidungen
- 2026-10-29 T3: kein `SERVER_METRIC_TYPES`, `routers/checks.py` bleibt unverändert — seit R-0749 gibt es die Menge `agent_types` in `get_check_metrics` nicht mehr, nur `agent_resources` liest nach Server; der Paritätstest prüft deshalb nur `_DYNAMIC_METRIC_PATTERNS` als Teilmenge
- 2026-10-29 T2: Test (c) prüft `commit` zuerst und die `remove` sortiert — die Reihenfolge von `.all()` ist nicht festgelegt
- 2026-10-29 T6: der Zweig `severity is None` in `emit_to_hub` bleibt — `tests/test_alerter_hub.py` ruft `emit_to_hub` direkt ohne `severity` und prüft die berechnete Stufe; die Datei und `tests/_helpers.py` (Docstrings) folgen dem Umbenennen. `_notify_rules` steht als Schleife in `process_alert` (vier Zeilen), dazu `_reserve_bell` für die Glocken-Reservierung, damit `_claim_transition` unter 60 Zeilen bleibt
- 2026-10-29 T7: `tests/test_seed.py` (14 Aufrufe) liest die Flags über den Router-Helfer `templates_router._template_dict` statt `to_dict()` — prüft so weiter die Antwortform; `tests/test_models_timestamps.py` ruft `to_dict` für jedes Modell und gibt `MonitorTemplate` die beiden Pflicht-Flags mit (`_TO_DICT_KWARGS`). Der Wächter wertet auch relative Imports als `app.<modul>`
- 2026-10-29 T8: `server_cleanup` loggt unter `monitor.server_cleanup` (eigener Logger je Modul, Text unverändert); die Modulübersicht hat `alert_bundle.py` und `check_types.py` schon, nur `server_cleanup.py` kommt dazu; `tests/test_scheduler_after_commit.py` nennt im Docstring den neuen Namen `apply_scheduler_actions`
- 2026-10-29 T9: vier Testdateien mehr folgen dem Namen (`tests/_helpers.py`, `test_alerter_hub.py`, `test_alerter_sent_state.py`, `test_agent_report.py` — dort ist es das monkeypatch-Ziel am Router-Modul); `docs/features/*.md` (Pläne, auch dieser) behalten den alten Namen als Befund, die grep-Leere gilt für `apps/monitoring` und `docs/developer`, `docs/en/developer`
- 2026-10-29 T10: `_find_nul` heißt auf main inzwischen `_find_unstorable` (NUL und einsame Surrogate) — umbenannt wird dieser zu `find_unstorable`, nur im Monitoring (`apps/server` hat eine eigene Kopie, nicht im Auftrag). Der Wächter (b) wertet `from app import <modul>` als Modulnamen (Pfad unter `app/` existiert) und zählt nur Zugriffe `<alias>._y` über solche Namen; Selbstimporte bleiben erlaubt
- 2026-10-29 T11: Schritte heißen `_record_liveness`, `_refuse_unstorable_report` (der Name `_find_nul` ist auf main `find_unstorable`, T10), `_store_host_facts`, `_report_lines`, `_push_checks`, `_evaluate_push_check` (Savepoint; gibt Zeilen, Übergang und Alert erst nach dem Block zurück, `try`/`continue` bleibt im Rumpf), `_result_lines`, `_locked_state`, `_prev_details`, `_commit_evaluation`; Kommentare zum Warum ziehen wörtlich zu ihrem Schritt
- 2026-10-29 T12: Die Hysterese-Buchführung (problems, status, problem_levels, prev_problems) trägt eine kleine Klasse `_Grader` statt einer Closure, damit die Schritte `_grade_usage`, `_grade_load`, `_grade_disks`, `_grade_temperatures` Modulfunktionen bleiben; `_resources_message`/`_resources_details` bauen Meldung und Details. Der Zweig „prev_problems ist kein dict“ ist jetzt ein Ausdruck in `_Grader.__init__` (Coverage zählt ihn nicht mehr als eigene Zeile: 46 → 45 fehlende Zeilen, kein Test entfiel).
- 2026-10-29 T13: `evaluate` ruft `_absent_result`, `_smart_thresholds`, je Platte `_grade_disk` (Methode, weil sie wie zuvor `self._check_ata`/`self._check_nvme` ruft; darin `_check_common` für SMART-Urteil, Uncorrectables, Exit-Code-Bits und Temperatur mit eigener Liste wie `_check_ata`, 2.32), `_disk_metrics` und `_smart_result`. `if category != "critical": category = "warning"` steht als `_worse(category, "warning")` (gleichwertig bei Kategorie ok/warning/critical); Reihenfolge der Probleme bleibt, weil die Listen in derselben Folge verlängert werden.
- 2026-10-29 T14: Die INFO-Zeile `"Check '%s': %s -> %s (%s)"` steht auf main schon in `log_transition` (Aufrufer nach dem Commit), nicht mehr in `apply_result`; `_write_state` schreibt also nur den State (neu oder aktualisiert, Regel `keep_previous_details_when_absent`) und gibt ihn zurück, `_damp` trägt Zähler, Hold, Kürzung und Suffix; die Sent-State-Entscheidung bleibt im Rumpf. `old_status` rechnet der Rumpf (Rückgabe) und reicht es an `_damp`.
