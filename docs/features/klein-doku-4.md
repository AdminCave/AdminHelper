<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-4 — Monitoring lokal: DATA_DIR in DEVELOPMENT.md (Roadmap R-0946)

## Problem
`DEVELOPMENT.md` (Abschnitt „Monitoring (lokal ohne Docker)“) startet `uvicorn app.main:app` ohne `DATA_DIR`.
`apps/monitoring/app/core/config.py:12-13` setzt den Default `/app/data` und legt das Verzeichnis beim Import an;
der Import bricht als Nicht-Root mit `PermissionError: [Errno 13] Permission denied: '/app'` ab (so auf der
Dev-Box nachgestellt: `env -u DATA_DIR python3 -c "import app.core.config"`). `DATA_DIR` hält zudem die
automatisch erzeugte `.api_key` (`config.py:38`), wenn `MONITOR_API_KEY` fehlt.

## Ziel & Nicht-Ziele
- Das Startbeispiel setzt ein beschreibbares `DATA_DIR`; ein Satz nennt, was dort liegt (die `.api_key`).
- Nicht-Ziel: den Default im Code ändern (Compose und Dockerfile setzen `/app/data` bewusst), andere Abschnitte.

## Betroffene Dateien
`DEVELOPMENT.md` (Abschnitt „Monitoring (lokal ohne Docker)“).

## Datenmodell / API / Externes
Keine.

## Trade-offs
Alternative: Code-Default auf ein Nutzerverzeichnis ändern — verworfen, ändert Container-Verhalten (BUG ist die Doku).

## Risiken & Rollback
Reine Doku; Revert des Commits.

## Doku-Impact
`DEVELOPMENT.md` (eine Sprache; die Entwickler-Seiten `docs/developer/monitoring.html` nennen `$DATA_DIR/.api_key` schon).

## Offene Fragen
Keine. Semantik: `docs/developer/monitoring.html:200` — „in `$DATA_DIR/.api_key` persistiert“.
