<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Proben-Wächter: Prüfung nach dem Verbindungsaufbau auch unter FreeBSD — Task-Ledger
Status: bereit · Branch: feature/kern-freebsd-3 · Review: pro Task
Spec: docs/features/kern-freebsd-3.md (Roadmap R-1402)
Heavy: linux-full — Agent (Proben-Wächter); dazu vor dem Merge die root-Tests von internal/probe auf der FreeBSD-Pool-Box (T1, von Hand oder über T2)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1402: osPeerSocket unter FreeBSD über getcred  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/peer_freebsd.go, apps/agent/internal/probe/peer_freebsd_test.go, apps/agent/internal/probe/peer_other.go, apps/agent/internal/probe/peer_getcred.go, apps/agent/internal/probe/peer_getcred_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @d5b49c580 2026-11-12T20:36:23+01:00
Review: approve (.ah-out/review/kern-freebsd-3/T1.verdict.json)
Änderung: Neue `peer_freebsd.go` (SPDX) fragt `net.inet.tcp.getcred` bzw. `net.inet6.tcp6.getcred` mit (Ziel,
Quelle) über `SYS___SYSCTLBYNAME`: gefunden → `peerConnected`, `ENOENT` → `peerNone`, sonst Fehler; `peer_other.go`
auf `!linux && !freebsd`. Tests (SPDX): Kodierung der Adresspaare (v4, v6, v4-mapped) plattformunabhängig wo
möglich; als root auf FreeBSD der echte Taker und eine fremde Quelle (`peerNone`), mit `AH_FREEBSD_PF=1` dazu eine
Umleitung im Paketfilter, die der Wächter abweist.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T3

### T2 — Box-Lauf: root-Tests von internal/probe in Phase roottests  [?] (Harness-Pfad scripts/tests/box_freebsdbox.sh: root-Tests von internal/probe aufnehmen? Empfehlung ja)
Komponente: scripts · Dateien: scripts/tests/box_freebsdbox.sh
Änderung: `ROOT_TESTS`/`roottests` nehmen die root-Tests aus T1 auf (mit `AH_FREEBSD_PF=1`), der Box-Benutzer lässt
sie aus; Harness-Pfad nur auf Kevins Wort.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskript)

### T3 — Doku und Changelog  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-freebsd-3.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @87e1c57ac 2026-11-12T20:46:21+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Admin-Doku: die Prüfung nach dem Verbindungsaufbau gilt unter Linux und FreeBSD; Entwickler-Doku:
`checkTaker` nennt `peer_freebsd.go` (getcred); Changelog-Fragment neutral.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-freebsd-3.md
Task-Review: am Ende

## Entscheidungen
