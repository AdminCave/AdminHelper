<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# API-Verträge: Antwortmodelle für Server und Monitoring, Client-Typen gegen den Snapshot (Teil monitoring) — Task-Ledger
Status: aktiv · Branch: feature/api-contracts-monitoring · Review: pro Task
Spec: docs/features/api-contracts.md (Roadmap R-0685)
Heavy: none — Teil-Ledger von tasks/api-contracts.md (T13–T17); die schwere Prüfung (linux-full + scenario + windows) fährt das Vorhabens-Ledger vor dem Merge
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Jede JSON-Route des Servers außer den Nicht-Zielen der Spec deklariert ein `response_model`, das die heutige
Antwort Schlüssel für Schlüssel abbildet (R-0684). (2) Dasselbe für Monitoring außer `/health` und dem Agent-Report
(R-0685). (3) Web- und Desktop-`types.ts` werden je von einem Vertragstest gegen die Snapshots geprüft, die Drift ist
behoben, auch das fehlende Datum eines neuen API-Schlüssels (R-0686, R-0687). (4) Die Monitoring-Sektionen der
Desktop-UI lesen `state.details` über Narrowing-Funktionen statt über `as` (R-0687). Keine Antwort ändert sich;
`scripts/dev/openapi-breaking.sh` meldet je Task 0 ERR. Zeilenangaben: origin/main@b25c65a6; der builder greppt sie
vor dem Schreiben neu.

Für alle Tasks:
- Blöcke und Reihenfolge: A Server T1–T12 (T2 nach T1, T11 vor T12), B Monitoring T13–T17, C Web T18–T19, D Desktop-UI
  T20–T25. A und B sind unabhängig. T18 und T23 gehen jederzeit. T19 nach T2, T9, T10, T12. T20 nach Block A und T19.
  T21 und T22 nach Block B und T20. T24 und T25 nach T23. Eine Teilung in die Teil-Ledger `api-contracts-server`
  (T1–T12), `api-contracts-monitoring` (T13–T17) und `api-contracts-clients` (T18–T25) ist Kevins Wort (Spec,
  Trade-off 8).
- Hängt ab von `fehlervertrag` (freigegeben, eigener Branch). Geteilte Dateien: `CHANGELOG.md` (hier T12, T17, T18),
  `apps/web/src/lib/api/types.ts` (hier T18, T19; dort die Klasse `ApiError`); über Folgeänderungen möglich
  `apps/desktop/ui/src/lib/stores/monitoring.ts` und `apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.svelte`.
  Ist `fehlervertrag` gemergt, vor der ersten Task, die eine dieser Dateien berührt, `origin/main` hineinmergen.
- Antwortmodelle nach den Regeln 1–7 der Spec („Datenmodell“): Schlüssel wie der Produzent, Feldname = JSON-Schlüssel,
  Zeitstempel `str`/`Optional[str]`, kein Typ enger als Spalte und alle Schreiber, die es je gab (bei JSON in einer
  Textspalte belegt `git log -S` an der Validierung, seit wann sie gilt; älter als die Spalte → `list[str]`, sonst
  `list[Any]`), bedingte Schlüssel als Feld mit Default `None` plus `response_model_exclude_unset=True` an jeder Route,
  die das Modell auch verschachtelt liefert, keine Validatoren, keine Grenzen. Ein Routen-Docstring ist die
  OpenAPI-description und bleibt unverändert.
- Testmuster je Server- und Monitoring-Task in `tests/test_response_shapes.py` der Komponente (T1 bzw. T13 legt die
  Datei an, SPDX per `reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`): (a) das
  2xx-Schema der Operation im laufenden `app.openapi()` verweist auf das neue Modell (rot auf HEAD); (b) Gleichheit über
  die echte Route, `resp.json() == jsonable_encoder(<Produzent>)`, mit einer vollen Zeile und einer dünnen (alle
  nullbaren Spalten `NULL`), Muster `TestConfigResponseShape` (`apps/server/tests/test_frp_config.py:581-680`);
  (c) jede bedingte Variante (Schlüssel fehlt / ist da). Danach den Snapshot neu schreiben
  (`pytest tests/test_openapi_snapshot.py --update-openapi-snapshot` im Komponenten-Verzeichnis) und
  `bash scripts/dev/openapi-breaking.sh <server|monitoring>` fahren: 0 ERR, Ausgabe-Zusammenfassung in den Commit-Body.
- `security` zusätzlich (`scripts/dev/review-risk.txt`): T1–T10, T12–T17, T19–T22.
- Platzhalter in Tests: Hosts unter `.example`, Adressen aus RFC 5737.

