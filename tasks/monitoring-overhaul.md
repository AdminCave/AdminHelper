<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Überarbeitung — Task-Ledger
Status: blockiert (Build komplett, T47 braucht Entscheidung) · Branch: feature/monitoring-overhaul · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/monitoring-overhaul.md
Fast-Suite: lokal · Warm-Profil: desktop
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hinweise: Server-pytest braucht die lokale Dev-Env (`source .devenv.sh`, dann
`DATABASE_URL="$AH_TEST_DB" python -m pytest`); Monitoring-pytest ist DB-frei.
Monitoring-Alembic-Kette hängt an `d9e1f3a5b7c2` — M1 (T1) → M2 (T9) → M3 (T23)
strikt sequenziell anlegen. T33 berührt docker-compose.yml nur als
env-parametrisierte Retention-Flag (kein Cross-Host-Pfad) — schwere
Verifikation via `run.sh integration` auf der Desktop-Warm-Box, kein multibox.

## Phase 1 — Backend-Fundament (Seeding, Liveness, Alert-Semantik)

### T1 — Migration M1: builtin_slug, seed_state, agent_liveness  [x] (f3b5d7a9c1e3, Parity-Smoke grün)
Komponente: apps/monitoring · Dateien: app/models.py, alembic/versions/<neu>_seed_and_liveness.py
Änderung: `MonitorTemplate.builtin_slug` (nullable, unique) + neue Modelle `MonitorSeedState(slug PK, seeded_at)` und `MonitorAgentLiveness(server_id PK, last_report_at)`; Migration mit Downgrade; `builtin_slug`/`builtinSlug` in `MonitorTemplate.to_dict()`.
Verify: `cd apps/monitoring && python -m pytest -q tests/test_migrations_smoke.py tests/` (Model↔Migration-Parity grün) && `ruff check apps/monitoring`
Doku: keine (intern; Doku gesammelt in T34/T35)

### T2 — agent_ping neustart-fest: Wall-Clock + Persistenz + stale-Default 15  [x] (Wall-Clock + Liveness-Upsert + Hydration, 29 Zieltests)
Komponente: apps/monitoring · Dateien: app/checkers/agent.py, app/routers/agent.py, app/main.py
Änderung: `_last_report` von `time.monotonic()` auf naive-UTC-Wall-Clock umstellen; beim Agent-Push zusätzlich `MonitorAgentLiveness` upserten; im Lifespan die Map aus der Tabelle hydratisieren; `stale_minutes`-Default 5 → 15 (Kommentar: 3 verpasste 5-min-Intervalle).
Verify: `cd apps/monitoring && python -m pytest -q tests/test_agent_ping_checker.py tests/test_agent_report.py` (neue Tests: Hydration nach „Neustart“, Default 15)
Doku: keine (intern; Verhaltens-Änderung landet in T34/T35 + CHANGELOG)
Abhängt von: T1

### T3 — unknown-Policy: nie benachrichtigen  [x] (Guard in process_alert, 4 neue Tests)
Komponente: apps/monitoring · Dateien: app/alerter.py, app/check_engine.py
Änderung: In `process_alert()` Transitionen mit `new_status == "unknown"` von Regel-Dispatch UND Hub-Emit ausnehmen (`unknown → ok` bleibt Recovery); POLICY NOTE in `check_engine.next_fail_count` auf die entschiedene Policy aktualisieren.
Verify: `cd apps/monitoring && python -m pytest -q tests/test_alerter.py tests/test_alerter_hub.py` (neue Fälle: ok→unknown kein Dispatch/kein Hub, unknown→ok Recovery ja)
Doku: keine (intern; T34 dokumentiert die Policy)

### T4 — Config-Schema-Validierung pro Check-Typ + Channel-Validator  [x] (check_configs.py, 19 neue Tests, Review-Blocker check_restarts toleriert)
Komponente: apps/monitoring · Dateien: app/check_configs.py (neu, SPDX), app/schemas.py, app/routers/checks.py
Änderung: Pro Check-Typ ein Pydantic-Config-Modell (bekannte Keys typisiert/begrenzt, unbekannte Keys abgelehnt) in `check_configs.py`; Validierung in `CheckCreate`/`CheckUpdate` und `TemplateCheckDef` (Bestandsdaten bleiben unangetastet — nur Create/Update-Boundary); `TemplateAlertDef` bekommt den fehlenden `channel`-Validator gegen `VALID_CHANNELS`.
Verify: `cd apps/monitoring && python -m pytest -q tests/test_check_configs.py tests/test_schemas.py` (invalide Keys/Werte → 422, valide Bestands-Configs passieren)
Doku: keine (intern)

### T5 — Built-in-Templates + idempotenter Lifespan-Seed  [x] (5 Built-ins, Tombstone-Seed, 7 Tests)
Komponente: apps/monitoring · Dateien: app/builtin_templates.py (neu, SPDX), app/main.py, tests/test_seed.py (neu, SPDX)
Änderung: Fünf Built-ins als Konstanten (Slugs `linux-base`, `windows-base`, `proxmox-host`, `docker-host`, `zfs-storage`; Inhalte + Schwellwerte exakt laut Spec, englische Namen, stabile `def_id`s); `seed_builtin_templates()` legt nur Templates an, deren Slug nicht in `monitor_seed_state` steht, und trägt den Slug ein; Aufruf im Lifespan vor `load_all_checks()`.
Verify: `cd apps/monitoring && python -m pytest -q tests/test_seed.py` (frisch → 5 Templates; zweiter Lauf → keine Duplikate; gelöschtes Template bleibt gelöscht; editiertes bleibt editiert; Defs validieren gegen TemplateCheckDef)
Verify-2: `grep -q "linux-base" apps/monitoring/app/builtin_templates.py`
Doku: keine (intern; T34 beschreibt die Templates)
Abhängt von: T1, T4

