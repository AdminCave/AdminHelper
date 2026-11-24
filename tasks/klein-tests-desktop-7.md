<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-7 — strictSelectors der Desktop-E2E — Task-Ledger
Status: erledigt · Branch: feature/klein-tests-desktop-7 · Review: am Ende
Spec: docs/features/klein-tests-desktop-7.md (Roadmap R-1135)
Heavy: linux-full — Desktop-Journeys; der GUI-Lauf auf frischer Box gehört zur Task (Kevin 2026-11-24), der Sammellauf prüft danach
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@c6065ef05`.

### T1 — strictSelectors einschalten, mehrdeutige Selektoren eingrenzen (R-1135)  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/wdio.conf.js, apps/desktop/e2e/test/lib/live.js, apps/desktop/e2e/test/specs/monitoring-alerts.live.js, apps/desktop/e2e/test/specs/monitoring-check.live.js, apps/desktop/e2e/test/specs/monitoring-server-page.live.js, apps/desktop/e2e/test/specs/monitoring-services.live.js, apps/desktop/e2e/test/specs/rdp-connect.live.js, apps/desktop/e2e/test/specs/rdp-embedded.live.js, apps/desktop/e2e/test/specs/settings-enroll.live.js, apps/desktop/e2e/test/specs/ssh-connect.live.js, apps/desktop/e2e/test/specs/tunnel-connect.live.js, apps/desktop/e2e/test/specs/two-installations.workspaces.js, apps/desktop/e2e/test/specs/web-connect.live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @379e81938 2026-11-24T19:50:37+01:00
Review: am Ende (Branch-Review)
Änderung: `strictSelectors: true` setzen und den Kommentar dazu streichen. Den GUI-Lauf (`desktop_e2e_*.sh`) auf einer
frischen Desktop-Box fahren, jeden Selektor eingrenzen, an dem wdio „multiple elements" meldet, bis alle Läufe grün
sind; die geänderten Specs oder Lib-Dateien mit `ledger.sh set-files` nachtragen. Der grüne Box-Lauf (Summary-Zeile je
Skript) steht im Commit-Body.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (interne Test-Konfiguration)
