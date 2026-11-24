<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-21 — Nachlese kern-server-14 und kern-agent-22 — Task-Ledger
Status: bereit · Branch: feature/klein-nachlese-21 · Review: am Ende
Spec: docs/features/klein-nachlese-21.md (Roadmap R-1762, R-1770)
Heavy: none — ein Test, ein Refactor im Agent-Linux-Pfad, ein Changelog-Fragment
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@f97e05f20`.

### T1 — Server-Test: Scope-Session vor dem Forward geöffnet und geschlossen (R-1762)  [x]
Komponente: server · Dateien: apps/server/tests/test_monitoring_proxy_plan.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @184711f2c 2026-11-24T20:25:52+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer kern-server-14 2026-11-24, test_monitoring_proxy_plan.py:305 (`open_at_forward == [0]` unterscheidet nichts)
Dedup-Key: ref:server:test_monitoring_proxy_plan.py:open_at_forward
Änderung: Der Handler merkt `(len(opened), len(closed))`; die Assertion ist `[(1, 1)]` statt `[0]`. Gegenprobe: die Scope-Prüfung hinter den Forward legen, der Test wird rot; Ergebnis in den Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_proxy_plan.py
Doku: keine (Test)

### T2 — Agent: Netlink-Aufbau teilen, Changelog-Fragment in Form (R-1770)  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/peer_linux.go, changelog.d/kern-agent-22.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @273454db5 2026-11-24T20:31:15+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer kern-agent-22 2026-11-24, peer_linux.go:191 und changelog.d/kern-agent-22.md:6-7
Dedup-Key: ref:agent:kern-agent-22:nachlese
Änderung: `osPeerSocket` und `diagDump` rufen zwei Helfer für Socket mit Timeout und für Header plus Sendto; Verhalten und Fehlertexte bleiben. Das Fragment: fettes Etikett je Eintrag, Zeilen höchstens 120 Zeichen, die Container-Ausnahme der ARC-Schonung im ersten Eintrag. `python3 scripts/release/changelog-assemble.py --check` grün.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: changelog.d/kern-agent-22.md
