<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-ui-3 — Task-Ledger
Status: bereit · Branch: feature/arch-monitoring-ui-3 · Review: pro Task
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

### T1 — Agent (Linux): systemd-Fakten je Dienst und `failed_details` (R-1226, Stufe 1)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services.go, apps/agent/internal/monitor/inventory.go, apps/agent/internal/monitor/services_linux_test.go, apps/agent/internal/monitor/inventory_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/monitor/allowlist_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @bebd6e486 2026-11-12T15:32:17+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T1.verdict.json)
Änderung: Ein gebündeltes `systemctl show -p Id,Names,SubState,Result,ExecMainCode,ExecMainStatus,NRestarts,StateChangeTimestampMonotonic,MemoryCurrent -- <geladene Units>` (ohne Templates; ein gescheiterter Batch lässt die Fakten weg, kein Einzel-Fallback). Die Inventar-Einträge bekommen `sub_state`, `since`, `restarts`, `result`, `exit`, `memory_bytes` (Spec, Tabelle). `inventoryHash` deckt alle neuen Felder außer `memory_bytes`. Neuer Schlüssel `systemd.failed_details` je fehlgeschlagener Unit, dazu der Allowlist-Eintrag. Tests: Parser mit Fixtures (altes systemd ohne `NRestarts`, `MemoryCurrent=[not set]` und 2^64−1, Signal statt Exit-Code), Hash ignoriert RAM und erkennt einen Neustart, Batch-Fehler, Allowlist.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T12

### T2 — Agent (Windows): Exit-Codes aus `sc query` und SCM-Ereignisse 7031/7034 (R-1226, Stufe 1)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/scquery.go, apps/agent/internal/monitor/scquery_test.go, apps/agent/internal/monitor/scmevents.go, apps/agent/internal/monitor/scmevents_test.go, apps/agent/internal/monitor/services_windows.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/monitor/allowlist_test.go, apps/agent/internal/monitor/services_test.go, apps/agent/internal/monitor/scmevents_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @571b5a7a0 2026-11-12T15:46:11+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T2.verdict.json)
Änderung: `parseScQuery` liest `DISPLAY_NAME`, `WIN32_EXIT_CODE` und `SERVICE_EXIT_CODE`; ein gestoppter Dienst mit Exit-Code ≠ 0 trägt `exit`. Nur dann ein fester `wevtutil qe System`-Aufruf (Ereignisse 7031/7034 der letzten 24 h, begrenzte Anzahl, XML), dessen Parser den Anzeigenamen auf den Dienst abbildet und `result=crashed` und `since` setzt. Syntax und Ereignis-Layout vorher bei Microsoft Learn nachlesen (Spec, Externe Integrationen). Kein neuer `failed`-Begriff. Parser ohne Build-Tag, Tests mit Fixtures; der Aufruf selbst läuft im CI-Job `agent-windows`.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T12

### T3 — Agent: Fehlerzeilen je Ausfall mit Schwärzung, Schalter aus dem Plan (R-1226, Stufe 2)  [~] (verschoben in arch-monitoring-ui-4: wartet auf Kevins Antwort (welche Zeilen sendet Stufe 2), abgetrennt als R-1413)
Komponente: agent · Dateien: apps/agent/internal/monitor/servicelogs.go, apps/agent/internal/monitor/servicelogs_test.go, apps/agent/internal/monitor/servicelogs_linux.go, apps/agent/internal/monitor/servicelogs_linux_test.go, apps/agent/internal/monitor/servicelogs_other.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/monitor.go, apps/agent/internal/probe/probe.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `probe.Plan` bekommt `ServiceLogs bool` (`service_logs`; fehlt es, keine Zeilen). Unter Linux liest der Agent je fehlgeschlagener Unit einmal je Ausfall (Schlüssel Unit + `since`, im Report-State) höchstens 10 Zeilen per festem `journalctl`-Aufruf (Auswahl nach Kevins Antwort, Frage 1). Jede Zeile wird geschwärzt (Regeln aus §3.9) und auf 300 Zeichen gekürzt, dann in `systemd.failed_logs` gelegt. Die Schwärzung ist rein (ohne Build-Tag) und besteht dieselben Testvektoren wie T5. Mehr als acht Dateien: Plan-Feld, Report-State und Allowlist sind nur gemeinsam grün.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T12
Abhängt von: T1

