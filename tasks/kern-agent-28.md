<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-28 — Agent: Zugangsdaten unter Windows trotz kurz gesperrter Datei lesen — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-28 · Review: am Ende
Spec: docs/features/kern-agent-28.md (Roadmap R-1823)
Heavy: windows — Windows-only-Code, verifiziert im CI-Job agent-windows (go test ./...)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen

### T1 — R-1823: readPrivate wiederholt das Öffnen bei vorübergehender Sperre  [ ]
Komponente: agent · Dateien: apps/agent/internal/credentials/store_windows.go, apps/agent/internal/credentials/store_windows_test.go, changelog.d/kern-agent-28.md
Beweis: ci.yml Lauf 45893033754 Attempt 1, Job 'Go Agent (test, Windows)', store_test.go:234 `open …credentials.json: Access is denied.`
Dedup-Key: bug:flaky-agent-credentials-set-concurrent-windows (Roadmap-Key flaky:agent-credentials-set-concurrent-windows)
HEAD: cc125c52a
Änderung: `openForRead` in `readPrivate` wird bei `ERROR_ACCESS_DENIED`/`ERROR_SHARING_VIOLATION` bis `replaceWait` wiederholt (Pause wie `replace`). Tests: Halter ohne Freigabe lässt nach 200 ms los → `Load` liest; zum Löschen anstehende Datei → nach dem Schließen keine Zugangsdaten statt Fehler.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/credentials/
Doku: changelog.d/kern-agent-28.md
