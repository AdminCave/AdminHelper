# Agent-Installation: apt-CA lesbar für apt, smartmontools nur auf Blech — Task-Ledger
Status: aktiv · Branch: feature/ops-8 · Review: pro Task
Spec: docs/features/ops-8.md (Roadmap R-0810, R-1541)
Heavy: scenario --agents 1 — `scripts/agent-install.sh` und `box_agentbox.sh` im Diff: der Installer-Pfad über die :8445-Repo-Ebene samt CA-Flip und echtem `apt-get update` läuft nur auf einer Agent-Box (Kevin 2026-11-18: Bedingung für den Selbst-Merge).
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0810: Agent zieht die öffentliche apt-CA-Kopie beim Speichern der Identität nach  [x]
Komponente: agent · Dateien: apps/agent/internal/enroll/enroll.go, apps/agent/internal/enroll/enroll_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ce66334ec 2026-11-18T16:26:19+01:00
Review: approve (.ah-out/review/ops-8/T1.verdict.json)
Änderung: Nach dem Commit in `Store` schreibt der Agent `ca.crt` atomar als 0644-Kopie nach `/etc/apt/adminhelper-ca.crt`, nur unter Linux und nur, wenn die Kopie schon existiert (der Installer legt sie an); ein Fehler wird gewarnt und kostet die Erneuerung nicht. Pfad als Variable, im Test umgebogen.
Beweis: main@db7eeb363 scripts/agent-install.sh:388 pinnt `/etc/adminhelper/identity/ca.crt` unter 0700 (postinst:9); Repro der Zeile (debian:13-slim 0700 rc=100, 0644-Kopie rc=0). Dedup-Key: bug:agent:scripts/agent-install.sh:CAInfo
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T3

### T2 — R-1541: smartmontools nur noch Suggests in deb und rpm  [x]
Komponente: agent · Dateien: apps/agent/deb/DEBIAN/control, apps/agent/rpm/adminhelper-agent.spec, apps/agent/cmd/adminhelper-agent/packaging_test.go, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @de1dc9fe8 2026-11-18T16:32:23+01:00
Review: approve (.ah-out/review/ops-8/T2.verdict.json)
Änderung: `Recommends: smartmontools` wird `Suggests: smartmontools` in control und spec; `packaging_test.go` verlangt genau eine Suggests-Zeile und weder Recommends noch eine harte Abhängigkeit (gewollte Verhaltensänderung, Ersatz gleichwertig). Satz in monitoring.html DE+EN nachziehen.
Beweis: Kevin 2026-11-17 Agent-Rollout; main@db7eeb363 control:6, spec:18. Dedup-Key: BUG:agent:packaging:smartmontools-recommends-virt
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html

### T3 — R-0810, R-1541: Installer legt die CA-Kopie an, smartmontools nur auf Blech, Capstone fährt apt-get update  [ ]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh, scripts/tests/box_agentbox.sh, scripts/tests/multibox.sh, scripts/tests/multibox_test.sh, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/ops-8.md
Änderung: Der CA-Flip (apt) kopiert `ca.crt` als 0644 nach `/etc/apt/adminhelper-ca.crt` (`AH_REPO_CA` im Test) und pinnt `CAInfo` darauf; nach dem Paket installiert der Installer `smartmontools` nur, wenn `systemd-detect-virt` `none` meldet (apt und dnf). Die Agent-Box fährt nach dem Flip `apt-get update` mit Marker `AGENT_APT_UPDATE_OK`, `multibox.sh` verlangt ihn. Tests: Kopie 0644 und CAInfo-Pfad, smartmontools bei `none` ja und bei `kvm`/`lxc` nein. Doku: manuelle Variante A auf die Kopie, Absatz Bestandshosts (Kopie, Konf, smartmontools entfernen), Changelog. Acht Dateien, eine Komponente: Installer, sein Test und der Beweis auf der Box gehören zusammen.
Beweis: wie T1; scripts/tests/box_agentbox.sh:159 greppt nur `CAInfo`.
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test multibox_test doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/ops-8.md
Abhängt von: T1

## Entscheidungen
- 2026-11-18: Ort der Kopie `/etc/apt/adminhelper-ca.crt` (Repro der Zeile), nicht Kevins Workaround-Pfad unter `/usr/local` (gehört dem Admin); Begründung in der Spec.
- 2026-11-18: „SMART-Check auf virtuellen Hosts nicht vorschlagen“ (R-1541) fährt nicht mit: Vorlage `linux-base` gehört zur Monitoring-Neuordnung; eigene Zeile.
- 2026-11-18 T1: `refreshRepoCA` läuft nur unter Linux (`repoCAOS`, im Test setzbar): unter Windows läge der Pfad auf dem Systemlaufwerk, wo jeder Nutzer ihn anlegen kann, und der Agent schreibt als SYSTEM (Fund der Task-Prüfung, korrigiert vor dem Commit). `TestMain` biegt `RepoCACopy` für das ganze Paket um.
