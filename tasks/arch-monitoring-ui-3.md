<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-ui-3 — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-ui-3 · Review: pro Task
Spec: docs/features/arch-monitoring-ui-3.md (Roadmap R-1226)
Heavy: linux-full — `apps/agent` (neue systemctl-/journalctl-Aufrufe), der Berichtspfad des Monitoring-Dienstes und eine neue Desktop-Journey; der Sammellauf fährt agent-monitoring, den Stack und die Desktop-Live-Specs. Der Windows-Teil (T2) läuft über die PR-CI-Jobs `agent-windows` und `rust-windows`
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@0645ec064`. Risikopfade (`scripts/dev/review-risk.txt`): T4 (`apps/monitoring/alembic/versions/`),
T5 (`routers/agent.py`), T6 (`schemas.py`), T7 (`lib/api/types.ts`): `security` je Task. Nicht auf der Liste, aber
sicherheitsrelevant: T3 (Schwärzung im Agent) und T9 (Remote-Befehl im Desktop): `security` auch dort. Neue
Quelldateien bekommen den SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later
<datei>`). Überlappung mit `feature/arch-monitoring-ui-2` (R-1227): `allowlist.go`, `checkers/agent.py`,
`checkDetails.ts` in anderen Abschnitten; nach dessen Merge `origin/main` hereinziehen und die ganzen Suiten von
`agent`, `monitoring` und `desktop-ui` fahren.

### T1 — Agent (Linux): systemd-Fakten je Dienst und `failed_details` (R-1226, Stufe 1)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services.go, apps/agent/internal/monitor/inventory.go, apps/agent/internal/monitor/services_linux_test.go, apps/agent/internal/monitor/inventory_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: Ein gebündeltes `systemctl show -p Id,Names,SubState,Result,ExecMainCode,ExecMainStatus,NRestarts,StateChangeTimestampMonotonic,MemoryCurrent -- <geladene Units>` (ohne Templates; ein gescheiterter Batch lässt die Fakten weg, kein Einzel-Fallback). Die Inventar-Einträge bekommen `sub_state`, `since`, `restarts`, `result`, `exit`, `memory_bytes` (Spec, Tabelle). `inventoryHash` deckt alle neuen Felder außer `memory_bytes`. Neuer Schlüssel `systemd.failed_details` je fehlgeschlagener Unit, dazu der Allowlist-Eintrag. Tests: Parser mit Fixtures (altes systemd ohne `NRestarts`, `MemoryCurrent=[not set]` und 2^64−1, Signal statt Exit-Code), Hash ignoriert RAM und erkennt einen Neustart, Batch-Fehler, Allowlist.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T12

### T2 — Agent (Windows): Exit-Codes aus `sc query` und SCM-Ereignisse 7031/7034 (R-1226, Stufe 1)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/scquery.go, apps/agent/internal/monitor/scquery_test.go, apps/agent/internal/monitor/scmevents.go, apps/agent/internal/monitor/scmevents_test.go, apps/agent/internal/monitor/services_windows.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `parseScQuery` liest `DISPLAY_NAME`, `WIN32_EXIT_CODE` und `SERVICE_EXIT_CODE`; ein gestoppter Dienst mit Exit-Code ≠ 0 trägt `exit`. Nur dann ein fester `wevtutil qe System`-Aufruf (Ereignisse 7031/7034 der letzten 24 h, begrenzte Anzahl, XML), dessen Parser den Anzeigenamen auf den Dienst abbildet und `result=crashed` und `since` setzt. Syntax und Ereignis-Layout vorher bei Microsoft Learn nachlesen (Spec, Externe Integrationen). Kein neuer `failed`-Begriff. Parser ohne Build-Tag, Tests mit Fixtures; der Aufruf selbst läuft im CI-Job `agent-windows`.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T12

### T3 — Agent: Fehlerzeilen je Ausfall mit Schwärzung, Schalter aus dem Plan (R-1226, Stufe 2)  [?] (Welche Zeilen sendet Stufe 2: letzte 10 des gescheiterten Laufs jeder Prioritaet (Empfehlung) oder nur err?)
Komponente: agent · Dateien: apps/agent/internal/monitor/servicelogs.go, apps/agent/internal/monitor/servicelogs_test.go, apps/agent/internal/monitor/servicelogs_linux.go, apps/agent/internal/monitor/servicelogs_linux_test.go, apps/agent/internal/monitor/servicelogs_other.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/monitor.go, apps/agent/internal/probe/probe.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `probe.Plan` bekommt `ServiceLogs bool` (`service_logs`; fehlt es, keine Zeilen). Unter Linux liest der Agent je fehlgeschlagener Unit einmal je Ausfall (Schlüssel Unit + `since`, im Report-State) höchstens 10 Zeilen per festem `journalctl`-Aufruf (Auswahl nach Kevins Antwort, Frage 1). Jede Zeile wird geschwärzt (Regeln aus §3.9) und auf 300 Zeichen gekürzt, dann in `systemd.failed_logs` gelegt. Die Schwärzung ist rein (ohne Build-Tag) und besteht dieselben Testvektoren wie T5. Mehr als acht Dateien: Plan-Feld, Report-State und Allowlist sind nur gemeinsam grün.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T12
Abhängt von: T1

