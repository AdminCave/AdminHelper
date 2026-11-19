<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-15 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-15 · Review: pro Task
Spec: docs/features/klein-nachlese-15.md (Roadmap R-1608, R-1620, R-1621, R-1623, R-1624, R-1627, R-1632, R-1635, R-1652)
Heavy: none — Doku, Mockup-UI, Monitoring-Unit-Tests, Agent-Unit-Tests, Ledger-Köpfe
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1608/R-1627: ADR 0004 und Feature-Spec nachziehen  [ ]
Komponente: scripts · Dateien: docs/adr/0004-monitoring-neuordnung.md, docs/features/arch-monitoring-neu-p0.md
Beweis: reviewer branch arch-monitoring-neu-p0 2026-11-18 (ADR :172 Fallzahl, Spec :138 Build-Test) und arch-monitoring-neu-p0-abnahme 2026-11-19 (ADR 3.1: Lagekarte kappt erst ab 40 Servern auf 20)
Semantik: keine Stelle in docs/ — die Texte selbst sind der Fund
Änderung: ADR: „118 Fälle“ aufschlüsseln (101 Szenarien, 4 benannte Abweichungen, der Rest wie die Tests zählen); Abschnitt 3.1: Lagekarte kappt erst ab 40 Servern auf 20. Spec: statt Build-Test über `dist/` den gebauten `isolation.test.ts` nennen. Zahlen vorher gegen die Tests zählen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst
Task-Review: am Ende

### T2 — R-1608/R-1627: Mockup monitoring-neu (Grund-Satz, Auswahlmarke, Lagekarte, Filter)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/exceptions.ts, apps/desktop/ui/src/mockups/monitoring-neu/views/ServerNav.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/Lagekarte.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/AllServers.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/sorting.test.ts
Beweis: reviewer branch arch-monitoring-neu-p0 2026-11-18 (exceptions.ts withoutRule) und arch-monitoring-neu-p0-abnahme 2026-11-19 (ServerNav :70, Lagekarte :74/:76, AllServers :257)
Semantik: keine Stelle in docs/ — Mockup (Spec docs/features/arch-monitoring-neu-p0-abnahme.md)
Änderung: (1) `withoutRule`: der Grund-Satz nennt nie die ausgenommene Regel, wenn eine andere der Stufe feuert. (2) Auswahlmarke der Serverliste folgt einer neuen Reihenfolge (Effekt hängt an `order`/der Liste). (3) Lagekarte zählt mit `needsLook` statt eigener Bedingung. (4) „Filter aufheben“ setzt `more` zurück. Je Punkt erst ein roter Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/mockups/monitoring-neu
Doku: keine (Mockup, nicht ausgeliefert)

### T3 — R-1632: i18n-Schlüssel monitoring.services.journal.notLinux umbenennen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte
Beweis: reviewer kern-monitoring-50 2026-11-19, dictionaries.ts:1276
Semantik: keine Stelle in docs/ — interner Schlüsselname
Änderung: Schlüssel DE+EN und Verwendung auf einen Namen ohne „Linux“ (`monitoring.services.journal.unsupported`); der Text nennt auch OPNsense, falls `ServiceList.svelte` die Plattform dafür kennt, sonst Text unverändert. Ein vorhandener Test (i18n-Gleichlauf) deckt den Schlüssel.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/i18n
Doku: keine (interner Schlüssel)

### T4 — R-1620: monitoring.html „Was der Hub nicht annimmt“ (DE+EN)  [ ]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html
Beweis: branch-review kern-monitoring-47 2026-11-18 · Dedup-Key: ref:monitoring:checks.py:nachlese-km47
Semantik: docs/developer/monitoring.html: „Was die Glocke verwirft, holt der Nachhol-Job nach“ — gemeint ist, was der Hub nicht annimmt
Änderung: DE „Was der Hub nicht annimmt, holt der Nachhol-Job nach“, EN „What the hub does not accept, the catch-up job sends“. Der Hub-POST in `toggle_check`/`delete_check` bleibt synchron (Entscheidungen).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst
Task-Review: am Ende