### T4 — Monitoring: Tabellen für Dienste-Inventar und Fehlerzeilen (Migration, R-1226)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/c1e3a5b7d9f0_service_inventory.py, apps/monitoring/app/server_cleanup.py, apps/monitoring/tests/test_service_tables.py, apps/monitoring/tests/test_migrations_smoke.py, apps/monitoring/tests/test_models_timestamps.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @48844bfb3 2026-11-12T15:55:27+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T4.verdict.json)
Änderung: `monitor_service_inventory` (`server_id` PK, `reported_at`, `services`, `log_lines` mit `server_default` true) und `monitor_service_logs` (PK `server_id`+`unit`, `since`, `collected_at`, `lines`), additive Revision nach `b8d0f2a4c6e8` mit Downgrade. `cleanup_server` löscht beide. Tests: Upgrade/Downgrade, Default des Schalters, Cleanup, naive UTC-Zeitstempel.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_tables.py tests/test_migrations_smoke.py tests/test_models_timestamps.py
Doku: → T12

### T5 — Monitoring: Bericht speichert Inventar und Fehlerzeilen, Grund im Check-Text (R-1226, Stufe 1/2)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/service_inventory.py, apps/monitoring/app/routers/agent.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_service_inventory.py, apps/monitoring/tests/test_agent_report_services.py, apps/monitoring/tests/test_service_process_checker.py, apps/monitoring/tests/service_log_redaction.json, apps/monitoring/tests/test_agent_report.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6627b9d35 2026-11-12T16:26:41+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T5.verdict.json)
Änderung: `agent_report` speichert neben `_store_host_facts` eigenständig, mit eigenem Commit und Rollback:
- `all_services` ohne `systemd.error` ersetzt das Inventar (gekappt auf 500 Einträge, Felder gekürzt).
- `failed_logs` nur bei Schalter an: noch einmal geschwärzt (Testvektoren je Muster aus §3.9, die T3 übernimmt), ≤ 10 × 300 Zeichen.
- Units, die nicht mehr in `failed` stehen, verlieren ihre Zeilen; ein Bericht mit `systemd.error` löscht nichts.
- `ServiceProcessChecker` hängt den Grund aus `failed_details` an (`Failed: nginx.service (exit-code, status=1)`, ohne Zähler und Zeit, damit sich der Text je Ausfall nicht ändert); Docstring von `_evaluate_auto` nachziehen.
- Die Zeilen gehen nie in Text, `_details` oder History; ein Test belegt das.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_inventory.py tests/test_agent_report_services.py tests/test_service_process_checker.py tests/test_agent_report.py tests/test_agent_report_v4.py
Doku: → T12
Abhängt von: T4

### T6 — Monitoring: Admin-Route für die Dienste-Liste, Schalter je Server, Plan-Feld (R-1226)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/schemas.py, apps/monitoring/app/module_plan.py, apps/monitoring/tests/test_service_inventory_api.py, apps/monitoring/tests/test_agent_plan.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @de78ab7cf 2026-11-12T16:36:36+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T6.verdict.json)
Änderung: `GET /status/server/{server_id}/services` (Inventar, Stand, Schalter, Zeilen je Unit) und `PUT /status/server/{server_id}/services/options` (`{log_lines}` strict; aus löscht die gespeicherten Zeilen), beide `require_internal` wie die Nachbarrouten. `build_plan` liefert `service_logs`. OpenAPI-Snapshot neu. Tests: leerer Server, Inventar mit Zeilen, Schalter an/aus samt Löschung, Plan-Feld, 404, strikte Validierung.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_inventory_api.py tests/test_agent_plan.py tests/test_openapi_snapshot.py
Doku: → T12
Abhängt von: T5

### T7 — Desktop-UI: Dienste-Liste mit Filter, Suche und Spalten (R-1226)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/monitoring.test.ts, apps/desktop/ui/src/components/monitoring/section/SecServices.svelte, apps/desktop/ui/src/components/monitoring/section/SecServices.test.ts, apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte, apps/desktop/ui/src/components/monitoring/section/ServiceList.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/monitoring/MonServerDashboard.svelte, apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/styles/app.css, apps/desktop/ui/src/components/monitoring/MonServerDashboard.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @78acb310a 2026-11-12T17:35:07+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T7.verdict.json)
Änderung: Client für `GET …/services`; `SecServices` öffnet die volle Liste (`ServiceList`):
- Filter nach Zustand (alle, fehlgeschlagen, inaktiv, aktiv) und Suche.
- Sortierung nach Name, seit, Neustarts, RAM; Spalten Zustand/Unterzustand, seit, Neustarts, RAM, Grund.
- Stand-Zeit des Inventars; „–“ für Felder, die die Plattform nicht liefert.
- i18n DE+EN, DesignSystem-Tokens.
Tests: Filter, Suche, Sortierung, fehlende Felder, Fehler- und Leerzustand.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T12
Abhängt von: T6