### T6 — Hysterese für agent_resources  [x] (per-Metrik statt prev_status — Sticky-Bug vermieden; 8 Checker- + 1 Round-Trip-Test)
Komponente: apps/monitoring · Dateien: app/checkers/agent.py, app/routers/agent.py, app/check_configs.py (Key `hysteresis_pp` in AgentResourcesConfig ergänzen — sonst lehnt die T4-Boundary ihn ab)
Änderung: Per-METRIK-Hysterese (Abweichung von der ursprünglichen prev_status-Formulierung — Check-Granularität hätte einen Sticky-Bug: alarmierende CPU kontaminiert die Release-Schwellen aller Metriken): `evaluate(config, report, prev_details)` liest die `problems`-Map `{metrik: level}` aus den vorherigen state.details; `_grade()` bekommt warn/crit-Release-Abschläge (crit nur bei zuvor kritischer Metrik). Push-Pfad lädt den State vor evaluate (unter demselben Lock).
Verify: `cd apps/monitoring && python -m pytest -q tests/test_agent_resources_checker.py tests/test_agent_report.py` (Fälle: 91 % → warning; Abfall auf 84 % bleibt warning; 79 % → ok; hysteresis_pp 0 = altes Verhalten; Round-Trip durch den Push-Endpoint)
Doku: keine (intern; Schwellwert-Doku in T34)

### T7 — Host-down-Suppression  [x] (ANY-Semantik-Query + 6 Tests inkl. Real-Session-Pin)
Komponente: apps/monitoring · Dateien: app/alerter.py
Änderung: In `process_alert()`: hat der Server des Checks einen `agent_ping`-Check mit State `critical` und ist der auslösende Check nicht selbst `agent_ping`, werden Dispatch + Hub-Emit unterdrückt (Debug-Log). Einfügestelle deckt Scheduler- und Push-Pfad ab.
Verify: `cd apps/monitoring && python -m pytest -q tests/test_alerter.py` (neue Fälle: Suppression aktiv, agent_ping selbst alarmiert weiter, Server ohne agent_ping unbeeinflusst)
Doku: keine (intern; T34 dokumentiert das Verhalten)
Abhängt von: T3

## Phase 2 — Tag-basierte Template-Zuweisung

### T8 — Server: interner Endpoint GET /api/internal/servers  [x] (require_internal_key wiederverwendet, 4 Tests, Auth-Gate grün)
Komponente: apps/server · Dateien: app/modules/servers/router.py (+ ggf. internes Auth-Dependency wiederverwenden), tests/
Änderung: `GET /api/internal/servers` (X-Internal-Key, Muster wie `/api/internal/events`) → `[{id, hostname, name, tags}]`.
Verify: `source .devenv.sh && cd apps/server && DATABASE_URL="$AH_TEST_DB" python -m pytest -q tests/ -k internal_servers` (ohne Key 401/403, mit Key Liste inkl. Tags)
Doku: keine (intern; developer-Doku in T35)

### T9 — Migration M2 + Tag-Assignment-Modell + CRUD  [x] (a5c7e9b1d3f5, source-Spalte, Slash-Guard, 9 neue Tests)
Komponente: apps/monitoring · Dateien: app/models.py, alembic/versions/<neu>_tag_assignments.py, app/routers/templates.py (+ app/schemas.py)
Änderung: `MonitorTemplateTagAssignment` (unique `(template_id, tag)`) + Spalte `source` (`manual|tag`, Default `manual`) auf `monitor_template_assignments`; Endpoints `POST /templates/{id}/assign-tag`, `DELETE /templates/{id}/assign-tag/{tag}`; Tag-Zuweisungen in Template-`to_dict` (`tagAssignments`).
Verify: `cd apps/monitoring && python -m pytest -q tests/test_migrations_smoke.py tests/test_templates_router.py` (CRUD + Unique-Konflikt 409)
Doku: keine (intern)
Abhängt von: T1

### T10 — Tag-Sync-Engine + Trigger + Safety-Net-Job  [x] (tag_sync.py, None≠[]-Semantik, manual gewinnt, 10 Tests)
Komponente: apps/monitoring · Dateien: app/tag_sync.py (neu, SPDX), app/routers/templates.py, app/scheduler.py
Änderung: `sync_tag_assignments()`: holt `GET {SERVER_HUB_URL}/api/internal/servers`, materialisiert pro Tag-Zuweisung fehlende Assignments via `apply_template` (source=`tag`; existiert bereits manuell → überspringen) und entfernt verwaiste source=`tag`-Assignments via `remove_template`. Trigger: `POST /templates/tag-sync` + Aufruf nach Tag-Assignment-CRUD + Scheduler-Job alle 15 min (best-effort, Fehler geloggt).
Verify: `cd apps/monitoring && python -m pytest -q tests/test_tag_sync.py` (materialisiert/entfernt korrekt; manuelle Assignments unangetastet; Hub nicht erreichbar → kein Crash)
Doku: keine (intern; developer-Doku in T35)
Abhängt von: T8, T9

