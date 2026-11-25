# Verworfene Events sichtbar machen — Task-Ledger
Status: aktiv · Branch: feature/kern-events-2 · Review: am Ende
Spec: docs/features/kern-events-2.md (Roadmap R-1732)
Heavy: none — nur der Event-Bus im Server-Prozess, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Verworfene Events: Sammelzeile und Glocke je Ansturm (R-1732)  [ ]
Komponente: server · Dateien: apps/server/app/core/events.py, apps/server/tests/test_events_after_commit.py
Änderung: `fire_event` zählt verworfene Events je Fenster (60 s ab dem ersten) und loggt nur das erste; ein Timer
schreibt danach eine Sammelzeile mit Anzahl und Typen und eine Glocken-Notiz an alle Admins (höchstens eine je
15 min, `server.events.dropped`); `shutdown_events` schreibt eine offene Sammelzeile sofort.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_events_after_commit.py
Doku: → T2

### T2 — Doku: Warteschlange, Logger, Changelog (R-1732)  [ ]
Komponente: scripts · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-events-2.md
Änderung: Absatz zur Warteschlange und Logger-Liste beschreiben Sammelzeile und Glocken-Notiz; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Dateien dieser Task
Task-Review: am Ende
Abhängt von: T1

## Entscheidungen