### T8 — Desktop-UI: Fehlerzeilen an ausgefallenen Diensten und Schalter je Server (R-1226, Stufe 2)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/monitoring.test.ts, apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte, apps/desktop/ui/src/components/monitoring/section/ServiceList.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0c2f17f91 2026-11-12T18:03:33+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T8.verdict.json)
Änderung: Ein fehlgeschlagener Dienst klappt seine Zeilen auf (Monospace, als Text gerendert, nie als HTML), mit Hinweis „geschwärzt, nur am Vorfall gespeichert“. Der Schalter „Fehlerzeilen senden“ je Server ruft `PUT …/services/options` und nennt die Wirkung (aus löscht sofort, der Agent folgt beim nächsten Plan). Tests: Aufklappen, kein HTML-Rendering, Schalter an/aus, Fehler beim Speichern.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T12
Abhängt von: T7

### T9 — Desktop-Rust: Befehl `terminal_open_ssh_journal` mit fester journalctl-Aktion (R-1226, Stufe 3)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @b8487a230 2026-11-12T18:35:09+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T9.verdict.json)
Änderung: `build_journal_args` nach dem Muster von `build_credential_args`:
- Feste Aktion `journalctl --no-pager --unit='<unit>' --lines=200` über `base_args`.
- Der Unit-Name wird gegen die Unit-Klasse geprüft (kein führendes `-`, kein `'`, Länge begrenzt) und für die entfernte Shell einfach quotiert.
- `terminal_open_ssh_journal` nur im Hauptfenster, mit `reject_foreign_port` und `PtyRegistry.open` wie `terminal_open_ssh_credential`; Registrierung in `main.rs`, `build.rs` und der Capability.
Tests: Argumente, abgelehnte Namen (Leerzeichen, `;`, `$(`, `'`, führendes `-`, zu lang), systemd-Escape `\x2d` erlaubt, Nebenfenster abgelehnt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T12

### T10 — Desktop-UI: Knopf „Mehr Log“ öffnet das Terminal mit der Unit (R-1226, Stufe 3)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/invoke.test.ts, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte, apps/desktop/ui/src/components/monitoring/section/ServiceList.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts, docs/developer/desktop.html, docs/en/developer/desktop.html, apps/desktop/ui/src/components/monitoring/section/SecServices.svelte
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @62190b2ef 2026-11-12T19:24:16+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T10.verdict.json)
Änderung: `terminalOpenSshJournal` in der Bridge, `connectServiceLog` im Connect-Flow nach dem Muster `connectCredential` (SSH-Verbindung des Servers wählen, Tunnel auflösen, Terminal-Tab mit Titel der Unit). Der Knopf erscheint nur bei Linux-Servern mit SSH-Verbindung, sonst ein Hinweis. Mehr als acht Dateien: Bridge, Flow, Terminal-Store und Knopf sind nur gemeinsam testbar. Tests: Aufruf mit Unit, keine Verbindung, Nicht-Linux, Abbruch.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T12
Abhängt von: T8, T9

### T11 — Desktop-Live-E2E: Dienste-Liste gegen den echten Agenten (R-1226)  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-services.live.js, scripts/tests/desktop_e2e_monitoring.sh
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @75cd5c0b0 2026-11-12T20:29:42+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T11.verdict.json)
Änderung: Live-Spec nach dem Muster `monitoring-server-page.live.js` (Agent im Container, `run --once`): Liste öffnen, Filter und Suche, Schalter umlegen, Screenshots in beiden Themes. Fehlerzeilen und „Mehr Log“, soweit die Agent-Box einen fehlgeschlagenen Dienst und SSH bietet; was sie nicht bietet, steht im Commit-Body als „nicht verifiziert“. Läuft im Sammellauf (`Heavy: linux-full`), lokal nur Lint.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T10

