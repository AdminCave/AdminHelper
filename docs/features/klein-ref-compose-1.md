<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-compose-1 — pg-backup im Compose gehaertet (Roadmap R-0819)

## Problem
Der auskommentierte Dienst `pg-backup` in `docker-compose.yml` (Block ab „Optionaler Postgres-Backup-Container“)
traegt weder `security_opt: no-new-privileges` noch `pids_limit` noch `mem_limit`, die jeder aktive Dienst hat
(`apps/server/tests/test_compose_hardening.py` verlangt alle drei fuer jeden Dienst). Wer ihn nach der Anleitung
einkommentiert, bekommt einen Dienst ohne diese Haertung; der Test sieht den Block nicht, weil `yaml.safe_load`
Kommentare verwirft.

## Ziel & Nicht-Ziele
- Der Block erhaelt dieselben drei Haertungen wie die aktiven Dienste, mit Begruendung im Stil der Nachbarn.
- Ein Test liest den auskommentierten Block, hebt die Kommentierung auf und verlangt dieselben Invarianten.
- Nicht-Ziel: den Dienst aktivieren, `scripts/pg-backup.sh` aendern, weitere Dienste.

## Betroffene Dateien
`docker-compose.yml` (nur der Kommentarblock), `apps/server/tests/test_compose_hardening.py`.

## Datenmodell / API / Externes
Keine. `security_opt`, `pids_limit`, `mem_limit` sind Compose-Service-Schluessel, wie bei den Nachbardiensten.

## Trade-offs
Alternative: nur Kommentarzeilen ohne Test — verworfen, der Block verwittert dann wieder unbemerkt.
Werte: `pids_limit: 128` und `mem_limit: 256m` wie `db-init` (ein kurzer Prozess); der Dienst fuehrt `sh`, `pg_dump`
und `find` nacheinander aus (`scripts/pg-backup.sh`).

## Risiken & Rollback
Aendert nur Kommentare und einen Test; im Betrieb wirkt nichts, solange der Block auskommentiert ist. Revert.

## Doku-Impact
Keine. `docs/admin/betrieb.html:100` und `docs/en/admin/operations.html:67` sagen nur „den `pg-backup`-Service einkommentieren“ und nennen keine Schluessel.

## Offene Fragen
Keine. Die Werte sind eine Implementierungsentscheidung (Ledger `## Entscheidungen`).
