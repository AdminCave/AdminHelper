<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Vorschlag passender Standard-Templates — Task-Ledger
Status: aktiv · Branch: feature/monitoring-discovery · Review: pro Task
Spec: docs/features/monitoring-discovery.md (Roadmap R-0421)
Heavy: linux-full + scenario --agents 1 + windows — ändert den Agent-Report (`host`-Block) und die Monitoring-API (Alembic-Revision, zwei Routen) sowie eine Desktop-Journey (`monitoring-check.live.js` im Sammellauf); `scenario --agents 1` vor dem Merge, weil erst ein echter Agent über das Gateway den Vorschlag im Desktop auslöst (Multibox von Kevin am 2026-10-16 für die Monitoring-Pakete erlaubt); `windows` für `host.Info`/`LookPath` unter Windows
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hängt ab von: R-0417, R-0418, R-0419 (alle ändern `apps/agent/internal/monitor/report.go` und das Report-Beispiel der Doku) und R-0420 (monitoring-templates, Phase A; deren Alembic-Revision ist hier `down_revision`). Erst nach deren Merge starten und `origin/main` hineinmergen.

Kevin 2026-10-16: Phase B von R-0420 als eigenes Vorhaben; keine Auto-Zuweisung, sondern ein Vorschlag im Monitoring-Tab des Servers (Zuweisen/Ignorieren, Ignorieren wird je Server und Template gemerkt und ist vorerst nicht rückgängig zu machen); kein Fallback auf `os_type` für Agents ohne `host`-Block; additive Report-Felder, Alembic-Migration und die zwei neuen Routen freigegeben. Zeilenangaben: origin/main@af4498a7.