Teil-Ledger (Kevin 2026-10-23, Spec Trade-off 8): T13–T17 aus `tasks/api-contracts.md`, gemergt in `feature/api-contracts`. CHANGELOG-Einträge in `changelog.d/api-contracts-monitoring.md` statt `CHANGELOG.md` (Konvention seit dem Plan).

### T13 — Monitoring: Checks, Status, Summary, Metriken (R-0685)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4256d779 2026-10-29T22:12:10+01:00
Review: approve (.ah-out/review/api-contracts-monitoring/T13.verdict.json)
Änderung: In `app/schemas.py`: `MonitorStateOut` wie `MonitorState.to_dict` (`apps/monitoring/app/models.py:125-135`; `details: Any`), `MonitorCheckOut` wie `MonitorCheck.to_dict` (`:77-100`; `config: Any`, nullbare Spalten `Optional`, `state: Optional[MonitorStateOut] = None` nur mit Zustandszeile `:98-99`), `StatusSummaryOut` (sechs `int`, `apps/monitoring/app/routers/checks.py:406-418`), `CheckMetricsOut` `{checkId, checkType, period, data: Any, statusHistory: Any}` (VictoriaMetrics-Durchreiche). Routen in `checks.py`: `127` (list), `146` (201), `187`, `197`, `291` (toggle), `311` (reset), `341` (run), `374` (status), `387` (status/server), `399` (summary), `427` (metrics); alle mit `MonitorCheckOut` mit `response_model_exclude_unset=True`. Neue Datei `tests/test_response_shapes.py` (SPDX) mit dem Testmuster; (c) Check mit und ohne Zustandszeile; Gegenprobe zu `test_stored_json_numbers.py`: Zahlen in `config`/`details` bleiben Zahlen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_checks_crud.py tests/test_checks_metrics.py tests/test_pagination.py tests/test_stored_json_numbers.py
Doku: keine
Beweis: origin/main@b25c65a6 · Snapshot-Probe (python3, `apps/monitoring/tests/openapi.snapshot.json`): alle 37 JSON-Antworten der 44 Operationen haben das Schema `{}`, die übrigen sieben sind 204
Orakel: contract — die Modelle gegen die `to_dict`-Methoden und Dict-Literale über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

### T14 — Monitoring: Alert-Regeln und Alert-Log (R-0685)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/alerts.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f96b1028 2026-10-29T22:21:14+01:00
Review: approve (.ah-out/review/api-contracts-monitoring/T14.verdict.json)
Änderung: `AlertRuleOut` wie `MonitorAlertRule.to_dict` (`apps/monitoring/app/models.py:154-173`; `channelConfig: dict[str, Any]` frei, das maskierte `smtp_password` bleibt `***`; `cooldownMinutes`, `enabled` nullbar), `AlertLogOut` wie `MonitorAlertLog.to_dict` (`:201-211`; `id: int`, Spalte `:188`). Routen in `apps/monitoring/app/routers/alerts.py`: `27`, `42` (201), `66` (log), `73`, `82`, `142` (toggle). Tests nach Muster; (b) mit einer Regel mit SMTP-Passwort (maskiert) und einer ohne `channelConfig`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_alert_secrets.py tests/test_stored_json_numbers.py
Doku: keine
Abhängt von: T13
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T13: die sechs Alert-Operationen mit `{}`
Orakel: contract — die Modelle gegen die `to_dict`-Methoden über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

### T15 — Monitoring: Wartung und Admin (R-0685)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/maintenance.py, apps/monitoring/app/routers/admin.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @725d48b0 2026-10-29T22:24:53+01:00
Review: approve (.ah-out/review/api-contracts-monitoring/T15.verdict.json)
Änderung: `MaintenanceOut` wie `MonitorMaintenance.to_dict` (`apps/monitoring/app/models.py:398-412`; `weekdays: list[Any]`, `enabled` nullbar), `AgentKeyOut` wie `MonitorAgentKey.to_dict` (`:351-357`; die Route `apps/monitoring/app/routers/admin.py:24` setzt `apiKey` beim Anlegen auf den Rohschlüssel, `:47`), `AgentKeyDeletedOut` `{deleted: bool}` (`:55`), `ServerCleanupOut` `{checksDeleted: int, alertsDeleted: int}` (`apps/monitoring/app/template_sync.py:743`). Routen `maintenance.py:39`, `:48` (201), `:59`; `admin.py:24`, `:51`, `:59`. Tests nach Muster. Der Server liest von `POST /agent-keys` nur `apiKey` (`apps/server/app/modules/provisioning/helpers.py:64-66`).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_maintenance_router.py tests/test_admin_router.py
Doku: keine
Abhängt von: T13
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T13: die Wartungs- und Admin-Operationen mit `{}`
Orakel: contract — die Modelle gegen `to_dict` und die Dict-Literale über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

