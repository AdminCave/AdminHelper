# klein-nachlese-24 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-24 · Review: pro Task
Spec: docs/features/klein-nachlese-24.md (Roadmap R-1777, R-1778, R-1838)
Heavy: none — Agent-Nits und Doku, kein Stack-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Agent: Platten-Test faellt rot statt zu haengen, Warntext zaehlt nur Netz-Mounts (R-1777)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/disks_test.go, apps/agent/internal/monitor/disks_bounded.go, apps/agent/internal/monitor/disks_freebsd.go, changelog.d/klein-nachlese-24.md
Beweis: reviewer kern-agent-24 2026-11-25 (disks_test.go:127, disks_bounded.go:60, disks_freebsd.go:58)
Änderung: Der Test bricht bei einem Fehlschlag sofort ab (kein Warten bis zum Timeout); ein doppelter Mountpfad in `boundedStats` zaehlt einmal, die FreeBSD-Warnung nennt nur die Netz-Mounts, die nicht antworteten. docs/developer/agent.html:224 nur pruefen (klein-doku-11 hat sie behoben).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/...
Doku: changelog.d/klein-nachlese-24.md

### T2 — Hooks: Kommentar und Glockentext nennen den richtigen Prozess (R-1778)  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_runner.py, docs/features/kern-server-15.md, apps/server/tests/test_hooks.py, changelog.d/klein-nachlese-24.md
Beweis: reviewer kern-server-15 2026-11-25 (script_runner.py:371, :362)
Änderung: Der Lock-Kommentar nennt `server.startup` als Scheduler-Hook; der Glockentext sagt "details in the log" ohne "server"; das Feature-Doc zieht den Satz nach. Ein Test in test_hooks.py haelt den neuen Text fest.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks.py
Doku: docs/features/kern-server-15.md, changelog.d/klein-nachlese-24.md

### T3 — Doku: Status-Check von nextcloud-aio braucht nur dann Port 8000, wenn der Scan Ports sah (R-1838)  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/klein-nachlese-24.md
Beweis: reviewer arch-monitoring-aio-status 2026-11-27 (T5, _lacks_port in module_sync.py)
Änderung: DE + EN: "sieht der Scan Ports am Container, muss 8000 darunter sein; sah er keine, bleibt der Check gebunden".
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html
Task-Review: am Ende

## Entscheidungen
- R-1791 faehrt nicht mit: ueberlappt feature/arch-monitoring-neu-p1c (alert_bundle.py, test_template_sync.py); Zug klein-nachlese-25.