### T5 — R-1621: module_sync bindet eine Zeile einer anderen Instanz nicht neu  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_module_sync.py
Beweis: branch-review kern-monitoring-46 2026-11-19 · Dedup-Key: ref:monitoring:module_sync.py:belongs-update
Semantik: apps/monitoring/app/module_sync.py:471 `_belongs`: „a check that names one instance (R-1528) at that one only“
Änderung: Eine bestehende Zeile, deren Katalog-Check eine andere Instanz nennt (`not _belongs`), wird weder von `_adopt` (`_update`, Aktivieren) noch vom Katalog-Sync (`updatable_checks`) angefasst: sie bleibt wie sie ist, ohne Grund. Erst ein roter Test: Check bekommt `instance` nach dem Anlegen, Adopt an anderer Instanz ändert die Zeile nicht.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: changelog.d/klein-nachlese-15.md

### T6 — R-1623/R-1652: Monitoring-Tests und Docstrings  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_bell_catch_up.py, apps/monitoring/tests/test_check_engine_concurrency.py, apps/monitoring/app/checkers/plugins.py
Beweis: reviewer-Nits kern-monitoring-49 2026-11-19 und arch-monitoring-neu-p1 Branch 2026-11-19 (plugins.py:528/:100, test_check_engine_concurrency.py:220/306/403)
Semantik: keine Stelle in docs/ — Tests und Kommentare; .claude/rules/testing.md „Fristen“: ≥ 30 s
Änderung: Test: `sync_assignment` ruft `send_all_clears` (alle Entwarnungen), gone-Test prüft, dass `catch_up_bell` ok sendet. Docstrings `_container_object`/`_guest_object` verweisen auf die ausstehende Übernahme in den Schlüssel (P1e) statt „fehlende Agent-Daten“. `barrier.wait(timeout=10)` → 30.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_bell_catch_up.py tests/test_check_engine_concurrency.py
Doku: keine (Tests, Kommentare)

### T7 — R-1624: Agent busybox: Changelog, programName, Test-Skip  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/target.go, apps/agent/internal/probe/sensor_local_linux_test.go, changelog.d/kern-agent-10.md
Beweis: kern-agent-10 Abschlussprüfung 2026-11-19 (Nits aus der Roadmap-Zeile)
Semantik: keine Stelle in docs/ — Changelog-Text, Lesepfad und Testvoraussetzung
Änderung: Fragment nennt, dass ein Prozess-Ziel busybox/toybox jetzt `count 0` meldet; `programName` liest den Multicall-Namen einmal; der busybox-Linux-Test sagt im Skip-Text, dass der CI-Runner busybox hat oder nicht (Befund aus der CI-Ausgabe, sonst „nicht verifiziert“). Verhalten bleibt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe
Doku: changelog.d/kern-agent-10.md (der Eintrag selbst)

### T8 — R-1635: drei Ledger-Köpfe auf erledigt  [ ]
Komponente: scripts · Dateien: tasks/desktop-blocking.md, tasks/host-uid-guard.md, tasks/kern-server-7.md
Beweis: Statuspruefung 2026-11-19 · origin/main@aab20ed34 · Dedup-Key: REF:tasks:ledger-status:stale-bereit
Semantik: tasks/README.md: ein gemergtes Ledger steht auf `erledigt`
Änderung: `Status:` der drei Ledger auf `erledigt` (die Zeile heißt „abgeschlossen“, das Ledger-Format kennt `erledigt`); Ursache des fehlenden Abschluss-Commits in `## Entscheidungen` festhalten.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: keine (Ledger)
Task-Review: am Ende

## Entscheidungen
- 2026-11-19 R-1620: Der Hub-POST in `toggle_check`/`delete_check` bleibt synchron. Ihn in den Hintergrund zu legen braucht eine eigene Sitzung für `release_hub_slot`/`refresh`, ändert die Antwort des Endpunkts und ist mehr als eine Nachlese; der Teil wird eine eigene Zeile.
