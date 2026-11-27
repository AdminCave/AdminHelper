<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-neu-p1c — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-neu-p1c · Review: pro Task
Spec: docs/features/arch-monitoring-neu-p1c.md (Roadmap R-1637, R-1793, R-1521)
Heavy: linux-full — Monitoring-Migration (Alembic-Revision und Startschritt) und Monitoring-API; dazu vor dem Merge die Abnahme `run.sh integration --strict --step upgrade-path` auf einer Pool-VM (Kevin 2026-11-27, „Vor der nächsten Beta“)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@9704ac3f3`, Alembic-Kopf `b6d8f0a2c4e6`. P1c der Monitoring-Neuordnung (ADR 0004 §7, §10, §12.2;
Kevins Entscheidungen 2026-11-27 in der Spec): Der Nutzerschalter `enabled` wird eine Ausnahme „nicht prüfen“
(`skip`), die fünf Ignorierlisten werden Objekt-Ausnahmen „prüfen, nicht bewerten“ (`no_rating`) mit
fnmatch-Mustern, exakte Werte maskiert. Die Spalte `enabled` bleibt der Schalter des Systems; ein Check **läuft**,
wenn die Spalte an ist und keine geltende `skip`-Ausnahme besteht. `MonitorCheckOut` und `MonitorStateOut` behalten
ihre Form, die Listen bleiben als API-Feld (der Server übersetzt). Bis T5 legt nichts eine `skip`-Ausnahme an, bis
T11 nichts eine `no_rating`-Ausnahme außer Tests; jeder Zwischenstand verhält sich für bestehende Daten wie `main`.
Neue Quelldateien bekommen den SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license
GPL-3.0-or-later <datei>`). Postgres-Tests (`tests/test_migrations_smoke.py`) laufen ohne Postgres in
`DATABASE_URL` als test-skip; die Tasks mit Migration fahren sie zusätzlich gegen die Test-DB des Worktrees und
nennen die Summary-Zeile im Commit-Body, die PR-CI fährt sie mit Postgres. Risikopfade
(`alembic/versions/*`, `schemas.py`, `alerter.py`, `check_engine.py`, `routers/agent.py`): `security` je Task dazu.
Route-Docstrings sind OpenAPI: wer einen ändert, nimmt `tests/test_openapi_snapshot.py` ins Verify. Überschneidung
mit anderen Monitoring-Zügen (`schemas.py`, `checks.py`, Checker, Alembic-Kopf): vor jedem Push `origin/main`
hereinmergen und `scripts/dev/overlap.sh` fahren; wer zweiter merged, hängt seine Revision um. Belegte Fehler
außerhalb des Auftrags werden Roadmap-Zeilen (`roadmap.py add`).

### T1 — SMART: ausgenommene Platte im Standby macht das Ergebnis unvollständig (R-1793)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py, apps/monitoring/tests/test_smart_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ecb8841a4 2026-11-27T12:07:46+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T1.verdict.json)
Beweis: reviewer arch-monitoring-neu-p1b T5 2026-11-25 an feature/arch-monitoring-neu-p1b@4208ad2bd, Code-Lesung `apps/monitoring/app/checkers/smart.py:310` (heute `:307`: eine per `ignore_devices` ausgenommene Platte im Standby endet in `continue`, `complete` aus `:303` bleibt wahr, `apply_objects` setzt `gone_at`); der erste Test der Task zeigt es dreimal rot
Dedup-Key: bug:monitoring:smart.py:excluded-standby-flicker
HEAD: 9704ac3f3
Änderung: Zuerst der rote Test in `test_smart_checker.py`. Erster Bericht: eine ausgenommene Platte wach (Objekt mit `excluded`). Zweiter Bericht: dieselbe im Standby. Erwartet `complete` falsch und über `apply_objects` kein `gone_at`; beobachtet `complete` wahr und `gone_at` gesetzt. Der Test muss auf `HEAD` dreimal rot sein. Fix (Kevin 2026-11-27, „Ergebnis unvollständig“): Im Zweig `if device in ignore` setzt eine schlafende Platte `complete = False`. `_disk_metrics` (`:160`) bleibt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py tests/test_object_state.py
Doku: → T14

### T2 — Ausnahme-Modell: Geltung Objekt, Wirkungen skip und no_rating, „läuft“ (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/c8e0a2b4d6f8_object_exceptions.py, apps/monitoring/app/exception_scope.py, apps/monitoring/tests/test_exception_scope.py, apps/monitoring/tests/test_migrations_smoke.py, apps/monitoring/tests/test_alembic_builtin.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f2e591337 2026-11-27T12:18:33+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T2.verdict.json)
Änderung:
- **Modell** (`MonitorException`, `models.py:592`): Spalten `object_kind` (String(20)) und `object_pattern` (String(255)). `to_dict` ergänzt `objectKind`, `objectPattern` und `unstable` (wahr bei `disk` und `container`).
- **Revision** `c8e0a2b4d6f8` (SPDX, nach `b6d8f0a2c4e6`): Spalten und ein Teilindex `(check_id, object_kind, object_pattern) WHERE ended_at IS NULL`. Der Downgrade schreibt zurück und entfernt danach Index, Zeilen (`scope_kind = 'object'` oder `effect = 'skip'`) und Spalten:
  - geltende `skip` → `enabled = false` und Marke `enabled` in `overridden_fields`;
  - geltende `no_rating` → Klartext in die Liste der `config`. Die Abbildung `mount`→`ignore_mounts`, `disk`→`ignore_devices`, `container`→`ignore_containers`, `guest-backup`→`exclude_vmids` (int), `service`→`ignore` (roh) steht in der Revision selbst.
- **`exception_scope.py`:**
  - Rang `object` vor `check`; `covers` und `narrowest` für Objekte.
  - `mask` und `unmask` (`[`→`[[]`, `*`→`[*]`, `?`→`[?]`; `unmask` nur für rein maskierte Muster, sonst `None`).
  - `OBJECT_KINDS` (Art ↔ Check-Typ ↔ Listenschlüssel).
  - Ausdruck `runs` (Spalte AND NOT EXISTS geltende `skip`) samt Gegenstück je Zeile (`check_runs(db, check)`).
  - Lader `load_skips` und `load_no_rating(db, check_id)`.
