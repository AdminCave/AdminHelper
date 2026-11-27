<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-18 — Betriebsskripte: Snapshot, Restore-Herkunft, Env-Prüfung, Backup-Rolle — Task-Ledger
Status: bereit · Branch: feature/ops-18 · Review: pro Task
Spec: docs/features/ops-18.md (Roadmap R-1782, R-1786, R-1821, R-1783)
Heavy: linux-full — scripts/install.sh, scripts/update.sh, scripts/restore.sh und docker-compose.yml (backup_restore und upgrade_path im Sammellauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-27: die Session merged ops-18 selbst (auch install.sh/update.sh).
- Kevin 2026-11-27 R-1783: Rolle ah_backup über db_roles.setup (pg_read_all_data, CONNECT), Passwort BACKUP_DB_PASSWORD über init-secrets.sh, keine DB-Migration.
- T1 (security T1): Der Snapshot entsteht in `$TMP` (0700, außerhalb jedes Container-Mounts), der Rollback entpackt nur ihn; die Kopie in `backups/` dient der Aufbewahrung, exklusiv angelegt (`dd conv=excl`) und per `mv -fT` umbenannt. Damit entfallen das `mktemp -d` unter `backups/` und der SHA-256-Vergleich der Änderung oben.
- T5 (security T5): `ah_backup` bekommt statt `pg_read_all_data` je Datenbank USAGE auf `public`, SELECT auf alle Tabellen und Sequenzen und Default-Privilegien für die Eigentümer-Rolle; `pg_read_all_data` liest auch die System-Kataloge. Enger als Kevins Vorgabe, gleiche Wirkung für pg_dump (Probe: TOC wie beim Superuser-Dump); im Bericht an Kevin genannt.

### T1 — R-1782: update.sh legt den Laufzeit-Snapshot sicher an und prüft ihn vor dem Rollback  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @faaf9e4b6 2026-11-27T13:07:59+01:00
Review: approve (.ah-out/review/ops-18/T1.verdict.json)
Änderung: Snapshot in einem eigenen `mktemp -d`-Verzeichnis unter `backups/` schreiben, dann per `mv -fT` unter seinen Namen; SHA-256 merken und vor `tar xzf "$SNAP"` im Rollback prüfen, sonst Rollback der Laufzeit-Dateien verweigern (laut, mit Weg). Tests: vorbelegter Name wird ersetzt, nicht beschrieben; getauschter Snapshot bricht den Rollback ab.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: → T6

### T2 — R-1786: restore.sh prüft die Herkunft des Archivs  [x]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @92209a5e2 2026-11-27T13:34:57+01:00
Review: approve (.ah-out/review/ops-18/T2.verdict.json)
Änderung: Argumente in beliebiger Reihenfolge (`--yes`, `--allow-foreign`). Archiv einmal öffnen, Eigentümer (Aufrufer oder root), Modus (nicht g/o-beschreibbar) und Ordner (nicht fremd beschreibbar ohne Sticky-Bit) prüfen, danach nur die eigene Kopie unter `$STAGE` lesen. `--allow-foreign` übergeht die Herkunftsprüfung, nicht die Inhaltsprüfung. Tests je Ablehnung, Schalter und Reihenfolge der Argumente.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: → T6

### T3 — R-1821: check_env_templates lehnt einen leeren Schlüssel sauber ab  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/install.sh, scripts/tests/update_test.sh, scripts/tests/install_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @66dcee79c 2026-11-27T13:55:36+01:00
Review: approve (.ah-out/review/ops-18/T3.verdict.json)
Änderung: Nach dem Trimmen ist ein leerer Schlüssel ein ungültiger (dieselbe Meldung mit Zeilennummer), bevor `ENV_SEEN` ihn sieht; beide Kopien gleich. Test zuerst rot: die Funktionskopie ohne erkanntes C.UTF-8 (wie update_test.sh:1234) mit `export <U+2003>=wert` endet mit der Ablehnung, nicht mit `bad array subscript`.
Beweis: Roadmap R-1821 (security-Nit kern-update-env-1 @a63b0bf60, Probe unter de_DE.UTF-8 rc=1)
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test install_test
Doku: keine (Ablehnung wie dokumentiert: nur Zeilennummer)
Abhängt von: T1

### T4 — R-1783: init-secrets.sh erzeugt BACKUP_DB_PASSWORD  [x]
Komponente: scripts · Dateien: scripts/init-secrets.sh, scripts/tests/init-secrets_test.sh, .env.example, scripts/restore.sh, scripts/tests/restore_guard_test.sh, scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @17ec6c035 2026-11-27T14:12:59+01:00
Review: approve (.ah-out/review/ops-18/T4.verdict.json)
Änderung: `BACKUP_DB_PASSWORD` in die Schleife der DB-Passwörter (neu und bei fehlendem Key auf Update), `.env.example` mit leerem Eintrag. Test: frische und bestehende `.env`.
Verify: bash scripts/dev/verify.sh scripts --strict -- init-secrets_test restore_guard_test diagnostics_test lib_e2e_stack_test
Doku: → T6

### T5 — R-1783: Rolle ah_backup und pg-backup liest als sie  [x]
Komponente: server · Dateien: apps/server/app/db_roles.py, apps/server/tests/test_db_roles.py, docker-compose.yml, scripts/pg-backup.sh, apps/server/tests/test_env_parity.py, scripts/tests/backup_restore_test.sh, docs/features/ops-18.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @90dcab63d 2026-11-27T14:24:34+01:00
Review: approve (.ah-out/review/ops-18/T5.verdict.json)
Änderung: `ROLES["backup"]` (`ah_backup`, `BACKUP_DB_PASSWORD`), in `setup` CONNECT auf beide DBs und je DB SELECT auf `public` samt Default-Privilegien (nicht `pg_read_all_data`, siehe Entscheidungen), sonst nichts. db-init bekommt das Passwort; pg-backup nur noch `BACKUP_DB_PASSWORD`, dumpt als `ah_backup`. Tests: Rolle kann lesen, nicht schreiben, kein DDL; Compose-Parität; der Live-Block in backup_restore_test.sh dumpt als ah_backup.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_db_roles.py tests/test_env_parity.py tests/test_compose_hardening.py
Doku: → T6
Abhängt von: T4

### T6 — Doku DE+EN und Changelog  [x]
Komponente: scripts · Dateien: docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/ops-18.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0557644b8 2026-11-27T14:29:26+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Restore: Herkunftsprüfung und `--allow-foreign`; pg-backup liest als `ah_backup`; `BACKUP_DB_PASSWORD` in der Env-Liste; Changelog neutral.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Seiten
Task-Review: am Ende

### T7 — Doku: ah_backup in README und Entwickler-Doku (Abschlussprüfung)  [x]
Komponente: scripts · Dateien: README.md, docs/developer/index.html, docs/en/developer/index.html, docs/features/ops-18.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @42c46dcdb 2026-11-27T14:40:55+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: README: init-secrets füllt fünf Rollen-Passwörter samt `BACKUP_DB_PASSWORD`, Rollenliste mit `ah_backup`; Abschnitt „Datenbank-Rollen“ DE+EN nennt `ah_backup` (nur lesend, CONNECT auf beide DBs, Default-Privilegien, pg-backup dumpt als sie); Spec R-1782 auf Entscheidung T1.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende
