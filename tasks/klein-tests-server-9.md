<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-9 — Task-Ledger
Status: geplant · Branch: feature/klein-tests-server-9 · Review: am Ende
Spec: docs/features/klein-tests-server-9.md (Roadmap R-1626)
Heavy: none — nur pytest
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1626: fd-Test zählt nur fds auf den Testpfad  [ ]
Komponente: server · Dateien: apps/server/tests/test_frp_status.py, apps/server/tests/test_frp_supervisor_status.py
Beweis: main-CI Lauf 44472169896 (Merge #569, 2026-11-19), py3.15 shard 2/2 · Dedup-Key: BUG:server:tests/test_frp_status.py:test_reading_a_list_that_is_no_regular_file_leaves_no_fd_open
Semantik: keine Stelle in docs/ — Testhygiene; der Test benennt das Soll (kein fd bleibt offen)
Änderung: Statt `len(os.listdir("/proc/self/fd"))` zählt ein kleiner Helfer die fds, deren `os.readlink` auf den Testpfad zeigt; vorher/nachher gleich. Dasselbe im Nachbartest `test_frp_supervisor_status.py`. Gegenprobe: ein im Test geleakter fd auf den Pfad macht ihn rot; Dauerlauf 50/50.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_status.py tests/test_frp_supervisor_status.py -k no_regular_file_leaves_no_fd_open
Doku: keine (Tests)