- **Tests:**
  - Maskieren und Klartext als Umkehrpaar, auch mit `/dev/bus/0 [megaraid_disk_00]`.
  - `fnmatchcase` des maskierten Musters trifft nur sich.
  - `runs` mit geltender, beendeter, ausgeschalteter und befristeter Zeile.
  - Postgres: Upgrade und Downgrade mit Rückschreiben, danach wieder Upgrade.
  - Revisionskette in `test_alembic_builtin.py`, falls sie den Kopf nennt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_exception_scope.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py tests/test_models_timestamps.py
Doku: → T14

### T3 — „Läuft“ im Lauf-Pfad: Planer, Engine, Push, Checks-Router (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/scheduler.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/routers/agent.py, apps/monitoring/app/main.py, apps/monitoring/app/template_sync.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_scheduler.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_template_sync.py, apps/monitoring/tests/test_checks_crud.py, apps/monitoring/app/module_sync.py, apps/monitoring/tests/_helpers.py, apps/monitoring/tests/test_check_engine_context.py, apps/monitoring/tests/test_health.py, apps/monitoring/tests/test_status_info.py, apps/monitoring/tests/test_module_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @b30322a58 2026-11-27T12:32:01+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T3.verdict.json)
Abhängt von: T2
Änderung: Die Leser fragen „läuft“ statt der Spalte:
- `scheduler.py:142`;
- `check_engine.py:406`, `:444`, `:526`;
- `routers/agent.py:423`;
- `main.py:187`;
- die Planer-Aktionen in `template_sync.py:504`, `:515`, `:627`;
- in `routers/checks.py` `_schedule` (`:117`), `run_check_now` (`:779`) und die Summary (`:965`).

Die Schreiber in `module_sync.py` und `template_sync.py` bleiben auf der Spalte. Vorher `grep -n "\.enabled" app/` über die übrigen Treffer; jeder bekommt eine Einordnung (Leser → „läuft“, Schreiber oder Systemvergleich → Spalte, mit Kommentar). Tests: je Leser ein Fall mit geltender `skip`-Zeile (direkt angelegt), der Check läuft nicht, wird nicht gepusht und nicht gezählt. 11 Dateien, weil die Leser des Lauf-Pfads eine Invariante teilen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_scheduler.py tests/test_check_engine.py tests/test_check_engine_context.py tests/test_agent_report.py tests/test_health.py tests/test_template_sync.py tests/test_checks_crud.py tests/test_status_info.py tests/test_module_sync.py
Doku: → T14

### T4 — „Läuft“ im Melde-Pfad: Alerter, Bündel, Glocke, Verlauf, Discovery, Modulplan (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/app/alert_bundle.py, apps/monitoring/app/bell_catch_up.py, apps/monitoring/app/history.py, apps/monitoring/app/discovery.py, apps/monitoring/app/module_plan.py, apps/monitoring/tests/test_alerter.py, apps/monitoring/tests/test_alert_bundle.py, apps/monitoring/tests/test_bell_catch_up.py, apps/monitoring/tests/test_status_history.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_agent_plan.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @46eb0b053 2026-11-27T12:42:25+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T4.verdict.json)
Abhängt von: T2
Änderung: Auf „läuft“ wechseln:
- `alerter.py:445`, `:476`;
- `alert_bundle.py:164`, `:219`;
- `bell_catch_up.py:88`, `:143` (Nachholen der Entwarnung eines nicht laufenden Checks);
- `history.py:200`;
- `module_plan.py:66`.

`discovery.py:682` wählt die Spalte aus: Meint der Abgleich den Systemwert, bleibt sie, mit Kommentar; die Entscheidung kommt nach `## Entscheidungen`. Tests: je Leser ein Fall mit geltender `skip`-Zeile. 12 Dateien, weil der Melde-Pfad dieselbe Invariante teilt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter.py tests/test_alert_bundle.py tests/test_bell_catch_up.py tests/test_status_history.py tests/test_discovery_match.py tests/test_module_sync.py tests/test_agent_plan.py
Doku: → T14

### T5 — Abschalten als Ausnahme: toggle und PUT enabled (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_switch.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/models.py, apps/monitoring/tests/test_checks_crud.py, apps/monitoring/tests/test_template_sync.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_openapi_snapshot.py, apps/monitoring/openapi.snapshot.json, apps/monitoring/app/exception_scope.py, apps/monitoring/tests/test_alerter_hub.py, apps/monitoring/tests/test_central_rebaseline.py, apps/monitoring/tests/test_models_timestamps.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/test_tag_sync.py, apps/monitoring/tests/test_template_overrides.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @16e5b0636 2026-11-27T13:15:36+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T5.verdict.json)
Abhängt von: T3, T4
Änderung:
- **Neu `app/check_switch.py`** (SPDX):
  - `stop_check`: geltende `skip` anlegen (`origin = api`, Akteur aus den Headern), `remove_check`, Entwarnung wie heute (`_all_clear_disabled`, `checks.py:657`).
  - `start_check`: `skip` beenden; frischer Start (`unknown`, 0, 0, `since = now`, R-1571); `add_check`.
- **`toggle_check` (`:682`) und `update_check` mit `enabled` (`:422`):**
  - Ein laufender Check → `stop_check`; eine geltende `skip` → `start_check`.
  - Steht die Spalte aus ohne `skip` (vom System abgeschaltet), bleibt das heutige Verhalten: Spalte an, `mark_overrides` und `mark_module_overrides`.
  - `create_check` mit `enabled = false` legt die `skip` gleich mit an.
