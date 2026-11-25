# Verworfene Events sichtbar machen — Task-Ledger
Status: aktiv · Branch: feature/kern-events-2 · Review: am Ende
Spec: docs/features/kern-events-2.md (Roadmap R-1732)
Heavy: none — nur der Event-Bus im Server-Prozess, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Verworfene Events: Sammelzeile und Glocke je Ansturm (R-1732)  [x]
Komponente: server · Dateien: apps/server/app/core/events.py, apps/server/tests/test_events_after_commit.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @16b30878a 2026-11-25T04:38:07+01:00
Review: am Ende (Branch-Review)
Änderung: `fire_event` zählt verworfene Events je Fenster (60 s ab dem ersten) und loggt nur das erste; ein Timer
schreibt danach eine Sammelzeile mit Anzahl und Typen und eine Glocken-Notiz an alle Admins (höchstens eine je
15 min, `server.events.dropped`); `shutdown_events` schreibt eine offene Sammelzeile sofort.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_events_after_commit.py
Doku: → T2

### T2 — Doku: Warteschlange, Logger, Changelog (R-1732)  [x]
Komponente: scripts · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-events-2.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @496f772af 2026-11-25T04:49:42+01:00
Review: am Ende (Branch-Review)
Änderung: Absatz zur Warteschlange und Logger-Liste beschreiben Sammelzeile und Glocken-Notiz; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Dateien dieser Task
Task-Review: am Ende
Abhängt von: T1

### T3 — Fund der Abschlussprüfung: Timer-Test wartet mindestens 30 s  [ ]
Komponente: server · Dateien: apps/server/tests/test_events_after_commit.py
Änderung: `test_the_burst_is_summed_up_after_the_window` wartet mit `timer.join(timeout=30)` statt 5 s (testing.md, Fristen); `join` kehrt mit dem Timer zurück.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_events_after_commit.py
Doku: keine (nur Test)

## Entscheidungen
