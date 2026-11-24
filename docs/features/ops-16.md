<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-16 — Betriebsskripte: Update, Install, Restore, Backup

Zug der Kern-Session (Roadmap R-1703, R-1686, R-1692, R-1712, R-1713, R-1714, R-1727). Kevin 2026-11-24: die
Session merged diesen Zug selbst, obwohl er `scripts/install.sh`, `scripts/update.sh` und
`scripts/agent-install.sh` ändert.

## Problem je Zeile

- **R-1703** `scripts/agent-install.sh`: Die Repo-Konfiguration (apt `99adminhelper-ca`, dnf `adminhelper.repo`)
  wird bei jedem Lauf im Bootstrap-Stand geschrieben (`setup_repo_apt`, `setup_repo_dnf`) und erst nach der
  Provisionierung gehärtet (Abschnitt „post-enroll hardening“). Ein Lauf ohne `--server-id` endet vorher.
  `agent-install-bsd.sh` (`write_repo_conf`) entscheidet dagegen schon beim Schreiben anhand der Identitäts-CA.
  Ziel: dieselbe Entscheidung in `agent-install.sh`, eine Stelle für beide Stände.
- **R-1692** `scripts/update.sh` `migrate_env`: hängt neue Schlüssel an eine `.env` ohne abschließendes
  Zeilenende an; der neue Schlüssel klebt dann an der letzten Zeile.
- **R-1714** `scripts/update.sh`: jeder Lauf legt `backups/runtime-prev-<ts>.tar.gz` an, nichts räumt auf.
  Kevin 2026-11-24: die letzten 3 behalten; am Ende nennt das Update die Größe von `backups/`. Die vollen
  `adminhelper-backup-*` bleiben unangetastet, die Doku sagt, wie man sie aufräumt.
- **R-1712** `scripts/install.sh`: entfernt nach dem Entpacken `VERSION`; ein Neustart mit `--reset` aus dem
  Verzeichnis kennt dann keine Version und installiert ungepinnt. Ziel: `VERSION` bleibt und dient im
  Checkout-Modus als Default für `REF`.
- **R-1686** `scripts/restore.sh`: `pg_restore --clean --if-exists` über einer schon vorwärts migrierten DB
  scheitert (neue Tabelle mit Fremdschlüssel) oder lässt Waisen (ohne). Ziel: vor `pg_restore` das Schema der
  beiden DBs leeren, danach wie heute; Live-Fall in `scripts/tests/backup_restore_test.sh`.
- **R-1713** `pg-backup`: heute ein auskommentierter Block in `docker-compose.yml`, den jedes Update
  überschreibt; `scripts/pg-restore.sh` fehlt im Bundle. Kevin 2026-11-24: Dienst regulär mit
  `profiles: [backup]` ausliefern, eingeschaltet über `COMPOSE_PROFILES=backup` in der `.env`;
  `pg-restore.sh` in `RUNTIME_FILES` (`install.sh`) und ins Release-Bundle (`release.yml`).
- **R-1727** `scripts/init-secrets.sh`: Aufräumen der temporären Datei auch bei einem Abbruch durch Signal,
  wie in `install.sh`/`update.sh` seit ops-15.

## Nicht-Ziele

Kein neues Backup-Konzept, keine Aufbewahrung der vollen Backups durch `update.sh`, keine Änderung an
`backup.sh`.

## Risiken & Rollback

Alle Änderungen wirken ohne Release nur auf Hosts, die das Skript aus `main` ziehen; `update.sh` und
`install.sh` laufen mit Release-Tag. Jede Task ist einzeln revertierbar. `restore.sh` leert das Schema nur
nach den bestehenden Schutzabfragen (`restore_guard_test`). Das Compose-Profil ändert nichts für Hosts ohne
`COMPOSE_PROFILES`: der Dienst startet ohne Profil nicht.

## Doku-Impact

`docs/admin/betrieb.html` und `docs/en/admin/operations.html` (pg-backup einschalten, Aufräumen von
`backups/`), `docs/admin/installation.html` DE+EN nur falls die Neustart-Anleitung `VERSION` nennt;
`changelog.d/ops-16.md`.

## Offene Fragen

Keine; beide Verhaltensfragen hat Kevin am 2026-11-24 entschieden.
