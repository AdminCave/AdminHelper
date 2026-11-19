# Provisionieren je Plattform — Task-Ledger
Status: aktiv · Branch: feature/kern-provision-1 · Review: pro Task
Spec: docs/features/kern-provision-1.md (Roadmap R-1594, R-1595, R-1596, R-1597)
Heavy: linux-full — Server-API, `docker-compose.yml` (Repo-Mount) und die Desktop-Journey `provisioning.live.js` ändern sich; kein Cross-Host-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1594: os_type als Plattform-Enum mit Migration  [x]
Komponente: server · Dateien: apps/server/app/modules/servers/schemas.py, apps/server/tests/test_server_platform_migration.py, apps/server/tests/test_servers_platform.py, apps/server/tests/openapi.snapshot.json, apps/server/alembic/versions/6a4e9feea1c5_server_os_type_platform.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d9e182985 2026-11-19T07:37:14+01:00
Review: approve (.ah-out/review/kern-provision-1/T1.verdict.json)
Änderung: `os_type` nimmt nur `linux|windows|freebsd|opnsense|other|null` (Literal in `ServerCreate`/`ServerUpdate`/`ServerOut`, 422 sonst). Die Migration ordnet die Freitexte nach der Spec zu (Linux-Distributionsnamen, `win`, `freebsd`, `opnsense`, sonst `other`; leer → `null`). Ihr Test fährt `upgrade` über Beispielzeilen und `downgrade`. Sie baut erst auf dem Alembic-Kopf nach dem Merge von #569 (kern-notify-6, zwei Migrationen).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_server_platform_migration.py tests/test_servers_platform.py tests/test_openapi_snapshot.py tests/test_migrations_smoke.py
Doku: → T10

### T2 — R-1594: Desktop-Auswahlfeld Plattform  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/ServerDetail.svelte, apps/desktop/ui/src/components/infra/ServerModal.svelte, apps/desktop/ui/src/components/infra/ServerModal.test.ts, apps/desktop/ui/src/components/monitoring/card/ModuleCard.svelte, apps/desktop/ui/src/components/monitoring/card/ModuleCard.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/models/infra.test.ts, apps/desktop/ui/src/lib/models/infra.ts, apps/desktop/ui/src/pages/Infrastructure.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @a7bac90e9 2026-11-19T07:47:41+01:00
Review: approve (.ah-out/review/kern-provision-1/T2.verdict.json)
Änderung: `osType` wird der Union-Typ. `ServerModal` zeigt ein Auswahlfeld mit übersetzten Namen, `ServerDetail` den übersetzten Namen. `ServerDetail` und `ModuleCard` prüfen `=== 'windows'` statt `includes`. Die Testdaten nehmen Plattformwerte.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Infrastructure.test.ts src/lib/models/infra.test.ts src/components/infra src/components/monitoring/card
Doku: → T10
Abhängt von: T1

### T3 — R-1595: Plattform-Katalog GET /api/provisioning/platforms  [x]
Komponente: server · Dateien: apps/server/app/modules/provisioning/catalog.py, apps/server/app/modules/provisioning/router.py, apps/server/app/modules/provisioning/schemas.py, apps/server/app/core/config.py, apps/server/app/main.py, docker-compose.yml, apps/server/tests/test_provisioning_catalog.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @5d2dd6553 2026-11-18T18:10:07+01:00
Review: approve (.ah-out/review/kern-provision-1/T3.verdict.json)
Änderung: Neu `catalog.py` (SPDX) liest `REPO_DIR` (Vorgabe `/app/repo`). Daraus `available`, `versions` und ABIs je Plattform nach der Spec; Windows immer, ohne `install` bis R-1578. Je Aktion strukturierte Befehle (`shell`, `base`, `args` mit `flag`, `value` aus `serverUrl|serverId|caFp|token`, `optional`, `automation`), `prerequisites` (Versionen, Ports 443/8444/8445, 7000 mit Tunnel), `doc` je Sprache. Die Route ist nur für Admins (Scope access). `docker-compose.yml`: Dienst `server` bekommt `./repo:/app/repo:ro`. Tests mit einem Repo-Baum unter `tmp_path` (leer, nur apt, alle), Auth und Snapshot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning_catalog.py tests/test_openapi_snapshot.py
Doku: → T10