### T1 — Agent meldet den Block `host`  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/hostfacts.go, apps/agent/internal/monitor/hostfacts_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/report_test.go
Änderung: Neue Datei `hostfacts.go` (SPDX-Header `// SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `//` / `// SPDX-License-Identifier: GPL-3.0-or-later`): `collectHostFacts()` liefert `{"os", "platform", "platform_version", "virtualization": {"system", "role"}, "subsystems": [...]}` (`os` aus `runtime.GOOS`, `platform`/`platform_version` aus gopsutil `host.PlatformInformation`, `virtualization` aus `host.Virtualization`; ein Fehler kostet nur die Felder seines Teils, „not implemented“ unter Windows zählt als leer) und `exec.LookPath` für `docker`, `zpool`, `pvesh` (Reihenfolge fest, nur gefundene); Info- und LookPath-Aufrufe über Paketvariablen, damit Tests sie ersetzen (Muster `pluginCollectors`, `report.go:84-89`). Ein Fehler von `host.Info` lässt die betroffenen Felder weg, nie den Report. `BuildReport` (`report.go:43-48`) setzt `report["host"]`. Signaturen an der eingebundenen gopsutil-Version (v4.26.5) prüfen. Neue Testdatei (SPDX), zuerst rot: mit ersetzten Aufrufen erscheinen alle Felder; nur gefundene Subsysteme; `host.Info`-Fehler → kein Fehler, Block ohne die Felder; `BuildReport` enthält `host`.
Verify: bash scripts/dev/verify.sh agent --strict -- -run 'HostFacts|BuildReport'
Doku: keine (intern; beschrieben in T7)

### T2 — Schema: Host-Fakten und ignorierte Vorschläge  [ ]
Komponente: monitoring · Dateien: apps/monitoring/alembic/versions/b9d1f3a5c7e9_host_facts_suggestions.py, apps/monitoring/app/models.py, apps/monitoring/app/template_sync.py, apps/monitoring/tests/test_template_suggestions.py
Änderung: Neue Revision (SPDX-Header `# SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `#` / `# SPDX-License-Identifier: GPL-3.0-or-later`, `down_revision` = die Revision aus monitoring-templates T1, nach deren Merge per `alembic heads` prüfen): Tabellen `monitor_host_facts` (server_id PK, os, platform, platform_version, virt_system, virt_role, subsystems Text NOT NULL server_default `'[]'`, updated_at) und `monitor_template_suggestion_dismissals` (id PK, server_id NOT NULL mit Index, builtin_slug NOT NULL, dismissed_at, `UniqueConstraint(server_id, builtin_slug)`); Modelle dazu. `cleanup_server` (`template_sync.py:421-455`) löscht beide Zeilenarten des Servers. Neue Testdatei `test_template_suggestions.py` (SPDX wie oben; T3 und T4 erweitern sie), zuerst rot: `cleanup_server` entfernt Fakten und Ablehnungen; doppelte Ablehnung verletzt die Eindeutigkeit. Kette: `test_alembic_builtin.py` (PR-CI).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_suggestions.py tests/test_alembic_builtin.py
Doku: keine (intern)

### T3 — Report speichert die Host-Fakten, geprüft und begrenzt  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/template_suggestions.py, apps/monitoring/tests/test_agent_report.py
Änderung: Neue Datei `template_suggestions.py` (SPDX-Header wie T2) mit `store_host_facts(db, server_id, host)`: `os` nur aus `{linux, windows, darwin}` (kleingeschrieben), Strings auf 64 Zeichen, `subsystems` nur aus `{docker, zfs, proxmox}`, Rest verworfen; Upsert, eigener Commit, Fehler nur geloggt — wie die Liveness (`agent.py:86-91`), damit ein Problem dort nie den Report kostet. `agent_report` (`agent.py:68-299`) ruft sie nach der NUL-Prüfung (`:96-109`), wenn `host` ein Objekt ist. Tests zuerst rot: gültiger Block gespeichert; unbekanntes OS/Subsystem verworfen; überlange Strings gekürzt; Block fehlt oder ist kein Objekt → nichts gespeichert, Report trotzdem `ok`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_template_suggestions.py
Doku: keine (intern)
Abhängt von: T2

### T4 — Vorschläge berechnen und ignorieren (Routen)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/template_suggestions.py, apps/monitoring/app/routers/templates.py, apps/monitoring/tests/test_template_suggestions.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: `suggest_templates(db, server_id)`: `linux` → `linux-base`, `windows` → `windows-base`, `docker` → `docker-host`, `zfs` → `zfs-storage`, `proxmox` → `proxmox-host`; nur Slugs, deren Template existiert, die dem Server nicht zugewiesen sind (jede Quelle) und nicht ignoriert wurden; Ergebnis `[{slug, templateId, templateName, reason}]` mit `reason` `os:<os>` bzw. `subsystem:<name>`. Routen in `templates.py`: `GET /templates/suggestions/{server_id}` und `POST /templates/suggestions/{server_id}/dismiss` mit Body `{"slug": …}` (422 bei unbekanntem Slug, idempotent). Die Pfade liegen unter dem Proxy-Präfix `templates` (`monitoring_proxy/router.py:59-66`) und kollidieren nicht mit `/templates/{template_id}` (drei Segmente, wie `/templates/assignments/{server_id}` `:80`). Tests zuerst rot: Linux mit Docker → beide Vorschläge; zugewiesen/ignoriert/gelöschtes Built-in → kein Vorschlag; ohne Fakten → leer. OpenAPI-Snapshot nachziehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_suggestions.py tests/test_openapi_snapshot.py
Doku: keine (intern; beschrieben in T7)
Abhängt von: T3

### T5 — Desktop: Vorschlag im Monitoring-Tab annehmen oder ignorieren  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/tabs/MonitoringTab.svelte, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/infra/tabs/MonitoringTab.test.ts
Änderung: `fetchTemplateSuggestions` und `dismissTemplateSuggestion` in `monitoring.ts` (Typ in `types.ts` nur, wenn nötig — dann `set-files`). Über dem Template-Abschnitt (`MonitoringTab.svelte:171`) steht bei vorhandenen Vorschlägen ein Hinweis „Vorgeschlagen: …“ mit je einem Kontrollkästchen (vorausgewählt), **Zuweisen** (vorhandenes `assignTemplate` mit Hostname und Name des Servers, je ausgewähltem Template) und **Ignorieren** (Ablehnung je ausgewähltem Slug); danach Vorschläge, Zuweisungen und Checks neu laden. Ohne Vorschläge kein Hinweis. Texte DE + EN. Tests zuerst rot: Hinweis nur mit Vorschlägen; Zuweisen ruft `assignTemplate` je ausgewähltem Template; Ignorieren ruft die Ablehnung je Slug; abgewähltes Template bleibt unberührt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/tabs/MonitoringTab.test.ts
Doku: keine (intern; beschrieben in T7)
Abhängt von: T4

### T6 — Live-E2E: Vorschlag annehmen legt die Standard-Checks an  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-check.live.js
Änderung: Die bestehende Spec (der Orchestrator `scripts/tests/desktop_e2e_monitoring.sh:59-66` fährt genau sie, bleibt also unverändert) prüft zusätzlich: Nach dem ersten Push des Agents zeigt der Monitoring-Tab des Servers den Vorschlag „Linux Server — Standard“; Zuweisen legt dessen Checks an (Heartbeat, System Resources), der Vorschlag verschwindet. Die bisherigen Schritte der Spec bleiben unverändert und laufen vorher; wenn sie selbst schon ein Template zuweisen, den neuen Schritt so legen, dass er auf einem Server ohne Zuweisung läuft. Live-Lauf über `Heavy:`.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T1, T5

### T7 — Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Änderung: Admin-Doku DE + EN (`monitoring.html:171-181`, „Templates zuweisen“): Vorschlag im Monitoring-Tab nach erkanntem OS und Subsystemen, Zuweisen/Ignorieren, keine Auto-Zuweisung; Agents vor dieser Version liefern keinen Vorschlag. Entwickler-Doku DE + EN: Report-Beispiel (`developer/monitoring.html:95-121`) um `host`, Satz zu optionalen Feldern (`:121`), Routen der Vorschläge. CHANGELOG unter `### Added`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html + docs/en/admin/monitoring.html · docs/developer/monitoring.html + docs/en/developer/monitoring.html · CHANGELOG.md
Abhängt von: T5, T6
