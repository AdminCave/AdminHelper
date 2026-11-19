# Nachlese Provisionieren — Task-Ledger
Status: erledigt · Branch: feature/kern-provision-2 · Review: pro Task
Spec: docs/features/kern-provision-2.md (Roadmap R-1629, R-1612, R-1613, R-1614, R-1628)
Heavy: linux-full — Server-API (Katalog, Fortschritt) und Desktop-Provisionieren
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1629: Zeichenprüfung im Befehlsbau  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/provisioning/command.ts, apps/desktop/ui/src/lib/provisioning/command.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @353284a5d 2026-11-19T17:12:44+01:00
Review: approve (.ah-out/review/kern-provision-2/T1.verdict.json)
Änderung: Die Zeichenprüfung für Kopf und Werte vereinheitlichen und erweitern (Einzelheiten tasks/private); je Klasse ein Testfall für Kopf und Wert, der keinen Befehl ergibt. `security` prüft mit.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/provisioning/command.test.ts
Doku: → T6

### T2 — R-1612: Katalog: Windows-Token über stdin, Test für unlesbares ABI-Verzeichnis  [x]
Komponente: server · Dateien: apps/server/app/modules/provisioning/catalog.py, apps/server/tests/test_provisioning_catalog.py, apps/server/app/modules/provisioning/schemas.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b3f428876 2026-11-19T19:18:52+01:00
Review: approve (.ah-out/review/kern-provision-2/T2.verdict.json)
Änderung: Windows `reregister` im Automationsmodus `--token-stdin` mit Wert `tokenStdin` statt `--token`/`token`; Test dafür und für ein `<ABI>/All`, dessen Auflistung scheitert (das ABI fällt weg, die übrigen bleiben).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning_catalog.py tests/test_openapi_snapshot.py
Doku: → T6

### T3 — R-1612: Desktop: Token als Pipe vor den Befehlskopf  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/provisioning/command.ts, apps/desktop/ui/src/lib/provisioning/command.test.ts, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0415b1d75 2026-11-19T17:25:42+01:00
Review: approve (.ah-out/review/kern-provision-2/T3.verdict.json)
Änderung: Wertetyp `tokenStdin` (nur Automationsmodus, nur bei gültigem Token): Flag ohne Wert anhängen, gequoteten Token per Shell-Pipe vor den Kopf setzen; Tests für PowerShell und sh, kein Token im argv-Teil.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/provisioning/command.test.ts src/components/infra/provisioning/ProvisioningDialog.test.ts
Abhängt von: T1
Doku: → T6

### T4 — R-1613/R-1628: Fortschritt: URL-Quoting, widerrufene Linie, kein Request ohne Key; Migrations-Docstring  [x]
Komponente: server · Dateien: apps/server/app/modules/provisioning/progress.py, apps/server/tests/test_provisioning_progress.py, apps/server/alembic/versions/6a4e9feea1c5_server_os_type_platform.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8dcafe2d6 2026-11-19T19:18:10+01:00
Review: approve (.ah-out/review/kern-provision-2/T4.verdict.json)
Änderung: `quote(server_id, safe='')` in der Monitoring-URL; `_certificate` nur aus nicht widerrufenen Linien; Test ohne Monitoring-Key prüft per `httpx_mock`, dass kein Request rausgeht; `downgrade()` begründet das bewusste Nichtstun im Docstring.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning_progress.py
Doku: keine (internes Verhalten)

### T5 — R-1614/R-1628: Dialog: Ersatztext für unbekannte Katalogwerte, Tab-Label und Fortschrittstest  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.svelte, apps/desktop/ui/src/components/infra/provisioning/ProvisioningDialog.test.ts, apps/desktop/ui/src/components/infra/provisioning/ProvisioningProgress.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @6a9a8d368 2026-11-19T17:37:53+01:00
Review: approve (.ah-out/review/kern-provision-2/T5.verdict.json)
Änderung: Unbekannter `reason`/`port.purpose` zeigt einen Ersatztext (DE+EN) statt des rohen Schlüssels; der Dialogtest findet die Aktions-Tabs per `getByRole('tablist', { name })`; Fortschrittstest „früherer Token, dann falsche Antwort“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/provisioning src/lib/i18n
Doku: keine (Ersatztext für Fehlerfall)

### T6 — R-1612: Doku und Changelog  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-provision-2.md, docs/developer/cicd.html, docs/en/developer/cicd.html, docs/features/kern-provision-2.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @2cb5542a1 2026-11-19T19:30:56+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Windows-Abschnitt: der Automationsbefehl des Desktops gibt den Token über stdin; Changelog-Eintrag (neutral für T1).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

### T7 — R-1628: oasdiff-Fall für die R-1594-Ausnahmen (Harness, Kevin 2026-11-19)  [x]
Komponente: scripts · Dateien: scripts/tests/openapi_breaking_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @30f90769c 2026-11-19T19:21:38+01:00
Review: approve (.ah-out/review/kern-provision-2/T7.verdict.json)
Änderung: Ein Fall gegen das echte oasdiff mit Fixture-Specs für den Plattform-Enum: mit Ausnahmedatei grün, ein weiterer Enum-Wert an anderem Feld bleibt ERR.
Verify: bash scripts/dev/verify.sh scripts --strict -- openapi_breaking_test
Doku: keine (Testfall)

### T8 — R-1612: oasdiff-Ausnahme für den Wertetyp `tokenStdin` (Harness, Kevin 2026-11-19)  [x]
Komponente: scripts · Dateien: scripts/dev/oasdiff-err-ignore.txt, scripts/tests/openapi_breaking_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @785f6b178 2026-11-19T19:28:45+01:00
Review: approve (.ah-out/review/kern-provision-2/T8.verdict.json)
Änderung: Eine Ausnahmezeile für den einen ERR aus T2 (`response-property-enum-value-added`, GET /api/provisioning/platforms, Wert `tokenStdin`); ein Fall gegen das echte oasdiff: mit der Datei grün, ein weiterer Wert an derselben Stelle bleibt ERR.
Verify: bash scripts/dev/verify.sh scripts --strict -- openapi_breaking_test
Doku: → T6 (cicd.html nennt die Ausnahmen)
Abhängt von: T2

## Entscheidungen
- R-1612 Variante A (Wertetyp `tokenStdin`, Pipe): Token nie im argv; ein älterer Desktop baut den Windows-Automationsbefehl dann nicht (dokumentiertes Verhalten für Unbekanntes).
- R-1612 oasdiff: `tokenStdin` ist ein neuer Antwort-Enum-Wert (1 ERR); Kevin 2026-11-19: eine Ausnahmezeile als eigene Task (T8).

### T9 — R-1612, R-1628: API-Referenz nachziehen (Abschlussprüfung)  [x]
Komponente: scripts · Dateien: docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/features/kern-provision-2.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @29e17e94e 2026-11-19T19:45:58+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Katalog: Wertname `tokenStdin` und was ein Client mit unbekanntem Wertnamen tut; Fortschritt: `certificate` nur aus einer nicht widerrufenen Linie (DE+EN). Spec-Zeile zu R-1614 an den Code angeglichen (Katalogwert in Klammern).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/api-reference.html, docs/en/developer/api-reference.html
Task-Review: am Ende
