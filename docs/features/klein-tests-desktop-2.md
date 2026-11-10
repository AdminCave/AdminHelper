<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-2 — Spec

## Problem
- **R-1168:** `AppShell.svelte` verdrahtet `keepOpenSessions` (Z. 291: `save: setOpenSessions`,
  `connect: (c) => initiateConnect(c, false, 'embedded')`, `stopKeeping()` beim Zerstören, Z. 339) und das Abdocken
  (`onDetach` → `detachTerminal`, Z. 481). Das Abdocken prüft `AppShell.sessions.test.ts` schon; die Restore-Seite
  nicht: der Test mockt den Connections-Store mit leerer Liste, `keepOpenSessions` läuft dort nie an. Die Logik selbst
  ist in `terminals.test.ts` getestet, nicht aber, dass die Shell sie richtig anschließt. Die Ansible-Unterzeile
  („<Playbook> --check“) prüft `SshTerminal.test.ts` (Z. 682); auf Shell-Ebene fehlt, dass ein Playbook-Lauf als Tab mit
  dem Playbook-Namen erscheint und nicht gespeichert wird.

## Ziel / Nicht-Ziele
Die Shell-Tests belegen: gespeicherte SSH-Tabs öffnen einmal als eingebettete Terminals (Reihenfolge, Doppelte, gelöschte
und Nicht-SSH-Verbindungen übersprungen), nichts bei ausgeschalteter Option, Warten auf die Verbindungsliste, Speichern
jeder Tab-Änderung, Ende mit der Shell, Ansible-Tab mit Namen und ohne Speichern. Keine Verhaltensänderung, kein
Produktcode.

## Dateien
`apps/desktop/ui/src/components/AppShell.sessions.test.ts`.

## Datenmodell / API / Integrationen
Keine.

## Trade-offs
Eine bestehende Testdatei erweitern statt einer neuen: Mocks (xterm, Bridge, Stores) stehen dort schon; der
Connections-Store-Mock wird beschreibbar, der Standard bleibt die leere Liste.

## Risiken & Rollback
Gering; nur Tests. Gegenprobe: Verdrahtung in `AppShell.svelte` im Probe-Worktree ändern, der Test wird rot.

## Doku-Impact
Keine (Tests).

## Offene Fragen
Keine. R-1135 (wdio `strictSelectors`) fährt nicht mit: es braucht GUI-Läufe auf einer Desktop-Box, und die warme Box
gehört der Lane `kern-rdp-7`; die Zeile wechselt in `tasks/klein-tests-desktop-3.md`.
