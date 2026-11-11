<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-4 — Task-Ledger
Status: geplant · Branch: feature/klein-tests-desktop-4 · Review: am Ende
Spec: docs/features/klein-tests-desktop-4.md (Roadmap R-1212)
Heavy: none — nur Vitest
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1212: Erst-Render der SettingsModal-Tests in ein beforeAll aufwärmen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.identity.test.ts, apps/desktop/ui/src/components/SettingsModal.save.test.ts
Beweis: kern-ansible-1 T4 task-close 2026-11-09 verify-20261109-125746 rot (2 Timeouts), bei 81b5aa48c grün · Dedup-Key: bug:desktop-ui:SettingsModal.test:timeout-under-load · HEAD: feature/kern-ansible-1@084065873
Änderung: Je Datei ein `beforeAll`, das den Dialog einmal rendert und mit `cleanup()` abräumt, damit der kalte Erst-Render nicht im 5-s-Budget des ersten Tests liegt. Vorher/nachher unter derselben künstlichen Last (24 Rechenschleifen, `timeout`-begrenzt) messen: Dauer des ersten Tests je Datei ins Ledger. Zeigt die Messung keinen Effekt: zurücknehmen, `advisor` fragen, kein größeres Timeout.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/SettingsModal.identity.test.ts src/components/SettingsModal.save.test.ts
Doku: keine (Tests)