### T11 — Server: Tag-Sync-Notify bei Server-Änderungen  [x] (best-effort Notify create/update/delete, 4 Tests)
Komponente: apps/server · Dateien: app/modules/servers/router.py, tests/
Änderung: Nach Server-Create/-Update(mit Tag-/Name-/Hostname-Änderung)/-Delete best-effort `POST /templates/tag-sync` ans Monitoring (Muster wie bestehender Cleanup-Call in `servers/router.py`).
Verify: `source .devenv.sh && cd apps/server && DATABASE_URL="$AH_TEST_DB" python -m pytest -q tests/ -k tag_sync` (Call gemockt ausgelöst; Monitoring down → Server-Op erfolgreich, Fehler geloggt)
Doku: keine (intern)
Abhängt von: T10

## Phase 3 — Template-Verwaltung im Desktop-Client

### T12 — API-Client: Tag-Assignment-Wrapper + Typen  [x] (2 Wrapper + Typen, Test-Tabelle vervollständigt)
Komponente: apps/desktop/ui · Dateien: src/lib/api/monitoring.ts, src/lib/api/types.ts
Änderung: `assignTemplateTag`/`unassignTemplateTag` + `tagAssignments` in `MonitoringTemplateFull`; Typen strict, kein `any`.
Verify: `cd apps/desktop/ui && npm run check && npm run lint`
Doku: keine (intern)
Abhängt von: T9

### T13 — Template-Modal: Zuweisungen editierbar (Server + Tags, Bulk)  [x] (Live-Store-Ableitung, Bulk + Tags, 12 Tests)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/MonitoringTemplateModal.svelte, src/lib/stores/monitoring.ts, src/lib/i18n/
Änderung: Read-only-Pills ersetzen durch verwaltbare Zuweisungs-Sektion: Server-Mehrfachauswahl (Bulk-Assign/-Unassign über vorhandene `assignTemplate`/`unassignTemplate`) + Tag-Zuweisung (T12); i18n-Keys DE+EN.
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/MonitoringTemplateModal.test.ts` (Komponententest: assign/unassign/bulk rufen API, Fehlerpfad zeigt Meldung)
Doku: keine (intern; Bedien-Doku in T34)
Abhängt von: T12

### T14 — Server-Detail: Templates-Sektion im Monitoring-Tab  [x] (Pills + Badge + Dropdown, Refresh-Pin, 3 Tests)
Komponente: apps/desktop/ui · Dateien: src/components/infra/tabs/MonitoringTab.svelte, src/lib/i18n/
Änderung: Sektion „Templates“: zugewiesene Templates (via `fetchAssignments`) mit Entfernen-Aktion + Dropdown „Template zuweisen“; Badge „Standard“ bei `builtinSlug`.
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/infra/tabs/MonitoringTab.test.ts`
Doku: keine (intern; Bedien-Doku in T34)
Abhängt von: T12

### T15 — ServerModal: Opt-in-Template-Dropdown beim Anlegen  [x] (Built-ins zuerst, Assign best-effort im Store, 7 Tests)
Komponente: apps/desktop/ui · Dateien: src/components/infra/ServerModal.svelte, src/lib/i18n/
Änderung: Beim Anlegen (nicht Editieren) Dropdown „Monitoring-Template (optional)“, Default leer; nach erfolgreichem Create wird `assignTemplate` mit den Serverdaten aufgerufen; Fehler beim Assign bricht das Server-Anlegen nicht ab (Toast).
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/infra/modals.regression.test.ts src/components/infra/ServerModal.test.ts` (Create ohne Auswahl = kein Assign; mit Auswahl = Assign mit server_id/hostname/name)
Doku: keine (intern; Bedien-Doku in T34)

## Phase 4 — GUI/Design Monitoring-Seite

### T16 — Desktop-UI-Primitives: Modal, ConfirmDialog, EmptyState  [x] (Web-Port inkl. aller Hardening-Fixes, 6 Tests)
Komponente: apps/desktop/ui · Dateien: src/components/ui/Modal.svelte, src/components/ui/ConfirmDialog.svelte, src/components/ui/EmptyState.svelte (alle neu, SPDX)
Änderung: Primitives nach Vorbild `apps/web/src/lib/components/ui/` in Svelte-5-Runes portieren (Overlay, Fokus-Handling, Escape, Slots); Design streng nach dem adoptierten AdminCave-Design-System (Tokens/Patterns aus der Design-Adoption, nichts Neues erfinden) — Design-Pass ausdrücklich Teil des Auftrags.
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/ui/` (Rendern, Escape schließt, Confirm ruft Callback)
Doku: keine (intern)

