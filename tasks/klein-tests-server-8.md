<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-8 — Task-Ledger
Status: geplant · Branch: feature/klein-tests-server-8 · Review: am Ende
Spec: docs/features/klein-tests-server-8.md (Roadmap R-1416, R-1417)
Heavy: none — nur pytest
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1416: Fake-sleep zählt nur im Thread des Tests  [ ]
Komponente: server · Dateien: apps/server/tests/test_ip_filter.py
Beweis: PR #506 CI 2026-11-12 · run 43299645291 job 131467178553 @91264bbe0 · Dedup-Key: BUG:server:tests/test_ip_filter.py:test_an_unexpected_error_drops_the_last_addresses
Semantik: keine Stelle in docs/ — Testhygiene; der Test selbst benennt das Soll (fail-closed nach unerwartetem Fehler)
Änderung: Die zwei Tests, die `mw.time.sleep` patchen, ersetzen es durch ein Fake, das nur im Thread des Tests wirkt und in jedem anderen das echte `sleep` ruft (kleiner Helfer in der Datei). Gegenprobe: alter Test mit einem Fremd-Thread, der `time.sleep` hämmert, ist rot, neu grün; Dauerlauf 50/50.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ip_filter.py
Doku: keine (Tests)

### T2 — R-1417: Untergrenze des Grace-Tests lastfest  [ ]
Komponente: server · Dateien: apps/server/tests/test_hook_isolation.py
Beweis: main CI 2026-11-12 · run 43305871179 job 131489014122 @b0d3babff · Dedup-Key: BUG:server:tests/test_hook_isolation.py:test_hook_reader_grace_is_one_deadline_for_both_streams
Semantik: keine Stelle in docs/ — der Test benennt das Soll (eine gemeinsame Frist für beide Ströme)
Änderung: Untergrenze von `0.8 * grace` auf `0.5 * grace`, Obergrenze `1.6 * grace` bleibt; Kommentar nennt das Warum (Differenz zweier Minima streut unter Last). Dauerlauf 50/50.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_isolation.py -k reader_grace
Doku: keine (Tests)
