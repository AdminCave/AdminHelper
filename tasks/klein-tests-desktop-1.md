<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-1 — Task-Ledger
Status: erledigt · Branch: feature/klein-tests-desktop-1 · Review: am Ende
Spec: docs/features/klein-tests-desktop-1.md (Roadmap R-0903, R-0886)
Heavy: none — nur Unit-Tests in Desktop-Backend und Desktop-UI, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — launcher-Test nicht mehr zeitknapp (R-0903)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/launcher.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @5f1ee8fe 2026-10-29T17:23:36+01:00
Review: am Ende (Branch-Review)
Änderung: `open_fails_at_once_when_the_workspace_ends_before_it_holds_its_lock` nutzt eine Frist von 10 s statt 900 ms; die Zusicherung `waited < timeout` bleibt und fällt, wenn `open_within` bis zur Frist wartet.
Beweis: main-CI Run 39986960668 · Desktop-Backend (cargo test, Windows): „waited 1.4127168s for the deadline“
Dedup-Key: bug:desktop:launcher.rs:open-fails-at-once-timing-flaky
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- launcher::tests::open_fails_at_once
Doku: keine (nur Tests)

### T2 — settings.test.ts mockt workspaceContext (R-0886)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/settings.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @46c387f7 2026-10-29T17:29:10+01:00
Review: am Ende (Branch-Review)
Änderung: `workspaceContext` im `$lib/bridge`-Mock (Server-Workspace); in den Logout-Tests lässt ein `console.error` den Test fallen (Spy, `afterEach` prüft).
Dedup-Key: ref:desktop-ui:settings.test.ts:bridge-mock-workspacecontext
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/settings.test.ts
Doku: keine (nur Tests)

## Entscheidungen
