<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-21 — Nachlese kern-server-14 und kern-agent-22

Zug `tasks/klein-nachlese-21.md` mit R-1762 und R-1770. `overlap.sh` (2026-11-24): kein offener Branch ändert die
betroffenen Dateien.

## Problem / Motivation
- **R-1762:** `test_no_db_session_is_open_while_the_agent_route_forwards`
  (`apps/server/tests/test_monitoring_proxy_plan.py`) prüft `open_at_forward == [0]`. Die Zahl ist auch 0, wenn die
  Scope-Prüfung gar nicht oder erst nach dem Forward lief; rot würde der Test nur über `len(opened)`.
- **R-1770:** `changelog.d/kern-agent-22.md` hat drei Einträge ohne fettes Etikett (`- **Bereich: Titel:** Text`), Zeilen
  über 120 Zeichen, und die Container-Ausnahme der ARC-Schonung (`loadgate.go`: im Container zählt der ARC nicht
  als verfügbar) fehlt im Eintrag. `diagDump` in `apps/agent/internal/probe/peer_linux.go` wiederholt die
  Netlink-Kette (Socket, Timeout, Header, Sendto) von `osPeerSocket`.

## Ziel & Nicht-Ziele
Der Server-Test hält fest, dass die Scope-Session vor dem Forward geöffnet **und** geschlossen war
(`(opened, closed) == (1, 1)`). `osPeerSocket` und `diagDump` teilen sich den Aufbau von Socket und Anfrage in zwei
kleinen Helfern; Verhalten, Fehlertexte und Leseschleifen bleiben. Das Fragment folgt der Form aus
`changelog.d/README.md` und nennt die Container-Ausnahme. Kein neues Verhalten.

## Betroffene Komponenten & Dateien
server (`apps/server/tests/test_monitoring_proxy_plan.py`), agent (`apps/agent/internal/probe/peer_linux.go`),
`changelog.d/kern-agent-22.md`.

## Datenmodell / API / Migrationen
Keine.

## Trade-offs & Alternativen
Zwei kleine Helfer statt einer Funktion mit Rückgabe der Antwort: die zwei Leseschleifen unterscheiden sich
(eine Antwort mit ENOENT gegen einen Dump bis `NLMSG_DONE`) und bleiben getrennt.

## Risiken & Rollback
Refactor im Agent-Linux-Pfad, abgesichert durch `peer_linux_test.go`; Rückgängig per Revert. Gegenprobe Server:
die Scope-Prüfung nach dem Forward lassen, der Test wird rot.

## Doku-Impact
Nur `changelog.d/kern-agent-22.md`.

## Offene Fragen
Keine.
