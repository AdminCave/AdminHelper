<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Tag-Sync-Test: Notify-Pool an jeder Testgrenze leer (R-0112) — Task-Ledger
Status: geplant · Branch: feature/tag-sync-test-drain · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: Roadmap R-0112
Heavy: none — nur Testcode unter `apps/server/tests/`; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format sauber, keine Doku, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-29 von der Aufsicht (adminhelper-ac) auf Kevins Wort („Probleme lösen oder Vorschläge machen“).
Befund: `apps/server/app/modules/servers/router.py:37` hält einen prozessweiten Single-Worker-Pool `_NOTIFY_POOL`;
jede Server-Anlage, -Änderung und -Löschung legt dort einen Notify ab (`:48`), der bis zu 30 s (`timeout=30`) auf
`monitoring:8080` wartet. Tests anderer Dateien leeren den Pool nie. `test_create_notifies`
(`tests/test_tag_sync_notify.py:54`) setzt den Spy (`:55`) und zählt danach auch die liegengebliebenen Aufträge
früherer Tests — in CI `assert 5 == 1`, daneben DNS-Fehler der alten Aufträge. `_drain_notify()` (`:35–40`) ist
die Barriere, die der Test schon kennt; sie läuft nur zu spät.

### T1 — Beweis-Paar und autouse-Fixture: der Notify-Pool ist an jeder Testgrenze leer  [ ]
Komponente: server · Dateien: apps/server/tests/test_tag_sync_notify.py, apps/server/tests/conftest.py
Änderung: Ans Ende von `test_tag_sync_notify.py` (heute 149 Zeilen) ein DB-freies Beweis-Paar in dieser Reihenfolge:
`test_leftover_notify_left_behind` patcht `servers_router.httpx.post` auf eine Antwort mit `status_code = 200`,
legt `servers_router._NOTIFY_POOL.submit(time.sleep, 1.0)` und danach `_notify_monitoring_tag_sync("leftover")` ab
und kehrt zurück, ohne zu warten; `test_leftover_notify_never_reaches_the_next_spy` setzt `_spy_notify`, ruft
`_drain_notify()` und erwartet `calls == []` (Meldung nennt die gefundenen URLs). In `conftest.py` nach
`_fresh_rate_limit_backend` (`:60–69`) eine autouse-Fixture `_idle_tag_sync_notify_pool`, die vor und nach jedem
Test eine No-op-Barriere in den Pool gibt — nur wenn `app.modules.servers.router` schon in `sys.modules` steht,
damit die Fixture kein Modul importiert (`import sys` oben ergänzen). `_drain_notify()` und seine Aufrufe bleiben.
Beweis: main@718e0901 plus nur das Beweis-Paar · `bash scripts/dev/verify.sh server --strict -- tests/test_tag_sync_notify.py -k leftover` →
dreimal identisch rot „leftover notifies of earlier tests reached the spy: ['http://monitoring:8080/templates/tag-sync']“
(1 failed, 1 passed); mit der Fixture 7 passed (Gegenprobe der Aufsicht, 2026-09-29, zweimal).
Metrik: Wanduhr der vollen Server-Suite vor und nach T1 (Summary-Zeile von `verify.sh server --strict`) in die
Evidenz; die Barriere wartet auf echte Notifies anderer Tests. Mehr als 10 % langsamer → `[?]` statt `[x]`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_tag_sync_notify.py
Doku: keine (intern)
Dedup-Key: bug:server:test_tag_sync_notify.py:spy-before-drain · HEAD: 718e0901
Semantik: keine Stelle in docs/ — gesucht nach Test-Isolation und Reihenfolge in docs/developer/; die Absicht steht
im Test selbst (`tests/test_tag_sync_notify.py:36–37`: „a no-op barrier guarantees every queued notify has
completed“) und in `.claude/rules/testing.md:36` („Ein erst roter, dann grüner Test ist `flaky`, kein PASS.“).
