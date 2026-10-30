<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-2 — Task-Ledger
Status: aktiv · Branch: feature/klein-doku-2 · Review: am Ende
Spec: docs/features/klein-doku-2.md (Roadmap R-0944, R-0882)
Heavy: none — reine Doku, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — agent-deployment: Vergleichswert und SAN-Aussage (R-0944, R-0882)  [ ]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md
Änderung: Der `--insecure`-Absatz nennt als Vergleichswert den SHA-256 des Server-Zertifikats (nicht den CA-Fingerprint), den man auf dem Server oder über einen zweiten Weg ermittelt. Die Aussage zu IP-Adressen nennt auch `DOMAIN` und `127.0.0.1`. Derselbe Satz im Eintrag `[Unreleased]` des CHANGELOG folgt.
Beweis: R-0944 provision.go (Fingerprint-Ausgabe); R-0882 Code-Lesung
Dedup-Key: bug:docs:agent-deployment.html:insecure-fp
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md
Task-Review: am Ende

### T2 — agent.html: Collector-Signaturen mit ctx (R-0882)  [ ]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html
Änderung: Die Collector-Liste und die Plattform-Tabelle nennen `ctx` bei `collectServiceHealth`, `collectWatchedServices`, `collectDocker`, `collectZFS`, `collectProxmox`, `collectSmart` und `collectSystemState`.
Beweis: Code-Lesung apps/agent/internal/monitor/*.go
Dedup-Key: ref:agent:service:darwin-vet-docs
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/agent.html, docs/en/developer/agent.html
Task-Review: am Ende
