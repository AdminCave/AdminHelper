<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Überarbeitung: Standard-Templates, Verwaltung, Alert-Qualität

## Problem / Motivation

Eine frische AdminHelper-Installation überwacht **nichts**: kein Seeding von
Templates/Checks/Alert-Regeln (weder Alembic, noch Lifespan, noch `install.sh`).
Das vorhandene Template-System (`MonitorTemplate` + Live-Sync via
`template_sync.py`) ist der vorgesehene Träger für Standard-Monitoring, wird
aber nie befüllt — und die Template-Zuweisung ist im Desktop-Client eine
Sackgasse: die Client-API (`assignTemplate`/`unassignTemplate`/`fetchAssignments`,
`apps/desktop/ui/src/lib/api/monitoring.ts:133-164`) existiert vollständig,
wird aber von keiner Komponente aufgerufen. Dazu Alert-Qualitäts-Lücken
(`unknown` eskaliert wie ein Failure; `agent_ping` verliert seinen Zustand bei
Neustart → False Alerts; keine Hysterese; keine Host-down-Unterdrückung; keine
Wartungsfenster) und UX-Schwächen (Check-CRUD nur unter Infrastruktur → Server,
kein Loading/Empty-State, dupliziertes Modal-CSS, keine Bulk-Aktionen).

## Ziel & Nicht-Ziele

**Ziel:**
1. Out-of-the-box-Monitoring: eingebaute Standard-Templates (englische Namen),
   idempotent beim Start geseedet; Zuweisung per Opt-in-Dropdown beim
   Server-Anlegen sowie voll verwaltbar im Client (Server-, Bulk- und
   Tag-basiert).
2. Alert-Qualität: `unknown` benachrichtigt nie; `agent_ping` überlebt
   Neustarts; Hysterese; Host-down-Suppression; Maintenance-Fenster
   (einmalig + wöchentlich); Disk-voll-Prediction.
3. GUI: Check-CRUD auf der Monitoring-Seite, gemeinsame UI-Primitives
   (Modal/ConfirmDialog/EmptyState) inkl. Design-Überarbeitung der drei
   Monitoring-Modals, Loading/Empty/Error-States, Host-Kachel-Grid +
   Heartbeat-Bar, Validierungs-Fixes, Bulk-CTA für Server ohne Checks.
4. Benachrichtigung out-of-the-box: neue Admin-User bekommen automatisch
   eine Default-Subscription (Glocke + Desktop, scope `all`, min. `warning`)
   — ohne Subscription erreicht heute kein Alert irgendjemanden
   (`resolve_recipients` iteriert nur über existierende Subscriptions);
   der dokumentierte `alert.triggered`-Hook wird implementiert statt aus
   der Doku gestrichen.
5. Betrieb: Alert-Log- und VictoriaMetrics-Retention env-konfigurierbar
   (`ALERT_LOG_RETENTION_DAYS`, `VM_RETENTION`).
6. Doku: verbleibenden Doku-Fehler fixen (Threshold-Modell), alles Neue
   DE+EN dokumentieren.

**Nicht-Ziele (bewusst raus):**
- Kein Monitoring im Web-Frontend (bleibt desktop-exklusiv).
- Keine Auto-Zuweisung nach OS-Typ (User-Entscheidung: Opt-in im Dialog).
- Kein SSE/WebSocket für Monitoring-Status (30s-Polling bleibt).
- Keine Vereinheitlichung Alert-Regeln ↔ Notification-Subscriptions.
- Kein Telegram-Kanal.
- Keine Konsolidierung des duplizierten Push-Pfads (`routers/agent.py` ↔
  `check_engine.py`) über das Nötige hinaus — Änderungen betreffen beide Pfade
  über die gemeinsame Stelle `process_alert()`.

## Betroffene Komponenten & Dateien

- **Monitoring-Backend** (`apps/monitoring/`): `app/models.py`, neue Alembic-
  Migrationen (Kette nach `d9e1f3a5b7c2`), `app/main.py` (Lifespan-Seed),
  neu `app/builtin_templates.py`, `app/check_configs.py`, `app/tag_sync.py`,
  `app/checkers/forecast.py`; `app/check_types.py`, `app/checkers/agent.py`,
  `app/check_engine.py`, `app/alerter.py`, `app/schemas.py`,
  `app/routers/agent.py`, `app/routers/templates.py`, neu
  `app/routers/maintenance.py`, `app/scheduler.py`; Tests unter
  `apps/monitoring/tests/`.
