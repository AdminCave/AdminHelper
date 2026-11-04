<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Regression backup_restore (crown-jewel DR) (2026-11-03) — Task-Ledger
Status: bereit · Branch: feature/reg-2026-11-03-backup-restore-crown-jewel-DR · Review: am Ende
Spec: Roadmap R-1118 · Quelle: Wochenlauf 2026-11-03-1503
Heavy: linux-full — der Schritt ist im Wochenlauf rot; der Fix beweist sich auf einer Box (`/test`: `bash scripts/tests/run.sh all --strict --step "backup_restore (crown-jewel DR)"`)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### R1 — backup_restore (crown-jewel DR) wieder grün  [x]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b6646c79 2026-11-04T05:19:26+01:00
Review: am Ende (Branch-Review)
Änderung: Ursache: `docker compose config --images <dienst>` nennt auch die Images der Abhängigkeiten (Compose v5.6.1 lokal: `b` mit `depends_on: [a]` gibt zwei Zeilen), in nicht festgelegter Reihenfolge (docker/compose `cmd/compose/config.go`, `runConfigImages` läuft über die Map `project.Services`); `db-init` hängt an `postgres`, also zwei Zeilen, und die Einzeilen-Prüfung von `restore.sh` (seit d7b07f1b, R-1028) bricht jeden Restore auf einem frischen Host ab. Fix: die Images je Dienst aus einem `docker compose --env-file <.env des Backups> config` (kanonisches YAML: Dienst auf Einrückung 2, `image:` auf 4) lesen; ein Wert, den YAML quotet oder als Block schreibt, fällt weiter durch die Prüfung. Der Compose-Stub im Test nennt wie das echte Compose die Images der Abhängigkeiten mit und liefert die Images im YAML von `compose config`; Test zuerst rot.
Semantik: docs/admin/betrieb.html „Vor der Rückfrage nennt <code>restore.sh</code> die Images, mit denen der Stack mit dieser <code>.env</code> startet.“
Beweis: main@03c4068a053596900cd7d9ba8e9c4e750f5f553a · `bash scripts/tests/run.sh all --strict --step "backup_restore (crown-jewel DR)"` → rot mit `FAIL empty host: restore.sh failed` (erste Box 3x, frische Zweit-VM), grün auf `e74aab15d055f770c75bb455724acd739c02fb67`
Dedup-Key: reg:backup-restore-crown-jewel-DR
HEAD: 03c4068a053596900cd7d9ba8e9c4e750f5f553a
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Verhalten wie dokumentiert; der Fehler kam nach v0.46.0 und ist nicht veröffentlicht)

### R2 — Leerer-Host-Abschnitt: Compose-Dateien als Host-Einstellung, nicht in der .env  [x]
Komponente: scripts · Dateien: scripts/tests/backup_restore_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @94be12bb 2026-11-04T05:43:06+01:00
Review: am Ende (Branch-Review)
Änderung: Zweite Ursache, die Box-Lauf `iter.sh all --strict --step "backup_restore (crown-jewel DR)"` mit R1 zeigt: die Install-`.env` des Abschnitts trägt `COMPOSE_FILE=docker-compose.yml:docker-compose.test.yml`, `restore.sh` lässt `COMPOSE_*` außer `COMPOSE_PROJECT_NAME` auf einem frischen Host wie dokumentiert weg (d7b07f1b), der Stack startet ohne Overlay mit `ghcr.io/…/server:latest` (`No module named app.db_roles`). Fix im Test: `COMPOSE_FILE` steht nicht mehr in der `.env`, `in_inst` gibt es jedem Aufruf als Umgebung des Hosts mit; `COMPOSE_PROJECT_NAME` kommt weiter nur aus dem Backup, alle Prüfungen bleiben.
Semantik: docs/admin/betrieb.html „Schlüssel, die Compose oder Docker selbst steuern (<code>COMPOSE_*</code>, <code>DOCKER_*</code>), fallen weg, außer <code>COMPOSE_PROJECT_NAME</code>.“
Beweis: Box-Lauf 2026-11-04 auf 528b2cf0, `.ah-out/heavy/dr.log` des Worktrees: `FAIL empty host: restore.sh failed`, Restore zieht `ghcr.io/admincave/adminhelper/server:latest`
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)

## Beweis (heavy.sh, 2026-11-03-1503)
- Schritt `backup_restore (crown-jewel DR)` war auf der ersten Box 3x rot, jedes Mal mit demselben Marker: `FAIL empty host: restore.sh failed`
- auf einer frischen zweiten VM (Lane w2) ebenfalls rot
- auf dem letzten PASS-Commit `e74aab15d055f770c75bb455724acd739c02fb67` in derselben Lane grün
- Artefakte: `/home/kevin/Dev/AdminCave/AdminHelper/.ah-out/weekly/2026-11-03-1503`

## Entscheidungen
- Lane und Test-DB heißen `reg-backup-restore-dr`: `worktree-setup.sh` verlangt einen Slug aus `[a-z0-9-]` mit höchstens 40 Zeichen, und der Ledger-Name von heavy.sh ist 42 lang und trägt `DR`; Teardown mit demselben Slug.
