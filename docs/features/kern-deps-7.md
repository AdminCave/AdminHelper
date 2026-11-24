<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Ungenutzte Python-Abhängigkeiten entfernen (kern-deps-7)

Roadmap: R-0701 (Code-Audit 2026-10-21, X-12), am 2026-11-24 gegen `main` neu geprüft.

## Problem

- `apps/server/requirements.in` führt `python-multipart`, obwohl keine Route `Form`, `File` oder `UploadFile`
  nimmt (grep über `apps/server/app`). Es landet im Image und zieht eine Apache-NOTICE-Pflicht in
  `THIRD_PARTY_LICENSES.md` nach sich.
- `sqlalchemy[asyncio]` in Server und Monitoring: keine Async-Engine, keine `AsyncSession`
  (`sqlalchemy.ext.asyncio` kommt nirgends vor). Das Extra zieht nur `greenlet` in beide Images.
- `pytest-asyncio` in `apps/server/requirements-dev.txt`: kein `async def test_`, kein `asyncio_mode`.
- Test-Deps ohne Untergrenze: `pytest` und `httpx` im CA-Issuer, `pytest-cov` im Monitoring.
- Die Lock-Drift aus dem Audit (fastapi im CA-Issuer) ist seit kern-deps-2 erledigt, alle drei Locks
  stehen auf `fastapi==0.162.0`.

## Ziel und Nicht-Ziele

Ziel: die drei ungenutzten Pakete fallen aus `.in`/Dev-Datei und Lock, die Test-Deps tragen eine Untergrenze wie
der Server. Nicht-Ziel: andere Pins anheben (`pip-compile` ohne `--upgrade` hält die übrigen Pins),
Lockverfahren ändern.

## Betroffene Dateien

`apps/server/requirements.in`, `apps/server/requirements.txt`, `apps/server/requirements-dev.txt`,
`apps/monitoring/requirements.in`, `apps/monitoring/requirements.txt`, `apps/monitoring/requirements-dev.txt`,
`apps/ca-issuer/requirements-dev.txt`, `THIRD_PARTY_LICENSES.md`, `changelog.d/kern-deps-7.md`.

## Datenmodell / API / Migrationen

Keine. Die OpenAPI bleibt gleich (Snapshot-Test).

## Trade-offs

Ein künftiger Upload-Endpunkt bräuchte `python-multipart` wieder; FastAPI meldet das beim Import mit einer klaren
Fehlermeldung, das Paket kommt dann mit der Route zurück (YAGNI).

## Risiken und Rollback

Nutzt doch etwas greenlet (etwa ein Async-Pfad in einer Bibliothek), fiele es erst zur Laufzeit auf: die Tasks
deinstallieren die Pakete im Worktree-Venv und fahren die Tests ohne sie; die PR-CI baut die Images aus dem neuen
Lock (`python-lock-*`, Stack-Job), der Sammellauf fährt den Stack. Rollback: Revert des Merge-Commits.

## Doku-Impact

`THIRD_PARTY_LICENSES.md` (Tabellenzeilen `python-multipart` und `greenlet`, NOTICE-Liste), Changelog-Fragment.
Sonst keine Seite nennt die Pakete.

## Offene Fragen

Keine.
