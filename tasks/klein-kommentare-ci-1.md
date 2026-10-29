<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-kommentare-ci-1 — Task-Ledger
Status: erledigt · Branch: feature/klein-kommentare-ci-1 · Review: am Ende
Spec: docs/features/klein-kommentare-ci-1.md (Roadmap R-0847, R-0877, R-0927)
Heavy: none — nur Kommentare in einem Workflow, kein Schritt ändert sich
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — ci.yml: drei Kommentare an den Stand (R-0847, R-0877, R-0927)  [x]
Komponente: server · Dateien: .github/workflows/ci.yml
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @6a017845 2026-10-29T21:41:34+01:00
Review: am Ende (Branch-Review)
Änderung: Der Kommentar am Schritt `go vet (windows)` nennt die Gruppen der windows-getaggten Dateien (Dienst, Event-Log, Config-Pfade, Secure-Dir, Enroll-Lock, frpc-Plattform, sc-query-Collector) statt nur des Collectors; der Kommentar am Schritt `No test skipped` hält fest, dass ein `xfail` als `skipped` in der JUnit-XML steht und den Schritt rot macht; der Kommentar am Schritt `Shared API types in lockstep` nennt drei Typen (FrpConfig, FrpStatus, FrpStatusProxy). Nur Kommentare.
Beweis: R-0847 Code-Lesung ci.yml:443-445; R-0877 ci.yml:101-103; R-0927 ci.yml:493-496
Dedup-Key: ref:ci:ci.yml:stale-comments
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: keine (Kommentare in einem Workflow)

## Entscheidungen
- R-0877: der Exit-75-Anteil (Keyring-Prüfung ohne automatischen Test) ist keine Kommentarfrage und fährt nicht mit; ein `xfail`-Gate bleibt eine eigene Zeile, wenn Kevin es will.
