<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-17 — Betriebsskripte: Nachlese aus ops-16 — Task-Ledger
Status: aktiv · Branch: feature/ops-17 · Review: pro Task
Spec: docs/features/ops-17.md (Roadmap R-1757, R-1761, R-1759, R-1765, R-1766)
Heavy: linux-full — scripts/agent-install.sh, scripts/update.sh, scripts/restore.sh und docker-compose.yml (Sammellauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- 2026-11-25 Kevin: die Session merged ops-17 selbst (auch agent-install.sh/update.sh).

### T1 — R-1757, R-1766, R-1765: agent-install.sh nach abgebrochener Provisionierung; Test-Nachlese  [x]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh, changelog.d/ops-17.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ef493aacd 2026-11-25T15:38:41+01:00
Review: approve (.ah-out/review/ops-17/T1.verdict.json)
Änderung: Scheitert `adminhelper-agent provision`, schreibt agent-install.sh vor dem Abbruch die Repo-Konfiguration nach der vorhandenen Identitäts-CA (`write_repo_tls`). Tests: Provisionierung scheitert auf einem Host mit CA (apt und dnf) → Konfiguration wie vor dem Lauf; dnf-Fall `--server-id` mit alter CA; Fehlerpfad der CA-Kopie; die Token-Prüfungen suchen den ganzen Token statt `zz9`.
Beweis: Roadmap R-1757 (Einzelheiten privat); scripts/tests/agent_install_test.sh:214,226 (R-1766)
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test
Doku: changelog.d/ops-17.md (neutral)

### T2 — R-1761, R-1765: update.sh setzt ältere Dumps auf nur-Besitzer; Test-Nachlese  [ ]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh, changelog.d/ops-17.md
Änderung: update.sh setzt Dump-Dateien in `backups/` (`*.dump`) auf nur-Besitzer, soweit es ihr Eigentümer ist; andere nennt es mit einer Warnung. Der Snapshot-Test prüft positiv statt mit `grep -qv`.
Beweis: Roadmap R-1761 (Einzelheiten privat)
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: changelog.d/ops-17.md (neutral)

### T3 — R-1759: pg-backup sichert je Dienst-Rolle  [ ]
Komponente: server · Dateien: scripts/pg-backup.sh, docker-compose.yml, apps/server/tests/test_env_parity.py, apps/server/tests/test_compose_hardening.py, scripts/tests/backup_restore_test.sh, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/ops-17.md
Änderung: pg-backup.sh dumpt `adminhelper` als `ah_server` und `adminhelper_monitor` als `ah_monitor` (Passwörter `SERVER_DB_PASSWORD`, `MONITOR_DB_PASSWORD` aus der Umgebung); der Dienst bekommt diese statt `POSTGRES_PASSWORD` und wartet auf db-init. test_env_parity: Superuser-Passwort wieder nur postgres/db-init. Live: backup_restore_test fährt pg-backup einmal im Profil und prüft beide Dumps (nur-Besitzer, nicht leer).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_env_parity.py tests/test_compose_hardening.py
Doku: docs/admin/betrieb.html DE + docs/en/admin/operations.html · changelog.d/ops-17.md

### T4 — R-1765: restore.sh leert auch Routinen und Typen; Trap-Nachlese  [ ]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh, scripts/init-secrets.sh, scripts/tests/init-secrets_test.sh, scripts/install.sh, scripts/update.sh, changelog.d/ops-17.md
Änderung: Das Leeren in restore_db entfernt auch Funktionen/Prozeduren/Aggregate und eigenständige Composite-/Range-Typen in public; scheitert das Leeren, läuft kein pg_restore (Test). Die EXIT-Traps über `ENV_TMPS` in init-secrets.sh, install.sh und update.sh vertragen ein leeres Array auch unter bash 4.2; der SIGTERM-Test prüft rc=143.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test init-secrets_test install_test update_test
Doku: changelog.d/ops-17.md
Abhängt von: T2