### T4 — Monitoring: Tabellen für Dienste-Inventar und Fehlerzeilen (Migration, R-1226)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/c1e3a5b7d9f0_service_inventory.py, apps/monitoring/app/server_cleanup.py, apps/monitoring/tests/test_service_tables.py, apps/monitoring/tests/test_migrations_smoke.py, apps/monitoring/tests/test_models_timestamps.py
Änderung: `monitor_service_inventory` (`server_id` PK, `reported_at`, `services`, `log_lines` mit `server_default` true) und `monitor_service_logs` (PK `server_id`+`unit`, `since`, `collected_at`, `lines`), additive Revision nach `b8d0f2a4c6e8` mit Downgrade. `cleanup_server` löscht beide. Tests: Upgrade/Downgrade, Default des Schalters, Cleanup, naive UTC-Zeitstempel.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_tables.py tests/test_migrations_smoke.py tests/test_models_timestamps.py
Doku: → T12

### T5 — Monitoring: Bericht speichert Inventar und Fehlerzeilen, Grund im Check-Text (R-1226, Stufe 1/2)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/service_inventory.py, apps/monitoring/app/routers/agent.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_service_inventory.py, apps/monitoring/tests/test_agent_report_services.py, apps/monitoring/tests/test_service_process_checker.py
Änderung: `agent_report` speichert neben `_store_host_facts` eigenständig, mit eigenem Commit und Rollback:
- `all_services` ohne `systemd.error` ersetzt das Inventar (gekappt auf 500 Einträge, Felder gekürzt).
- `failed_logs` nur bei Schalter an: noch einmal geschwärzt (Testvektoren je Muster aus §3.9, die T3 übernimmt), ≤ 10 × 300 Zeichen.
- Units, die nicht mehr in `failed` stehen, verlieren ihre Zeilen; ein Bericht mit `systemd.error` löscht nichts.
- `ServiceProcessChecker` hängt den Grund aus `failed_details` an (`Failed: nginx.service (exit-code, status=1)`, ohne Zähler und Zeit, damit sich der Text je Ausfall nicht ändert); Docstring von `_evaluate_auto` nachziehen.
- Die Zeilen gehen nie in Text, `_details` oder History; ein Test belegt das.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_inventory.py tests/test_agent_report_services.py tests/test_service_process_checker.py tests/test_agent_report.py tests/test_agent_report_v4.py
Doku: → T12
Abhängt von: T4

### T6 — Monitoring: Admin-Route für die Dienste-Liste, Schalter je Server, Plan-Feld (R-1226)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/schemas.py, apps/monitoring/app/module_plan.py, apps/monitoring/tests/test_service_inventory_api.py, apps/monitoring/tests/test_agent_plan.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: `GET /status/server/{server_id}/services` (Inventar, Stand, Schalter, Zeilen je Unit) und `PUT /status/server/{server_id}/services/options` (`{log_lines}` strict; aus löscht die gespeicherten Zeilen), beide `require_internal` wie die Nachbarrouten. `build_plan` liefert `service_logs`. OpenAPI-Snapshot neu. Tests: leerer Server, Inventar mit Zeilen, Schalter an/aus samt Löschung, Plan-Feld, 404, strikte Validierung.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_inventory_api.py tests/test_agent_plan.py tests/test_openapi_snapshot.py
Doku: → T12
Abhängt von: T5

