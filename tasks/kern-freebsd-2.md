<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FreeBSD-Nacharbeit: Log-Hinweis, Swap-Fehlertext, Rotationsprüfung — Task-Ledger
Status: bereit · Branch: feature/kern-freebsd-2 · Review: am Ende
Spec: docs/features/kern-freebsd-2.md (Roadmap R-1327, R-1330, R-1331)
Heavy: none — Agent nur Konstante und Test, Rest Doku und Box-Skript; dazu vor dem Merge der FreeBSD-Box-Lauf `bash scripts/tests/freebsd_box.sh` auf der Pool-VM (prüft T2)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1330: Swap-Fehlertext von gopsutil als Konstante mit Pin-Test  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @e7bbe1b63 2026-11-12T13:52:18+01:00
Review: am Ende (Branch-Review)
Änderung: `collector.go:215` vergleicht mit einer Konstante; ein Test liest `mem/mem_freebsd.go` aus dem Modulverzeichnis des gepinnten gopsutil (`go list -m`) und verlangt `errors.New("<Konstante>")`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: keine (internes Verhalten unverändert)

### T2 — R-1331: Rotationsprüfung der FreeBSD-Box vergleicht MOUNT und INUM  [x]
Komponente: scripts · Dateien: scripts/tests/box_freebsdbox.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e779822d7 2026-11-12T14:02:23+01:00
Review: am Ende (Branch-Review)
Änderung: `box_freebsdbox.sh:231` zählt nur fstat-Zeilen, deren MOUNT (Spalte 5) der Mountpunkt der Logdatei (`df -P`) und deren INUM (Spalte 6) ihre Inode ist; Harness-Pfad auf Kevins Wort (Notiz R-1331). Beweis ist der FreeBSD-Box-Lauf aus `Heavy:`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskript)

### T3 — R-1327: Hinweis auf frpc-Altzeilen im syslog, Changelog  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-freebsd-2.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @db1bb083e 2026-11-12T14:12:38+01:00
Review: am Ende (Branch-Review)
Änderung: Abschnitt Logs (FreeBSD-Absatz, `agent-deployment.html:340`, EN entsprechend): frühere Builds schrieben frpc-Ausgaben ins syslog (`/var/log/messages`, `/var/log/daemon.log`); diese Zeilen und ihre Archive bleiben bis zur Rotation durch newsyslog, das Paket ändert fremde Systemlogs nicht. Fragment `### Changed`, neutral.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/agent-deployment.html · docs/en/admin/agent-deployment.html · changelog.d/kern-freebsd-2.md
Task-Review: am Ende

## Entscheidungen
