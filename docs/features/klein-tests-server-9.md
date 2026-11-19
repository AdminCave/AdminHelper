<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-9

## Problem / Motivation
R-1626: `apps/server/tests/test_frp_status.py::test_reading_a_list_that_is_no_regular_file_leaves_no_fd_open` zählt
`/proc/self/fd` prozessweit vorher und nachher (main-CI Lauf 44472169896: 16 statt 15). Ein fremder Thread oder ein
Hintergrund-Fixture öffnet oder schließt dazwischen eigene fds, und der Test fällt, obwohl `read_proxy_list` nichts
leckt. Der Nachbartest `test_frp_supervisor_status.py::test_reading_a_status_that_is_no_regular_file_leaves_no_fd_open`
trägt dieselbe Messung; er wird mitgezogen (gleiches Muster, gleiche Komponente).

## Ziel & Nicht-Ziele
Ziel: gezählt werden nur fds, die auf den Testpfad zeigen (`os.readlink` je Eintrag von `/proc/self/fd`); ein
Leck von `read_proxy_list` bzw. `read_supervisor_status` bleibt sichtbar, fremde fds zählen nicht. Nicht-Ziele:
Produktivcode, Fristen.

## Betroffene Komponenten & Dateien
`apps/server/tests/test_frp_status.py`, `apps/server/tests/test_frp_supervisor_status.py` (nur Tests).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Pfadgefilterte Zählung (Empfehlung, behält die Aussage „kein fd auf diesen Pfad bleibt offen“) oder `gc`/Threads
anhalten (nicht zuverlässig).

## Risiken & Rollback
Nur Testcode; Revert. Gegenprobe: ein künstliches Leck (fd auf den Pfad bleibt offen) macht den Test rot. Dauerlauf
50/50 (`testing.md`).

## Doku-Impact
Keiner (Tests).

## Offene Fragen
Keine.
