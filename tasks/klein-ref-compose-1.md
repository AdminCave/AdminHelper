<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-compose-1 — Task-Ledger
Status: aktiv · Branch: feature/klein-ref-compose-1 · Review: am Ende
Spec: docs/features/klein-ref-compose-1.md (Roadmap R-0819)
Heavy: linux-full — Compose-Datei (nur ein Kommentarblock, im Betrieb ohne Wirkung)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — pg-backup-Block härten und per Test absichern (R-0819)  [ ]
Komponente: server · Dateien: docker-compose.yml, apps/server/tests/test_compose_hardening.py
Beweis: R-0819 docker-compose.yml (Block `# pg-backup:`) ohne `security_opt`, `pids_limit`, `mem_limit`; `test_compose_hardening.py` liest ihn nicht (`yaml.safe_load` verwirft Kommentare)
Dedup-Key: idee:compose:docker-compose.yml:pg-backup-hardening
Änderung: Der auskommentierte Block erhält `security_opt: [no-new-privileges:true]`, `pids_limit: 128` und `mem_limit: 256m` mit Begründungskommentar wie die Nachbardienste. Ein neuer Test hebt die Kommentierung des Blocks auf (Präfix `  # ` → `  `), lädt ihn per `yaml.safe_load` und verlangt dieselben drei Invarianten wie für die aktiven Dienste. Gegenprobe: `pids_limit` aus dem Block entfernen → rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_hardening.py
Doku: keine (die Betriebsdoku nennt keine Schluessel des Blocks)

## Entscheidungen
- `pids_limit: 128`, `mem_limit: 256m` wie `db-init` (ein kurzer Prozess: `sh`, dann `pg_dump`, dann `find`, `scripts/pg-backup.sh`); die Zeile nennt nur security_opt und pids_limit, `mem_limit` kommt dazu, weil `test_every_service_has_a_memory_limit_of_at_least_128m` es fuer jeden Dienst verlangt.