- **Ausgabe:** `MonitorCheck.to_dict` und damit `MonitorCheckOut.enabled` melden „läuft“. `run_check_now` antwortet 409 für einen nicht laufenden Check.
- **Tests:**
  - Toggle zweimal (Ausnahme mit Akteur angelegt und beendet, Planer aus und ein, frischer Start).
  - Entwarnung bei Alarm in der Glocke.
  - Ein Vorlagen-Sync dreht die `skip` nicht zurück.
  - Ein Modul-Sync mit verschwundener Instanz schaltet die Spalte, die `skip` bleibt.
  - PUT mit `enabled` antwortet wie bisher.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checks_crud.py tests/test_template_sync.py tests/test_module_sync.py tests/test_openapi_snapshot.py tests/test_alerter_hub.py tests/test_central_rebaseline.py tests/test_models_timestamps.py tests/test_response_shapes.py tests/test_tag_sync.py tests/test_template_overrides.py tests/test_exception_scope.py
Doku: → T14

### T6 — Ausnahme-API: Geltung object, Wirkungen skip und no_rating (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/exceptions.py, apps/monitoring/tests/test_exceptions_api.py, apps/monitoring/tests/test_openapi_snapshot.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/app/check_switch.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @3a834254f 2026-11-27T13:29:10+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T6.verdict.json)
Abhängt von: T5
Änderung:
- **Eingabe** (`ExceptionInput`, `schemas.py:375`; Konstanten `:370`–`:372`): `scope_kind = "object"` mit `object_kind` und `object_pattern` (1–255 Zeichen); Wirkungen `skip` und `no_rating`.
- **Prüfungen** (Validatoren, sonst 422):
  - `skip` nur mit `check` und `permanent`;
  - `no_rating` nur mit `object` und `permanent`;
  - Objektfelder nur bei `object`.
- **`_apply`** (`routers/exceptions.py:29`):
  - Die Objektart passt zum Typ des Checks (sonst 422).
  - Eine zweite geltende `skip` ergibt 409.
  - `skip` anlegen und beenden läuft über `check_switch` (Planer, Entwarnung, frischer Start).
  - `PUT` darf Geltung und Wirkung einer bestehenden Zeile nicht wechseln (422).
- **Tests:** jede Kombination (erlaubt und 422), Art ↔ Typ, 409, Anlegen und Beenden einer `skip` mit Planer-Wirkung, Akteur, `to_dict` mit den Objektfeldern.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_exceptions_api.py tests/test_openapi_snapshot.py tests/test_response_shapes.py tests/test_checks_crud.py tests/test_alerter_hub.py
Doku: → T14

### T7 — Engine mit Mustern: Mounts, Dienste, Prognose (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/checkers/context.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/app/checkers/forecast.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_check_engine_context.py, apps/monitoring/tests/test_agent_resources_checker.py, apps/monitoring/tests/test_service_process_checker.py, apps/monitoring/tests/test_checker_forecast.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/_helpers.py, apps/monitoring/app/models.py, apps/monitoring/app/objects.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @0f703842b 2026-11-27T13:42:02+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T7.verdict.json)
Abhängt von: T2
Änderung:
- **Engine:** `_load_run` (`check_engine.py:521`) lädt die geltenden `no_rating`-Ausnahmen des Checks. Sie gibt dem Checker eine Musterliste `(muster, quelle)`:
  - Einträge der `config` maskiert (Dienste roh) mit dem Namen der Einstellung als Quelle;
  - Ausnahmen mit ihrer ID als Quelle.
- **Kontext:** `_load_disk_rules` (`:433`, Liste `:452`–`:469`) und `DiskRules.ignore_mounts` (`context.py:40`) werden Musterlisten.
- **Abgleich per `fnmatchcase`** an diesen Stellen:
  - `agent.py`: Mounts `:445` und `:591`, Dienste `_is_ignored` (`:850`);
  - `forecast.py:93`.

  `excluded_object` (`agent.py:153`) trägt die Quelle (passt in `excluded`, String(40)).
- **Tests:**
  - Mount und Dienst mit `[`, `*` und `?` im Namen, ausgenommen über die `config` und über die Ausnahme.
  - Ein maskierter Eintrag blendet keinen Nachbarn aus.
  - Ein Dienst-Muster wirkt wie heute.
  - Die Prognose lässt ausgenommene Mounts aus.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine.py tests/test_check_engine_context.py tests/test_agent_resources_checker.py tests/test_service_process_checker.py tests/test_checker_forecast.py
Doku: → T14

### T8 — SMART, Docker und Proxmox-Backup mit Mustern (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py, apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_smart_checker.py, apps/monitoring/tests/test_plugin_checkers.py, apps/monitoring/app/checkers/agent.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @00a07c8f0 2026-11-27T13:46:49+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T8.verdict.json)
Abhängt von: T1, T7
Änderung:
- **SMART:** `ignore_devices` (`smart.py:289`, `:307`, `_disk_metrics` `:160`).
- **Proxmox-Backup:** `exclude_vmids` (`plugins.py:170`, `:194`); VMID als `str` gegen das Muster.
- **Docker:** `ignore_containers` (`plugins.py:643`, `:671`).

Alle drei gleichen gegen die Musterliste aus T7 ab und tragen die Quelle in `excluded`; der Fix aus T1 bleibt. Tests: Gerät `/dev/bus/0 [megaraid_disk_00]`, Container mit `*`, VMID `1` trifft nicht `10`, Ausnahme statt `config`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py tests/test_plugin_checkers.py
Doku: → T14

### T9 — Objekt-API: Objekt-Ausnahme und nicht geprüfter Check (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/objects.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_objects_api.py, apps/monitoring/tests/test_openapi_snapshot.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/app/exception_scope.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f439ae431 2026-11-27T13:52:48+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T9.verdict.json)
Abhängt von: T6, T8
Änderung:
- **Objekt-Ausnahme:** `_exception` (`routers/objects.py:38`) löst eine `excluded`-Quelle, die eine Ausnahme-ID ist, zur Ausnahme auf: `{source: exception, effect: no_rating, scopeKind: object, id, reason, unstable}`. Eine Einstellung bleibt wie in P1b.
- **Nicht geprüfter Check:** Gilt für den Check eine `skip` (`list_objects` `:75`, `:115`), meldet jedes Objekt `not_collected` mit `{effect: skip, scopeKind: check}` (§12.2).
- **Bleibt:** Die Sortierung (ausgenommene zuletzt) und das Schema der Antwort (nur neue Werte); `no_notify` wie bisher.
- **Tests:** Objekt per Ausnahme, Objekt per Einstellung, Check mit `skip`, beendete Ausnahme.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_objects_api.py tests/test_openapi_snapshot.py
Doku: → T14