### T17 — Monitoring-Modals auf Primitives umstellen (inkl. Design)  [x] (3 Modals migriert, Review fand Stacked-Escape-Bug → modalStack-Fix im Primitive. Merker: Web-Modal hat dieselbe Escape-Schwäche — portieren, falls Web je confirmDialog aus einem offenen Modal ruft)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/AlertRuleModal.svelte, src/components/monitoring/MonitorCheckModal.svelte, src/components/monitoring/MonitoringTemplateModal.svelte
Änderung: Dupliziertes `.editor-overlay`/`.editor-panel`-CSS entfernen, auf `Modal` umstellen; Zwei-Klick-Delete durch `ConfirmDialog` ersetzen; visuelles Design vereinheitlichen (Abstände, Buttons, Formular-Layout) — streng nach AdminCave-Design-System, keine neuen Stil-Erfindungen.
Verify: `cd apps/desktop/ui && npm run check && npm run lint && npm run test` (bestehende + angepasste Modal-Tests grün)
Doku: keine (intern)
Abhängt von: T16, T13

### T18 — Check-CRUD auf der Monitoring-Seite  [x] (Store-getriebener Editor-State, Add-Button + Edit-Icon, 2 Tests)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/MonServerDashboard.svelte, src/components/monitoring/section/MonCheckLine.svelte, src/lib/stores/monitoring.ts
Änderung: „Neuer Check“-Button im Server-Dashboard (öffnet `MonitorCheckModal` mit vorbelegtem Server) + Edit-Aktion an der Check-Zeile; Store lädt nach Create/Edit/Delete neu.
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/` (Button/Edit öffnen Modal mit korrektem Kontext)
Doku: keine (intern; Bedien-Doku in T34)
Abhängt von: T17

### T19 — Overview: Loading-/Empty-/Error-States  [x] (hasLoaded-Gate gegen Refresh-Flackern + Kaltstart-Flash, Inline-Error mit Retry, 5 Tests. MonServerList bewusst unangefasst — Overview-Gating deckt sie ab)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/MonitoringOverview.svelte, src/components/monitoring/MonServerList.svelte, src/lib/stores/monitoring.ts
Änderung: `loading`-Flag des Stores konsumieren (Skeleton beim Erstladen), `EmptyState` für „keine Server/Checks“ (mit CTA „Template zuweisen“), Fehlerzustand inline mit Retry statt nur Status-Bar-Toast.
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/MonitoringOverview.test.ts` (drei Zustände gerendert)
Doku: keine (intern)
Abhängt von: T16

### T20 — Validierungs-Fixes in Monitoring-Formularen  [x] (Bounds = T4-Spiegel, warn≥crit-Hinweis, Cooldown-Clamp, info-Option, check_restarts raus, hysteresis_pp-Feld. Kandidat notiert: Backend Field(ge=0) für cooldown_minutes in AlertRuleCreate/TemplateAlertDef)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/AlertRuleModal.svelte, src/components/monitoring/CheckConfigFields.svelte
Änderung: Zahlenfelder gegen negative/unsinnige Werte begrenzen (cooldown ≥ 0, Thresholds 0–100 wo prozentual, warn < crit-Hinweis); Severity-Optionen konsistent zu `VALID_SEVERITIES` (info/warning/critical).
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/` (invalide Eingaben blockiert)
Doku: keine (intern)
Abhängt von: T17

## Phase 5 — Host-Grid + Heartbeat

### T21 — MonServerGrid: Kachel-Ansicht mit View-Toggle  [x] (worst-*-Modifier gegen globales Klassen-Leck, Pill-Parität, localStorage-Persistenz, 4 Tests)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/MonServerGrid.svelte (neu, SPDX), src/components/monitoring/MonitoringOverview.svelte, src/lib/stores/monitoring.ts
Änderung: Kachel pro Server (Worst-State-Farbe, Status-Count-Pills, Klick selektiert Server und wechselt ins Dashboard); Toggle Liste ⇄ Grid im Overview, Auswahl persistent (localStorage im Store).
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/MonServerGrid.test.ts` (Worst-State-Berechnung, Toggle persistiert)
Doku: keine (intern; Bedien-Doku in T34)
Abhängt von: T19

