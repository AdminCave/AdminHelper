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

### T2 — Ausnahme-Modell: Geltung Objekt, Wirkungen skip und no_rating, „läuft“ (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/c8e0a2b4d6f8_object_exceptions.py, apps/monitoring/app/exception_scope.py, apps/monitoring/tests/test_exception_scope.py, apps/monitoring/tests/test_migrations_smoke.py, apps/monitoring/tests/test_alembic_builtin.py
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

### T3 — „Läuft“ im Lauf-Pfad: Planer, Engine, Push, Checks-Router (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/scheduler.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/routers/agent.py, apps/monitoring/app/main.py, apps/monitoring/app/template_sync.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_scheduler.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_template_sync.py, apps/monitoring/tests/test_checks_crud.py
Abhängt von: T2
Änderung: Die Leser fragen „läuft“ statt der Spalte:
- `scheduler.py:142`;
- `check_engine.py:406`, `:444`, `:526`;
- `routers/agent.py:423`;
- `main.py:187`;
- die Planer-Aktionen in `template_sync.py:504`, `:515`, `:627`;
- in `routers/checks.py` `_schedule` (`:117`), `run_check_now` (`:779`) und die Summary (`:965`).

Die Schreiber in `module_sync.py` und `template_sync.py` bleiben auf der Spalte. Vorher `grep -n "\.enabled" app/` über die übrigen Treffer; jeder bekommt eine Einordnung (Leser → „läuft“, Schreiber oder Systemvergleich → Spalte, mit Kommentar). Tests: je Leser ein Fall mit geltender `skip`-Zeile (direkt angelegt), der Check läuft nicht, wird nicht gepusht und nicht gezählt. 11 Dateien, weil die Leser des Lauf-Pfads eine Invariante teilen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_scheduler.py tests/test_check_engine.py tests/test_agent_report.py tests/test_template_sync.py tests/test_checks_crud.py
Doku: → T14

### T4 — „Läuft“ im Melde-Pfad: Alerter, Bündel, Glocke, Verlauf, Discovery, Modulplan (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/app/alert_bundle.py, apps/monitoring/app/bell_catch_up.py, apps/monitoring/app/history.py, apps/monitoring/app/discovery.py, apps/monitoring/app/module_plan.py, apps/monitoring/tests/test_alerter.py, apps/monitoring/tests/test_alert_bundle.py, apps/monitoring/tests/test_bell_catch_up.py, apps/monitoring/tests/test_status_history.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_module_sync.py
Abhängt von: T2
Änderung: Auf „läuft“ wechseln:
- `alerter.py:445`, `:476`;
- `alert_bundle.py:164`, `:219`;
- `bell_catch_up.py:88`, `:143` (Nachholen der Entwarnung eines nicht laufenden Checks);
- `history.py:200`;
- `module_plan.py:66`.

`discovery.py:682` wählt die Spalte aus: Meint der Abgleich den Systemwert, bleibt sie, mit Kommentar; die Entscheidung kommt nach `## Entscheidungen`. Tests: je Leser ein Fall mit geltender `skip`-Zeile. 12 Dateien, weil der Melde-Pfad dieselbe Invariante teilt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter.py tests/test_alert_bundle.py tests/test_bell_catch_up.py tests/test_status_history.py tests/test_discovery_match.py tests/test_module_sync.py
Doku: → T14

### T5 — Abschalten als Ausnahme: toggle und PUT enabled (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/check_switch.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/models.py, apps/monitoring/tests/test_checks_crud.py, apps/monitoring/tests/test_template_sync.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_openapi_snapshot.py, apps/monitoring/openapi.snapshot.json
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
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checks_crud.py tests/test_template_sync.py tests/test_module_sync.py tests/test_openapi_snapshot.py
Doku: → T14

### T6 — Ausnahme-API: Geltung object, Wirkungen skip und no_rating (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/exceptions.py, apps/monitoring/tests/test_exceptions_api.py, apps/monitoring/tests/test_openapi_snapshot.py, apps/monitoring/openapi.snapshot.json, apps/monitoring/tests/test_response_shapes.py
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
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_exceptions_api.py tests/test_openapi_snapshot.py tests/test_response_shapes.py
Doku: → T14

### T7 — Engine mit Mustern: Mounts, Dienste, Prognose (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/checkers/context.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/app/checkers/forecast.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_check_engine_context.py, apps/monitoring/tests/test_agent_resources_checker.py, apps/monitoring/tests/test_service_process_checker.py, apps/monitoring/tests/test_checker_forecast.py
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

### T8 — SMART, Docker und Proxmox-Backup mit Mustern (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py, apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_smart_checker.py, apps/monitoring/tests/test_plugin_checkers.py
Abhängt von: T1, T7
Änderung:
- **SMART:** `ignore_devices` (`smart.py:289`, `:307`, `_disk_metrics` `:160`).
- **Proxmox-Backup:** `exclude_vmids` (`plugins.py:170`, `:194`); VMID als `str` gegen das Muster.
- **Docker:** `ignore_containers` (`plugins.py:643`, `:671`).

