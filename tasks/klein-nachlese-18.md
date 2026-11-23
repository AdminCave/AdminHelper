<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-18 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-18 · Review: pro Task
Spec: docs/features/klein-nachlese-18.md (Roadmap R-1673, R-1674, R-1675, R-1669, R-1676, R-1677, R-1685)
Heavy: none — Tests, ein Desktop-UI-Anzeigefehler, Doku und Changelog-Fragmente, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1673: Katalogtests für leeren DHCP-Server und nie aktualisierte Defender-Signatur  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_catalog_windows_server.py, apps/monitoring/tests/test_catalog_windows_roles.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @15a8ea494 2026-11-23T10:49:20+01:00
Review: approve (.ah-out/review/klein-nachlese-18/T1.verdict.json)
Beweis: reviewer kern-agent-15 branch 2026-11-20, test_catalog_windows_server.py:155. Dedup-Key: REF:nachlese:kern-agent-15
Änderung: Zeile `("windows-dhcp", "scopes", {"scopes": 0}, "unknown")` in der Regeltabelle und ein Defender-Fall mit `signature_age_d: 65535` (sonst gesund) → `critical`; beide müssen ohne die Agent-Änderung fallen können (Gegenprobe).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_windows_server.py tests/test_catalog_windows_roles.py
Doku: keine (nur Tests)

### T2 — R-1674: RPM-Scriptlets ohne systemd: Ausgabe prüfen  [x]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/packaging_rpm_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @cbd22b20f 2026-11-23T10:51:25+01:00
Review: approve (.ah-out/review/klein-nachlese-18/T2.verdict.json)
Beweis: reviewer kern-agent-16 branch 2026-11-20, packaging_rpm_test.go:342. Dedup-Key: REF:nachlese:kern-agent-16
Änderung: `TestRPMScriptletsPassWithoutSystemd` prüft zusätzlich, dass die Ausgabe der Scriptlets die Stub-Meldung ("System has not been booted") nicht enthält, also `daemon-reload` still scheitert; Gegenprobe mit dem Spec ohne `2>/dev/null`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./cmd/adminhelper-agent -run RPM
Doku: keine (nur Test)

### T3 — R-1675: Server-Kachel zeigt „-“, wenn die Serverliste nicht lädt  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Dashboard.svelte, apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/pages/Dashboard.load.test.ts
Beweis: reviewer kern-dashboard-1 branch 2026-11-20, Dashboard.svelte:109, monitoring.ts:237. Dedup-Key: REF:nachlese:kern-dashboard-1
Änderung: Rot zuerst: Test „loadServers scheitert, Checks laden" → Kachel `-`. Dann ein Signal im Store, das `loadServers` bei Erfolg setzt und bei Fehler löscht; die Kachel zeigt die Zahl nur, wenn es gesetzt ist. Alt-Verhalten sonst unverändert.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Dashboard.load.test.ts
Doku: keine (der Wortlaut von changelog.d/kern-dashboard-1.md deckt das ab)

### T4 — R-1676, R-1669: Changelog-Fragmente deutsch und umlautfrei  [ ]
Komponente: scripts · Dateien: changelog.d/kern-agent-17.md, changelog.d/kern-dashboard-1.md, changelog.d/kern-monitoring-53.md, changelog.d/README.md
Beweis: reviewer kern-agent-17 branch 2026-11-20 (changelog.d/kern-agent-17.md:2); reviewer klein-nachlese-17 2026-11-20 (kern-monitoring-53.md:12). Dedup-Key: ref:nachlese:klein-nachlese-17
Änderung: (zusätzlich von Hand: `python3 scripts/release/changelog-assemble.py --check`) die beiden englischen Fragmente als `- **Bereich: Titel:** Text`, deutsch, ae/oe/ue, mit dem Inhalt von heute; in `kern-monitoring-53.md:12` „desselben Checks“ statt „desselben Objekts“; `README.md` nennt Deutsch und fetten Titel ausdrücklich.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: changelog.d/README.md

### T5 — R-1669, R-1677, R-1685: Doku-Nachträge (Satzbau, Self-Update, waitUntil)  [ ]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/features/ci-19.md, docs/features/kern-desktop-e2e-2.md
Beweis: reviewer klein-nachlese-17 (monitoring.html:296, ci-19.md:33), reviewer branch windows-self-update 2026-11-20, reviewer kern-desktop-e2e-2 branch 2026-11-23 (Spec:30). Dedup-Key: ref:nachlese:klein-nachlese-17
Änderung: `monitoring.html` DE+EN: die zwei Klammern hinter `history.server_events` zu einem Satz; `ci-19.md:33` auf höchstens 120 Zeichen umbrechen; `agent.html` DE+EN: `internal/selfupdate`, `self-update-apply <version>` (main.go:68) und die Gesund-Marke (`selfupdate.MarkHealthy`, `run_windows.go`) in Verzeichnisbaum und Windows-Abschnitt, nach dem Code belegt; `kern-desktop-e2e-2.md`: `waitUntil` wiederholt eine werfende Bedingung bis zum Timeout und trägt dessen Text (nach wdio-Quelltext belegt).
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/monitoring.html DE+EN, docs/developer/agent.html DE+EN, zwei Specs
