# Agent-RPM: Scriptlets ohne systemd ohne Fehlermeldung — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-16 · Review: am Ende
Spec: Roadmap R-0576
Heavy: none — nur die Scriptlets der rpm-Spec; packaging_rpm_test.go fährt sie mit /bin/sh gegen einen systemctl-Stub, kein Bau- oder Install-Skript geändert
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0576: daemon-reload in %post und %postun geschützt  [ ]
Komponente: agent · Dateien: apps/agent/rpm/adminhelper-agent.spec, apps/agent/cmd/adminhelper-agent/packaging_rpm_test.go, changelog.d/kern-agent-16.md
Änderung: Die drei `systemctl daemon-reload` in `%post` und `%postun` bekommen `>/dev/null 2>&1 || true` wie die übrigen systemctl-Aufrufe der Spec; ohne systemd als PID 1 (Container) endet `%post` sonst mit Exit 1 und rpm/dnf meldet „scriptlet failed“. Neuer Test: der systemctl-Stub scheitert wie ohne systemd, Installation, Upgrade und Entfernen laufen trotzdem mit Exit 0 durch (erst rot).
Beweis: reviewer agent-followups T1, 2026-10-21 · feature/agent-followups@732a441f (rpm-Probe rockylinux:9/8); apps/agent/rpm/adminhelper-agent.spec %post endet mit ungeschütztem `systemctl daemon-reload`
HEAD: 70b4f3719
Dedup-Key: bug:agent:rpm-spec:post-daemon-reload-unguarded
Semantik: keine Stelle in docs/ — gesucht in docs/admin/agent-deployment.html (DE+EN) nach Container, systemd, Scriptlet; die Spec schützt jeden anderen systemctl-Aufruf mit `|| true`, ein scheiternder Scriptlet ist kein gewolltes Verhalten
Verify: bash scripts/dev/verify.sh agent --strict -- ./cmd/adminhelper-agent/
Doku: changelog.d/kern-agent-16.md (Doku-Seiten beschreiben die Scriptlets nicht)