### T10 — Listen als API-Feld: lesen zusammengesetzt, schreiben als Ausnahmen (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/exception_scope.py, apps/monitoring/app/template_sync.py, apps/monitoring/tests/test_checks_crud.py, apps/monitoring/tests/test_template_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @29b5db406 2026-11-27T14:12:37+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T10.verdict.json)
Abhängt von: T6
Änderung:
- **Lesen:** `GET /checks` (Liste und einzeln) setzt jede der fünf Listen aus `config` ∪ geltenden Ausnahmen der Art zusammen. Maskierte Muster erscheinen als Klartext, VMIDs als int, Dienste roh. Ein Muster ohne Klartext erscheint roh.
- **Schreiben:** `PUT` und `POST` mit einer Liste: Einträge, die die Vorlage vorgibt, bleiben in der `config`; andere werden Ausnahmen (`origin = api`, Akteur); geltende Ausnahmen der Art, die nicht in der Liste stehen, enden. Ohne Liste im Body bleibt alles.
- **Überschreibungen:** `mark_overrides` (`template_sync.py:190`) läuft auf der gespeicherten `config`. Ein eigener Eintrag macht die `config` damit nicht mehr zur Überschreibung.
- **Tests:**
  - PUT mit Liste und gleiche Liste zurück.
  - Entfernen beendet die Ausnahme.
  - Vorlagen-Eintrag bleibt in der `config`.
  - Eintrag mit `[`.
  - Alter Desktop (`ignore` mit Rohnamen) liest dasselbe zurück.
  - Ein Vorlagen-Sync danach bringt neue Schwellen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checks_crud.py tests/test_template_sync.py
Doku: → T14

### T11 — Datenmigration mit Trockenlauf und Schwellen-Rückfall (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/exception_migration.py, apps/monitoring/app/main.py, apps/monitoring/tests/test_exception_migration.py, apps/monitoring/tests/test_migrations_smoke.py, apps/monitoring/alembic/env.py, apps/monitoring/app/exception_scope.py, apps/monitoring/app/routers/checks.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @95764b451 2026-11-27T14:42:04+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T11.verdict.json)
Abhängt von: T5, T10
Änderung:
- **Neu `app/exception_migration.py`** (SPDX), `plan(db)` und `apply(db, plan)`:
  - **Nutzer-Abschaltung → `skip`.** Das gilt für einen manuellen Check mit `enabled = false` und für einen Vorlagen- oder Modul-Check mit `enabled = false` und Marke `enabled`. Die Spalte geht an, und die Marke fällt weg. Ist die Modul-Instanz verschwunden, bleibt die Spalte aus. Eine Abschaltung durch das System bleibt.
  - **Listen:** Jeder Listeneintrag außerhalb der Vorlage wird eine `no_rating`-Ausnahme (`origin = migration`, ohne Akteur). Die `config` behält die Vorlagen-Einträge, der Schlüssel bleibt.
  - **Schwellen-Rückfall:** Gleicht die `config` danach der Vorlage, fällt die Marke `config`.
  - **Idempotenz:** IDs per `uuid5` aus Check, Art und Muster.
  - **Einmal-Marke** `migration:exceptions-p1c` in `monitor_seed_state`.
- **Startschritt** in `lifespan` (`main.py:39`) nach `record_override_baseline`, vor `reconcile_builtin_templates`, wie die Nachbarn mit try/rollback/log.
- **`python -m app.exception_migration --dry-run [--json]`:** Er fährt `alembic upgrade head`, `plan` und `apply` in einer Transaktion. Danach gibt er den Diff-Bericht aus und rollt zurück. Der Bericht nennt je Check `skip`, Ausnahmen (Muster, instabil), `config`, Marken und beim Rückfall die alten und neuen Schwellen. Vorher die Postgres-Doku zu transaktionalem DDL nachlesen (Spec, nicht verifiziert).
- **Tests:**
  - Je Quellfall einer.
  - Zweiter Lauf ändert nichts.
  - Systemabschaltung bleibt.
  - Rückfall mit Bericht.
  - Postgres: Trockenlauf auf Kopf minus eins lässt Schema und Daten unverändert.
  - Startschritt läuft einmal.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_exception_migration.py tests/test_migrations_smoke.py tests/test_seed.py tests/test_checks_crud.py tests/test_template_sync.py tests/test_alembic_builtin.py
Doku: → T14

### T12 — Desktop: ignoreService maskiert den Dienstnamen (R-1637, R-1521)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/lib/stores/monitoring.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @18d4d2f94 2026-11-27T14:53:40+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T12.verdict.json)
Änderung:
- `ignoreService` (`monitoring.ts:489`) maskiert `[`, `*` und `?` im Namen, bevor er in `ignore` geht. Das passt zu den Dienst-Mustern des Servers.
- Tests:
  - Name mit `[` wird maskiert;
  - ein gescheiterter `PUT` lässt den Check unverändert und meldet den Fehler;
  - die Antwort des `PUT` ersetzt den Check im Store.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/monitoring.test.ts
Doku: → T14