### T7 — Desktop-UI: Dienste-Liste mit Filter, Suche und Spalten (R-1226)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/monitoring.test.ts, apps/desktop/ui/src/components/monitoring/section/SecServices.svelte, apps/desktop/ui/src/components/monitoring/section/SecServices.test.ts, apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte, apps/desktop/ui/src/components/monitoring/section/ServiceList.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Client für `GET …/services`; `SecServices` öffnet die volle Liste (`ServiceList`):
- Filter nach Zustand (alle, fehlgeschlagen, inaktiv, aktiv) und Suche.
- Sortierung nach Name, seit, Neustarts, RAM; Spalten Zustand/Unterzustand, seit, Neustarts, RAM, Grund.
- Stand-Zeit des Inventars; „–“ für Felder, die die Plattform nicht liefert.
- i18n DE+EN, DesignSystem-Tokens.
Tests: Filter, Suche, Sortierung, fehlende Felder, Fehler- und Leerzustand.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T12
Abhängt von: T6

### T8 — Desktop-UI: Fehlerzeilen an ausgefallenen Diensten und Schalter je Server (R-1226, Stufe 2)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/monitoring.test.ts, apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte, apps/desktop/ui/src/components/monitoring/section/ServiceList.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Ein fehlgeschlagener Dienst klappt seine Zeilen auf (Monospace, als Text gerendert, nie als HTML), mit Hinweis „geschwärzt, nur am Vorfall gespeichert“. Der Schalter „Fehlerzeilen senden“ je Server ruft `PUT …/services/options` und nennt die Wirkung (aus löscht sofort, der Agent folgt beim nächsten Plan). Tests: Aufklappen, kein HTML-Rendering, Schalter an/aus, Fehler beim Speichern.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T12
Abhängt von: T7

### T9 — Desktop-Rust: Befehl `terminal_open_ssh_journal` mit fester journalctl-Aktion (R-1226, Stufe 3)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json
Änderung: `build_journal_args` nach dem Muster von `build_credential_args`:
- Feste Aktion `journalctl --no-pager --unit='<unit>' --lines=200` über `base_args`.
- Der Unit-Name wird gegen die Unit-Klasse geprüft (kein führendes `-`, kein `'`, Länge begrenzt) und für die entfernte Shell einfach quotiert.
- `terminal_open_ssh_journal` nur im Hauptfenster, mit `reject_foreign_port` und `PtyRegistry.open` wie `terminal_open_ssh_credential`; Registrierung in `main.rs`, `build.rs` und der Capability.
Tests: Argumente, abgelehnte Namen (Leerzeichen, `;`, `$(`, `'`, führendes `-`, zu lang), systemd-Escape `\x2d` erlaubt, Nebenfenster abgelehnt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T12

### T10 — Desktop-UI: Knopf „Mehr Log“ öffnet das Terminal mit der Unit (R-1226, Stufe 3)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/invoke.test.ts, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte, apps/desktop/ui/src/components/monitoring/section/ServiceList.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: `terminalOpenSshJournal` in der Bridge, `connectServiceLog` im Connect-Flow nach dem Muster `connectCredential` (SSH-Verbindung des Servers wählen, Tunnel auflösen, Terminal-Tab mit Titel der Unit). Der Knopf erscheint nur bei Linux-Servern mit SSH-Verbindung, sonst ein Hinweis. Mehr als acht Dateien: Bridge, Flow, Terminal-Store und Knopf sind nur gemeinsam testbar. Tests: Aufruf mit Unit, keine Verbindung, Nicht-Linux, Abbruch.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T12
Abhängt von: T8, T9

### T11 — Desktop-Live-E2E: Dienste-Liste gegen den echten Agenten (R-1226)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-services.live.js
Änderung: Live-Spec nach dem Muster `monitoring-server-page.live.js` (Agent im Container, `run --once`): Liste öffnen, Filter und Suche, Schalter umlegen, Screenshots in beiden Themes. Fehlerzeilen und „Mehr Log“, soweit die Agent-Box einen fehlgeschlagenen Dienst und SSH bietet; was sie nicht bietet, steht im Commit-Body als „nicht verifiziert“. Läuft im Sammellauf (`Heavy: linux-full`), lokal nur Lint.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T10

### T12 — Doku DE+EN und CHANGELOG-Fragment (R-1226)  [ ]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/arch-monitoring-ui-3.md
Änderung: Admin-Doku: Dienste-Liste, Stufen 1–3, was in Mail und Webhook steht, Schwärzungsregeln, Speicherdauer, Schalter, Plattformgrenzen. Entwickler-Doku: neue Bericht-Schlüssel, Plan-Feld, Tabellen; API-Referenz: beide Routen. Agent-Doku: neue Allowlist-Aufrufe. Fragment unter `### Added`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_openapi_snapshot.py
Doku: docs/admin/monitoring.html, docs/developer/monitoring.html, docs/developer/api-reference.html, docs/developer/agent.html DE+EN · changelog.d/arch-monitoring-ui-3.md
Task-Review: am Ende