### T16 — Monitoring: Templates und Builtin-Update (R-0685)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: `TemplateOut` wie `MonitorTemplate.to_dict` (`apps/monitoring/app/models.py:232-257`; Check- und Alert-Definitionen `list[dict[str, Any]]`, weil ihre Schlüssel je Definition wechseln), dazu `assignments`, `tagAssignments` (`TemplateAssignmentOut` wie `MonitorTemplateAssignment.to_dict` `:281-289`, `TagAssignmentOut` wie `MonitorTemplateTagAssignment.to_dict` `:329-334`) und `syncResult` (`SyncResultOut` `{created, updated, deleted, servers}`, `apps/monitoring/app/template_sync.py:388-393`) je `Optional[...] = None`; `BuiltinUpdateOut` `{currentVersion, shippedVersion, current, shipped}` (`apps/monitoring/app/routers/templates.py:301-306`). Routen `templates.py:68` (list), `136` (201), `166`, `185` (PUT, mit `syncResult`), `281` (builtin-update GET), `310` (builtin-update POST, mit `syncResult`); alle mit `response_model_exclude_unset=True`. Tests nach Muster; (c) GET ohne, PUT mit `syncResult`, ein Template mit Zuordnungen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_templates_router.py tests/test_template_overrides.py tests/test_stored_json_numbers.py
Doku: keine
Abhängt von: T13
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T13: die sechs Template-Operationen mit `{}`
Orakel: contract — die Modelle gegen `to_dict` und die Ergänzungen der Routen über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

### T17 — Monitoring: Zuordnungen, Vorschläge, Tag-Sync (R-0685)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_response_shapes.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/tests/test_templates_router.py, changelog.d/api-contracts-monitoring.md
Änderung: `ServerAssignmentOut` (`TemplateAssignmentOut` plus `templateName: Optional[str]`, `removedChecks: int`, `apps/monitoring/app/routers/templates.py:97`), `TemplateSuggestionOut` `{slug, templateId, templateName, reason}` (`:255`), `ApplyResultOut` `{checksCreated: list[str], alertsCreated: list[str]}` (die IDs, nicht Zahlen: `apps/monitoring/app/template_sync.py:583-612`) für `assign`, `RestoreOut` `{restored: int}` (`templates.py:399`, `template_sync.py:672-674`), `TagSyncOut` `{created, removed, refreshed: int}` (`apps/monitoring/app/tag_sync.py:142`); `assign-tag` (`templates.py:412`, 201) mit `TagAssignmentOut` aus T16 (`:427`). Routen `templates.py:97`, `:255`, `:332`, `:385`, `:412`, `:453`. Der Stand-in in `tests/test_templates_router.py:195-205` liefert heute `{"created": 2, "removed": 1}` ohne `refreshed` und würde mit dem Modell zur 500: er liefert und erwartet künftig `{"created": 2, "removed": 1, "refreshed": 0}`, die echte Form (keine Test-Löschung, die Assertion prüft weiter die Durchreiche). Tests nach Muster.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_templates_router.py tests/test_template_suggestions.py tests/test_tag_sync.py
Doku: changelog.d/api-contracts-monitoring.md (Changed, umlautfrei: die OpenAPI-Beschreibung des Monitoring-Dienstes nennt die Felder seiner JSON-Antworten; die Antworten bleiben gleich)
Abhängt von: T16
Beweis: origin/main@b25c65a6 · Snapshot-Probe wie T13: die sechs Operationen mit `{}`; `test_templates_router.py:200-205` patcht `sync_tag_assignments` auf eine Form, die `tag_sync.py:142` nie liefert
Orakel: contract — die Modelle gegen die Dict-Literale über die echte Route
Dedup-Key: ref:cross:openapi:response-side-blind
HEAD: b25c65a6

## Entscheidungen
- T14: `AlertRuleOut.channelConfig` ist `Any` statt `dict[str, Any]` (Plan): `masked_channel_config` gibt eine gespeicherte Nicht-Objekt-Konfiguration unverändert heraus; ein Dict-Typ machte eine solche Altzeile und damit die ganze Liste zur 500 (Regel 3). Test `rule-legacy` mit `["x"]`.