### T22 — MonHeartbeatBar: Verfügbarkeits-Balken  [x] (Lazy-Timeline via MonStatusTimeline-Reuse, untrack-Fix gegen Effect-Loop, 2 Tests. Merker: MonSparkline hat denselben latenten untrack-Fallback-Bug — in Produktion unerreichbar, bei Gelegenheit fixen)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/MonHeartbeatBar.svelte (neu, SPDX), src/components/monitoring/MonServerGrid.svelte, src/components/monitoring/MonServerDashboard.svelte
Änderung: Segment-Balken der letzten 24 h aus der Status-Timeline des `agent_ping`-Checks (`fetchMetrics`, lazy via IntersectionObserver wie `MonSparkline`); in Grid-Kachel + Dashboard-Header; Server ohne agent_ping → ausgeblendet.
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/MonHeartbeatBar.test.ts` (Segmente aus Timeline, lazy-load)
Doku: keine (intern)
Abhängt von: T21

## Phase 6 — Maintenance-Fenster

### T23 — Migration M3 + MonitorMaintenance + is_in_maintenance  [x] (b7d9f1a3c5e7, zoneinfo-DST-Logik, Out-of-range-Guard, 12 Tests)
Komponente: apps/monitoring · Dateien: app/models.py, alembic/versions/<neu>_maintenance.py, app/maintenance.py (neu, SPDX)
Änderung: Modell laut Spec (kind `once|weekly`, `server_id` NULL = alle Server, `timezone` IANA-String) + reine Logik `is_in_maintenance(windows, server_id, now_utc)` (einmalig: naive-UTC starts/ends; wöchentlich: Auswertung in der Fenster-Zeitzone via stdlib-`zoneinfo`, DST-korrekt, inkl. Mitternachts-Überlauf).
Verify: `cd apps/monitoring && python -m pytest -q tests/test_maintenance.py tests/test_migrations_smoke.py` (Fenster-Logik inkl. Wochen-Überlauf, NULL-Scope, DST-Wechsel-Fall Europe/Berlin)
Doku: keine (intern)
Abhängt von: T9

### T24 — Maintenance-Router + Proxy-Allowlist  [x] (CRUD + ZoneInfo-Validierung + Proxy-Prefix, 3+1 Tests)
Komponente: apps/monitoring + apps/server · Dateien: app/routers/maintenance.py (neu, SPDX), app/routers/__init__.py, apps/server/app/modules/monitoring_proxy/router.py
Änderung: `GET/POST /maintenance`, `PUT/DELETE /maintenance/{id}` (X-Internal-Key, Pydantic-Validierung: kind-abhängige Pflichtfelder, weekdays 0–6, HH:MM, `timezone` gegen ZoneInfo-Konstruktion validieren — Review-Hinweis aus T23: sonst bleibt der UTC-Fallback ein Typo-Fänger); `maintenance` in `_ALLOWED_PATH_PREFIXES` des Server-Proxys.
Verify: `cd apps/monitoring && python -m pytest -q tests/test_maintenance_router.py` && `source .devenv.sh && cd apps/server && DATABASE_URL="$AH_TEST_DB" python -m pytest -q tests/ -k monitoring_proxy`
Doku: keine (intern; T34/T35)
Abhängt von: T23

### T25 — Maintenance-Suppression in process_alert  [x] (Guard-Kette unknown→maintenance→host-down, 4 Tests)
Komponente: apps/monitoring · Dateien: app/alerter.py
Änderung: Aktives Fenster für `check.server_id` (oder globales Fenster) ⇒ Dispatch + Hub-Emit unterdrückt, kein Alert-Log-Eintrag; Zustands-Übergänge selbst laufen weiter („collect but mute“).
Verify: `cd apps/monitoring && python -m pytest -q tests/test_alerter.py -k maintenance` (im Fenster still, danach wieder aktiv; globales Fenster wirkt auf alle)
Doku: keine (intern; T34)
Abhängt von: T23, T7

### T26 — Maintenance-UI: Verwaltung + API-Client  [x] (Modal + Tab-Liste, TZ-Default Client, lokal↔UTC, 5 Tests)
Komponente: apps/desktop/ui · Dateien: src/lib/api/monitoring.ts (+types), src/components/monitoring/MaintenanceModal.svelte (neu, SPDX), src/components/infra/tabs/MonitoringTab.svelte
Änderung: API-Wrapper für `/api/monitoring/maintenance`; Modal (einmalig/wöchentlich; `timezone`-Default = Client-Zeitzone, einmalige Fenster lokal↔UTC konvertiert) + Verwaltungs-Liste im Monitoring-Tab des Servers; i18n DE+EN.
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/MaintenanceModal.test.ts` (TZ-Default, UTC-Konvertierung einmaliger Fenster, kind-abhängige Felder)
Doku: keine (intern; Bedien-Doku in T34)
Abhängt von: T24, T16

