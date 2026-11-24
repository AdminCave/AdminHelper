<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-23 — Nachlese kern-pycommon-2 — Task-Ledger
Status: geplant · Branch: feature/klein-nachlese-23 · Review: am Ende
Spec: docs/features/klein-nachlese-23.md (Roadmap R-1776)
Heavy: none — ein Fixture-Kommentar und ein Test
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@fd8687a0c`.

### T1 — Kopien-Wächter sieht ah_common, Fixture-Kommentar stimmt (R-1776)  [ ]
Komponente: server · Dateien: apps/server/tests/test_no_python_copies.py, apps/server/tests/fixtures/mail_template_parity.json
Beweis: reviewer kern-pycommon-2 2026-11-24 · test_no_python_copies.py:14 `_TREES` ohne ah_common (Gegenprobe grün), mail_template_parity.json:2 `_comment`
Semantik: keine Stelle in docs/ — gesucht: Testwächter und Fixture-Kommentar sind kein dokumentiertes Verhalten
Dedup-Key: ref:server:test_no_python_copies.py:nachlese-kern-pycommon-2
Änderung: `_TREES` nimmt `apps/pycommon/ah_common` auf, die Meldung des Wächters nennt es. Der `_comment` der Fixture nennt den Renderer in `apps/pycommon/ah_common/mail_template.py` und den Test `test_notify_mail_template.py` statt der gelöschten Monitoring-Kopie. Beweis der Wirkung: erst eine Kopie einer `ah_common`-Funktion in `apps/server/app` (Probe-Worktree) → der Wächter wird rot, ohne die Änderung grün.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_no_python_copies.py tests/test_notify_mail_template.py
Doku: keine (Test und Fixture-Kommentar)
