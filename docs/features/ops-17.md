<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-17 — Betriebsskripte: Nachlese aus ops-16

Zug der Kern-Session (Roadmap R-1757, R-1761, R-1759, R-1765, R-1766). Kevin 2026-11-25: die Session merged diesen
Zug selbst, obwohl er `scripts/agent-install.sh` und `scripts/update.sh` ändert.

## Problem je Zeile

- **R-1757** `scripts/agent-install.sh`: Scheitert die Provisionierung eines schon eingebundenen Hosts, bleibt die
  Repo-Konfiguration im Stand vor dem Enrollment stehen. Ziel: auf dem Abbruchpfad den Stand nach der vorhandenen
  Identitäts-CA wieder schreiben (`write_repo_tls`).
- **R-1761** `scripts/update.sh`: Sicherungen in `backups/`, die vor ops-16 entstanden sind, behalten ihre alten
  Dateirechte. Ziel: das Update setzt Dump-Dateien in `backups/` auf nur-Besitzer, soweit es sie ändern darf.
- **R-1759** `pg-backup`: sichert beide Datenbanken als Superuser. Ziel: jede Datenbank mit ihrer Dienst-Rolle
  (`ah_server`, `ah_monitor`), der Dienst sieht das Superuser-Passwort nicht mehr; die Ausnahme in
  `apps/server/tests/test_env_parity.py` entfällt. Live-Beweis im Docker-Test `backup_restore_test.sh`.
- **R-1765** Nachlese ops-16: `restore.sh` leert auch Funktionen, Prozeduren und eigenständige Composite-/Range-Typen;
  Abbruchpfad des Leerens getestet; `init-secrets.sh` und `install.sh`: Trap über ein leeres Array auch unter
  bash 4.2; Tests schärfer (`rc=143` beim Signal, positiver Snapshot-Check, dnf-Fall mit `--server-id`, Fehlerpfad
  der CA-Kopie).
- **R-1766** `scripts/tests/agent_install_test.sh`: die Prüfung „Token nicht in der Ausgabe“ sucht `zz9`, das zufällig
  in Temp-Pfaden stehen kann. Ziel: nach dem ganzen Token suchen.

## Nicht-Ziele

Keine neue Backup-Strategie, keine Änderung an `backup.sh`.

## Risiken & Rollback

Jede Task einzeln revertierbar. R-1759 ändert, als wer `pg-backup` liest; scheitert ein Dump als Rolle, zeigt das
der Live-Test, und die Dumps bleiben wie bisher verwendbar (`pg-restore.sh` spielt als Superuser ein).

## Doku-Impact

`docs/admin/betrieb.html` DE + `docs/en/admin/operations.html` (pg-backup liest je Dienst-Rolle),
`changelog.d/ops-17.md`.

## Offene Fragen

Keine.
