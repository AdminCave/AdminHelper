<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Regression desktop_e2e_monitoring (2026-11-13) — Task-Ledger
Status: geplant · Branch: feature/reg-2026-11-13-desktop-e2e-monitoring · Review: am Ende
Spec: Roadmap R-1420 · Quelle: Wochenlauf 2026-11-13-0130 (Klasse fail) und `--step` über main@680bb5ceb
Heavy: linux-full — der Schritt ist im Wochenlauf rot; der Fix beweist sich auf einer Box (`/test`: `bash scripts/tests/run.sh all --strict --step desktop_e2e_monitoring`)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### R1 — Agent-Container im Monitoring-E2E sieht Docker (R-1420)  [ ]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_monitoring.sh
Änderung: Ursache: seit c2a677e12 (R-1324) gilt ein laufender `dockerd` ohne antwortenden Standard-Socket als „Docker da, nicht lesbar“, und der Wächter weist jede TCP-Probe auf eine eigene Adresse ab. Der Agent-Container des Tests sieht mit `--pid host` den `dockerd` des Hosts, hat aber weder Socket noch `docker`-CLI; der Scan findet den Gateway-Port nicht mehr. Der Container bekommt `/var/run/docker.sock` und die `docker`-CLI des Hosts (nur lesend), wie ein Agent auf einem Docker-Host sie hat; das Verhalten des Wächters bleibt.
Beweis: main@680bb5ceb · `bash scripts/tests/run.sh all --strict --step desktop_e2e_monitoring` auf der Box → `FAIL no finding tcp-<port> after the scan` und `monitoring-server-page GUI spec failed`; Repro auf der Box: `probe.RecognizePort` im Container wie im Test → `target not allowed: the published ports of the containers cannot be read: docker ps: exec: "docker": executable file not found`, mit Socket und CLI eingehängt → `banner`
Semantik: docs/developer/agent.html:164 „Läuft ein `dockerd`, ohne dass der Standard-Socket antwortet (`dockerSocketServes`, `dockerdRuns`), gilt Docker als da und nicht lesbar: jede TCP-Probe auf eine eigene Adresse wird abgewiesen (fail-closed).“
Dedup-Key: reg:scripts:desktop_e2e_monitoring.sh:agent-container-docker
HEAD: 680bb5ceb278d53e817248e6bbda005ab4435c39
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: keine (Test-Harness; das Verhalten des Wächters steht schon in docs/developer/agent.html)

## Beweis (heavy.sh, 2026-11-13-0130)
- Schritt `desktop_e2e_monitoring` 3x rot, Klasse `fail` („differing markers“): der Marker trägt den zufälligen E2E-Port (`tcp-NNNNN`), der Fehler ist derselbe (R-1421)
- zuletzt grün auf baa979053 (2026-11-11), wackelnd auf 185870ddf, rot ab b0d3babff; dazwischen #489 mit c2a677e12

## Entscheidungen
- Kevin 2026-11-13: Testfix annehmen (Socket und CLI in den Agent-Container), den Wächter nicht lockern.
