<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-2 — Task-Ledger
Status: geplant · Branch: feature/klein-tests-desktop-2 · Review: am Ende
Spec: docs/features/klein-tests-desktop-2.md (Roadmap R-1168)
Heavy: none — nur Vitest
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1168: AppShell-Tests für Restore und den Playbook-Tab  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/AppShell.sessions.test.ts
Review: am Ende (Branch-Review)
Beweis: review kern-terminal-1 2026-11-06 · Dedup-Key: REF:desktop-ui:AppShell.svelte:detach_restore_tests
Änderung: Fünf Tests: Restore öffnet die gespeicherten SSH-Tabs einmal mit `initiateConnect(c, false, 'embedded')`; nichts bei ausgeschalteter Option; wartet auf die Verbindungsliste; `setOpenSessions` bekommt die Tab-Ids und verstummt nach dem Unmount; ein Playbook-Lauf ist ein Tab mit Playbook-Namen, `<name> --check` im Kopf, und wird nicht gespeichert. Gegenprobe: `connect`/`save`-Verdrahtung in `AppShell.svelte` im Probe-Worktree ändern, die Tests werden rot.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/AppShell.sessions.test.ts
Doku: keine (Tests)