### T27 — Maintenance-Badge in Übersicht  [x] (Client-Spiegel von is_in_maintenance via Intl, Badge Liste+Grid, 5+1 Tests)
Komponente: apps/desktop/ui · Dateien: src/lib/stores/monitoring.ts, src/components/monitoring/MonServerListItem.svelte, src/components/monitoring/MonServerGrid.svelte
Änderung: Store lädt Maintenance-Fenster mit und berechnet „aktiv jetzt“ pro Server; Badge/Icon in Listen-Zeile und Grid-Kachel (Uptime-Kuma-Konvention: gedämpfte Farbe).
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/` (Badge bei aktivem Fenster)
Doku: keine (intern)
Abhängt von: T26, T21

## Phase 7 — Disk-voll-Prediction

### T28 — Checker disk_forecast  [x] (Least-Squares-Forecast, escape_label_value geteilt, Metrics-Endpoint-Eintrag + Fallback-Suffix-Fix, 11 Tests)
Komponente: apps/monitoring · Dateien: app/checkers/forecast.py (neu, SPDX), app/checkers/__init__.py, app/check_types.py
Änderung: Neuer Pull-Check `disk_forecast` (push_only False): `victoria.query_range()` über `monitor_agent_disk_percent{server_id=…}` (window_hours 24, Step 10 m), lineare Regression pro Mount, Restzeit bis 100 %; Grade `warn_hours` 24 / `crit_hours` 8; < min_history_hours (6) oder Rate ≤ 0 ⇒ ok/unknown laut Spec; `_details` mit Restzeit pro Mount; Config-Modell in `check_configs.py` ergänzen.
Verify: `cd apps/monitoring && python -m pytest -q tests/test_checker_forecast.py` (Regression deterministisch: steigende Serie → Restzeit, flache Serie → ok, zu wenig Daten → unknown)
Doku: keine (intern; T34)
Abhängt von: T4

### T29 — disk_forecast: UI-Felder + Aufnahme in Built-ins  [x] (4 Editor-Felder, Typ-Union, linux+windows-Built-ins, Seed-Tests erweitert)
Komponente: apps/desktop/ui + apps/monitoring · Dateien: src/components/monitoring/CheckConfigFields.svelte, src/lib/i18n/, apps/monitoring/app/builtin_templates.py
Änderung: Config-Felder (warn_hours/crit_hours/window_hours) im Check-Editor; `disk_forecast`-Def (interval 1h, severity warning) in `linux-base` + `windows-base` ergänzen (neue def_id — Live-Sync verteilt sie an zugewiesene Server; Seed-Tombstone bleibt unberührt).
Verify: `cd apps/desktop/ui && npm run check` && `cd apps/monitoring && python -m pytest -q tests/test_seed.py` (Built-ins enthalten forecast-Def, Sync-Test grün)
Doku: keine (intern; T34)
Abhängt von: T28, T5

## Phase 8 — Out-of-the-box-Benachrichtigung & Betrieb

### T30 — Default-Subscription für neue Admin-User  [x] (alle 4 Admin-Create-Pfade: API, CLI, Env, Bootstrap-Endpoint — 6d308a8)
Komponente: apps/server · Dateien: User-Create-Pfade (users-Router + create-admin-Einstieg), Nutzung von notifications/models.py
Änderung: Beim Anlegen eines Users mit `is_admin=True` (API **und** `create-admin`) automatisch eine `NotificationSubscription` anlegen (scope `all`, `min_severity` `warning`, Glocke/Desktop an, E-Mail/Telegram aus) — sonst erreicht auf Frisch-Installationen kein Alert irgendjemanden (`resolve_recipients` iteriert nur über existierende Subscriptions). Bewusst kein Backfill für Bestands-Admins.
Verify: `source .devenv.sh && cd apps/server && DATABASE_URL="$AH_TEST_DB" python -m pytest -q tests/ -k default_subscription` (Admin-Create legt Subscription an, Non-Admin nicht)
Doku: keine (intern; CHANGELOG in T35)

### T31 — alert.triggered-Hook implementieren  [x] (Ingest feuert bei critical-Transition; Payload = Ingress-Pass-Through {server_id, severity, title, message} — check_name/old_status/new_status sind nicht im Monitoring→Server-Contract; Doku DE+EN — d12b10e. Merker: Web-HOOK_EVENTS-Picker (apps/web/src/lib/utils/hooks.ts) driftet gegen VALID_EVENTS — playbook.* fehlte schon vorher, jetzt auch alert.triggered + i18n-Keys; Follow-up mit Sync-Guard-Test analog test_event_whitelist)
Komponente: apps/server · Dateien: app/modules/notifications/router.py, app/modules/hooks/schemas.py
Änderung: Im internen Ingest (`/api/internal/events`): bei `event_type == "monitoring.check.transition"` mit Severity `critical` zusätzlich `fire_event("alert.triggered", {server_id, check_name, old_status, new_status, message})`; `"alert.triggered"` in die Event-Liste in hooks/schemas.py aufnehmen — macht die bestehende Doku-Aussage wahr.
Verify: `source .devenv.sh && cd apps/server && DATABASE_URL="$AH_TEST_DB" python -m pytest -q tests/ -k alert_triggered` (critical → fire_event aufgerufen; warning/info → nicht)
Doku: docs/developer/hooks.html + docs/en/developer/hooks.html (Event-Liste) im selben Commit

### T32 — Bulk-CTA „Server ohne Checks“  [x] (serversWithoutChecks-Derived, Banner + Modal-Dialog mit Vorselektion, Built-ins zuerst, 3 Tests — 4989294)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/MonitoringOverview.svelte, src/lib/stores/monitoring.ts, src/lib/i18n/
Änderung: Store berechnet Server ohne einen einzigen Check; Banner im Overview („N Server ohne Monitoring“) öffnet den Bulk-Zuweisungs-Dialog aus T13 mit vorselektierten Servern (Template im Dialog wählbar, Built-ins zuerst).
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/MonitoringOverview.test.ts` (Banner nur bei Servern ohne Checks; Aktion öffnet Dialog vorselektiert)
Doku: keine (intern; Bedien-Doku in T34)
Abhängt von: T13, T19

### T33 — Retention env-konfigurierbar  [x] (config.py-Env mit Fallback-Guards, Compose VM_RETENTION + Passthrough + Drift-Kommentare, 4 Tests — Commit siehe git log)
Komponente: apps/monitoring + Root · Dateien: app/core/config.py, app/scheduler.py, docker-compose.yml
Änderung: `ALERT_LOG_RETENTION_DAYS` aus Env (Default 90) statt Konstante in scheduler.py; VictoriaMetrics-Command auf `-retentionPeriod=${VM_RETENTION:-90d}` umstellen; Compose-Kommentar zum Drift-Risiko (zwei getrennte Stellhebel).
Verify: `cd apps/monitoring && python -m pytest -q tests/ -k retention` (Env greift, Default 90) && `python -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"`
Doku: keine (intern; README-Env-Tabelle + CHANGELOG in T35)

## Phase 9 — Doku