Alle drei gleichen gegen die Musterliste aus T7 ab und tragen die Quelle in `excluded`; der Fix aus T1 bleibt. Tests: Gerät `/dev/bus/0 [megaraid_disk_00]`, Container mit `*`, VMID `1` trifft nicht `10`, Ausnahme statt `config`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py tests/test_plugin_checkers.py
Doku: → T14

### T9 — Objekt-API: Objekt-Ausnahme und nicht geprüfter Check (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/objects.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_objects_api.py, apps/monitoring/tests/test_openapi_snapshot.py, apps/monitoring/openapi.snapshot.json
Abhängt von: T6, T8
Änderung:
- **Objekt-Ausnahme:** `_exception` (`routers/objects.py:38`) löst eine `excluded`-Quelle, die eine Ausnahme-ID ist, zur Ausnahme auf: `{source: exception, effect: no_rating, scopeKind: object, id, reason, unstable}`. Eine Einstellung bleibt wie in P1b.
- **Nicht geprüfter Check:** Gilt für den Check eine `skip` (`list_objects` `:75`, `:115`), meldet jedes Objekt `not_collected` mit `{effect: skip, scopeKind: check}` (§12.2).
- **Bleibt:** Die Sortierung (ausgenommene zuletzt) und das Schema der Antwort (nur neue Werte); `no_notify` wie bisher.
- **Tests:** Objekt per Ausnahme, Objekt per Einstellung, Check mit `skip`, beendete Ausnahme.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_objects_api.py tests/test_openapi_snapshot.py
Doku: → T14

### T10 — Listen als API-Feld: lesen zusammengesetzt, schreiben als Ausnahmen (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/exception_scope.py, apps/monitoring/app/template_sync.py, apps/monitoring/tests/test_checks_crud.py, apps/monitoring/tests/test_template_sync.py
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

### T11 — Datenmigration mit Trockenlauf und Schwellen-Rückfall (R-1637)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/exception_migration.py, apps/monitoring/app/main.py, apps/monitoring/tests/test_exception_migration.py, apps/monitoring/tests/test_migrations_smoke.py
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
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_exception_migration.py tests/test_migrations_smoke.py tests/test_seed.py
Doku: → T14

### T12 — Desktop: ignoreService maskiert den Dienstnamen (R-1637, R-1521)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/lib/stores/monitoring.test.ts
Änderung:
- `ignoreService` (`monitoring.ts:489`) maskiert `[`, `*` und `?` im Namen, bevor er in `ignore` geht. Das passt zu den Dienst-Mustern des Servers.
- Tests:
  - Name mit `[` wird maskiert;
  - ein gescheiterter `PUT` lässt den Check unverändert und meldet den Fehler;
  - die Antwort des `PUT` ersetzt den Check im Store.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/monitoring.test.ts
Doku: → T14

### T13 — Abnahme im Upgrade-Pfad: Trockenlauf, Migration, Rückweg (R-1637)  [ ]
Komponente: scripts · Dateien: scripts/tests/upgrade_path_test.sh
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

### T14 — Doku DE+EN und CHANGELOG-Fragment (R-1637, R-1793, R-1521)  [ ]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/arch-monitoring-neu-p1c.md
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

## Entscheidungen
- Kevin 2026-11-27 (Gate, R-1637): Ignorierlisten als Muster-Ausnahme. Jeder Eintrag der fünf Listen wird eine Objekt-Ausnahme mit fnmatch-Muster; exakte Werte werden maskiert, Dienst-Einträge bleiben Muster; der Desktop maskiert in `ignoreService` (R-1521).
- Kevin 2026-11-27 (Gate, R-1637): Schwellen-Rückfall auf die Vorlage. Unterscheidet sich die `config` eines Vorlagen-Checks nur in der Ignorierliste, fällt die Marke `config`; der Trockenlauf nennt jeden Fall mit alten und neuen Werten.
- Kevin 2026-11-27 (Gate, R-1637): Datenkopie vor der nächsten Beta. Gemergt wird nach der synthetischen Abnahme auf einer Pool-VM (T13); Kevins Backup kommt über eine eigene `blockiert`-Zeile, Diff-Bericht nur unter `tasks/private/`.
- Kevin 2026-11-27 (Gate, R-1793): Ergebnis unvollständig. Schläft eine ausgenommene Platte, setzt `smart.py` `complete = False`; der rote Test kommt zuerst (T1).
- Session 2026-11-27: `skip` und `no_rating` in P1c nur dauerhaft. Die Migrationsziele des ADR (§10) sind dauerhaft; andere Dauern kommen mit dem Dialog in P2, additiv.
- Session 2026-11-27: Ein per Ausnahme ausgenommenes Objekt bleibt `not_collected` mit Marke, wie in P1b; Kennzahlen für ausgenommene Objekte erst, wenn P2 sie zeigt.
- Session 2026-11-27: „Läuft“ als Ausdruck über Spalte und Ausnahme, keine gespiegelte Spalte. Die Systemschreiber bleiben auf der Spalte, der Nutzer schreibt nur Ausnahmen.
- Session 2026-11-27: Die Datenmigration ist ein Startschritt mit Einmal-Marke, keine SQL-Revision. Sie braucht die aufgelöste Vorlage (`resolve_template_check`); die Revision bleibt rein strukturell plus Rückschreiben im Downgrade.
