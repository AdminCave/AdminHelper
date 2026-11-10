<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-ui — Task-Ledger
Status: erledigt · Branch: feature/arch-monitoring-ui · Review: pro Task
Spec: docs/features/arch-monitoring-ui.md (Roadmap R-1225)
Heavy: linux-full — Monitoring-API hinter dem Server-Proxy und eine neue Desktop-Journey; dazu vor dem Merge die Live-Spec aus T11 auf der warmen Desktop-VM (Screenshots für Kevin, Spec „Screenshots“)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@2980eaab5`. Gebaut wird erst nach dem Merge von #438 (R-1223, Datenvertrag); danach `origin/main`
in den Worktree. R-1226 und R-1227 fahren im Folgezug `arch-monitoring-ui-2` (überlappen `feature/arch-freebsd-agent`);
aus R-1227 nur das HTTPS-Zertifikat hier (T2). Risikopfade (`scripts/dev/review-risk.txt`): T1 (`schemas.py`,
`alerter.py`), T3 (`lib/api/types.ts`), T10 (`lib/bridge/types.ts`): `security` je Task; T9 trägt eine Fern-Aktion
über SSH und eine neue Capability: `security` auch dort. Neue Quelldateien bekommen den SPDX-Header (`reuse annotate
--copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`). UI nur aus Tokens und Komponenten unter
`apps/desktop/ui/src/components/ui/`, Texte DE+EN in `dictionaries.ts`.

### T1 — Monitoring: Status-API für die Server-Seite (R-1225)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/app/schemas.py, apps/monitoring/app/alerter.py, apps/monitoring/tests/test_status_page_api.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/tests/test_response_shapes.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @38ae97808 2026-11-10T11:41:55+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T1.verdict.json)
Änderung: Check-Antworten von `/status` und `/status/server/{server_id}` tragen `muted_reason`, gebündelt je Antwort berechnet (Wartungsfenster einmal, Host-down einmal je Server) mit derselben Semantik wie `alerter.muted_reason`; `/status/summary` trägt `last_result_at` und `min_interval_s` (SQL-Aggregat); neu `GET /status/server/{server_id}/costs` aus den Collector-Reihen (Mittel 1 h, Treffer, Faktor, gebremst; 502 ohne VictoriaMetrics). Tests (neue Datei, SPDX): Gleichlauf gebündelt ↔ `muted_reason` über alle Gründe, Abfragezahl unabhängig von der Check-Zahl, Summary leer/gefüllt, Kosten mit gestubbtem VM-Client und 502.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_page_api.py tests/test_alerter.py tests/test_response_shapes.py tests/test_openapi_snapshot.py
Doku: → T12

### T2 — Monitoring: HTTPS-Zertifikat im HTTP-Check (R-1225, aus R-1227)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/http.py, apps/monitoring/tests/test_http_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @8bdc25245 2026-11-10T11:48:50+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T2.verdict.json)
Änderung: Vorher httpx `network_stream` und `ssl.SSLSocket.getpeercert` in der Primärdoku nachlesen (Spec „Externe Integrationen“). Beim ersten https-Hop mit `verify_ssl` an `details.cert` = `not_before`, `not_after`, `issuer`, `subject_cn`; ohne Prüfung kein `cert`; Status, Meldung und Metriken des Checks bleiben unverändert. Kommt das Zertifikat durch `_PinnedTransport` nicht heraus, wird `ssrf.py` nicht nebenbei geändert: Task `[?]` mit Befund. Tests: lokaler TLS-Server mit Test-Zertifikat (Ablauf, Aussteller), Redirect http→https, `verify_ssl: false` ohne `cert`, Status unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_http_checker.py
Doku: → T12

### T13 — Monitoring: Katalog-Schlüssel je Check in der Check- und Status-API (R-1225)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_checks_crud.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @94dc67feb 2026-11-10T11:55:06+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T13.verdict.json)
Änderung: `MonitorCheck.to_dict` und `MonitorCheckOut` tragen `moduleCheckKey` (die Spalte `module_check_key`, gesetzt von `module_sync`), additiv und nur lesend: die Modulkarte (T5) ordnet die Katalog-`card`-Einträge (`check_key`) damit den Checks einer Instanz zu. Test: der bestehende Modul-Check-Test liest das Feld für Modul- und einfachen Check; OpenAPI-Snapshot neu aufgenommen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checks_crud.py tests/test_response_shapes.py tests/test_openapi_snapshot.py
Doku: → T12

### T3 — Desktop-UI: Datenschicht für Katalog, Erkennung, Funde, Kosten und Puls (R-1225)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/monitoring.test.ts, apps/desktop/ui/src/lib/models/monitoring.ts, apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/lib/stores/monitoring.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @33ec3cfec 2026-11-10T12:09:26+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T3.verdict.json)
Änderung: Typen gegen die gemergten Schemas (`CatalogOut`, `DiscoveryOut`, `FindingOut`, `AdoptOut`, `AdoptAllOut`, Status mit `muted_reason`, Summary, Kosten, `details.cert`); API-Aufrufe für `/catalog`, `/discovery/{id}` (+ `scan`), `/findings` (+ adopt, adopt-all, dismiss), `/status/server/{id}/costs`; der Store lädt Katalog einmal je Sitzung, Erkennung und Funde mit dem Server-Refresh, nach adopt/dismiss neu. Tests: Aufruf-Pfade und Parameter, Store-Ablauf (adopt lädt Checks und Funde neu, Fehler bleibt lesbar).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/monitoring.test.ts src/lib/stores/monitoring.test.ts
Doku: → T12
Abhängt von: T1

### T4 — Desktop-UI: Klartext und Bausteine Karte, Querschnitts-Tabelle, Funde-Eingang (R-1225)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/monitoringText.ts, apps/desktop/ui/src/lib/models/monitoringText.test.ts, apps/desktop/ui/src/components/monitoring/card/MonCard.svelte, apps/desktop/ui/src/components/monitoring/card/MonCard.test.ts, apps/desktop/ui/src/components/monitoring/cross/CrossTable.svelte, apps/desktop/ui/src/components/monitoring/cross/CrossTable.test.ts, apps/desktop/ui/src/components/monitoring/card/FindingsInbox.svelte, apps/desktop/ui/src/components/monitoring/card/FindingsInbox.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @37a8e5f39 2026-11-10T12:29:04+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T4.verdict.json)
Änderung: `monitoringText.ts` (SPDX): Fühler-Status, Unterdrückungsgrund, Ablauf (Tage/Stunden, Einstufung nach Konzept §5 relativ zu L, mindestens 12 h), Alter und Einheiten als Sätze DE+EN. `MonCard` (Kopf mit Status, Titel, Kurzzeile; zu bei ok, auf bei Problem; Inhalt als Slot), `CrossTable` (Spalten, Sortierung, Filter, leere Ansicht), `FindingsInbox` (Liste mit übernehmen/alle übernehmen/ignorieren, Art neu/geändert/verschwunden) — nur Tokens und `components/ui/`. Neun Dateien: Bausteine und ihre Tests gehören in einen Commit, die Texte teilen sie.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/monitoringText.test.ts src/components/monitoring/card src/components/monitoring/cross
Doku: → T12

### T5 — Desktop-UI: Server-Seite mit Karten (R-1225)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/MonServerDashboard.svelte, apps/desktop/ui/src/components/monitoring/MonServerDashboard.test.ts, apps/desktop/ui/src/components/monitoring/card/ModuleCard.svelte, apps/desktop/ui/src/components/monitoring/card/ModuleCard.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/monitoring/card/MonCard.svelte, apps/desktop/ui/src/components/monitoring/card/MonCard.test.ts, apps/desktop/ui/src/lib/models/checkDetails.ts, apps/desktop/ui/src/lib/models/checkDetails.test.ts, apps/desktop/ui/src/lib/models/monitoringText.ts, apps/desktop/ui/src/lib/models/monitoringText.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @840381918 2026-11-10T13:03:19+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T5.verdict.json)
Änderung: `MonServerDashboard` umgebaut: Kopf mit Problemzahl und [Jetzt scannen]; Karte System (heutige Sektionen Live, Netz, Heartbeat, System, ZFS, SMART, Prognose), Karten Dienste, Docker, Backups (heutige `Sec*`), je Modul-Instanz eine `ModuleCard` aus Katalog-`card` und den Checks der Instanz (Kennzahlen, Klartext des Fühler-Status, stille Checks markiert), „Neu gefunden (n)“ mit `FindingsInbox`; Unterdrückungsgrund an der Karte. Bestehende Tests der Datei bleiben in ihrer Aussage und ziehen auf die neue Struktur um; neue Tests: zu/auf nach Status, Modulkarte aus Katalog, Neu gefunden mit adopt, Scan-Knopf, Unterdrückungsgrund.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/MonServerDashboard.test.ts src/components/monitoring/card src/lib/models/checkDetails.test.ts src/lib/models/monitoringText.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T3, T4, T13

### T6 — Desktop-UI: Monitoring-Kosten je Server und Warnung „ohne Ergebnis“ (R-1225)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/monitoringPulse.ts, apps/desktop/ui/src/lib/stores/monitoringPulse.test.ts, apps/desktop/ui/src/components/StatusFooter.svelte, apps/desktop/ui/src/components/StatusFooter.test.ts, apps/desktop/ui/src/components/monitoring/card/MonCosts.svelte, apps/desktop/ui/src/components/monitoring/card/MonCosts.test.ts, apps/desktop/ui/src/components/monitoring/MonServerDashboard.svelte, apps/desktop/ui/src/components/monitoring/MonServerDashboard.test.ts, apps/desktop/ui/src/pages/Monitoring.svelte, apps/desktop/ui/src/pages/Monitoring.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @64a57b917 2026-11-10T13:19:29+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T6.verdict.json)
Änderung: `monitoringPulse.ts` (SPDX): alle 60 s `/status/summary`, solange eine Sitzung besteht; Grenze max(10 min, 2 × `min_interval_s`); Warnung bei altem `last_result_at` oder Ausfall länger als die Grenze, keine ohne Checks. Statusleiste zeigt „Monitoring seit X min ohne Ergebnis“ (Klick → Monitoring), die Server-Seite die Kosten je Collector (`MonCosts`: Dauer, CPU, gebremst, Treffer). Tests mit Fake-Timern: Grenze, Ausfall, Erholung, keine Checks, Abmelden stoppt den Puls.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/monitoringPulse.test.ts src/components/StatusFooter.test.ts src/components/monitoring/card/MonCosts.test.ts src/components/monitoring/MonServerDashboard.test.ts src/pages/Monitoring.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T3, T5

### T7 — Desktop-UI: Querschnitt Zertifikate & Domains und Backups (R-1225)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Monitoring.svelte, apps/desktop/ui/src/components/monitoring/cross/CertsView.svelte, apps/desktop/ui/src/components/monitoring/cross/CertsView.test.ts, apps/desktop/ui/src/components/monitoring/cross/BackupsView.svelte, apps/desktop/ui/src/components/monitoring/cross/BackupsView.test.ts, apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/pages/Monitoring.test.ts, apps/desktop/ui/src/components/monitoring/cross/ServerLink.svelte, apps/desktop/ui/src/lib/stores/monitoring.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e1ebf0295 2026-11-10T13:41:53+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T7.verdict.json)
Änderung: Neue Reiter der Monitoring-Seite. Zertifikate & Domains: Zeilen aus `details.cert` der HTTP-Checks und aus `probe`-Checks mit Feld `not_after` (Server, Ziel, Aussteller, Ablauf, Einstufung), nach Ablauf sortiert. Backups: aus den `proxmox_backup`-Checks aller Server (was, letzter Erfolg, Alter, Status). Beide auf `CrossTable`, Klick führt zur Server-Seite. Tests: Sortierung, Einstufung relativ zu L, Fühler-Zeilen über den Check-Status, leere Ansicht.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/cross src/pages/Monitoring.test.ts src/lib/stores/monitoring.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T2, T4

### T8 — Desktop-UI: Querschnitt Updates & Neustarts und Funde (R-1225)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Monitoring.svelte, apps/desktop/ui/src/components/monitoring/cross/UpdatesView.svelte, apps/desktop/ui/src/components/monitoring/cross/UpdatesView.test.ts, apps/desktop/ui/src/components/monitoring/cross/FindingsView.svelte, apps/desktop/ui/src/components/monitoring/cross/FindingsView.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/pages/Monitoring.test.ts, apps/desktop/ui/src/lib/models/monitoringText.ts, apps/desktop/ui/src/lib/models/monitoringText.test.ts, apps/desktop/ui/src/components/monitoring/MonServerDashboard.svelte, apps/desktop/ui/src/lib/stores/monitoring.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @c0237ac04 2026-11-10T13:59:13+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T8.verdict.json)
Änderung: Updates & Neustarts aus den `system_state`-Checks (Sicherheitsupdates, Updates, Neustart nötig je Server; Paketnamen folgen mit R-1227). Funde: offener Eingang aller Server (`/findings?status=open`) mit `FindingsInbox`, gruppiert nach Server, übernehmen/ignorieren wie auf der Server-Seite. Tests: Zeilen aus Details, Gruppierung, adopt/dismiss lädt neu.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/cross src/components/monitoring/MonServerDashboard.test.ts src/lib/models/monitoringText.test.ts src/pages/Monitoring.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T3, T4

### T9 — Desktop-Rust: Terminal mit fester Aktion „Zugangsdaten hinterlegen“ (R-1225)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/capabilities/default.json
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @5165d50b2 2026-11-10T14:12:53+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T9.verdict.json)
Änderung: Vorher Tauri-Capabilities und Commands in der Primärdoku nachlesen. Neues Kommando `terminal_open_ssh_credential(connection, ref, cols, rows, output)`: wie `terminal_open_ssh` (gleiche Prüfungen, `ssh_spawn`, Fenster-Regel), aber mit `-t` und der in Rust gebauten Fern-Aktion `sudo adminhelper-agent monitor credential set <ref>`; `ref` gegen das Agent-Muster (Spec), sonst Fehler ohne Start. Eingetragen in `COMMANDS`, `generate_handler!`, Capability des Hauptfensters und `capabilities.rs`. Tests: Argumentliste exakt, `ref` mit Leerzeichen, `;`, `$(`, Backtick, führendem `-`, Zeilenumbruch, leerem und zu langem Wert abgelehnt, gültige Formen angenommen; Capability-Listen im Gleichlauf.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T12

### T10 — Desktop-UI: Dialog „Zugangsdaten hinterlegen“ (R-1225)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/invoke.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/components/monitoring/card/CredentialDialog.svelte, apps/desktop/ui/src/components/monitoring/card/CredentialDialog.test.ts, apps/desktop/ui/src/components/monitoring/card/ModuleCard.svelte, apps/desktop/ui/src/components/monitoring/card/ModuleCard.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @ec50507ce 2026-11-10T14:36:37+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T10.verdict.json)
Änderung: Bridge-Funktion für T9; an der Modulkarte bei `no_credential` der Knopf „Zugangsdaten hinterlegen“: Dialog wählt die SSH-Verbindung des Servers (eine: direkt; mehrere: Auswahl) und öffnet das Terminal; Ziel nicht Linux oder keine SSH-Verbindung → der Befehl zum Kopieren. Danach Hinweis, dass „hinterlegt“ mit dem nächsten Report erscheint. Tests: Kommando-Name und Parameter, Auswahl, Kopier-Fallback, kein Geheimnis-Feld im Dialog.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/bridge/invoke.test.ts src/lib/stores/terminals.test.ts src/lib/stores/connectFlow.test.ts src/components/monitoring/card/CredentialDialog.test.ts src/components/monitoring/card/ModuleCard.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T5, T9

### T11 — Desktop-E2E: Journey Server-Seite mit Schritt-Screenshots (R-1225)  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-server-page.live.js, scripts/tests/desktop_e2e_monitoring.sh, scripts/tests/e2e_api.py, apps/desktop/e2e/test/specs/monitoring-check.live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @01d7f8593 2026-11-10T15:36:11+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T11.verdict.json)
Änderung: Live-Spec (SPDX, nur ESLint) gegen den geseedeten Server mit echtem Agent: Server-Seite öffnen, System-Karte zu bei ok, „Neu gefunden“ zeigt den Port-Fund des Agents, übernehmen erzeugt die Modulkarte, Querschnitt-Reiter öffnen, Statusleiste ohne Warnung; an jedem Schritt ein Screenshot nach `.ah-out/screenshots/` (hell und dunkel). `desktop_e2e_monitoring.sh` fährt die Spec nach `monitoring-check.live.js`. Live-Lauf auf der warmen Desktop-VM (`/test`), Ergebnis und Screenshot-Pfad hier vermerkt.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: → T12
Abhängt von: T5, T6, T7, T8

### T12 — Doku DE+EN und Changelog (R-1225)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/arch-monitoring-ui.md, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @65711eab3 2026-11-10T15:56:10+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Admin-Doku: Server-Seite (Karten, zu/auf, Neu gefunden, Jetzt scannen, Unterdrückungsgrund, Kosten), Querschnitt-Reiter, Warnung „ohne Ergebnis“ mit Grenze, Zugangsdaten hinterlegen (Befehl, Linux-Ziele, Kopier-Fallback). Entwickler-Doku: `muted_reason`, `last_result_at`, `min_interval_s`, Route `costs`, `details.cert`, das neue Tauri-Kommando. Changelog-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/arch-monitoring-ui.md
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11

### T14 — Desktop-UI: Vertragstest und Monitoring-Übersicht nach den neuen Monitor-Typen (R-1225)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/components/monitoring/MonitoringOverview.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @d8c2dfa02 2026-11-10T16:19:47+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T14.verdict.json)
Änderung: Fund der ganzen Desktop-UI-Suite nach dem Basis-Merge (die Task-Verifys fuhren nur ihre Tests): `types.contract.test.ts` (R-0687) ordnet die neuen Interfaces ihren Schemas im Monitoring-Snapshot zu (`StatusSummaryOut`, `ServerCostsOut`, `CollectorCostOut`, `Catalog*Out`, `DiscoveryOut`, `FindingOut`, `AdoptOut`, `AdoptAllOut`), `MonitorCheck` beiden Antworten (`MonitorCheckOut` und `MonitorCheckStatusOut` mit `mutedReason`); die freien `details` von HTTP- und Probe-Check kommen nach `EXEMPT`. `MonitoringOverview.test.ts` mockt `sessionStore` mit, den `connections.ts` beim Import liest (seit T10 über `ModuleCard.svelte`). Drift zwischen Typ und Schema wird in `types.ts` behoben, nicht im Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts src/components/monitoring/MonitoringOverview.test.ts
Doku: keine (nur Tests und Typen)

### T15 — Desktop-UI: Test der Credential-Sitzung im Terminal ohne Snippets, Dateien und Broadcast (R-1225)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/terminal/SshTerminal.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @f0305bd1b 2026-11-10T16:41:32+01:00
Review: approve (.ah-out/review/arch-monitoring-ui/T15.verdict.json)
Änderung: Fund der Abschlussprüfung (blocker): `SshTerminal.svelte` blendet in der Credential-Sitzung aus T10 (`session.credential`) Snippets, Dateien und den Broadcast-Hinweis aus, damit nichts in die Eingabe des Geheimnisses gerät, doch kein Test mountet eine solche Sitzung. Neuer Fall neben dem Playbook-Fall (R-1073): Credential-Sitzung zeigt ihr Ziel, aber weder Snippets noch Dateien noch den Broadcast-Hinweis; Gegenprobe ohne `!session.credential` rot.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/terminal/SshTerminal.test.ts
Doku: keine (nur Test)

## Entscheidungen
- 2026-11-10 T1: neue Felder camelCase (`mutedReason`, `lastResultAt`, `minIntervalS`, Kosten `serverId`, `durationMs` …) statt snake_case wie in der Spec — die Status- und Verlaufsantworten (`MonitorCheckOut`, `ServerHistoryOut`) sind durchgehend camelCase, der Desktop liest sie so.
- 2026-11-10 T1: `alerter.muted_reasons` als eigene Bündel-Funktion neben `muted_reason`, nicht als dessen Umbau — die Fakes der Alerter-Tests (`_HostDownDb`, `_helpers.py`) hängen an der Abfrageform von `_host_is_down`; Gleichlauf hält `test_status_page_api.py` über alle Gründe und Rangfälle.
- 2026-11-10 T1: `minIntervalS` aus den DISTINCT-Intervallen aktiver Checks, das Minimum in Python über `scheduler.interval_timedelta` — `interval` ist Text ("15m" < "5m" lexikalisch), ein SQL-`min()` wäre falsch; ein unbekannter Wert zählt nicht.
- 2026-11-10 T1: Kosten-Route mit drei `query_range` über die letzten 5 min (Schritt 60 s), der jüngste Punkt je Reihe steht für die Stunde davor — der VM-Client kennt keine Instant-Abfrage; Semantik gegen VictoriaMetrics v1.155.0 im Docker geprobt (Mittel, Summe ohne Werte älter als 1 h, last, fremder Server ausgeschlossen).
- 2026-11-10 T2: `details.cert.not_before`/`not_after` als Unix-Sekunden (int) — wie `not_after` der Agent-Fühler `tls`/`certfile`, damit der Querschnitt „Zertifikate & Domains“ beide Quellen gleich liest. Weg belegt: httpx-Doku `network_stream` → `get_extra_info("ssl_object")`, Python-Doku `getpeercert()` („If the certificate was not validated, the dict is empty“), Test mit echtem TLS-Server durch `_PinnedTransport`; `ssrf.py` unverändert. Über einen Proxy (CONNECT-Tunnel) nicht getestet.
- 2026-11-10 T2: Test-PKI zur Laufzeit mit dem `openssl`-CLI (CA + zwei Blätter) — die Test-Abhängigkeiten tragen keinen X.509-Builder, und ein privater Schlüssel gehört nicht ins Repo; Erwartung der Daten aus `openssl x509 -dateopt iso_8601`, nicht aus `ssl`.
- 2026-11-10 Plan: T13 nachgetragen — die Status-API nennt je Check nur `moduleId`/`moduleInstance`, nicht den Katalog-Schlüssel; die Zuordnung Katalog-`card` → Check über Namen oder Fühler wäre brüchig (Checks sind umbenennbar, spätere Module teilen Fühler). Additives, nur lesendes Feld `moduleCheckKey` (camelCase wie T1).
- 2026-11-10 T5: `Verify:` um `checkDetails.test.ts` und `monitoringText.test.ts` erweitert — die Task ändert beide Modelle (`probeDetails`, `cardNote`, `cardSummary`), ihr Beweis gehört in denselben Lauf.
- 2026-11-10 T5: `MonCard` nimmt `status: null` (kein Punkt, kein `data-status`) und `defaultOpen` — die Karte „Neu gefunden“ hat keinen Status eigener Art und ist offen, solange sie etwas zeigt; eine zweite Kartenkomponente wäre Doppelcode.
- 2026-11-10 T5: `probeDetails` als `Partial<MonitorProbeDetails>` — die Details kommen vom Agenten; ein fehlendes Feld lässt die Karte auf Zählung und Rohtext zurückfallen statt zu brechen.
- 2026-11-10 T5: Kartenhinweis nach Gewicht: Host down vor Wartungsfenster, „still“ nur, wenn jeder Check der Karte still ist — ein einzelner stiller Check steht als Badge an seiner Zeile.
- 2026-11-10 T5: Checks mit `moduleId` gehören zur Karte ihrer Instanz, gleich welcher Typ; ein `probe` ohne Modul (von Hand angelegt) bekommt eine eigene Karte unter seinem Typ statt keiner.
- 2026-11-10 T5: Scheitert das Laden der Funde, bleibt die Karte „Neu gefunden“ mit der alten Liste und dem Hinweis „Liste nicht aktuell“; ohne Liste sagt sie „Funde gerade nicht abrufbar“ — eine verschwundene Karte läse sich wie „nichts gefunden“.
- 2026-11-10 T5: Eine Karte mit nur einer Sektion blendet deren Kopf aus (Titel, Punkt und Zahl stehen schon im Kartenkopf); die Sektionen verlieren in der Karte ihren eigenen Rahmen.
- 2026-11-10 T5: Was Übernehmen auslässt (`skippedChecks` mit Grund, bei „Alle übernehmen“ auch `failed`), steht als Warn-Callout (`role="status"`) unter dem Kopf der Serverseite, nicht in der Karte „Neu gefunden“ — die verschwindet mit dem letzten übernommenen Fund. Der Hinweis gilt nur für seinen Server, bleibt bis Schließen oder zum nächsten Übernehmen; die Gründe kommen roh vom Server (englisch, wie die Checker-Meldungen), der Check mit seinem Katalognamen. `Verify:` dazu um `i18n.test.ts` erweitert (neue Schlüssel DE+EN). Der Nit (Titel „probe“ einer Karte ohne Modul) bleibt: es gibt keinen Schlüssel für Check-Typen, einer nur dafür lohnt nicht.
- 2026-11-10 T6: „Statusleiste“ ist `StatusFooter.svelte` (die Fußzeile mit Modus, Tunnel, Problemen); `StatusBar.svelte` ist der Toast-Stapel. `Dateien:` und `Verify:` darauf umgestellt, dazu `pages/Monitoring.svelte` (der Hinweis der Monitoring-Seite aus der Spec) und `MonServerDashboard.test.ts` (die Kostenkarte dort gestubbt) mit ihren Tests und `i18n.test.ts`; elf Dateien, weil Spec-Ziel „Warnung“ Fußzeile und Seite zugleich trifft.
- 2026-11-10 T6: Totmann-Lesart: „Warnton“ der Spec ist der visuelle Warn-Ton (`--warning`, Callout `warning`), kein Klang. Keine Warnung vor der ersten Antwort (ob es aktive Checks gibt, ist dann unbekannt) und keine ohne aktiven Check (`minIntervalS` null; `total` zählt auch abgeschaltete). Die Dauer zählt ab dem letzten Ergebnis (`lastResultAt`, sonst ab der ersten Antwort mit Checks ohne Ergebnis), spätestens ab Beginn des Ausfalls des Servers; eine Uhrabweichung zwischen Desktop und Server bleibt hingenommen. Der Puls fragt nur bei An- und Abmelden neu an (der Session-Store feuert auch bei Einstellungen) und verwirft Antworten einer früheren Sitzung; eine hängende Anfrage endet spätestens am 90-s-Backstop von `apiRequest`.
- 2026-11-10 T6: Kostenkarte zu, ohne Status-Punkt (Kosten sind kein Check-Zustand), teuerster Collector zuerst nach CPU-Zeit, dann Dauer; „gebremst“ heißt Faktor > 1 oder zuletzt ausgesetzt, angezeigt als „läuft einmal in n Läufen“ (Bedeutung des Faktors aus `selfmeasure.go`). Keine Karte, solange die Antwort aussteht oder der Agent keine Collector-Kosten meldet (ältere Agenten); ein Fehler bleibt als Karte mit Grund stehen. Geladen wird je Serverwechsel, nicht periodisch (Mittel über 1 h).
- 2026-11-10 T7: `Dateien:` um `ServerLink.svelte` (Server-Link der Querschnitte, T8 nutzt ihn mit), `pages/Monitoring.test.ts` und `lib/stores/monitoring.test.ts` (neue Reiter und `openServerPage`) erweitert, zehn Dateien; `Verify:` dazu um diese Tests und `i18n.test.ts` (neue Schlüssel DE+EN).
- 2026-11-10 T7: Ein Server-Link öffnet die Listenansicht der Übersicht mit diesem Server (`openServerPage`), auch wenn vorher die Kachelansicht gewählt war — die Kachel zeigt keine Serverseite.
- 2026-11-10 T7: Die Backup-Details tragen keinen Zeitpunkt des letzten Backups, nur `backupStatus` und bei veralteten `ageHours`. Statt „letzter Erfolg“ und „Alter“ eine Spalte „Letztes Backup“: aktuell = „in den letzten <max> h“, veraltet = „vor n h/Tagen“, fehlend = „keins gefunden“. Ein Zeitstempel je VM wäre eine Erweiterung des Checkers (Kandidat für eine eigene Zeile).
- 2026-11-10 T7: Ein Backup-Check ohne VM-Zeile (Proxmox nicht lesbar, noch keine Daten, keine VM) behält eine Zeile mit Grund, damit der Server nicht aus der Liste fällt; der Ausfall nimmt die Farbe des Check-Status wie auf der Serverseite.
- 2026-11-10 T7: Zertifikat eines HTTP-Checks ohne brauchbares `not_before` bleibt „unbekannt“ (der HTTP-Status sagt nichts über das Zertifikat); Fühler-Zeilen (`tls`, `certfile`) nehmen den Check-Status (ihre Schwellen auf `days_left`), nur „abgelaufen“ ist am Datum sicher. Eine Fühler-Zeile bleibt, solange der Fühler scheitert, mit dessen Antwort statt Datum.
- 2026-11-10 T7: Der Reiter heißt nach Spec „Zertifikate & Domains“; Domain-Zeilen kommen erst mit dem RDAP-Fühler (R-1224), bis dahin stehen dort nur Zertifikate. Die leeren Ansichten sagen, woher Zeilen kommen (HTTPS-Checks und Fühler; Template „Proxmox Host“).
- 2026-11-10 T8: `Dateien:` um `pages/Monitoring.test.ts`, `lib/stores/monitoring.ts` (Reiter-Typ), `monitoringText.ts` mit Test und `MonServerDashboard.svelte` erweitert, elf Dateien; `Verify:` um deren Tests und `i18n.test.ts`. Die Sätze dazu, was Übernehmen auslässt (`findingLabel`, `adoptNoteLines`), wandern von der Serverseite nach `monitoringText.ts`, damit Serverseite und Funde aller Server denselben Text bauen; die Fälle der Serverseite (`MonServerDashboard.test.ts`) bleiben unverändert grün.
- 2026-11-10 T8: „Updates & Neustarts“ zeigt je Linux-Server Neustart nötig und offene Sicherheits-Updates, keine Gesamtzahl der Updates — der Agent zählt nur Sicherheits-Updates (`updates_linux.go`), alle Updates und Paketnamen kommen mit R-1227. Bewertung wie die Serverseite: „handeln“, wenn der Checker Neustart oder Sicherheits-Updates als Problem nennt (Farbe nach Check-Status, ein noch gedämpftes Problem grau), „Aktuell“ nur bei bekanntem Nein und 0, sonst „Nicht bewertet“ bzw. „Noch keine Daten“. Gleiche Bewertung bleibt in Reihenfolge der Servernamen.
- 2026-11-10 T8: „Funde“ gruppiert den offenen Eingang aller Server nach Server (Name, Zahlen nach Wert; ein unbekannter Server mit seiner ID), je Gruppe `FindingsInbox` mit „Alle übernehmen“ dieses Servers (`adopt-all?server_id`, wie auf der Serverseite) — ein „alle Server übernehmen“ gibt es nicht, es legte Checks auf vielen Hosts zugleich an. Was Übernehmen auslässt, steht wie auf der Serverseite als Warn-Callout über der Liste, mit dem Servernamen vor dem Fund. Der Reiter zählt eine nicht leere Liste (nie eine 0, wie Alerts).
- 2026-11-10 T9: `capabilities.rs` aus `Dateien:` genommen — die bestehenden Gleichlauf-Tests (`build.rs` = `generate_handler!` = Hauptfenster, feste Liste des abgelösten Terminal-Fensters) decken das neue Kommando ohne Änderung ab. Das Argument heißt `credential_ref` (JS `credentialRef`): `ref` ist in Rust ein Schlüsselwort.
- 2026-11-10 T9: `terminal_open_ssh_credential` nur aus dem Hauptfenster (`window.label() != pty::MAIN`, wie `terminal_detach`) statt `may_open_terminal` — ein abgelöstes Fenster öffnet nur seine eigene Sitzung neu, und seine Capability trägt das Kommando nicht. Die Sitzung nimmt keinen Broadcast der Snippet-Leiste an (er landete in der Eingabe des Geheimnisses), hat keinen SFTP-Kanal und keinen ControlMaster, und ssh bekommt die Schalter der Verbindung ohne Weiterleitungen und Agent-Forwarding (`base_args(…, false)`, wie der SFTP-Kanal): die Aktion braucht sie nicht, und ein offenes Terminal derselben Verbindung hält die Weiterleitungen schon. Muster und Länge des `ref` hält ein Test gegen `apps/agent/internal/credentials/store.go` im Gleichlauf.
- 2026-11-10 T10: `Dateien:` um `terminals.ts`, `connectFlow.ts` (je mit Test), `SshTerminal.svelte` und `ModuleCard.test.ts` erweitert, `bridge/types.ts` gestrichen (kein neuer Typ), zwölf Dateien: ein Fluss Bridge → Terminal-Store → Verbindungsfluss → Terminal-Ansicht → Karte und Dialog. `Verify:` um deren Tests und `i18n.test.ts` (neue Schlüssel DE+EN).
- 2026-11-10 T10: Die Aufforderung läuft als eigener Reiter des eingebetteten Terminals (`TerminalSession.credential`), unabhängig von der Konsolen-Einstellung (eine externe Konsole bekäme die feste Aktion nicht); ohne Snippets, Dateien und Broadcast-Hinweis, „Neu verbinden“ startet wieder die Aufforderung, und `openSessionIds` merkt sie nicht für den nächsten Start. Sie zählt wie ein SSH-Start als Sitzung der Verbindung (`markConnectionUsed`).
- 2026-11-10 T10: Der Knopf steht bei `no_credential` und `denied` (abgelehnt heißt meist falsches Geheimnis), nur wenn die Check-Konfiguration einen `credential.ref` trägt, der das Agent-Muster und 255 Zeichen einhält — die Desktop-UI prüft ihn selbst, bevor er Befehlstext zum Kopieren wird (ein manipulierter Server bekäme sonst Shell-Zeichen in den angezeigten Befehl). Windows erkennt die Karte an `Server.osType` wie die Serverdetails: die Agent-Fakten (`os`) liefert die Monitoring-API der Desktop-UI nicht, sie freizugeben wäre ein API-Vertrag (Kevins Bereich). Ohne `osType` gilt Linux; auf einem Windows-Host scheitert der Terminal-Weg dann sichtbar an `sudo`.
- 2026-11-10 T10: Die bestehende Annahme in `connectFlow.test.ts` (eingebettetes SSH) prüft jetzt, dass ein Shell-Start keinen `ref` mitgibt (`undefined` als viertes Argument von `openTerminal`).
- 2026-11-10 T11: Der Agent-Container lebt den ganzen Lauf (`sleep 7200`, `docker rm -f` im EXIT-Trap), damit die zweite Spec ihn erneut melden lassen kann (`AH_E2E_AGENT`), und läuft mit `--pid host --cap-add SYS_PTRACE --security-opt apparmor=unconfined`: der Probe-Guard verbindet sich mit keinem Port, dessen Besitzer er nicht lesen kann (`checkListener`, fail-closed), im eigenen PID-Namensraum fand der Scan daher keinen Port. Die Ursache war das Test-Setup, nicht der Guard; so sieht der Agent die Host-Prozesse wie ein auf dem Host installierter Agent.
- 2026-11-10 T11: Der Port-Fund der Spec ist der veröffentlichte Gateway-Port (`tcp-$E2E_HTTPS_PORT`, ein `docker-proxy` auf dem Host-Netz); das Skript prüft ihn vor den Specs über die neue Operation `findings <server_id>` in `e2e_api.py` (`Dateien:` dazu erweitert). Weitere `docker-proxy`-Ports des Stacks stehen ebenfalls in „Neu gefunden“, die Spec übernimmt nur ihren.
- 2026-11-10 T11: `monitoring-check.live.js` Schritt 3 (R-1103): der Verlauf steht jetzt in der Karte „System“ der Serverseite, die Spec öffnet sie. Ihr Check aus Schritt 1 ist Push-only (`PUSH_ONLY_TYPES`) und bleibt bis zum nächsten Report wartend, die Karte also zu; die Spec öffnet sie bei „wartend“ statt auf „ok“ zu warten (Box-Lauf 3: „never left pending“). Die Annahmen an Verlauf und Vergleich bleiben dieselben (verschobener Test, kein Rückbau).
- 2026-11-10 T11 Live-Lauf: eigene Desktop-Box der Lane `arch-monitoring-ui` (`iter.sh`, `run.sh e2e --strict --step desktop_e2e_monitoring`): `desktop_e2e_monitoring: 8 passed, 0 failed`, `run.sh[e2e]: 1 passed, 0 failed, 0 skipped, 0 test-skips, 0 reruns`; monitoring-check 4/4, monitoring-server-page 8/8. Screenshots je Schritt hell und dunkel unter `.ah-out/screenshots/server-page-0{1..9}-*-{light,dark}.png`, an Kevin vor dem Merge gegeben.
- 2026-11-10 T12: `Dateien:` um `docs/developer/desktop.html` und `docs/en/developer/desktop.html` erweitert: das neue Tauri-Kommando `terminal_open_ssh_credential` gehört in die Zeile „Eingebettetes Terminal“ der Desktop-Entwickler-Doku, nicht in die Monitoring-Seite. Die Kostenkarte ist in der Admin-Doku mit dem Fenster der Route beschrieben (Mittel der letzten Stunde).