### T34 — Admin-Doku DE+EN: Fehler fixen + Neues dokumentieren  [x] (beide Seiten komplett neu strukturiert + synchron, Fakten gegen Code verifiziert; Review-Fixes: Sparkline-Behauptung raus, Hysterese auf agent_resources eingegrenzt. Merker für T35: Proxy-Allowlist-/SSRF-Hinweis in docs/developer/monitoring.html aufnehmen)
Komponente: docs · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html
Änderung: Threshold-Doku-Fehler fixen (`warn_threshold`/`crit_threshold`-Modell durch echte per-Typ-Config-Keys ersetzen); `alert.triggered`-Abschnitt an den implementierten Hook (T31) angleichen (Auslösebedingung + Payload); neue Abschnitte: Standard-Templates + Schwellwert-Tabelle, Zuweisung (Dialog/Server/Tag/Bulk-CTA), unknown-Policy, Hysterese, Host-down-Suppression, Maintenance-Fenster (inkl. Zeitzonen-Verhalten und Hinweis: Transitionen, die vollständig IM Fenster passieren, werden nach Fenster-Ende nicht nachgemeldet — Alerter ist transitionsbasiert), disk_forecast, Grid/Heartbeat-Ansicht, Default-Subscription. Beide Sprachen synchron.
Verify: `! grep -q "warn_threshold" docs/admin/monitoring.html docs/en/admin/monitoring.html && grep -qi "Linux Server" docs/admin/monitoring.html docs/en/admin/monitoring.html`
Doku: ist die Doku
Abhängt von: T29, T27, T31, T32

### T35 — Developer-Doku, README, CHANGELOG  [x] (Dev-Doku DE+EN: Seeding/Tag-Sync/Guards/Liveness/Forecast/Chart-Allowlist; README-Env-Tabelle; CHANGELOG Unreleased; .env.example ergänzt — 40fecac)
Komponente: docs + Root · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, README.md, CHANGELOG.md
Änderung: Developer-Doku: Seeding-Mechanik (seed_state/Tombstone), `GET /api/internal/servers`, Tag-Sync-Datenfluss, Maintenance-Suppression (inkl. zoneinfo), forecast-Query, Liveness-Persistenz; README-Monitoring-Abschnitt + Env-Tabelle (`ALERT_LOG_RETENTION_DAYS`, `VM_RETENTION`) aktualisieren; CHANGELOG (Added: Templates/Seeding/Tag/Maintenance/Forecast/Grid/Default-Subscription/alert.triggered-Hook/Retention-Env; Changed: unknown-Policy, stale-Default 15, Host-down-Suppression).
Verify: `grep -q "tag-sync\|tag_sync" docs/developer/monitoring.html && grep -q "monitoring" CHANGELOG.md`
Doku: ist die Doku
Abhängt von: T34

## Phase 10 — Code-Review-Findings (Abschluss-Review, 15 CONFIRMED)

### T36 — alert.triggered nur bei echtem critical-Übergang  [x] (new_status im Hub-Payload + Ingest-Guard, Doku 4 Stellen — 567e6e0)
Komponente: apps/monitoring + apps/server · Dateien: app/alerter.py (_emit_to_hub), server notifications/schemas.py + router.py
Änderung: Hub-Severity ist worse-of-both, daher feuert der Hook auch bei critical→ok/critical→warning (F3). Fix: `_emit_to_hub` sendet zusätzlich optionales `new_status`; Ingest feuert den Hook nur bei `new_status == "critical"` (Fallback aufs alte Verhalten, wenn Feld fehlt). Doku hooks.html DE+EN Auslösebedingung präzisieren.
Verify: pytest -k alert_triggered (Recovery mit severity critical + new_status ok feuert NICHT)

### T37 — server_id-Fallback für agent_ping/disk_forecast  [x] (resolve_config_server_id in check_engine, 4 Tests — c3f709c)
Komponente: apps/monitoring · Dateien: app/check_engine.py (bzw. Aufruf-Pfade)
Änderung: Handangelegte Checks ohne config.server_id sind ewig unknown (F5) — execute_check reichert config um `check.server_id` an, wenn der Typ es braucht und es fehlt.
Verify: pytest (neuer Test: agent_ping-Check mit leerer config + server_id-Spalte liefert nicht "No server_id configured")

### T38 — Hysterese-Memory überlebt unknown-Push  [x] (None-Details-Guard + Test — c3f709c)
Komponente: apps/monitoring · Dateien: app/routers/agent.py
Änderung: `details_json = json.dumps(details) if details else None` nullt state.details bei unknown-Evaluation und löscht die problems-Map (F6). Fix: bei None-Details den Bestand behalten.
Verify: pytest -k hysteresis (Push ohne resources-Block löscht prev_problems nicht)

### T39 — Default-Subscription auch bei Admin-Promotion  [x] (update_user-Guard, 3 Tests — 1751cc3)
Komponente: apps/server · Dateien: app/modules/users/router.py (update_user)
Änderung: PUT /api/users/{id} mit is_admin False→True legt die Baseline-Regel an, wenn der User noch keine Subscription hat (F8).
Verify: pytest -k default_subscription (Promotion legt an; Re-Promotion/vorhandene Regel dupliziert nicht)

### T40 — Legacy-Configs bleiben editierbar  [x] (skip-if-unchanged auf effective_type-Basis, UI-Payload-Test — c3f709c; Review-Blocker gefixt)
Komponente: apps/monitoring · Dateien: app/routers/checks.py
Änderung: PUT re-validiert unveränderte Bestands-Configs → Alt-Checks mit Extra-Key sind uneditierbar (F9). Fix: Validierung beim Update überspringen, wenn die Config unverändert zur gespeicherten ist.
Verify: pytest (Update nur des Intervalls bei gespeicherter Config mit Extra-Key → 200)

