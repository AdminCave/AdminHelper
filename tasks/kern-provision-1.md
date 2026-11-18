# Provisionieren je Plattform — Task-Ledger
Status: aktiv · Branch: feature/kern-provision-1 · Review: pro Task
Spec: docs/features/kern-provision-1.md (Roadmap R-1594, R-1595, R-1596, R-1597)
Heavy: linux-full — Server-API, `docker-compose.yml` (Repo-Mount) und die Desktop-Journey `provisioning.live.js` ändern sich; kein Cross-Host-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1594: os_type als Plattform-Enum mit Migration  [ ]
Komponente: server · Dateien: apps/server/app/modules/servers/schemas.py, apps/server/app/modules/servers/models.py, apps/server/alembic/versions/, apps/server/tests/test_server_platform_migration.py, apps/server/tests/test_servers_platform.py, apps/server/tests/openapi.snapshot.json
Änderung: `os_type` nimmt nur `linux|windows|freebsd|opnsense|other|null` (Literal in `ServerCreate`/`ServerUpdate`/`ServerOut`, 422 sonst). Die Migration ordnet die Freitexte nach der Spec zu (Linux-Distributionsnamen, `win`, `freebsd`, `opnsense`, sonst `other`; leer → `null`). Ihr Test fährt `upgrade` über Beispielzeilen und `downgrade`. Sie baut erst auf dem Alembic-Kopf nach dem Merge von #569 (kern-notify-6, zwei Migrationen).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_server_platform_migration.py tests/test_servers_platform.py tests/test_openapi_snapshot.py tests/test_migrations_smoke.py
Doku: → T10

### T2 — R-1594: Desktop-Auswahlfeld Plattform  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/ServerModal.svelte, apps/desktop/ui/src/components/infra/ServerDetail.svelte, apps/desktop/ui/src/components/monitoring/card/ModuleCard.svelte, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/models/infra.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/pages/Infrastructure.test.ts, apps/desktop/ui/src/lib/models/infra.test.ts
Änderung: `osType` wird der Union-Typ. `ServerModal` zeigt ein Auswahlfeld mit übersetzten Namen, `ServerDetail` den übersetzten Namen. `ServerDetail` und `ModuleCard` prüfen `=== 'windows'` statt `includes`. Die Testdaten nehmen Plattformwerte.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Infrastructure.test.ts src/lib/models/infra.test.ts src/components/infra src/components/monitoring/card
Doku: → T10
Abhängt von: T1

### T3 — R-1595: Plattform-Katalog GET /api/provisioning/platforms  [ ]
Komponente: server · Dateien: apps/server/app/modules/provisioning/catalog.py, apps/server/app/modules/provisioning/router.py, apps/server/app/modules/provisioning/schemas.py, apps/server/app/core/config.py, apps/server/app/main.py, docker-compose.yml, apps/server/tests/test_provisioning_catalog.py, apps/server/tests/openapi.snapshot.json
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

### T5 — R-1597/R-1594: GET /api/servers/{id}/provision/progress  [ ]
Komponente: server · Dateien: apps/server/app/modules/provisioning/router.py, apps/server/app/modules/provisioning/schemas.py, apps/server/app/modules/provisioning/progress.py, apps/server/tests/test_provisioning_progress.py, apps/server/tests/openapi.snapshot.json
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

### T6 — R-1595: Desktop-Katalog-Client und Befehlsbau je Shell  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/provisioning.ts, apps/desktop/ui/src/lib/api/provisioning.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/provisioning/command.ts, apps/desktop/ui/src/lib/provisioning/command.test.ts, apps/desktop/ui/src/lib/utils/powershell.ts, apps/desktop/ui/src/lib/utils/powershell.test.ts
Änderung: Client für `platforms()` und `progress()`. Neu `command.ts` (SPDX) baut aus einem Katalog-Befehl und den Werten den Text: bash/sh mit `shellQuote` und ` \`-Umbruch, PowerShell mit neuem `psQuote` (`'…'`, `'` verdoppelt, nach `about_Quoting_Rules`) und Backtick-Umbruch. Unbekannte Shell oder Wert-Art, oder ein Pflichtwert fehlt → kein Befehl. Den Token setzt `command.ts` nur im Automatisierungsmodus ein. Die Wertprüfungen (`TOKEN_FORM`, `UUID_FORM`) wandern aus dem Tab hierher. Tests mit feindlichen Werten (`'`, `$(…)`, Backtick, Zeilenumbruch).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/provisioning src/lib/utils/powershell.test.ts src/lib/api/provisioning.test.ts
Doku: keine (intern; Verhalten dokumentiert T10)
Abhängt von: T3, T5

### T7 — R-1596: Provisionieren-Fenster ersetzt den Linux-Tab  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.test.ts, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.test.ts, apps/desktop/ui/src/components/infra/ServerDetail.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/e2e/test/specs/provisioning.live.js
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
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra
Doku: → T10
Abhängt von: T2, T6

### T8 — R-1597/R-1594: Live-Fortschritt und Plattform-Abweichung  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/provisioning/ProvisioningProgress.svelte, apps/desktop/ui/src/components/infra/provisioning/ProvisioningProgress.test.ts, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/components/infra/ServerDetail.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Neu `ProvisioningProgress` (SPDX). Vier Stufen; Abfrage alle 5 s, solange das Fenster offen und nicht alles grün ist; Stopp beim Schließen. Hinweise: Token abgelaufen; kein Bericht 5 min nach `usedAt` → Ports 443/8444, Uhrzeit, Proxy; Tunnel fehlt. Am Ende Knopf „Monitoring-Vorschläge ansehen“ (Navigation zu den Vorlagen-Vorschlägen des Servers). `ServerDetail` zeigt bei `platformMismatch` einen Hinweis neben der Plattform. Tests mit Fake-Timern.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra
Doku: → T10
Abhängt von: T7

### T9 — R-1596: Doku-Link im Fenster  [?] (Ziel des Doku-Links: GitHub-Quelltext der HTML-Datei oder eine gehostete Doku?)
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.test.ts, apps/desktop/ui/src/lib/provisioning/docs.ts
Änderung: Der Link im Fenster setzt die Basis-URL aus Kevins Antwort vor `doc.<sprache>` des Katalogs und öffnet sie über den Shell-Opener.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/provisioning
Doku: keine (Verhalten in T10)
Abhängt von: T7

### T10 — R-1596: Doku je Plattform, API, Changelog  [ ]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-provision-1.md
Änderung: `agent-deployment` gliedert je Plattform (Linux, Windows, FreeBSD, OPNsense), je Abschnitt Installieren, Aktualisieren, Neu registrieren und Entfernen. Dazu das Provisionieren-Fenster mit Fortschritt, das Plattformfeld samt Migration (Freitext → Plattform) und die zwei neuen Routen in `developer/api-reference`. Erst nach dem Merge von ops-8, kern-windows-1 und ops-9, auf frischem `origin/main` (gleiche Datei). Anker der Katalog-`doc`-Einträge (T3) gegen die neue Gliederung prüfen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-provision-1.md
Task-Review: am Ende
Abhängt von: T3, T8

## Entscheidungen
- 2026-11-18 Plan: Katalog liest das eingebundene `./repo` statt einer Env-Liste; Befehle strukturiert, Zitieren im Desktop (R-1595).
- 2026-11-18 Plan: Windows ohne Installationsbefehl bis R-1578 (Notiz an R-1596).
- 2026-11-18 Plan: Monitoring-Route in `agent.py`, nicht `checks.py` (offen auf feature/kern-monitoring-45).