- **Server** (`apps/server/`): `app/modules/servers/router.py` (interner
  Server-Listen-Endpoint + Tag-Sync-Notify), `app/modules/monitoring_proxy/
  router.py` (Allowlist + `maintenance`), `app/modules/notifications/
  router.py` (alert.triggered-Emit), `app/modules/hooks/schemas.py`
  (Event-Registrierung), User-Create-Pfade (Default-Subscription);
  `docker-compose.yml` (VM_RETENTION).
- **Desktop-UI** (`apps/desktop/ui/`): `src/lib/api/monitoring.ts`,
  `src/lib/api/types.ts`, `src/lib/stores/monitoring.ts`,
  `src/components/monitoring/*` (Overview, Modals, neu MonServerGrid,
  MonHeartbeatBar, MaintenanceModal), `src/components/infra/ServerModal.svelte`,
  `src/components/infra/tabs/MonitoringTab.svelte`, neu
  `src/components/ui/{Modal,ConfirmDialog,EmptyState}.svelte`,
  `src/lib/i18n/*` (DE+EN-Keys).
- **Doku:** `docs/admin/monitoring.html` + `docs/en/admin/monitoring.html`,
  `docs/developer/monitoring.html` + EN, `README.md`, `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Drei additive Alembic-Migrationen (Kette nach `d9e1f3a5b7c2`, Downgrades
vorhanden):

**M1 — Seeding + Liveness:**
- `monitor_templates.builtin_slug` (String, nullable, unique) — markiert
  Built-in-Herkunft (UI-Badge „Standard“), Templates bleiben normal
  editier-/löschbar.
- `monitor_seed_state(slug PK, seeded_at)` — Tombstone: einmal geseedete Slugs
  werden nie erneut angelegt (User-Löschung wird respektiert, User-Edits
  werden nie überschrieben).
- `monitor_agent_liveness(server_id PK, last_report_at)` — persistierter
  letzter Agent-Report. `_last_report` wird auf Wall-Clock (naive UTC)
  umgestellt, beim Push zusätzlich in die Tabelle geschrieben und im Lifespan
  hydratisiert → `agent_ping` übersteht Neustarts.

**M2 — Tag-Zuweisung:**
- `monitor_template_tag_assignments(id PK, template_id FK→templates CASCADE,
  tag, UNIQUE(template_id, tag))`.
- `monitor_template_assignments.source` (String, default `'manual'`,
  Werte `manual|tag`) — materialisierte Tag-Zuweisungen sind markiert und
  werden vom Sync verwaltet; manuelle bleiben unangetastet.

**M3 — Maintenance:**
- `monitor_maintenance(id PK, server_id nullable → NULL = alle Server, note,
  kind 'once'|'weekly', starts_at, ends_at, weekdays JSON [0-6],
  start_time 'HH:MM', duration_minutes, timezone IANA-String, enabled,
  created_at)`. Einmalige Fenster: naive-UTC-Timestamps (UI konvertiert
  lokal↔UTC). Wöchentliche Fenster: Auswertung in der Fenster-Zeitzone via
  stdlib-`zoneinfo` (DST-korrekt — „Sonntag 02:00“ bleibt Wanduhr-Zeit);
  Default beim Anlegen = Client-Zeitzone.

**Neue/geänderte API (Monitoring-Dienst, alle `X-Internal-Key`):**
- `POST /templates/{id}/assign-tag` `{tag}` / `DELETE /templates/{id}/assign-tag/{tag}` /
  Tag-Zuweisungen in `GET /templates` (`tagAssignments` im `to_dict`).
- `POST /templates/tag-sync` — stößt die Materialisierung an (ruft der Server
  nach Server-Create/Update/Delete auf; zusätzlich Scheduler-Safety-Net alle 15m).
- `GET/POST /maintenance`, `PUT/DELETE /maintenance/{id}`.
- Proxy-Allowlist (`monitoring_proxy/router.py:43`) um `maintenance` erweitern
  (`templates/…` ist bereits abgedeckt).

**Neue Server-API:** `GET /api/internal/servers` (X-Internal-Key, Muster wie
`/api/internal/events`) → `[{id, hostname, name, tags}]` — einzige Quelle für
Tag-Mitgliedschaft; Monitoring kennt weiterhin nur `server_id`-Strings.

**Weitere Server-seitige Änderungen:**
- Default-Subscription: User-Create mit `is_admin=True` (API + `create-admin`)
  legt eine `NotificationSubscription` an (scope `all`, `min_severity`
  `warning`, Glocke/Desktop an, E-Mail/Telegram aus). Bewusst kein Backfill
  für Bestands-Admins — bewusst gelöschte Regeln dürfen nicht
  wiederauferstehen.
- `alert.triggered`-Hook: der interne Event-Ingest feuert bei
  `monitoring.check.transition` mit Severity `critical` zusätzlich
  `fire_event("alert.triggered", …)`; Event in `hooks/schemas.py`
  registriert — die bisher falsche Doku-Aussage wird damit wahr.
- Retention konfigurierbar: `ALERT_LOG_RETENTION_DAYS` (Monitoring-Env,
  Default 90) und `VM_RETENTION` (Compose-Variable für `-retentionPeriod`,
  Default `90d`) — zwei getrennte Stellhebel, Drift-Hinweis in Doku und
  Compose-Kommentar.

**Kein Vertrags-Drift:** Agent-Wire-Format unverändert (JSON-Push).
Desktop-Client bekommt nur additive API-Wrapper. Web unberührt.

## Built-in-Templates (Inhalte)

Englische Namen (Konvention: user-facing Strings englisch). Keine
`alert_definitions` — Benachrichtigungen laufen out-of-the-box über den
Notification-Hub; Alert-Regeln (Webhook/E-Mail) bleiben Opt-in. Schwellwerte
destilliert aus Zabbix-„Linux by Zabbix agent“, Netdata-Stock-Health,
Checkmk-Defaults und Backblaze-SMART-Empirie (Recherche 2026-07-15):

| Slug | Name | Checks (Kern-Config) |
|---|---|---|
| `linux-base` | Linux Server — Standard | `agent_ping` (stale 15m, cf 1) · `agent_resources` (cpu 90/95, mem 90/98, disk 80/90, temp 80/95, cf 3) · `service_process` (mode auto, cf 2) · `smart_health` (Code-Defaults) |
| `windows-base` | Windows Server — Standard | `agent_ping` (stale 15m, cf 1) · `agent_resources` (wie oben) · `smart_health` |
| `proxmox-host` | Proxmox Host | `proxmox_backup` (max_backup_age_hours 26) |
| `docker-host` | Docker Host | `docker_health` |
| `zfs-storage` | ZFS Storage | `zfs_health` (capacity 80/90) |

Plugin-Checks liegen bewusst in eigenen Templates (auf Hosts ohne Subsystem
liefern sie `unknown` — sichtbar, aber nicht alarmierend, s. unknown-Policy).
`disk_forecast` wird nach Implementierung in `linux-base`/`windows-base`
ergänzt (interval 1h, warn < 24 h, crit < 8 h Restzeit, severity warning).
Zusätzlich wird der Code-Default `stale_minutes` von 5 auf 15 angehoben —
5 min ist identisch mit dem Push-Intervall des Agents und produziert False
Positives (Standard anderswo: 3 verpasste Intervalle).

## Verhaltens-Änderungen (Alert-Semantik)

1. **unknown benachrichtigt nie** (User-Entscheidung): Transitionen mit
   `new_status == "unknown"` lösen weder Regel-Dispatch noch Hub-Emit aus;
   der Status bleibt im Dashboard sichtbar. `unknown → ok` sendet weiterhin
   Recovery (bypass Cooldown, wie bisher). Echtes „Agent weg“ meldet der
   persistierte `agent_ping` als `critical`. POLICY NOTE in
   `check_engine.next_fail_count` wird entsprechend aktualisiert.
2. **Hysterese** (nur `agent_resources`, **per Metrik**): War eine Metrik in
   der Vorrunde `warning`/`critical`, gelten für sie Release-Schwellen
   `threshold − hysteresis_pp` (Config-Key, Default 10); die crit-Schwelle
   sinkt nur für zuvor kritische Metriken (keine Eskalation über die
   Release-Schwelle). Umsetzung: `evaluate()` bekommt die vorherigen
   `state.details`, deren `problems`-Map `{metrik: level}` das Gedächtnis ist.
   Ursprünglich war Check-Granularität geplant (`prev_status`) — verworfen,
   weil ein alarmierender CPU-Wert die Release-Schwellen aller anderen
   Metriken kontaminiert hätte (selbsterhaltende Warnings für Metriken, die
   nie Entry gerissen haben).
3. **Host-down-Suppression** (Alertmanager-Inhibition-Muster): Ist der
   `agent_ping`-Check eines Servers `critical`, werden Dispatch + Hub-Emit
   für alle anderen Checks desselben Servers unterdrückt (ein Incident = eine
   Meldung). Einzige Einfügestelle: `process_alert()` — beide Pfade
   (Scheduler + Agent-Push) laufen dort durch.
4. **Maintenance-Fenster** („collect but mute“): Daten + Zustands-Übergänge
   laufen weiter, `process_alert()` unterdrückt Dispatch + Hub-Emit, kein
   Alert-Log-Eintrag. UI zeigt Badge.

## Externe Integrationen

- **VictoriaMetrics:** `disk_forecast` liest `monitor_agent_disk_percent`
  über das vorhandene `victoria.query_range()` (`/api/v1/query_range`,
  bereits vom Metrics-Endpoint genutzt — kein neues Wire-Format). Lineare
  Regression über `window_hours` (Default 24, min. 6 h Historie), Restzeit
  bis 100 % pro Mount; zu wenig Historie ⇒ `unknown`.
- Kein FRP-/Tauri-Kontakt (Desktop nutzt den bestehenden `api_proxy`-Weg).

## Trade-offs & Alternativen

- **Seed im Lifespan statt Alembic-Data-Migration:** Migrationen sind
  einmalig; der Lifespan-Seed + `monitor_seed_state` erlaubt, in späteren
  Versionen neue Built-ins nachzuliefern, ohne User-Edits oder -Löschungen
  anzufassen. Alternative (Alembic-Seed) verworfen: kein sauberer Weg für
  „nachliefern, aber Tombstones respektieren“.
- **Tag-Auflösung im Monitoring-Dienst (Pull vom Server) statt im Server:**
  Templates + Assignments leben im Monitoring; der Server bleibt einzige
  Tag-Quelle (`GET /api/internal/servers`) und stößt Sync nur an
  (Notify + Safety-Net-Job). Alternative (Server orchestriert assign/unassign)
  verworfen: verteilt Template-Logik über zwei Dienste.
- **Hub-only Default-Benachrichtigung statt geseedeter Alert-Regel:**
  E-Mail-Regeln ohne konfiguriertes SMTP würden nur Fehler produzieren; der
  Hub funktioniert ohne Setup (Glocke + optionale Desktop-Notification).
- **Keine echte Flap-Detection:** Hysterese + `consecutive_fails` + Cooldown
  decken den realen Bedarf; Zabbix-artige Trigger-Dependencies wären Overkill.

## Risiken & Rollback

- **Alert-Semantik ändert sich** (unknown, stale 15m, Suppression) — für
  Bestandsnutzer sichtbar; CHANGELOG „Changed“ + Doku. Rollback: Guards in
  `process_alert` sind lokal und einzeln revertierbar.
- **Seeding:** idempotent, additiv, per Tombstone abgesichert. Rollback:
  Templates + `monitor_seed_state`-Zeilen löschen; Migrationen haben Downgrades.
- **Tag-Sync:** best-effort (wie bestehende Server→Monitoring-Aufrufe);
  Safety-Net-Job korrigiert verpasste Notifies. Unique-Constraint
  `(template_id, server_id)` verhindert Doppel-Materialisierung.
- **Single-Worker-Invariante bleibt bestehen** (Liveness-Persistenz macht
  `agent_ping` neustart-fest, ersetzt aber nicht die Invariante — Scheduler
  bleibt prozess-lokal).
- **Push-Pfad-Duplikat:** Hysterese ändert die `evaluate()`-Signatur — beide
  Aufrufstellen (`routers/agent.py`) im selben Task anfassen + Tests.

## Doku-Impact

Erheblich: `docs/admin/monitoring.html` DE+EN (`warn_threshold`/
`crit_threshold` → echte per-Typ-Config-Keys; `alert.triggered`-Abschnitt an
den nun implementierten Hook angleichen; neue Abschnitte Standard-Templates/
Schwellwerte, Tag-Zuweisung, Maintenance, unknown-Policy, Grid),
`docs/developer/monitoring.html` DE+EN (Seeding, interne Endpoints, Tag-Sync,
forecast, Liveness), `docs/developer/hooks.html` DE+EN (Event-Liste +
`alert.triggered`), `README.md` (Monitoring-Abschnitt + Env-Tabelle),
`CHANGELOG.md`.

## Entscheidungen (Gate-Durchsprache, 2026-07-15)

1. Monitoring-Modals **inkl. Design** in diesem Plan; der reservierte
   Modal-Design-Pass (audit-fixes 1.11) ist dafür aufgehoben. Leitplanke:
   streng nach dem adoptierten AdminCave-Design-System, nichts Neues
   erfinden. — bestätigt (erneut 2026-07-19)
2. `unknown` benachrichtigt nie (Dashboard-sichtbar, kein Dispatch/Hub-Emit).
3. Maintenance: einmalig + wöchentlich, **Zeitzonen-Feld** (IANA,
   `zoneinfo`-Auswertung, DST-korrekt).
4. Built-in-Templates englisch; Zuweisung Opt-in im Server-Dialog (keine
   Auto-Zuweisung nach OS-Typ).
5. `disk_forecast` Default-Severity `warning`.
6. Zusatzpunkte aufgenommen: Default-Subscription für Admins,
   `alert.triggered`-Hook implementieren, Bulk-CTA „Server ohne Checks“,
   Retention env-konfigurierbar.

Keine offenen Fragen.