### T41 — Proxy forwardet Raw-Pfad (Encoding erhalten)  [x] (raw_path-Forward, Guard bleibt auf dekodiertem Pfad — 1751cc3)
Komponente: apps/server · Dateien: app/modules/monitoring_proxy/router.py
Änderung: Der dekodierte Pfad wird re-embedded — %23/%3F im Tag truncatet die Forward-URL (F10). Fix: Pfad aus request.scope["raw_path"] (hinter dem Prefix) übernehmen.
Verify: pytest (DELETE assign-tag/web%231 erreicht Monitoring mit Tag "web#1")

### T42 — cleanup_server räumt Maintenance + Liveness  [x] (server-scoped Fenster + Liveness-Row, globales Fenster überlebt — c3f709c)
Komponente: apps/monitoring · Dateien: app/template_sync.py (cleanup_server)
Änderung: Server-Delete hinterlässt MonitorMaintenance-Fenster (unlöschbar in der UI) und MonitorAgentLiveness-Rows (F11). Beide mitlöschen.
Verify: pytest -k cleanup (beide Tabellen leer nach cleanup_server)

### T43 — disk_forecast-Sektion im Server-Dashboard  [x] (SecForecast.svelte + Types + i18n — 22cd30e)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/MonServerDashboard.svelte
Änderung: disk_forecast hat keinen Render-Bucket — Phantom-Warning ohne sichtbare Ursache (F12). Sektion ergänzen (+ i18n-Key).
Verify: npx vitest run src/components/monitoring/ && npm run check

### T44 — Cooldown 0 bleibt 0  [x] (beide Modals + Backend ge=0, 0-bleibt-0-Test — c3f709c/22cd30e)
Komponente: apps/desktop/ui + apps/monitoring · Dateien: AlertRuleModal.svelte, MonitoringTemplateModal.svelte, app/schemas.py
Änderung: `Math.max(0, x || 30)` macht aus expliziter 0 wieder 30 (F13). Fix: Fallback nur bei NaN/leer; Backend-Backstop `ge=0` für cooldown_minutes (Merker aus T20).
Verify: npx vitest run (0 bleibt 0) && pytest (negativer Cooldown → 422)

### T45 — Server-Anlege-Opt-in toleriert Tag-Sync-Race  [x] (409 als Erfolg im Create-Pfad + Test — 22cd30e)
Komponente: apps/desktop/ui · Dateien: src/lib/stores/infra.ts
Änderung: Opt-in-Assign racet gegen den synchronen Tag-Sync → 409-Toast für korrekt eingerichtete Server (F15). Conflict („bereits zugewiesen") im Create-Pfad als Erfolg behandeln.
Verify: npx vitest run src/lib/stores/infra.test.ts

### T46 — Tag-Sync-Notify blockiert Server-CRUD nicht  [x] (Single-Worker-Pool fire-and-forget, Dauer-Test — 1751cc3)
Komponente: apps/server · Dateien: app/modules/servers/router.py
Änderung: Synchroner 5s-Notify vor kürzerem Callee-Deadline → langsame Saves + spurious ReadTimeout-Warnings (F14). Notify fire-and-forget in den Event-Thread-Pool auslagern.
Verify: pytest -k tag_sync (CRUD-Antwort wartet nicht auf den Notify; Notify wird weiterhin gefeuert)

### T47 — Alert-Semantik ohne Sent-State  [?]
F1 (Host-down edge-triggered: Alert geht verloren, wenn der Check nach Host-Recovery critical BLEIBT; Recovery ohne gesendeten Alert), F2 (Maintenance: Recovery für VOR dem Fenster gesendete Alerts entfällt — Catch-up wäre neues Feature; „keine Nachmeldung IM Fenster" ist dokumentierte Gate-Entscheidung), F7 (ok→unknown→ok-Flapping erzeugt Recovery-Spam für nie gemeldete Incidents). Gemeinsame Wurzel: der Alerter ist rein transitionsbasiert, es gibt kein „Alert wurde gesendet"-State. Sauber lösbar nur mit Sent-State-Tracking (Alertmanager-Level-Semantik: Re-Emit bei Suppression-Release, Recovery nur nach gesendetem Alert). ENTSCHEIDUNG NÖTIG: Sent-State-Feature als Folge-Vorhaben planen, oder Ist-Verhalten dokumentieren und akzeptieren?
Merker (kein Fix, pre-existing): restore.sh ist auf Warm-Boxen nicht idempotent — `find data -mindepth 1 -delete 2>/dev/null || true` lässt root-owned Reste (Container-Writes) stehen, das folgende `tar xzf` scheitert als non-root an `Cannot utime` (Zweitlauf von backup_restore_test rot; Erstlauf grün). Fix-Kandidat: `tar -m` oder sudo-Cleanup in restore.sh. Unabhängig vom Branch-Diff (Workaround: data/ auf der Box löschen).
Merker (kein Fix): F4 — agent_ping-Staleness ist seit T6 wall-clock-basiert (Persistenz erfordert das); NTP-Step > stale_minutes erzeugte einen fleet-weiten False-Positive-Sturm. Bewusster Trade-off, ggf. später Slew-Guard.