### T13 — Abnahme im Upgrade-Pfad: Trockenlauf, Migration, Rückweg (R-1637)  [x]
Komponente: scripts · Dateien: scripts/tests/upgrade_path_test.sh, scripts/tests/upgrade_exceptions.py
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @940ff1b33 2026-11-27T16:35:46+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T13.verdict.json)
Abhängt von: T11
Änderung: `upgrade_path_test.sh` bekommt neue Schritte.
- **Auf dem letzten Release:** Über die Admin-API anlegen:
  - einen Agent-Check mit `ignore_mounts` und Dienst-`ignore` (Muster und Name mit `[`);
  - SMART mit `ignore_devices`;
  - Docker mit `ignore_containers`;
  - Proxmox-Backup mit `exclude_vmids`;
  - einen manuellen abgeschalteten Check;
  - einen Vorlagen-Check mit eigenem Eintrag.
- **Nach dem Backup:**
  - Trockenlauf mit dem Image des Checkouts; Dump davor und danach gleich.
  - Update und Migration: die Ausnahmen da, die Listen über `GET /checks` unverändert, der Check weiter aus.
  - Rückweg über `restore.sh` mit den Images des Releases: der Dump wie vor dem Update.

PASS/FAIL wie die bestehenden Schritte, shellcheck-sauber. Der Lauf auf der Pool-VM steht in `Heavy:`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T14

### T14 — Doku DE+EN und CHANGELOG-Fragment (R-1637, R-1793, R-1521)  [x]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/arch-monitoring-neu-p1c.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7d62e043c 2026-11-27T16:38:18+01:00
Review: am Ende (nur Doku, Branch-Review)
Task-Review: am Ende
Änderung:
- **Entwickler-Doku:**
  - das Ausnahme-Modell mit Geltung Objekt und den Wirkungen „nicht prüfen“ und „prüfen, nicht bewerten“;
  - „läuft“;
  - die Übersetzung der Listen;
  - Startschritt und Trockenlauf.
- **API-Referenz:** `ExceptionInput`, Objekt-API, `enabled` effektiv.
- **Admin-Doku:**
  - Abschalten und Ignorieren sind Ausnahmen mit Spur;
  - Muster und Maskierung;
  - Schwellen-Rückfall nach dem Update;
  - der Trockenlauf vor dem Update (`betrieb.html`/`operations.html`).
- **Fragment** (umlautfrei): Added, Changed (Schwellen-Rückfall), Fixed (R-1793, R-1521).
- Lokal zusätzlich `doc-smoke --env` fahren, wie die PR-CI.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/monitoring.html, docs/developer/api-reference.html, docs/admin/monitoring.html, docs/admin/betrieb.html je DE+EN · changelog.d/arch-monitoring-neu-p1c.md

### T15 — Ein umgezogener Check nimmt seine Ausnahmen mit (R-1637)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_checks_crud.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @52cb13ba6 2026-11-27T17:05:13+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1c/T15.verdict.json)
Beweis: Abschlussprüfung `branch.verdict.json` @e0d3a4a1d. Probe-Test: `agent_resources` auf srv-a mit `ignore_mounts` und `enabled: false`, PUT `server_id` srv-b, `cleanup_server(srv-a)`, danach zeigt GET `enabled: true`, `ignore_mounts: []`.
Änderung:
- `update_check` (`routers/checks.py:594`) zieht einen Check über `server_id` auf einen anderen Server um.
- Die `server_id` seiner Ausnahmen zieht jetzt mit: Geltung `check` und `object`, beendete eingeschlossen.
- Bisher blieben sie am alten Server, und `cleanup_server` des alten Servers (`server_cleanup.py:109`) nahm sie mit. Der Check lief dann wieder und verlor seine Ignorier-Einträge.
- Vor P1c zogen Schalter und Listen als Spalte und `config` mit.
- Test (erst rot):
  - Schalter und Liste bleiben nach dem Aufräumen des alten Servers;
  - `/exceptions?server_id=` nennt den neuen Server.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checks_crud.py
Doku: keine (die Doku beschreibt das Umziehen eines Checks nicht; das Verhalten ist wieder das von vor P1c)

### T16 — Nits der Abschlussprüfung: „gone“ meldet nur, was es abschaltet; Fragment nennt den Umzug (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py, changelog.d/arch-monitoring-neu-p1c.md
Beweis: Nit der Abschlussprüfung `branch.verdict.json` @e0d3a4a1d (`module_sync._adopt`); Hinweis der Task-Prüfung T15 (`no_notify` blieb beim Umzug schon auf `main` am alten Server).
Änderung:
- `_adopt` (`module_sync.py:607`), Fall „gone“ und Tag-Wechsel: `disabled` und die `remove`-Aktion nur für einen Check, der lief (`check_runs`). So macht es schon der Weg „new“ mit `enabled`.
- Bisher meldete „gone“ einen Check, den eine Ausnahme `skip` des Admins schon anhielt, als abgeschaltet. Die Spalte zieht weiter auf aus.
- Test: „gone“ mit einem angehaltenen Check meldet nur den laufenden.
- Fragment unter Fixed: Ein auf einen anderen Server umgezogener Check behält seine Ausnahmen, auch „nicht benachrichtigen“, wenn der alte Server gelöscht wird (T15).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: changelog.d/arch-monitoring-neu-p1c.md

