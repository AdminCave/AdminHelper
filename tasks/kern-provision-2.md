# Nachlese Provisionieren — Task-Ledger
Status: aktiv · Branch: feature/kern-provision-2 · Review: pro Task
Spec: docs/features/kern-provision-2.md (Roadmap R-1629, R-1612, R-1613, R-1614, R-1628)
Heavy: linux-full — Server-API (Katalog, Fortschritt) und Desktop-Provisionieren
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1629: Zeichenprüfung im Befehlsbau  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/provisioning/command.ts, apps/desktop/ui/src/lib/provisioning/command.test.ts
Änderung: Die Zeichenprüfung für Kopf und Werte vereinheitlichen und erweitern (Einzelheiten tasks/private); je Klasse ein Testfall für Kopf und Wert, der keinen Befehl ergibt. `security` prüft mit.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/provisioning/command.test.ts
Doku: → T6

### T2 — R-1612: Katalog: Windows-Token über stdin, Test für unlesbares ABI-Verzeichnis  [ ]
Komponente: server · Dateien: apps/server/app/modules/provisioning/catalog.py, apps/server/tests/test_provisioning_catalog.py
Änderung: Windows `reregister` im Automationsmodus `--token-stdin` mit Wert `tokenStdin` statt `--token`/`token`; Test dafür und für ein `<ABI>/All`, dessen Auflistung scheitert (das ABI fällt weg, die übrigen bleiben).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning_catalog.py tests/test_openapi_snapshot.py
Doku: → T6

### T3 — R-1612: Desktop: Token als Pipe vor den Befehlskopf  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/provisioning/command.ts, apps/desktop/ui/src/lib/provisioning/command.test.ts
Änderung: Wertetyp `tokenStdin` (nur Automationsmodus, nur bei gültigem Token): Flag ohne Wert anhängen, gequoteten Token per Shell-Pipe vor den Kopf setzen; Tests für PowerShell und sh, kein Token im argv-Teil.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/provisioning/command.test.ts
Abhängt von: T1
Doku: → T6

### T4 — R-1613/R-1628: Fortschritt: URL-Quoting, widerrufene Linie, kein Request ohne Key; Migrations-Docstring  [ ]
Komponente: server · Dateien: apps/server/app/modules/provisioning/progress.py, apps/server/tests/test_provisioning_progress.py, apps/server/alembic/versions/6a4e9feea1c5_server_os_type_platform.py
Änderung: `quote(server_id, safe='')` in der Monitoring-URL; `_certificate` nur aus nicht widerrufenen Linien; Test ohne Monitoring-Key prüft per `httpx_mock`, dass kein Request rausgeht; `downgrade()` begründet das bewusste Nichtstun im Docstring.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning_progress.py
Doku: keine (internes Verhalten)

### T5 — R-1614/R-1628: Dialog: Ersatztext für unbekannte Katalogwerte, Tab-Label und Fortschrittstest  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.test.ts, apps/desktop/ui/src/components/infra/provisioning/ProvisioningProgress.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Unbekannter `reason`/`port.purpose` zeigt einen Ersatztext (DE+EN) statt des rohen Schlüssels; der Dialogtest findet die Aktions-Tabs per `getByRole('tablist', { name })`; Fortschrittstest „früherer Token, dann falsche Antwort“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/provisioning src/lib/i18n
Doku: keine (Ersatztext für Fehlerfall)

### T6 — R-1612: Doku und Changelog  [ ]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-provision-2.md
Änderung: Windows-Abschnitt: der Automationsbefehl des Desktops gibt den Token über stdin; Changelog-Eintrag (neutral für T1).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

### T7 — R-1628: oasdiff-Fall für die R-1594-Ausnahmen (Harness, Kevin 2026-11-19)  [ ]
Komponente: scripts · Dateien: scripts/tests/openapi_breaking_test.sh
Änderung: Ein Fall gegen das echte oasdiff mit Fixture-Specs für den Plattform-Enum: mit Ausnahmedatei grün, ein weiterer Enum-Wert an anderem Feld bleibt ERR.
Verify: bash scripts/dev/verify.sh scripts --strict -- openapi_breaking_test
Doku: keine (Testfall)

## Entscheidungen
- R-1612 Variante A (Wertetyp `tokenStdin`, Pipe): Token nie im argv; ein älterer Desktop baut den Windows-Automationsbefehl dann nicht (dokumentiertes Verhalten für Unbekanntes).
