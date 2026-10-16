<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Templates: Anpassungen erhalten, Standard-Templates aktualisieren — Task-Ledger
Status: geplant · Branch: feature/monitoring-templates · Review: pro Task
Spec: docs/features/monitoring-templates.md (Roadmap R-0420)
Heavy: linux-full — ändert die Monitoring-API (neue Routen, Alembic-Revision, Sync-Verhalten) und Desktop-Journeys (Template-UI): `run.sh integration`/`e2e` im Sammellauf auf einer Pool-VM; kein Agent, kein Cross-Host-Pfad, darum kein `scenario`/`windows`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: zwei Vorhaben — dieses ist Phase A (Anpassungen, Tombstones, Versionierung der Standard-Templates, Umbenennung); der Discovery-Vorschlag folgt als `tasks/monitoring-discovery.md` nach R-0417/R-0418/R-0419. Alembic-Migration und die vier neuen Routen sind freigegeben. Anpassungen von vor dem Update gelten nicht als „angepasst“ (hingenommen, in CHANGELOG und Doku genannt). Nicht in diesem Ledger: Linux-Basis v2 und Alert-Qualität (Folgezeilen, Notiz an R-0420). Zeilenangaben: origin/main@af4498a7. Alembic-Kopf heute `c1d3e5f7a9b1`.