## Entscheidungen
- Kevin 2026-11-27 (Gate, R-1637): Ignorierlisten als Muster-Ausnahme. Jeder Eintrag der fünf Listen wird eine Objekt-Ausnahme mit fnmatch-Muster; exakte Werte werden maskiert, Dienst-Einträge bleiben Muster; der Desktop maskiert in `ignoreService` (R-1521).
- Kevin 2026-11-27 (Gate, R-1637): Schwellen-Rückfall auf die Vorlage. Unterscheidet sich die `config` eines Vorlagen-Checks nur in der Ignorierliste, fällt die Marke `config`; der Trockenlauf nennt jeden Fall mit alten und neuen Werten.
- Kevin 2026-11-27 (Gate, R-1637): Datenkopie vor der nächsten Beta. Gemergt wird nach der synthetischen Abnahme auf einer Pool-VM (T13); Kevins Backup kommt über eine eigene `blockiert`-Zeile, Diff-Bericht nur unter `tasks/private/`.
- Kevin 2026-11-27 (Gate, R-1793): Ergebnis unvollständig. Schläft eine ausgenommene Platte, setzt `smart.py` `complete = False`; der rote Test kommt zuerst (T1).
- Session 2026-11-27: `skip` und `no_rating` in P1c nur dauerhaft. Die Migrationsziele des ADR (§10) sind dauerhaft; andere Dauern kommen mit dem Dialog in P2, additiv.
- Session 2026-11-27: Ein per Ausnahme ausgenommenes Objekt bleibt `not_collected` mit Marke, wie in P1b; Kennzahlen für ausgenommene Objekte erst, wenn P2 sie zeigt.
- Session 2026-11-27: „Läuft“ als Ausdruck über Spalte und Ausnahme, keine gespiegelte Spalte. Die Systemschreiber bleiben auf der Spalte, der Nutzer schreibt nur Ausnahmen.
- Session 2026-11-27: Die Datenmigration ist ein Startschritt mit Einmal-Marke, keine SQL-Revision. Sie braucht die aufgelöste Vorlage (`resolve_template_check`); die Revision bleibt rein strukturell plus Rückschreiben im Downgrade.
- Session 2026-11-27 T2: Das Downgrade setzt an Vorlagen- und Modul-Checks die Marke `config`, wenn es ihre Liste verlängert, und `enabled`, wenn es sie abschaltet (wie `mark_overrides`); sonst schriebe der nächste Vorlagen-Sync die zurückgeschriebenen Einträge über. Eigene Checks tragen keine Marken.
- Session 2026-11-27 T2: Das Downgrade löscht die Marke `migration:exceptions-p1c` aus `monitor_seed_state`, damit ein späteres Upgrade die Listen erneut übernimmt. Ein Muster auf einer exakten Liste (kein maskierter Name) geht wörtlich zurück, damit der Admin es sieht; nur Gast-IDs aus Ziffern werden wieder Zahlen.
- Session 2026-11-27 T2: Der bestehende Migrationstest von R-1636 fragt das ORM erst nach `upgrade head` ab: das Modell ist das des Kopfs, auf `f4b6d8a0c2e4` fehlen die neuen Spalten. Der Rohzeilen-Vergleich auf `f4b6d8a0c2e4` bleibt.
- Session 2026-11-27 T2: Die Migrationstests laufen lokal nur mit Postgres in `DATABASE_URL` (Verify überspringt sie); gegen die Test-DB des Worktrees `test_migrations_smoke.py`, `test_alembic_builtin.py`, `test_exception_scope.py`, `test_models_timestamps.py`: 91 passed, die PR-CI fährt sie mit Postgres.
- Session 2026-11-27 T3: Die Planer-Aktion beim Übernehmen in `module_sync.py` (`_adopt`, nach `row.silent = False`) ist ein Leser und fragt „läuft“; das Verify nimmt dafür `test_module_sync.py` auf, dazu `test_check_engine_context.py`, `test_health.py` und `test_status_info.py`, wo die Fälle von Partner, Plattenregeln, Planer-Verzug und Summary schon stehen.
- Session 2026-11-27 T3: Einordnung der übrigen `.enabled`-Treffer. `sync_catalog` (`dropped`/`changed`) fragt „beobachtet“ wie `discovery.py:682` und geht nach T4. Schreiber, die auf der Spalte bleiben: `module_sync.py` „gone“ und Tag-Wechsel (ihr `remove` ist für einen übersprungenen Check folgenlos), die Anlage neuer Zeilen, `routers/checks.py` Anlage, Update und Toggle (T5). `to_dict` geht nach T5. `alerter`, `alert_bundle`, `template_sync` (Regeln), `routers/findings.py` (`AdoptResult`) und die Wartungs-, Ausnahme- und Regel-Router meinen andere Tabellen.
- Session 2026-11-27 T3 → T5: Der Planer-Verzug in `main.py` zählt ab `updated_at`; endet ein Skip, setzt T5 `updated_at` des Checks neu, sonst zählt der Verzug ab dem letzten Lauf vor dem Skip.
- Session 2026-11-27 T4: `discovery._update_findings` (`watched`) und `sync_catalog` (`dropped`/`changed`) fragen „läuft“ (Spalte an, kein Skip aus `load_skips`). Bisher schrieb das Abschalten des Admins die Spalte, ab T5 einen Skip: Eine Instanz, deren Checks der Admin abgeschaltet hat, beobachtet weiter nichts, und ein abgeschalteter Check öffnet sie beim Katalog-Update nicht wieder. Das Abschalten beim Übernehmen von „gone“ schreibt weiter die Spalte.
- Session 2026-11-27 T4: `lag_target` bekommt `running` vom Aufrufer (`check_runs` in `_catch_up_one`) und bleibt ohne Datenbank. Die Entwarnung eines übersprungenen Checks heißt weiter „check disabled“, weil das Abschalten ab T5 ein Skip ist. Das Verify nimmt `test_agent_plan.py` auf, wo der Fall von `module_plan._probes` steht.
- Session 2026-11-27 T5: `MonitorCheck.to_dict` nimmt `running` als Pflicht-Schlüsselwort: die Liste fragt `load_skips` einmal für alle Zeilen, einzelne Routen fragen `check_runs`. So kann kein Aufrufer die Spalte allein als `enabled` melden; die direkten Aufrufer in den Tests (`test_models_timestamps`, `test_response_shapes`, `test_central_rebaseline`) übergeben es.
- Session 2026-11-27 T5: `app/check_switch.py` ändert nur die Datenbank (Skip, Zustand, Glocken-Slot); die Route committet und stellt danach den Planer ein, die Entwarnung geht als Hintergrund-Aufgabe nach der Antwort (R-1660). `send_all_clear` ersetzt `_all_clear_disabled` aus `checks.py` unverändert.
- Session 2026-11-27 T5: Das Abschalten des Admins setzt die Marke `enabled` nicht mehr (Spec: „Die Marke fällt weg“). Die Tests, die sie prüften, behalten ihren Namen und prüfen jetzt Skip und leere Marken (`test_toggle_marks_enabled_and_toggling_back_clears_it`, `test_the_api_marks_the_admins_switch_and_rules_on_a_module_check`, `test_sync_keeps_a_check_the_user_disabled_disabled`); `test_a_field_the_stored_definition_leaves_out_compares_with_its_default` prüft das ausgelassene Feld über `consecutive_oks` statt über `enabled`.
- Session 2026-11-27 T5: PUT mit `enabled` schaltet nur, wenn der Wert von „läuft“ abweicht; der Editor schickt alle Felder zurück, ein zweites Aus legt keine zweite Skip an. `enabled: null` lässt den Schalter, wie ein fehlender Schlüssel (bisher schrieb es NULL in die Spalte). Eine Altzeile mit NULL in der Spalte meldet `enabled: false` (sie läuft nicht).
- Session 2026-11-27 T5: `create_check` mit `enabled = false` legt die Spalte an und die Skip mit dem Akteur dazu; eine Entwarnung entfällt (ein neuer Check hat keinen Alarm). `reset_check` beendet die Skips: vor R-1637 brachte Zurücksetzen das `enabled` der Vorlage zurück, das sichtbare Ergebnis bleibt gleich.
- Session 2026-11-27 T5: `end_skips` setzt `updated_at` des Checks (der Planer-Verzug aus T3 → T5). `start_check` auf einer vom System abgeschalteten Spalte (ohne Skip) schaltet sie an und markiert sie wie bisher; PUT `enabled: false` auf so einem Check legt keine Skip an, er läuft ja nicht.
- Session 2026-11-27 T6: Skip und no_rating haben je einen Geltungsbereich (Skip: `check`, no_rating: `object`), beide nur `permanent`; `object` nur mit no_rating, weil die Engine auf Objekten nichts anderes kennt. Eine andere Kombination ist 422 wie in R-1636 (keine Zeile, die nichts tut). Ob der Check existiert und Objekte der Art hat (`OBJECT_KINDS[kind].check_type`), prüft der Router, weil er die Datenbank braucht.
- Session 2026-11-27 T6: Eine zweite stehende Skip auf demselben Check ist 409 (eine abgeschaltete stört nicht, bis sie angeschaltet wird). Das ist eine Bedienregel, keine DB-Invariante: zwei Skips wirken wie eine, `load_skips` nimmt die kleinere id.
- Session 2026-11-27 T6: PUT lässt den Effekt stehen, und Skip und no_rating behalten ihren Check (422); no_notify darf den Geltungsbereich weiter wechseln (R-1636, `test_a_new_scope_clears_the_old_one`). So bleibt die Spur einer Skip an einem Check, und der Router muss beim Umwidmen nicht zwei Checks schalten.
- Session 2026-11-27 T6: `check_switch` teilt `stopped` (Entwarnung) und `started` (frischer Zustand, `updated_at` für den Planer-Verzug) aus `stop_check`/`start_check` heraus; `/exceptions` vergleicht „läuft“ vor und nach der Änderung einer Skip und ruft das passende auf, der Planer folgt nach dem Commit. `_schedule` bleibt in `routers/checks.py` (die Tests patchen dort `add_check`), `routers/exceptions.py` hat dieselben drei Zeilen in `_after_commit`.
- Session 2026-11-27 T7: Die Muster lädt der Push-Pfad (`routers/agent.py` `_evaluate_push_check`), nicht `_load_run`: die fünf Typen mit Listen sind push-only, `_load_run` gibt für sie `None` zurück. Er setzt `config["_no_rating"]` für jeden der fünf Typen, auch leer, und überschreibt damit einen gespeicherten Schlüssel; `_load_disk_rules` lädt die Ausnahmen des resources-Checks für die Prognose selbst. Trifft ein Objekt Einstellung und Ausnahme, nennt `excluded` die Einstellung: Sie hält es auch nach dem Ende der Ausnahme draußen. Grund „Excluded by exception“, die ID löst T9 auf.
- Session 2026-11-27 T8: `exclude_vmids` gleicht die VMID dezimal gegen `mask(str(vmid))` ab, nur für Zahlen (`check_configs` nimmt auch Strings an, die schon vorher keine VMID trafen; das bleibt so, ein Test hält es fest). Ein Gast ohne VMID wird von keinem Muster getroffen, auch nicht von `*`. SMART vergleicht den Gerätepfad, auch in `_disk_metrics` (keine Reihe für eine ausgenommene Platte); Docker den Namen. Der Nit aus der T7-Prüfung (Umbruch im Docstring von `_resource_objects`) ist hier mit behoben.
- Session 2026-11-27 T9: `ObjectExceptionOut` bekommt das Feld `unstable` (Spec Ziel 6; nur hinzugefügt, null außer bei einer Objekt-Ausnahme), sonst nur neue Werte. Reihenfolge: `skip` des Checks vor der Marke, die Marke (Einstellung oder Ausnahme-ID) vor der engsten `no_notify`. Eine ID in `excluded` wird ohne Blick auf den Stand aufgelöst: Das Beenden einer `no_rating` startet keinen Lauf, das Objekt nennt sie bis zum nächsten Lauf; ist die Zeile nach der Aufbewahrung gelöscht, steht die Marke allein da. Ein Objekt eines Checks mit `skip` zeigt statt des eingefrorenen Stands `not_collected`, Grund `Not checked by exception`, `badSince` null, `since` spätestens ab der Ausnahme, und sortiert mit den ausgenommenen ans Ende (ADR §12.2); dafür ist `skipped` in `exception_scope` ein eigener Ausdruck, aus dem `runs` gebildet wird.
- Session 2026-11-27 T10: Die zusammengesetzte Liste ist sortiert (Zahlen nach Wert vor Text), weil die Reihenfolge der Ausnahmen nichts sagt (`created_at` ist in einer Transaktion gleich, die IDs sind zufällig). Ein PUT, dessen `config` der gelesenen gleicht, schreibt die rohe gespeicherte `config` zurück und legt nichts an. Ein Eintrag gilt als dieselbe Ausnahme, wenn eine geltende so liest (`list_entry`); ein Glob aus der Ausnahmen-API erscheint roh und bleibt beim Rundlauf stehen. Was keine Ausnahme aufnimmt, bleibt in der `config`: VMID als String, ein Muster über 255 Zeichen (Spalte `object_pattern`). Die gespeicherte Liste ist die der Vorlage, solange die eigenen Einträge sie nur ergänzen; fehlt der Schlüssel in der Vorlage und bleibt nichts, fällt er weg; erst ein fehlender Vorlagen-Eintrag macht `config` zur Überschreibung. `reset` beendet alle `no_rating`-Objekt-Ausnahmen des Checks mit dem Akteur, jeder Art. Nach einem Typwechsel bleiben Ausnahmen der alten Art stehen und wirken nicht (der neue Typ fragt eine andere Art). Module legen keine Checks dieser fünf Typen an, `mark_module_overrides` bleibt unberührt; `template_sync.py` bleibt unverändert, weil `mark_overrides` die gespeicherte `config` bekommt.
- Session 2026-11-27 T11: Die Migration teilt die Liste mit der API (`split_list` in `exception_scope`, aus `_store_list` herausgezogen): eigene Einträge werden Ausnahmen, Vorlagen-Einträge bleiben, fehlt der Schlüssel in der Vorlage und bleibt nichts, fällt er weg (wie T10; die Ledger-Zeile „der Schlüssel bleibt“ gilt für Vorlagen mit dem Schlüssel und für manuelle Checks). Ein Eintrag, den keine Ausnahme aufnimmt (VMID als String), bleibt in der `config`. Rückfall nur, wo die Liste den Unterschied machte und nichts von ihr übrig bleibt, `check_type` nicht markiert ist und jeder andere Schlüssel den Wert der Vorlage hat (ein Schlüssel, den nur die Vorlage hat, zählt als ihrer); dann wird die `config` direkt die der Vorlage, weil kein Sync gleich folgt (`reconcile_builtin_templates` wirkt nur bei neuer Version). Ein eigener Wert hält die Marke, der Bericht nennt seine Schlüssel (`own_values`). Die Spalte geht nach der Skip auf den Wert des Systems: Vorlagen-`enabled`, beim Modul-Check an, außer die Instanz ist als `gone` übernommen. Der Trockenlauf reicht seine Verbindung an Alembic (`config.attributes["connection"]`, Cookbook „Sharing a Connection“); `env.py` nimmt sie ohne Advisory-Lock und ohne Commit (Alembic 1.20.1 öffnet in einer laufenden Transaktion keine eigene). Die Session des Trockenlaufs nutzt `join_transaction_mode="create_savepoint"`, damit der Commit von `record_override_baseline` nur einen Savepoint löst; der Trockenlauf nimmt wie der Start erst die Baseline, dann den Plan. `SET LOCAL lock_timeout = '5s'`: hält der laufende Dienst eine Sperre länger, scheitert der Trockenlauf, statt den Dienst hinter sich warten zu lassen; die Sperren des Upgrades (ACCESS EXCLUSIVE) hält er bis zum Rollback. Kein eigener Advisory-Lock und keine Dialekt-Prüfung (nur Postgres). Im Container braucht der Trockenlauf `--entrypoint python`, sonst migriert der Entrypoint vorher echt (Doku T14). Das `Verify:` nimmt `test_checks_crud.py` und `test_template_sync.py` auf, weil `_store_list` jetzt über `split_list` läuft.
- Session 2026-11-27 T11 (Prüfer Runde 1): `alembic/env.py` teilt nur eine `sqlalchemy.engine.Connection` aus `config.attributes["connection"]`; pytest-alembic legt unter demselben Schlüssel ein Engine ab, das den bisherigen Weg (eigene Engine, Advisory-Lock) nimmt. `tests/test_alembic_builtin.py` steht dafür im Verify. Wirft `resolve_template_check` (unlesbare Definitionen der Vorlage), bleibt der Check unverändert und die Migration läuft für die übrigen weiter, wie die Override-Baseline.
- Session 2026-11-27 T13: Der Vergleich „Dump davor und danach gleich“ nimmt das Schema der Monitoring-DB und die Zeilen der Konfigurations-Tabellen (`monitor_checks`, Vorlagen samt Zuweisungen, Seed-Stand, Grabsteine, Alarmregeln, Wartung, `alembic_version`), nicht die Laufzeit-Tabellen, in die der laufende Dienst des Releases zwischen zwei Dumps schreibt; `upgrade_exceptions.py normalize` sortiert die Zeilen. Dass der Dump die Seeds überhaupt enthält, prüft der Schritt eigens (alle neun IDs), sonst wären zwei leere Dumps auch gleich.
- Session 2026-11-27 T13: Backup mit dem `scripts/backup.sh` des Releases (von GitHub, sonst aus dem lokalen Clone), Rückweg mit dem `scripts/restore.sh` des Checkouts auf den Images des Releases, beide in einem eigenen Installationsverzeichnis mit den Compose-Dateien und der `.env` des Stacks und leerer Umgebung (`env -i`), wie auf einem Host: Das `restore.sh` des Releases kann über das neuere Schema nicht zurückspielen (R-1846). Der Trockenlauf läuft gegen die laufende Instanz des Releases, mit `--entrypoint python` (der Entrypoint migrierte sonst echt) und `run --no-deps`; `lock_timeout` hält ihn kurz. Der zurückgespielte Stack geht vor Schritt 4 herunter, weil `restore.sh` auch frps auf 7000/7443 startet; das Installationsverzeichnis räumt beim EXIT ein Helfer-Container des Releases (die Container schreiben dort als root). Der Helfer wiederholt nur GETs auf 502/503: Der Proxy des Servers meldet 502 auch nach einem gesendeten Request, ein wiederholter POST legte einen zweiten Check an; der Seed beginnt deshalb mit einem GET.
