<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ci-2 — Task-Ledger
Status: aktiv · Branch: feature/ci-2 · Review: am Ende
Spec: docs/features/ci-2.md (Roadmap R-0950)
Heavy: none — nur Test-Auswahl in conftest und CI-Jobs; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@0c474527`, vor dem Schreiben neu greppen. Messung 2026-10-30: 2564 Tests in 1452 s,
die 60 langsamsten 446 s; CI-Jobs 13–14 min (Lauf 41092318397).

### T1 — pytest-Option `--shard K/N` für die Server-Suite (R-0950)  [ ]
Komponente: server · Dateien: apps/server/tests/conftest.py, apps/server/tests/test_shard.py
Änderung: `pytest_addoption` (`conftest.py:459`) bekommt `--shard K/N`; ein `pytest_collection_modifyitems` teilt die Testdateien (nach Pfad sortiert, je an den Shard mit den wenigsten Tests) und wählt die fremden ab (`pytest_deselected`). Ohne Option keine Änderung. `test_shard.py` (SPDX) prüft: Shards zusammen = alle Tests, disjunkt, deterministisch, eine Datei bleibt ganz, `0/2`, `3/2`, `x` abgewiesen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_shard.py
Doku: → T2

### T2 — CI: Server-pytest-Jobs in zwei Shards mit Sammeljob (R-0950)  [ ]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_shards.py, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: `server` (`ci.yml:31`) läuft als Matrix Python × Shard 1..2 mit `--shard`, Skip-Prüfung je 3.13-Shard; ein Sammeljob je Python trägt die Pflicht-Namen `Server (pytest, py3.12|py3.13)` und ist nur bei Erfolg aller Shards grün. `python-lock-server` (`ci.yml:236`) ebenso in zwei Shards. `test_ci_shards.py` (SPDX) prüft, dass Matrix und `--shard` zueinander passen und die Sammeljobs die Pflicht-Namen tragen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_shards.py tests/test_shard.py
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (Server-Jobs in Shards, Sammeljob, Skip-Prüfung je Shard)
Abhängt von: T1

## Entscheidungen
