<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-16 — Betriebsskripte: Update, Install, Restore, Backup — Task-Ledger
Status: aktiv · Branch: feature/ops-16 · Review: pro Task
Spec: docs/features/ops-16.md (Roadmap R-1703, R-1686, R-1692, R-1712, R-1713, R-1714, R-1727)
Heavy: linux-full — scripts/install.sh, scripts/update.sh, scripts/restore.sh und docker-compose.yml (backup_restore und upgrade_path im Sammellauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- 2026-11-24 Kevin: die Session merged ops-16 selbst (auch install/update/agent-install.sh).
- 2026-11-24 Kevin (R-1713): pg-backup als Compose-Profil `backup`, eingeschaltet über `COMPOSE_PROFILES` in der `.env`; pg-restore.sh ins Bundle.
- 2026-11-24 Kevin (R-1714): update.sh behält die letzten 3 runtime-prev-Archive.

### T1 — R-1703: agent-install.sh schreibt die Repo-Konfiguration nach dem Stand der Identitäts-CA  [ ]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh, changelog.d/ops-16.md
Änderung: Eine Stelle schreibt die apt- bzw. dnf-TLS-Konfiguration: mit vorhandener Identitäts-CA den gehärteten Stand, sonst den Bootstrap-Stand; `setup_repo_apt`, `setup_repo_dnf` und der Schritt nach der Provisionierung rufen sie. Test: erneuter Lauf ohne `--server-id` auf einem Host mit Identitäts-CA (apt und dnf), Gegenprobe ohne CA.
Beweis: Roadmap R-1703 (Einzelheiten privat)
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test
Doku: changelog.d/ops-16.md (neutral)

### T2 — R-1692, R-1714: update.sh: Zeilenende vor neuen .env-Schlüsseln, runtime-prev auf 3 begrenzt  [ ]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/ops-16.md
Änderung: `migrate_env` ergänzt ein fehlendes Zeilenende der `.env` vor dem ersten Anhängen. Nach dem Anlegen von `runtime-prev-<ts>.tar.gz` bleiben die neuesten 3, ältere werden einzeln mit vollem Pfad gelöscht; am Ende eine Log-Zeile mit der Größe von `backups/`. Tests: `.env` ohne Zeilenende (roter Fall zuerst), vier vorhandene runtime-prev → drei bleiben, die neuesten.
Beweis: main@6895f8eaf scripts/update.sh:954-973 (Stub-Lauf: KEY=wertNEUER_KEY=); scripts/update.sh:787,808-817 · Dedup-Key: bug:ops:update.sh:migrate-env-no-trailing-newline, ref:ops:update.sh:backups-grow-unbounded
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: docs/admin/betrieb.html DE + docs/en/admin/operations.html (Aufräumen von backups/) · changelog.d/ops-16.md

### T3 — R-1712: install.sh behält VERSION und nimmt sie beim Neustart als Version  [ ]
Komponente: scripts · Dateien: scripts/install.sh, scripts/tests/install_test.sh, changelog.d/ops-16.md
Änderung: `VERSION` wird nach dem Entpacken nicht mehr entfernt; im Checkout-Modus ohne `--ref` liest install.sh sie als Default für `REF`, sodass die Image-Pins geschrieben werden. Test: abgebrochener Erstversuch, Neustart mit `--reset` aus dem Verzeichnis → gepinnte Version (roter Fall zuerst).
Beweis: main@6895f8eaf scripts/install.sh:164,192-199,645-649 · Dedup-Key: bug:ops:install.sh:retry-after-abort-unpinned-latest
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test
Doku: changelog.d/ops-16.md

### T4 — R-1686: restore.sh leert das Schema vor pg_restore  [ ]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh, scripts/tests/backup_restore_test.sh, changelog.d/ops-16.md
Änderung: Vor `restore_db` werden in beiden DBs die Objekte entfernt (Schema `public` neu, Eigentümer die Service-Rolle wie nach db-init), danach `pg_restore` wie heute. Live-Fall in backup_restore_test.sh: nach dem Backup eine Tabelle mit Fremdschlüssel auf eine alte anlegen, restore → Exit 0, Tabelle weg, alembic_version wie im Backup. Der Live-Fall läuft zusätzlich einmal lokal (Docker), Summary in den Commit-Body; im Sammellauf als Schritt backup-restore.
Beweis: main@6895f8eaf scripts/restore.sh:528-530,554-556; Gegenprobe pg_restore auf PostgreSQL 17 (mit FK Exit 1, ohne FK Waise) · Dedup-Key: bug:ops:restore.sh:pg-restore-over-migrated-schema
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: changelog.d/ops-16.md

### T5 — R-1713: pg-backup als Compose-Profil, pg-restore.sh im Bundle  [ ]
Komponente: scripts · Dateien: docker-compose.yml, .env.example, scripts/install.sh, .github/workflows/release.yml, scripts/tests/install_test.sh, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/ops-16.md
Änderung: Der Dienst `pg-backup` wird regulär mit `profiles: [backup]` ausgeliefert; `.env.example` nennt `COMPOSE_PROFILES` (leer, Kommentar). `scripts/pg-restore.sh` kommt in `RUNTIME_FILES` und ins Release-Bundle. Doku DE+EN: Einschalten über `COMPOSE_PROFILES=backup`. Tests: `docker compose config` ohne Profil ohne pg-backup, mit Profil mit; RUNTIME_FILES und Bundle-Liste enthalten pg-restore.sh.
Beweis: main@6895f8eaf docker-compose.yml:636-637, scripts/update.sh:886,893-899, .github/workflows/release.yml:421-423, scripts/install.sh:61 · Dedup-Key: bug:ops:docker-compose.yml:pg-backup-lost-on-update
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test image_pins_test
Doku: docs/admin/betrieb.html DE + docs/en/admin/operations.html · changelog.d/ops-16.md

### T6 — R-1727: init-secrets.sh räumt auch bei einem Abbruch auf  [ ]
Komponente: scripts · Dateien: scripts/init-secrets.sh, scripts/tests/init-secrets_test.sh, changelog.d/ops-16.md
Änderung: Ein Trap (EXIT und Signale) entfernt die temporäre Kopie neben der `.env`, solange sie nicht umbenannt ist, wie in install.sh/update.sh seit ops-15. Test: Abbruch per Signal zwischen Anlegen und Umbenennen → keine Kopie bleibt.
Beweis: Roadmap R-1727 (Einzelheiten privat)
Verify: bash scripts/dev/verify.sh scripts --strict -- init-secrets_test
Doku: changelog.d/ops-16.md (neutral)
