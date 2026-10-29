<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI wieder grün: pytest unter 9.2 halten, bis pytest-alembic 9.2 verträgt — Task-Ledger
Status: erledigt · Branch: feature/ci-pytest-pin · Review: am Ende
Spec: Roadmap R-0916
Heavy: none — nur Test-Abhängigkeiten in `requirements-dev.txt`; kein Stack-, Gateway-, PKI-, Compose- oder Install-Pfad, das Image installiert sie nicht.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kurz-Ledger aus der Roadmap-Zeile (Kevin hat R-0916 am 2026-10-28 angenommen). pytest 9.2.0 (2026-10-27) und
pytest-alembic 0.13.1 (neueste Version) vertragen sich nicht; die CI installiert die losen `requirements-dev.txt` und
bricht beim Sammeln ab, ohne Codeänderung.

### T1 — pytest in Server und Monitoring unter 9.2 pinnen  [x]
Komponente: monitoring · Dateien: apps/monitoring/requirements-dev.txt, apps/server/requirements-dev.txt
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @40aefa8f 2026-10-28T14:42:30+01:00
Review: am Ende (Branch-Review)
Änderung: `pytest` → `pytest<9.2` (Monitoring) und `pytest>=9.0.3` → `pytest>=9.0.3,<9.2` (Server), je mit einem Kommentar zum Grund und zur Bedingung für die Rücknahme (pytest-alembic verträgt pytest 9.2). CA-Issuer nutzt pytest-alembic nicht und bleibt.
Beweis: origin/main@a1165595 · frisches Venv unter `~/.cache` mit `pip install -r apps/monitoring/requirements-dev.txt` (löst pytest 9.2.0, pytest-alembic 0.13.1), in `apps/monitoring`: `python -m pytest --collect-only -q -m "not schemathesis"` → Exit 2, `AttributeError: 'TestCollector' object has no attribute '_nodeid'`, dreimal identisch; CI-Lauf 40690492187 (Jobs Server- und Monitoring-pytest, Schema-Fuzzing) mit derselben Meldung
Dedup-Key: rel:ci-pytest-alembic
HEAD: a1165595
Semantik: docs/developer/cicd.html:40 — „Lint &amp; Tests aller Komponenten: Server-<code>pytest</code> (Postgres-Service, Python&nbsp;3.12/3.13 …)“: die CI soll die Tests fahren, nicht beim Sammeln abbrechen
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alembic_builtin.py
Doku: keine (Test-Abhängigkeit ohne dokumentiertes Verhalten)

## Entscheidungen
- 2026-10-28 T1: obere Grenze statt fester Version — pytest-Patches unter 9.2 bleiben möglich; zurücknehmen, sobald pytest-alembic eine mit pytest 9.2 verträgliche Version veröffentlicht.
