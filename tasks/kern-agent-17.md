# Agent-DEB: Maintainer-Skripte ohne systemd als PID 1 — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-17 · Review: am Ende
Spec: Roadmap R-1670
Heavy: none — nur postinst/postrm und ein Go-Test, der sie mit systemctl-Stub fährt; wie R-0576 (#627) für das RPM, build-deb.sh unverändert
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1670: daemon-reload in postinst und postrm still, wenn systemd nicht läuft  [ ]
Komponente: agent · Dateien: apps/agent/deb/DEBIAN/postinst, apps/agent/deb/DEBIAN/postrm, apps/agent/cmd/adminhelper-agent/packaging_deb_test.go, changelog.d/kern-agent-17.md
Änderung: Die drei `systemctl daemon-reload` (postinst:3, :19, postrm:3) laufen unter `set -e` als `systemctl daemon-reload >/dev/null 2>&1 || true`, wie die übrigen systemctl-Aufrufe der Skripte und wie die RPM-Spec seit #627. Neuer Test (SPDX-Header) fährt postinst configure, prerm remove und postrm remove/purge mit dem systemctl-Stub aus packaging_rpm_test.go in einer Wurzel ohne systemd: Exit 0 und keine Stub-Meldung in der Ausgabe. Test erst rot.
Beweis: kern-agent-16 Plan 2026-11-20, Code-Lesung; heute apps/agent/deb/DEBIAN/postinst:2-3,19 und postrm:2-3 (`set -e`, ungeschützt)
HEAD: b940b1687
Dedup-Key: bug:agent:deb:daemon-reload-without-systemd
Semantik: keine Stelle in docs/ — gesucht in docs/admin/agent-deployment.html (DEB-Installation); Vorbild: RPM-Spec nach R-0576 und die übrigen systemctl-Aufrufe derselben Skripte (`|| true`)
Verify: bash scripts/dev/verify.sh agent --strict -- ./cmd/adminhelper-agent/
Doku: changelog.d/kern-agent-17.md (die Doku beschreibt die Skripte nicht)
