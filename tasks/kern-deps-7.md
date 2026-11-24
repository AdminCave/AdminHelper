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

### T1 — R-0701: Server ohne python-multipart, greenlet und pytest-asyncio  [ ]
Komponente: server · Dateien: apps/server/requirements.in, apps/server/requirements.txt, apps/server/requirements-dev.txt
Änderung: `python-multipart` aus `requirements.in`, `sqlalchemy[asyncio]` → `sqlalchemy`, `pytest-asyncio` aus
`requirements-dev.txt`; Lock mit dem DEVELOPMENT.md-Rezept (pip-compile in python:3.14-slim, ohne `--upgrade`)
neu erzeugen, nur die drei Pakete fallen heraus. Die Pakete im Worktree-Venv deinstallieren, damit der Lauf ohne
sie belegt ist.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_snapshot.py
Doku: → T4

### T2 — R-0701: Monitoring ohne greenlet, pytest-cov mit Untergrenze  [ ]
Komponente: monitoring · Dateien: apps/monitoring/requirements.in, apps/monitoring/requirements.txt, apps/monitoring/requirements-dev.txt
Änderung: `sqlalchemy[asyncio]` → `sqlalchemy`, Lock neu wie T1 (nur greenlet fällt heraus); `pytest-cov` bekommt
die Untergrenze des Servers. greenlet im Worktree-Venv deinstallieren.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_tag_sync.py
Doku: → T4

### T3 — R-0701: CA-Issuer-Test-Deps mit Untergrenze  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/requirements-dev.txt
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
