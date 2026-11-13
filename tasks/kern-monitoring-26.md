<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Probe-Guard: weitere Weiterleiter, klarere Abweisung nach dem connect — Task-Ledger
Status: erledigt · Branch: feature/kern-monitoring-26 · Review: pro Task
Spec: docs/features/kern-monitoring-26.md (Roadmap R-1407, R-1409)
Heavy: linux-full — Agent (Proben-Wächter, `apps/agent`); Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1407: weitere Weiterleiter und Super-Server  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @19be0d1a6 2026-11-13T09:43:17+01:00
Review: approve (.ah-out/review/kern-monitoring-26/T1.verdict.json)
Änderung: `forwarders` um die Programme aus der privaten Notiz (Linux/FreeBSD und Windows) erweitern, als Präfix
bzw. in `forwarderNames`, wo ein Präfix fremde Programme träfe; `judgeListener` wertet `xinetd` und `inetd` wie
`systemd` als Aktivator (Listener nur beim Super-Server → abweisen). Tests: `TestGuardNeverProbesAPortAForwarderListensOn`
um die neuen Namen, ein Fall je Super-Server.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T3

### T2 — R-1409: Queue voll und beendete Verbindung nicht als Umleitung merken  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/peer_linux.go, apps/agent/internal/probe/peer_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c266c0825 2026-11-13T09:55:13+01:00
Review: approve (.ah-out/review/kern-monitoring-26/T2.verdict.json)
Änderung: `judgePeer` meldet für einen Listener mit voller Accept-Queue (`rqueue`/`wqueue` aus `inet_diag_msg`) einen
eigenen Zustand; `checkTaker` prüft im letzten Versuch zusätzlich die eigene Client-Socket (Lookup mit vertauschten
Enden). Queue voll oder eigene Socket weg → `ErrNotAllowed` mit eigener Meldung, ohne `rememberRedirect`. Tests:
`TestJudgePeerWantsTheExactEnds` um den vollen Listener, `guard_test.go` je Fall mit gestubbtem `peerSocket`
(kein Merker, Meldung), `TestGuardRemembersARedirectedPort` bleibt grün.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T3
Abhängt von: T1

### T3 — Doku: Wächter-Absatz und Changelog  [x]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-26.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @890b8041a 2026-11-13T09:57:51+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Absatz „Wächter“ DE+EN: Super-Server wie Socket-Aktivierung, die zwei Abweisungsgründe nach dem connect
ohne Merker; Changelog-Fragment neutral (ohne Angriffspfad).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/agent.html DE+EN · changelog.d/kern-monitoring-26.md
Task-Review: am Ende

### T4 — Doku: Admin-Handbuch „Nur dieser Host“  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @850190cdd 2026-11-13T10:09:35+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Absatz „Nur dieser Host“ DE+EN nachziehen (Fund der Abschlussprüfung): die neuen Weiterleiter in der
Liste, Super-Server wie Socket-Aktivierung, die zwei Abweisungen nach dem Verbindungsaufbau ohne Sperre.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html DE+EN
Task-Review: am Ende

## Entscheidungen
- T1: ein nativ laufendes frps zählt als Weiterleiter (security T1, Einzelheiten privat); das frps des AdminHelper-Servers läuft in Docker und ist nicht betroffen. Folgezeilen R-1426, R-1427.
- T2: Restrisiko (keine Merker bei voller Queue und sofort beendeter Verbindung) hingenommen, Kevin 2026-11-13; Einzelheiten privat.