### T4 — R-1597: Monitoring-Route GET /agent/{server_id}/state  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_agent_state.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/tests/test_response_shapes.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @0d9377608 2026-11-18T17:46:14+01:00
Review: approve (.ah-out/review/kern-provision-1/T4.verdict.json)
Änderung: Interne Route (`require_internal`) liefert `lastReportAt` (aus `MonitorAgentLiveness`) und `hostFacts` (`os`, `platform`, `platformVersion` aus `MonitorHostFacts`). Bei unbekanntem Server kommen beide als `null`, nie 404, damit der Server nicht zwischen „unbekannt“ und „noch kein Bericht“ raten muss.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_state.py tests/test_openapi_snapshot.py tests/test_response_shapes.py
Doku: keine (interne Route)

### T5 — R-1597/R-1594: GET /api/servers/{id}/provision/progress  [x]
Komponente: server · Dateien: apps/server/app/modules/provisioning/router.py, apps/server/app/modules/provisioning/schemas.py, apps/server/app/modules/provisioning/progress.py, apps/server/tests/test_provisioning_progress.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8dc9418a8 2026-11-18T18:15:35+01:00
Review: approve (.ah-out/review/kern-provision-1/T5.verdict.json)
Änderung: Neu `progress.py` (SPDX). Die Route liefert:
- Token: neuester, `createdAt`/`usedAt`/`expiresAt`
- Zertifikat: neuestes der Agent-Identität (`subject_id`=Server-ID, Scope agent), `issuedAt`
- Bericht: `lastReportAt` und Host-Fakten über T4; Ausfall → `null` und `monitoringReachable: false`
- Tunnel: nur mit Tunnel, aus `read_proxy_list`
- `reportedPlatform` (Abbildung `os` → Plattform) und `platformMismatch` (FreeBSD und OPNsense gelten als gleich)

Admin, Scope access. Tests decken alle Stufen ab, Monitoring aus, fremden Server, Mismatch und Snapshot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning_progress.py tests/test_openapi_snapshot.py
Doku: → T10
Abhängt von: T1, T4

