<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-4 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-4 · Review: pro Task
Spec: docs/features/klein-nachlese-4.md (Roadmap R-1414)
Heavy: linux-full — Desktop-E2E-Helfer (T4), Lauf im Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1414: Docstring von server_cleanup.py umbrechen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/server_cleanup.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @bfec41a0d 2026-11-13T11:08:19+01:00
Review: approve (.ah-out/review/klein-nachlese-4/T1.verdict.json)
Beweis: reviewer arch-monitoring-ui-3 T4 2026-11-12 · Dedup-Key: REF:desktop:ServiceList.svelte:nachlese-arch-monitoring-ui-3
Änderung: Die Docstring-Zeile mit der Tabellenaufzaehlung bricht wie der Rest bei etwa 84 Zeichen um. Kein Verhalten aendert sich.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_tables.py
Doku: keine (interner Kommentar)

### T2 — R-1414: waitFor-Fristen gelten (testTimeout je Datei)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/ServiceList.test.ts, apps/desktop/ui/src/components/ConnectionEditor.tabs.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @911d1b013 2026-11-13T11:13:09+01:00
Review: approve (.ah-out/review/klein-nachlese-4/T2.verdict.json)
Beweis: reviewer arch-monitoring-ui-3 T7 2026-11-12 (waitFor 30 s, testTimeout 5 s)
Änderung: Beide Dateien setzen `vi.setConfig({ testTimeout: 60_000 })` am Dateianfang mit einem Kommentar zum Warum; die 30-s-Fristen der Waits bleiben (testing.md, Fristen).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/ServiceList.test.ts src/components/ConnectionEditor.tabs.test.ts
Doku: keine (interner Test)

### T3 — R-1414: kein "Mehr Log"-Hinweis bei leerem Inventar  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte, apps/desktop/ui/src/components/monitoring/section/ServiceList.test.ts
Beweis: reviewer arch-monitoring-ui-3 T10 2026-11-12 (ServiceList.svelte:362)
Änderung: Der SSH-Zweig (Hinweis und Verbindungswahl) braucht `rows.length > 0`; erst ein roter Test (leeres Inventar mit SSH-Verbindung zeigt weder Hinweis noch Auswahl), dann der Fix.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/ServiceList.test.ts
Doku: keine (nur ein Hinweis bei leerem Inventar entfaellt)
Abhängt von: T2

### T4 — R-1414: gemeinsame Live-Helfer fuer die Monitoring-E2E-Specs  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/lib/monitoring-live.js, apps/desktop/e2e/test/specs/monitoring-services.live.js, apps/desktop/e2e/test/specs/monitoring-server-page.live.js
Beweis: reviewer arch-monitoring-ui-3 T11 2026-11-12 (monitoring-services.live.js:73,93)
Änderung: `setTheme`, `shot`, `fixtureAgentConf`, `createCheck` und `postReport` ziehen in `test/lib/monitoring-live.js` (SPDX-Header); Praefix, Frist und der optionale `config` sind Parameter, beide Specs behalten ihr Verhalten. Nicht lokal lauffaehig (kein Display): `Heavy: linux-full`, im PR-Text "Heavy: Sammellauf".
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (interne Testhelfer)
