<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-7 — Task-Ledger
Status: aktiv · Branch: feature/kern-deps-7 · Review: pro Task
Spec: docs/features/kern-deps-7.md (Roadmap R-0701)
Heavy: linux-full — Laufzeit-Locks von Server und Monitoring ändern das Image; kein PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — R-0701: Server ohne python-multipart, greenlet und pytest-asyncio  [x]
Komponente: server · Dateien: apps/server/requirements.in, apps/server/requirements.txt, apps/server/requirements-dev.txt
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @ff0eefd89 2026-11-24T14:26:32+01:00
Review: approve (.ah-out/review/kern-deps-7/T1.verdict.json)
Änderung: `python-multipart` aus `requirements.in`, `sqlalchemy[asyncio]` → `sqlalchemy`, `pytest-asyncio` aus
`requirements-dev.txt`; Lock mit dem DEVELOPMENT.md-Rezept (pip-compile in python:3.14-slim, ohne `--upgrade`)
neu erzeugen, nur die drei Pakete fallen heraus. Die Pakete im Worktree-Venv deinstallieren, damit der Lauf ohne
sie belegt ist.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_snapshot.py
Doku: → T4

### T2 — R-0701: Monitoring ohne greenlet, pytest-cov mit Untergrenze  [x]
Komponente: monitoring · Dateien: apps/monitoring/requirements.in, apps/monitoring/requirements.txt, apps/monitoring/requirements-dev.txt
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @1522140e1 2026-11-24T14:27:36+01:00
Review: approve (.ah-out/review/kern-deps-7/T2.verdict.json)
Änderung: `sqlalchemy[asyncio]` → `sqlalchemy`, Lock neu wie T1 (nur greenlet fällt heraus); `pytest-cov` bekommt
die Untergrenze des Servers. greenlet im Worktree-Venv deinstallieren.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_tag_sync.py
Doku: → T4

### T3 — R-0701: CA-Issuer-Test-Deps mit Untergrenze  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/requirements-dev.txt
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @645c348ef 2026-11-24T14:28:29+01:00
Review: approve (.ah-out/review/kern-deps-7/T3.verdict.json)
Änderung: `pytest` und `httpx` bekommen die Untergrenzen des Servers (`pytest>=9.2.0`, `httpx>=0.28.1`); der Lock
bleibt (Dev-Deps stehen nicht darin).
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_db_token_store.py
Doku: keine (Dev-Datei, kein dokumentiertes Verhalten)

### T4 — R-0701: Lizenzliste und Changelog  [ ]
Komponente: scripts · Dateien: THIRD_PARTY_LICENSES.md, changelog.d/kern-deps-7.md
Änderung: Zeilen `python-multipart` und `greenlet` aus Tabelle 1, `python-multipart` aus beiden NOTICE-Listen;
Fragment unter `### Changed` (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: THIRD_PARTY_LICENSES.md · changelog.d/kern-deps-7.md
Task-Review: am Ende

## Entscheidungen
- T1: Das Worktree-Venv (`~/.cache/ah-venv-kern-deps-7`) entstand beim ersten Verify frisch aus den neuen Requirements; `python-multipart`, `greenlet` und `pytest-asyncio` fehlen darin (find_spec leer), der Lauf belegt den Stand ohne sie. Lock per pip-compile ohne `--upgrade`: nur die drei Pakete fallen heraus, `sqlalchemy[asyncio]` wird `sqlalchemy`, alle übrigen Pins gleich.