### T6 — R-1595: Desktop-Katalog-Client und Befehlsbau je Shell  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/provisioning.ts, apps/desktop/ui/src/lib/api/provisioning.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/provisioning/command.ts, apps/desktop/ui/src/lib/provisioning/command.test.ts, apps/desktop/ui/src/lib/utils/powershell.ts, apps/desktop/ui/src/lib/utils/powershell.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @198758015 2026-11-18T18:00:01+01:00
Review: approve (.ah-out/review/kern-provision-1/T6.verdict.json)
Änderung: Client für `platforms()` und `progress()`. Neu `command.ts` (SPDX) baut aus einem Katalog-Befehl und den Werten den Text: bash/sh mit `shellQuote` und ` \`-Umbruch, PowerShell mit neuem `psQuote` (`'…'`, `'` verdoppelt, nach `about_Quoting_Rules`) und Backtick-Umbruch. Unbekannte Shell oder Wert-Art, oder ein Pflichtwert fehlt → kein Befehl. Den Token setzt `command.ts` nur im Automatisierungsmodus ein. Die Wertprüfungen (`TOKEN_FORM`, `UUID_FORM`) wandern aus dem Tab hierher. Tests mit feindlichen Werten (`'`, `$(…)`, Backtick, Zeilenumbruch).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/provisioning src/lib/utils/powershell.test.ts src/lib/api/provisioning.test.ts
Doku: keine (intern; Verhalten dokumentiert T10)

### T7 — R-1596: Provisionieren-Fenster ersetzt den Linux-Tab  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.test.ts, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.test.ts, apps/desktop/ui/src/components/infra/ServerDetail.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/e2e/test/specs/provisioning.live.js, apps/desktop/ui/src/lib/provisioning/command.ts, apps/desktop/ui/src/lib/provisioning/command.test.ts, apps/desktop/ui/src/lib/i18n/i18n.test.ts, apps/desktop/ui/src/lib/api/types.contract.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e92fa1847 2026-11-18T18:31:10+01:00
Review: approve (.ah-out/review/kern-provision-1/T7.verdict.json)
Änderung: Neu `ProvisioningDialog` (SPDX), im Tab geöffnet. Er zeigt:
- Plattform-Auswahl aus dem Katalog, vorgewählt aus `osType`; nicht verfügbare Plattformen ausgegraut mit Grund
- Voraussetzungen
- Reiter Installieren/Aktualisieren/Neu registrieren/Entfernen
- einen Befehl mit Kopieren
- Token-Erzeugung wie heute (verdeckt, Auto-Ausblenden)
- Umschalter „Für Automatisierung“ mit Warnung

Der Tab behält die Token-Liste und den Knopf, der das Fenster öffnet. Die Tests übernehmen die heutigen
Tab-Prüfungen und ergänzen Plattformwechsel, Automatisierung und fehlenden Katalog. Die E2E-Spec bedient das Fenster.
Test-Löschung: apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.test.ts::* — die Befehlsprüfungen ziehen gleichwertig nach ProvisioningDialog.test.ts und command.test.ts
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra src/lib/provisioning src/lib/i18n src/lib/api/types.contract.test.ts src/styles/tokens.test.ts
Doku: → T10
Abhängt von: T2, T6

### T8 — R-1597/R-1594: Live-Fortschritt und Plattform-Abweichung  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/provisioning/ProvisioningProgress.svelte, apps/desktop/ui/src/components/infra/provisioning/ProvisioningProgress.test.ts, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/components/infra/ServerDetail.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.test.ts, apps/desktop/ui/src/components/infra/ServerDetail.test.ts, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte, apps/desktop/ui/src/lib/i18n/i18n.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @cbf0c8c35 2026-11-18T18:47:30+01:00
Review: approve (.ah-out/review/kern-provision-1/T8.verdict.json)
Änderung: Neu `ProvisioningProgress` (SPDX). Vier Stufen; Abfrage alle 5 s, solange das Fenster offen und nicht alles grün ist; Stopp beim Schließen. Hinweise: Token abgelaufen; kein Bericht 5 min nach `usedAt` → Ports 443/8444, Uhrzeit, Proxy; Tunnel fehlt. Am Ende Knopf „Monitoring-Vorschläge ansehen“ (Navigation zu den Vorlagen-Vorschlägen des Servers). `ServerDetail` zeigt bei `platformMismatch` einen Hinweis neben der Plattform. Tests mit Fake-Timern.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra src/lib/i18n src/styles/tokens.test.ts
Doku: → T10
Abhängt von: T7

### T9 — R-1596: Doku-Link im Fenster  [x]
Komponente: desktop · Dateien: apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.test.ts, apps/desktop/src-tauri/src/doc_link.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/pages/Infrastructure.test.ts, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @47a78b49b 2026-11-18T19:23:27+01:00
Review: approve (.ah-out/review/kern-provision-1/T9.verdict.json)
Änderung: Der Link im Fenster setzt die Basis-URL aus Kevins Antwort vor `doc.<sprache>` des Katalogs und öffnet sie über den Shell-Opener.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html (Befehlstabelle `open_doc`); Verhalten in T10
Abhängt von: T7

### T10 — R-1596: Doku je Plattform, API, Changelog  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-provision-1.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1667325ab 2026-11-19T09:11:30+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: `agent-deployment` gliedert je Plattform (Linux, Windows, FreeBSD, OPNsense), je Abschnitt Installieren, Aktualisieren, Neu registrieren und Entfernen. Dazu das Provisionieren-Fenster mit Fortschritt, das Plattformfeld samt Migration (Freitext → Plattform) und die zwei neuen Routen in `developer/api-reference`. Erst nach dem Merge von ops-8, kern-windows-1 und ops-9, auf frischem `origin/main` (gleiche Datei). Anker der Katalog-`doc`-Einträge (T3) gegen die neue Gliederung prüfen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-provision-1.md
Task-Review: am Ende
Abhängt von: T3, T8

### T11 — R-1595: Windows-Programmpfad im Katalog (Abschlussprüfung)  [ ]
Komponente: server · Dateien: apps/server/app/modules/provisioning/catalog.py, apps/server/tests/test_provisioning_catalog.py
Änderung: `WINDOWS_EXE` zeigt auf `C:\Program Files\AdminHelper Agent\adminhelper-agent.exe` (seit 180479cd3 der Agent-Ordner, `service_windows.go` `programDirName`; `AdminHelper` ist der Ordner der Desktop-App). Test nagelt den Pfad in Neu registrieren und Entfernen fest.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning_catalog.py
Doku: keine (Doku nennt den Ordner schon richtig)

### T12 — R-1594/R-1596: Desktop-Fixtures, Aktions-Label, E2E-Fristen, Entfernen-Hinweis (Abschlussprüfung)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/provisioning/command.test.ts, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.test.ts, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/e2e/test/specs/provisioning.live.js, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Änderung: Fixtures auf den Agent-Ordner `AdminHelper Agent`; die Aktions-Tabs bekommen ein eigenes Label `infra.prov.actionLabel` (Vorgang/Action) statt „Plattform“; die drei E2E-Wartezeiten des Dialogs auf 30 s (`testing.md`: der Dialog lädt erst den Katalog); Windows-Abschnitt nennt, dass Entfernen im Fenster `service uninstall --purge` nimmt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra src/lib/provisioning src/lib/i18n
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Abhängt von: T11

## Entscheidungen
- 2026-11-18 Plan: Katalog liest das eingebundene `./repo` statt einer Env-Liste; Befehle strukturiert, Zitieren im Desktop (R-1595).
- 2026-11-18 Plan: Windows ohne Installationsbefehl bis R-1578 (Notiz an R-1596).
- 2026-11-18 Plan: Monitoring-Route in `agent.py`, nicht `checks.py` (offen auf feature/kern-monitoring-45).
- 2026-11-18 T6 vor T3/T5: die Antwortformen stehen als Vertrag in der Spec („Antwortformen“); die Zuordnung der neuen Typen im Vertragstest `types.contract.test.ts` kommt mit T7, wenn der Server-Snapshot sie trägt.
- 2026-11-18 T9: Kevin: Doku-Link als GitHub-blob-Link (`https://github.com/AdminCave/AdminHelper/blob/main/docs/…#anker`).
- 2026-11-18 T3 (aus security T6): Windows PowerShell 5.1 reicht eingebettete `"` an native `.exe` kaputt weiter. Der Katalog (T3) ruft die `.exe` direkt auf; daher lehnt `buildCommand` in T7 bei `shell === 'powershell'` jeden Wert mit `"` ab (null), mit Test (reviewer T3: Pflicht T7 zugeordnet, `command.ts` in T7-Dateien). T7 nutzt `ProvisionPlatformId`/`ProvisionAction` oder streicht sie und entfernt die Formen-Kopie im Tab (reviewer T6).
- 2026-11-18 T7 vor T2 (T2 wartet auf #569): die Vorauswahl nimmt `osType` nur, wenn es eine Katalog-ID ist, sonst die erste verfügbare Plattform; mit T2 trägt `osType` immer einen Plattformwert. Plattformen und Aktionen, für die der Desktop keine Beschriftung hat (`ProvisionPlatformId`/`ProvisionAction`), blendet das Fenster aus. Die Formen-Kopie `TOKEN_FORM`/`UUID_FORM` im Tab ist weg (der Tab baut keine Befehle mehr).
- 2026-11-18 T7: Der eigene „Nur provisionieren“-Befehl des alten Tabs entfällt; „Neu registrieren“ aus dem Katalog ersetzt ihn (Linux: der Installer erneut, liest den Token verdeckt). Die E2E-Spec wählt Windows, weil es unabhängig vom Paket-Repo des Stacks einen Befehl mit Token trägt.
- 2026-11-18 T8: Die Token-Bereinigung löscht eingelöste Tokens; „Token eingelöst“ gilt daher auch mit einem Agent-Zertifikat, und der 5-min-Hinweis rechnet ab `usedAt`, sonst ab `certificate.issuedAt`. Der Fortschritt läuft nur unter Installieren/Neu registrieren, fragt alle 5 s, bis alle Stufen erledigt sind, und endet mit dem Fenster. Ohne erreichbares Monitoring steht „Erster Bericht“ auf unbekannt, ohne Hinweis. „Monitoring-Vorschläge ansehen“ schließt das Fenster und wechselt in den Monitoring-Reiter des Servers (dort liegen die Vorlagen-Vorschläge). Die Server-Ansicht fragt den Fortschritt einmal je Server mit gewählter Plattform ab, nur für Admins, für den Abweichungs-Hinweis. Nach reviewer T8: alle Stufen hängen am neuesten Token (Zertifikat und Bericht zählen erst ab seinem `createdAt`), ein im Fenster erzeugter Token startet den Fortschritt neu.
- 2026-11-18 T9: Der Desktop hatte keinen Weg, eine URL im Browser zu öffnen (das Shell-Plugin trägt keine `shell:allow-open`-Berechtigung). Statt einer offenen Opener-Berechtigung bekommt er den Befehl `open_doc(path)`: die Basis `https://github.com/AdminCave/AdminHelper/blob/main/docs/` steht fest in Rust, der Pfad aus dem Katalog nimmt nur Kleinbuchstaben, Ziffern, `-`, `_`, Segmente mit `/`, Endung `.html` und einen Anker. Die Task wird damit Komponente `desktop` (Rust + UI, neun Dateien).
- 2026-11-18 T9: Das volle Desktop-Verify fand `pages/Infrastructure.test.ts` rot seit T8: der Seitentest mockte die Session ohne `session`-Store, `ServerDetail` liest ihn seit T8. Das T8-Verify war auf `components/infra` begrenzt; der Mock-Fix geht in T9 mit, dazu der Eintrag `open_doc` in der IPC-Befehlstabelle (DE+EN, `ipc.inventory.test.ts`).
- 2026-11-19 Abschlussprüfung reviewer: Blocker Windows-Pfad (T11), wichtig E2E-Fristen und zwei Nits (T12); T9 `Dateien:` ohne die nie angelegte `docs.ts`.
