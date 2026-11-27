<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-28 — Agent: Zugangsdaten unter Windows trotz kurz gesperrter Datei lesen — Task-Ledger
Status: bereit · Branch: feature/kern-agent-28 · Review: am Ende
Spec: docs/features/kern-agent-28.md (Roadmap R-1823)
Heavy: windows — Windows-only-Code, verifiziert im CI-Job agent-windows (go test ./...)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen

### T1 — R-1823: readPrivate wiederholt das Öffnen bei vorübergehender Sperre  [x]
Komponente: agent · Dateien: apps/agent/internal/credentials/store_windows.go, apps/agent/internal/credentials/store_windows_test.go, changelog.d/kern-agent-28.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @2f4eb6952 2026-11-27T15:51:39+01:00
Review: am Ende (Branch-Review)
Beweis: ci.yml Lauf 45893033754 Attempt 1, Job 'Go Agent (test, Windows)', store_test.go:234 `open …credentials.json: Access is denied.`
Dedup-Key: bug:flaky-agent-credentials-set-concurrent-windows (Roadmap-Key flaky:agent-credentials-set-concurrent-windows)
HEAD: cc125c52a
Änderung: `openForRead` in `readPrivate` wird bei `ERROR_ACCESS_DENIED`/`ERROR_SHARING_VIOLATION` bis `replaceWait` wiederholt (Pause wie `replace`). Tests: Halter ohne Freigabe lässt nach 200 ms los → `Load` liest; zum Löschen anstehende Datei → nach dem Schließen keine Zugangsdaten statt Fehler.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/credentials/
Doku: changelog.d/kern-agent-28.md

### T2 — R-1823: Tests ohne kurze feste Frist, Frist-Ablauf geprüft  [x]
Komponente: agent · Dateien: apps/agent/internal/credentials/store_windows.go, apps/agent/internal/credentials/store_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ddf44cd46 2026-11-27T16:49:19+01:00
Review: am Ende (Branch-Review)
Änderung: Beide Halter-Tests setzen `replaceWait` auf 30 s (Cleanup setzt zurück) statt auf die Produktfrist von 2 s zu bauen. Der Test ohne Lese-Freigabe prüft vorher, dass `openForRead` `ERROR_SHARING_VIOLATION` liefert. Ein neuer Test zeigt, dass `Load` mit `replaceWait = 0` an einem gehaltenen File scheitert. Der Kommentar von `openForRead` kommt zurück an seine Funktion.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/credentials/
Doku: keine (nur Tests und ein Kommentar)
