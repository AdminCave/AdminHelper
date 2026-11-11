<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-4 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-desktop-4 · Review: am Ende
Spec: docs/features/klein-tests-desktop-4.md (Roadmap R-1212)
Heavy: none — nur Vitest
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1212: Erst-Render der SettingsModal-Tests in ein beforeAll aufwärmen  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.identity.test.ts, apps/desktop/ui/src/components/SettingsModal.save.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e80a7544d 2026-11-11T07:09:46+01:00
Review: am Ende (Branch-Review)
Beweis: kern-ansible-1 T4 task-close 2026-11-09 verify-20261109-125746 rot (2 Timeouts), bei 81b5aa48c grün · Dedup-Key: bug:desktop-ui:SettingsModal.test:timeout-under-load · HEAD: feature/kern-ansible-1@084065873
Änderung: Je Datei ein `beforeAll`, das den Dialog einmal rendert und mit `cleanup()` abräumt, damit der kalte Erst-Render nicht im 5-s-Budget des ersten Tests liegt. Vorher/nachher unter derselben künstlichen Last (24 Rechenschleifen, `timeout`-begrenzt) messen: Dauer des ersten Tests je Datei ins Ledger. Zeigt die Messung keinen Effekt: zurücknehmen, `advisor` fragen, kein größeres Timeout.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/SettingsModal.identity.test.ts src/components/SettingsModal.save.test.ts
Doku: keine (Tests)

## Entscheidungen
- Ursache (2026-11-11, gemessen unter 24 Rechenschleifen auf 8 Kernen): kalter Erst-Render des Dialogs und die erste Rollen-Abfrage auf dem grossen DOM. Vorher -> nachher: Identity-Erst-Test 2194 -> 881 ms, Save-Erst-Test 1570 -> 344 ms, langsamster Test 2982 -> 2136 ms; ungestoert schwerer Terminal-Test 658 -> 425 ms. Der Rest ist reine CPU-Ueberbuchung (3x), kein Einzelposten; kein Timeout angehoben. hidden:true bei getByRole brachte nichts (verworfen).