### T1 — Schema: angepasste Felder, Tombstones, Version der Standard-Templates  [ ]
Komponente: monitoring · Dateien: apps/monitoring/alembic/versions/a7c9e1b3d5f7_template_overrides_versions.py, apps/monitoring/app/models.py, apps/monitoring/tests/test_template_overrides.py
Änderung: Neue Revision (SPDX-Header `# SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `#` / `# SPDX-License-Identifier: GPL-3.0-or-later`, `down_revision = "c1d3e5f7a9b1"`; den Revisionsbezeichner frei wählen, er muss nur eindeutig sein): `monitor_checks.overridden_fields` (Text, NOT NULL, server_default `'[]'`), `monitor_templates.builtin_version` (Integer NULL) und `builtin_hash` (String NULL), Tabelle `monitor_check_tombstones` (id PK, template_id FK `monitor_templates.id` ON DELETE CASCADE, server_id NOT NULL mit Index, def_id NOT NULL, created_at mit `utc_now_sql()`, `UniqueConstraint(template_id, server_id, def_id)`); Downgrade entfernt alles. Modelle in `models.py` passend (`MonitorCheck` `:24-40`, `MonitorTemplate` `:167-179`, neues `MonitorCheckTombstone`). `MonitorCheck.to_dict` (`:42-60`) liefert zusätzlich `templateDefId` und `overriddenFields` (Liste). Neue Testdatei (SPDX wie oben), zuerst rot: `to_dict` enthält beide Schlüssel, `overriddenFields` ist für einen neuen Check `[]`, ein zweiter Tombstone mit gleichem (template, server, def) verletzt die Eindeutigkeit, das Löschen des Templates entfernt seine Tombstones (Cascade). Die Migrationskette selbst belegt `tests/test_alembic_builtin.py` (läuft mit Postgres in der PR-CI; lokal ohne `DATABASE_URL` übersprungen, siehe `scripts/tests/run.sh:343`).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_overrides.py tests/test_alembic_builtin.py
Doku: keine (intern)

### T2 — Änderungen an Template-Checks als „angepasst“ merken  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/template_sync.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_template_overrides.py
Änderung: Neue Hilfsfunktion in `template_sync.py`, die für einen Check mit `template_id` und `template_def_id` die aufgelöste Template-Definition liefert (Zuweisung des Servers → `_build_variables` `:76-82` → `substitute_variables`), oder `None`, wenn Zuweisung oder Definition fehlen. `update_check` (`checks.py:180-253`) und `toggle_check` (`:271-287`) vergleichen für Template-Checks jedes gesendete Feld aus `{name, description, check_type, config, enabled, interval, severity, consecutive_fails}` mit dem aufgelösten Template-Wert: anders → in `overridden_fields`, gleich → heraus; ein Wechsel von `check_type` markiert `check_type` und `config`. Manuelle Checks bleiben unverändert. Tests zuerst rot: PUT `interval` auf einem Template-Check → `overriddenFields == ["interval"]`; PUT zurück auf den Template-Wert → `[]`; `toggle` → `["enabled"]`; Typwechsel → `check_type` und `config`; manueller Check → `[]`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_overrides.py tests/test_checks_crud.py
Doku: keine (intern)
Abhängt von: T1

### T3 — Sync behält Anpassungen, gelöschte Template-Checks bleiben gelöscht  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/template_sync.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_template_sync.py
Änderung: `_sync_checks_for_server` (`template_sync.py:188-249`) schreibt beim Aktualisieren (`:217-233`) nur Felder, die nicht in `overridden_fields` stehen, und legt keine Definition an (`:234-239`), für die ein Tombstone (Template, Server, def_id) existiert. Eine Definition, die nicht mehr im Template steht, löscht ihren Check weiterhin (`:241-247`), auch wenn er angepasst ist. `delete_check` (`checks.py:255-268`) legt für einen Template-Check mit bestehender Zuweisung einen Tombstone an. `remove_template` (`:373-413`) und `cleanup_server` (`:421-455`) löschen die Tombstones des Paars bzw. Servers. Tests zuerst rot: angepasstes Intervall bleibt beim Sync, die nicht angepasste Severity folgt dem Template; ein deaktivierter (angepasster) Check bleibt deaktiviert; ein gelöschter Template-Check entsteht beim Sync nicht neu; Entfernen und erneutes Zuweisen legt ihn wieder an. Die bestehenden Tests in `test_template_sync.py` (`:213-325`) bleiben grün.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_sync.py tests/test_template_overrides.py
Doku: keine (intern)
Abhängt von: T2

### T4 — Zurücksetzen und Wiederherstellen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_templates_router.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: `POST /checks/{check_id}/reset`: 404 bei unbekanntem Check, 409 bei manuellem Check oder fehlender Definition; sonst `overridden_fields = []`, aufgelöste Template-Werte setzen, Scheduler wie in `update_check`, Antwort wie `to_dict`. `POST /templates/{template_id}/assign/{server_id}/restore`: 404 ohne Zuweisung; löscht die Tombstones des Paars, synchronisiert genau diesen Server, Antwort `{"restored": n}`. `GET /templates/assignments/{server_id}` (`templates.py:80`) liefert je Zuweisung `removedChecks` (Anzahl Tombstones). Beide Pfade liegen unter den Proxy-Präfixen `checks`/`templates` (`apps/server/app/modules/monitoring_proxy/router.py:59-66`), der Server bleibt unverändert. Tests zuerst rot (Statuscodes, Wirkung, `removedChecks`); OpenAPI-Snapshot nachziehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_templates_router.py tests/test_openapi_snapshot.py
Doku: keine (intern; sichtbar mit T9/T10, beschrieben in T12)
Abhängt von: T3

### T5 — Standard-Templates versionieren, unveränderte automatisch aktualisieren  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/builtin_templates.py, apps/monitoring/app/main.py, apps/monitoring/tests/test_seed.py
Änderung: Jeder Eintrag in `BUILTIN_TEMPLATES` (`builtin_templates.py:93-178`) bekommt `"version": 1`; Hash = sha256 über das kanonische JSON (`sort_keys=True`, `separators=(",", ":")`) von `[check_definitions, alert_definitions]`. `seed_builtin_templates` (`:181-207`) setzt `builtin_version` und `builtin_hash`. Neue Funktion `reconcile_builtin_templates(db)`, aufgerufen im Lifespan direkt nach dem Seed (`main.py:56`, ebenfalls best effort): Zeile mit `builtin_slug` ohne `builtin_hash` → `builtin_version = 1`, Hash der mitgelieferten Definitionen; mitgelieferte Version > `builtin_version` und Hash der aktuellen Definitionen == `builtin_hash` → Definitionen ersetzen (Name/Beschreibung bleiben), Version und Hash setzen, `sync_template`; sonst nichts. `MonitorTemplate.to_dict` liefert `builtinVersion`, `builtinEdited`, `builtinUpdateAvailable` (dafür liest `to_dict` die mitgelieferte Version aus `BUILTIN_TEMPLATES`). Tests zuerst rot, mit per monkeypatch auf Version 2 gehobenem `BUILTIN_TEMPLATES`: unverändert → aktualisiert und synchronisiert (angepasstes Feld eines Checks bleibt); angepasst → unverändert, `builtinUpdateAvailable`; Bestandszeile ohne Hash → Baseline; gelöscht → bleibt gelöscht; Wiederholung idempotent.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_seed.py tests/test_template_sync.py
Doku: keine (intern; beschrieben in T12)
Abhängt von: T3

### T6 — Update eines angepassten Standard-Templates anzeigen und übernehmen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_templates_router.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: `GET /templates/{template_id}/builtin-update` → 404 ohne `builtin_slug`; sonst `{currentVersion, shippedVersion, current: {checkDefinitions, alertDefinitions}, shipped: {checkDefinitions, alertDefinitions}}`. `POST /templates/{template_id}/builtin-update` → 409, wenn kein Update verfügbar; sonst mitgelieferte Definitionen übernehmen, Version und Hash setzen, `sync_template` (Anpassungen je Check bleiben, T3), Antwort `to_dict` plus `syncResult` wie `update_template` (`templates.py:157-193`). Tests zuerst rot; OpenAPI-Snapshot nachziehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_templates_router.py tests/test_openapi_snapshot.py
Doku: keine (intern; beschrieben in T12)
Abhängt von: T5

### T7 — Neuer Hostname oder Servername erreicht bestehende Zuweisungen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/tag_sync.py, apps/monitoring/app/template_sync.py, apps/monitoring/tests/test_tag_sync.py
Änderung: `sync_tag_assignments` (`tag_sync.py:57-124`) prüft zusätzlich jede Zuweisung (Quelle `manual` und `tag`) gegen das Inventar: weichen `hostname`/`name` von `server_hostname`/`server_name` ab, werden die Spalten aktualisiert und genau dieses (Template, Server)-Paar über eine neue Funktion in `template_sync.py` neu synchronisiert (nur nicht angepasste Felder, T3). Rückgabe um `"refreshed": n` erweitern. Der Server meldet Umbenennungen schon (`apps/server/app/modules/servers/router.py:172-177`); dort ändert sich nichts. Tests zuerst rot: Umbenennung im Inventar → Zuweisung und `{{hostname}}`-Config des Checks neu; angepasster Name bleibt; Server nicht im Inventar → unverändert; kein Inventar → nichts geändert (wie heute).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_tag_sync.py tests/test_template_sync.py
Doku: keine (intern; beschrieben in T12)
Abhängt von: T3

### T8 — Desktop: Typen und API-Aufrufe für Anpassungen, Wiederherstellen und Updates  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/monitoring.test.ts
Änderung: `MonitorCheck` (`types.ts:363`) um `templateDefId?: string | null` und `overriddenFields?: string[]`, `TemplateAssignment` (`:50`) um `removedChecks?: number`, `MonitoringTemplateFull` (`:556`) um `builtinVersion?`, `builtinEdited?`, `builtinUpdateAvailable?`; neuer Typ für die Antwort von `builtin-update`. In `monitoring.ts` (neben `:109-184`): `resetCheck`, `restoreTemplateChecks`, `fetchBuiltinUpdate`, `applyBuiltinUpdate` mit `encodeURIComponent` wie die Nachbarn. Tests zuerst rot: Methode und Pfad je Aufruf.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/monitoring.test.ts
Doku: keine (intern)
Abhängt von: T4, T6

### T9 — Desktop: Badge „angepasst“ und „Auf Template zurücksetzen“ am Check  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/MonCheckLine.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/monitoring/MonCheckLine.template.test.ts
Änderung: `MonCheckLine.svelte` zeigt bei Checks mit `templateId` und nichtleerem `overriddenFields` ein Badge „angepasst“ (Tooltip: übersetzte Feldnamen) und neben den Aktionen (`:84-103`) „Auf Template zurücksetzen“ mit Rückfrage im App-Dialog (nicht `@tauri-apps/plugin-dialog`); nach Erfolg wird die Zeile mit der Antwort aktualisiert, ein Fehler erscheint wie bei den anderen Aktionen. Texte DE + EN. Neue Testdatei (SPDX-Header `// SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `//` / `// SPDX-License-Identifier: GPL-3.0-or-later`), zuerst rot: Badge nur bei angepasstem Template-Check, Zurücksetzen ruft `resetCheck` genau einmal nach Bestätigung, Abbrechen ruft nichts.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/MonCheckLine.template.test.ts
Doku: keine (intern; beschrieben in T12)
Abhängt von: T8

### T10 — Desktop: gelöschte Template-Checks wiederherstellen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/tabs/MonitoringTab.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/infra/tabs/MonitoringTab.test.ts
Änderung: Im Template-Abschnitt (`MonitoringTab.svelte:171-206`) zeigt jede Zuweisung mit `removedChecks > 0` „N gelöschte Checks wiederherstellen“; der Klick ruft `restoreTemplateChecks` und lädt Zuweisungen und Checks neu. Texte DE + EN (Plural). Tests zuerst rot: Link nur bei `removedChecks > 0`, Klick ruft den Aufruf mit Template und Server, danach neu geladen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/tabs/MonitoringTab.test.ts
Doku: keine (intern; beschrieben in T12)
Abhängt von: T8

### T11 — Desktop: „Update verfügbar“ bei Standard-Templates mit Vergleich und Übernehmen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/MonitoringTemplates.svelte, apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.test.ts
Änderung: Die Template-Liste (`MonitoringTemplates.svelte`) zeigt bei `builtinUpdateAvailable` ein Badge „Update verfügbar“; es öffnet ein neues Modal (SPDX-Kommentar wie in `TunnelIndicator.svelte`), das aktuelle und mitgelieferte Check-Definitionen je `def_id` nebeneinander zeigt (neu, entfernt, geändert mit Feldnamen) und „Übernehmen“ anbietet (`applyBuiltinUpdate`, danach Liste neu laden) mit dem Hinweis, dass angepasste Felder einzelner Checks erhalten bleiben. Texte DE + EN. Neue Testdatei (SPDX), zuerst rot: Badge nur bei verfügbarem Update, Vergleich zeigt neue/entfernte/geänderte Definitionen, Übernehmen ruft den Aufruf genau einmal.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/BuiltinUpdateModal.test.ts
Doku: keine (intern; beschrieben in T12)
Abhängt von: T8

### T12 — Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Änderung: Admin-Doku DE + EN, Abschnitt Templates (`monitoring.html:139-181`): angepasste Felder bleiben beim Sync, Badge und „Auf Template zurücksetzen“, gelöschte Template-Checks bleiben gelöscht und lassen sich wiederherstellen, Standard-Templates mit Version (unverändert → automatisch aktualisiert, angepasst → „Update verfügbar“), neuer Name/Hostname erreicht bestehende Zuweisungen; ausdrücklich: Anpassungen von vor dem Update sind nicht als angepasst bekannt. Den Satz zum einmaligen Seeding (`:169`) entsprechend ändern. Entwickler-Doku DE + EN (`developer/monitoring.html:155`): `overridden_fields`, Tombstones, Built-in-Version/-Hash, neue Routen. CHANGELOG unter `### Changed` bzw. `### Added`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html + docs/en/admin/monitoring.html · docs/developer/monitoring.html + docs/en/developer/monitoring.html · CHANGELOG.md
Abhängt von: T7, T9, T10, T11