### T12 — Doku DE+EN und CHANGELOG-Fragment (R-1226)  [x]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/arch-monitoring-ui-3.md, docs/features/arch-monitoring-ui-3.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @b6dde475c 2026-11-12T20:45:33+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Admin-Doku: Dienste-Liste, Stufen 1–3, was in Mail und Webhook steht, Schwärzungsregeln, Speicherdauer, Schalter, Plattformgrenzen. Entwickler-Doku: neue Bericht-Schlüssel, Plan-Feld, Tabellen; API-Referenz: beide Routen. Agent-Doku: neue Allowlist-Aufrufe. Fragment unter `### Added`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_openapi_snapshot.py
Doku: docs/admin/monitoring.html, docs/developer/monitoring.html, docs/developer/api-reference.html, docs/developer/agent.html DE+EN · changelog.d/arch-monitoring-ui-3.md
Task-Review: am Ende

### T13 — Monitoring: Grund im Text des Listen-Modus (R-1226)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_service_process_checker.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/arch-monitoring-ui-3.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @9ff277c6c 2026-11-12T21:14:09+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-3/T13.verdict.json)
Änderung: Abschlussprüfung (reviewer branch): Spec Nicht-Ziele verspricht den Grund auch „im Text des Listen-Modus“, `_evaluate_list` nennt ihn nicht. Ein Dienst, der im Modus `list` nicht läuft, trägt in der Meldung und in `_details.watched[].reason` seinen Grund: `failed_details` (Linux), sonst `result`/`exit` aus dem Inventar (ohne `result` `success`), bei gedrosseltem Push aus `prev_details`. Dazu der Doku-Nit „alle Units“ → Service-Units.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_process_checker.py
Doku: docs/admin/monitoring.html, docs/developer/monitoring.html DE+EN

