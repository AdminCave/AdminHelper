<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-17 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-17 · Review: am Ende
Spec: docs/features/klein-nachlese-17.md (Roadmap R-1643, R-1649, R-1662, R-1664)
Heavy: none — Kommentar, Doku, Changelog-Fragmente und ein Test, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1643: WWN-Text eingrenzen (Kommentar, Doku, Changelog)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/smart.go, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-agent-11.md
Beweis: reviewer branch kern-agent-11 2026-11-19. Dedup-Key: REF:agent:apps/agent/internal/monitor/smart.go:smartWWN
Änderung: Kommentar an `smartWWN`, `agent.html` (DE+EN) und das Fragment sagen nicht mehr "in der Form von lsblk", sondern: wie `smartctl` sie liefert, ähnlich `lsblk -o WWN`; bei NVMe mit NGUID kann `lsblk` eine andere Kennung zeigen (nicht verifiziert, welche der Kernel wählt). Kein Codeverhalten.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/agent.html DE+EN, changelog.d/kern-agent-11.md

### T2 — R-1662, R-1664: Monitoring-Doku, Fragmente, Testhygiene  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_check_engine_concurrency.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-53.md, changelog.d/ops-13.md
Beweis: reviewer kern-monitoring-53 2026-11-20, reviewer ops-13 2026-11-20. Dedup-Key: ref:nachlese:kern-monitoring-53, ref:nachlese:ops-13
Änderung: `monitoring.html` DE+EN: `history.server_events` faltet `alert_log`-Zeilen desselben Checks mit gleichem Wechsel innerhalb von 60 s (nicht desselben Objekts); beide Fragmente ohne Umlaute; im Test `first` in `try/finally` schließen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine_concurrency.py
Doku: docs/developer/monitoring.html DE+EN, changelog.d/kern-monitoring-53.md, changelog.d/ops-13.md

### T3 — R-1649: ci-19-Spec: Suche als ganzes Wort  [ ]
Komponente: scripts · Dateien: docs/features/ci-19.md
Beweis: reviewer ci-19 2026-11-19, docs/features/ci-19.md:33. Dedup-Key: nit:ci-19:spec-tradeoff
Änderung: Trade-off-Absatz: die Kontext-Namen werden als ganzes Wort gesucht (nicht nur vor `.` oder `[`), Literale vorher entfernt.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: keine (die Task ändert die Spec selbst)