## Entscheidungen
- 2026-11-12 T1: `inventoryHash` nimmt das `since` eines inaktiven Dienstes nicht auf (Spec: „die übrigen Felder gehen in den Hash ein“) — ein Timer-Oneshot verschiebt sein `since` bei jedem Lauf, sonst ginge das volle Inventar alle fünf Minuten mit statt stündlich; der Neustart eines laufenden Dienstes bleibt über `since` und `restarts` erkannt.
- 2026-11-12 T1: `since` = Wanduhr minus `CLOCK_MONOTONIC` plus `StateChangeTimestampMonotonic`, nicht die Boot-Zeit aus `/proc/stat` — `btime` zählt Suspend mit, und LXCFS meldet in Containern den Container-Start.
- 2026-11-12 T1: Der Fakten-Batch fragt die Units aus `list-units` und die fehlgeschlagenen jedes Typs; ein Name außerhalb der Unit-Klasse (etwa `-.mount`) bleibt draußen und steht in `failed_details` nur mit Namen — die Allowlist lehnte sonst den ganzen Batch ab.
- 2026-11-12 T1: Der Allowlist-Test der neuen Property-Liste steht im Paket `monitor` (`allowlist_linux_test.go`), nicht in `allowlist/allowlist_test.go` — dort prüft das Paket nur Sonden- und Discovery-Aufrufe.
- 2026-11-12 T2: Kein `exit` für `WIN32_EXIT_CODE` 0 und 1077 (`ERROR_SERVICE_NEVER_STARTED`, jeder nie gestartete Dienst seit dem Boot — sonst trügen die meisten manuellen Dienste einen Exit und `wevtutil` liefe bei jedem Bericht); 1066 wird `service=<SERVICE_EXIT_CODE>`, nur dann gilt dieser Code (`SERVICE_STATUS`, Microsoft Learn).
- 2026-11-12 T2: `param1` von 7031/7034 wird mit Anzeige- und Dienstname verglichen (beide sind im SCM eindeutig) — welcher Name drinsteht, dokumentiert Microsoft nicht; `scmevents_windows_test.go` prüft im CI-Job `agent-windows` an 7036 desselben Anbieters, dass `param1` den Anzeigenamen trägt.
- 2026-11-12 T2: `result=crashed` und `since` nur für gestoppte Dienste mit `exit`; ein nach dem Absturz neu gestarteter Dienst bleibt unverändert. `/c:50`: ein Dienst, der im Kreis abstürzt, kann die Ereignisse der anderen verdrängen, die dann nur ihr `exit` behalten. Kein Cache: der Aufruf läuft nur, solange ein gestoppter Dienst einen Exit trägt.
- 2026-11-12 T4: `reported_at` darf leer sein: der Schalter je Server kann vor dem ersten Bericht gesetzt werden (Zeile ohne Inventar). Keine `to_dict` an den neuen Modellen — die Route serialisiert wie `findings.py` mit `iso_utc`, `test_models_timestamps.py` bleibt daher unverändert; die Gleichheit von Kette und Modellen prüft `test_migration_chain_matches_models` ohne Änderung an `test_migrations_smoke.py`. Die Migrationstests laufen lokal nur mit Postgres in `DATABASE_URL` (Verify überspringt sie wie bei R-1223); gegen die Worktree-Test-DB: 32 passed, die PR-CI fährt sie mit Postgres.
- 2026-11-12 T5: Die Schwärzungs-Vektoren liegen in einer Datei, `apps/monitoring/tests/service_log_redaction.json` (`[{name, in, out}]`); T3 liest sie im Go-Test über `../../../monitoring/tests/service_log_redaction.json`, damit Agent und Server dieselben Regeln beweisen. Die Regeln vermeiden Rückverweise und Lookaround (RE2-tauglich).
- 2026-11-12 T5: Eine Zeile über `MAX_AGENT_TEXT` wird vor den Regeln gekürzt (begrenzt ihre Arbeit), das dabei angeschnittene Token fällt weg — ein halber Schlüssel ist kürzer als 32 Zeichen und keine Regel fände ihn mehr; der Schnitt auf 300 Zeichen läuft nach den Regeln. Base64 ab 32 Zeichen nur mit Ziffer, Groß- und Kleinbuchstabe, sonst fielen Pfade und Wörter mit.
- 2026-11-12 T5: `_MAX_REPORT_ENTRIES` heißt jetzt `MAX_REPORT_ENTRIES`: `service_inventory.py` kappt das Inventar mit derselben Grenze, und `test_module_boundaries.py` verbietet den Import privater Namen über Modulgrenzen.
- 2026-11-12 T5: Die Schlüssel- und die Authorization-Regel beginnen am Schlüsselwort (der Name davor bleibt ohnehin im Text), der Name danach ist auf 64 Zeichen begrenzt, das URL-Schema auf 32, damit Pythons backtrackendes `re` je Zeile linear bleibt. Dazu speichert ein Bericht die Zeilen von höchstens `MAX_LOG_UNITS` = 20 Units (die ersten mit Zeilen in `failed`); T3 sendet höchstens so viele.
- 2026-11-12 T6: Die Antwort folgt der Admin-API in camelCase (`serverId`, `reportedAt`, `logLines`, `services`, `logs.<unit>.{since, collectedAt, lines}`), der Rumpf von PUT in snake_case (`{log_lines}`) wie jedes Request-Schema des Dienstes; `services` trägt die Einträge, wie der Agent sie sandte (wie `DiscoveryOut.inventory`). PUT antwortet mit demselben Rumpf wie GET.
- 2026-11-12 T6: „Server bekannt“ heißt: Agent-Key, ein Agent-Bericht (`monitor_agent_liveness`, auch für Agenten mit Zertifikat ohne Key) oder eine Inventar-Zeile. Sonst 404 für GET und PUT, damit ein PUT für einen vertippten oder gelöschten Server keine Zeile hinterlässt, die kein `cleanup_server` mehr entfernt. GET zeigt bei ausgeschaltetem Schalter keine Zeilen, auch keine, die ein schon laufender Bericht noch gespeichert hat.
- 2026-11-12 T7: Die volle Liste öffnet ein Dialog aus dem Dienste-Abschnitt (Knopf „Alle Dienste anzeigen“, nur für einen echten Server); sie lädt erst beim Öffnen, das Dashboard fragt nichts zusätzlich. Die Tabelle ist `CrossTable` (Suche, Sortierung, fehlende Werte zuletzt) mit einem `Segmented`-Filter samt Zählern; keine neue Tabellen-Komponente.
- 2026-11-12 T7: Zustandsgruppen: `failed` → Fehlgeschlagen; `active`, `reloading`, `refreshing` → Aktiv; alles andere (auch `activating`, `deactivating`, unbekannt, Windows `inactive`) → Inaktiv. Grund: `result` außer `success`, mit `exit`; ohne `result` das `exit` allein (Windows). Ein Alias ist keine eigene Zeile (sein Zustand ist nicht der des Ziels): sein Name steht beim Ziel und findet es in der Suche, ohne Ziel fällt er weg. Je Unit die erste Zeile. Was eine Plattform nicht sendet, zeigt „—“.
- 2026-11-12 T7: Die Hilfsfunktionen stehen im Modul-Skript von `ServiceList.svelte` und nutzen Records ohne Prototyp statt `Map`/`Set` (`svelte/prefer-svelte-reactivity` verlangt in Svelte-Dateien sonst `SvelteMap`, die Werte sind aber nicht reaktiv); ohne Prototyp, weil Unit-Namen Agent-Text sind. Die Fußzeile mit dem Knopf ist eine globale Regel `.mon-section-foot` in `app.css` wie der Rest des Abschnitts: ein scoped `<style>` in `SecServices.svelte` hängte seinen Hash auch an die dynamischen `mon-dot`-Klassen.
- 2026-11-12 T8: Die Fehlerzeilen klappen in der Grund-Spalte der vollen Liste auf (Knopf „Fehlerzeilen (n)“ mit `aria-expanded`, `<pre>` mit Text-Interpolation, nie HTML), nur an Units im Zustand `failed` mit eigenem Schlüssel in `logs` und mindestens einer Zeile. Welche Zeilen aufgeklappt sind, hält ein `SvelteSet`, geleert bei jedem Serverwechsel.
- 2026-11-12 T8: Der Schalter steht über der Liste, sobald das Inventar geladen ist, auch vor dem ersten Bericht (T4: Zeile ohne Inventar). Er bindet einen eigenen Zustand, der beim Klick sofort umspringt und zurückspringt, wenn Speichern scheitert (Meldung `role="alert"`); während des Speicherns ist er gesperrt, die Antwort von PUT ersetzt Inventar und Schalterstand, eine späte Antwort oder ein später Fehler für den vorigen Server fällt weg. Der Hinweistext sagt „blendet sofort aus und löscht“: Zeilen aus einem Bericht, der beim Ausschalten schon unterwegs war, bleiben bis zum nächsten Bericht gespeichert, GET zeigt sie nicht (T6).
- 2026-11-12 T9: Die Unit-Klasse ist die des Agenten (`argClasses["unit"]` in `apps/agent/internal/allowlist/allowlist.go`), ein Quelltext-Test hält beide gleich; dazu höchstens 255 Zeichen (systemd.unit(5)). Ein führendes `-` fällt durch die Klasse (`-.mount` steht nach T1 nicht im Inventar); Glob-Zeichen fehlen ihr, `--unit=` nimmt also nie ein Muster. Die Unit steht in einfachen Anführungszeichen, die kein Zeichen der Klasse beendet, weil die Login-Shell des Hosts die Wörter nach dem Ziel als eine Zeile liest.
- 2026-11-12 T9: `journalctl` läuft ohne `sudo` mit den Rechten des Admin-Logins (Konzept §3.9, Stufe 3); fremde Dienste sieht nur, wer in `systemd-journal` oder `adm` ist (Doku T12). `-t` gibt journalctl ein Terminal, damit es nach Priorität färbt; `--no-pager`, weil die Sitzung mit der Aktion endet und der Verlauf im Terminal bleibt. Kein Broadcast, kein SFTP-Kanal, wie beim Zugangsdaten-Terminal.
- 2026-11-12 T9: Neuer Quelltext-Test `terminal_commands_that_open_a_connection_check_its_port` über die drei Terminal-Befehle mit Verbindung: ohne ihn überlebte das Entfernen von `reject_foreign_port` jeden Test.
- 2026-11-12 T10: „Mehr Log“ steht nur an Units mit der Endung `.service`: der Linux-Agent listet `--type=service`, Windows- und FreeBSD-Namen tragen keine Endung (Stufe 3 liest das systemd-Journal). Ohne SSH-Verbindung des Servers oder ohne systemd-Unit steht statt des Knopfs ein Hinweis; bei mehreren SSH-Verbindungen wählt ein Auswahlfeld, vorbelegt mit der ersten.
- 2026-11-12 T10: Der Reiter heißt „Verbindung · Unit“ über eine umbenannte Kopie der Verbindung (`id` bleibt, Rust nutzt den Namen nicht); so zeigen Reiter, Fenstertitel, abgelöstes Fenster und Schließen-Rückfrage die Unit ohne eigenen Zweig. Der Journal-Reiter verhält sich wie der Zugangsdaten-Reiter: keine Shell, keine Snippets, keine Dateien, erneutes Verbinden auf demselben Weg, nicht in `openSessionIds`.
- 2026-11-12 T10: Die Dienste-Liste schließt bei „Mehr Log“: ein verdecktes offenes Modal hielte seinen `keydown`-Listener am Dokument und nähme dem Terminal Tab und Escape. Der IPC-Inventartest der UI (rot seit T9, dessen Verify nur `desktop-rs` fuhr) wird hier mit Aufrufer und Doku-Zeile grün.
