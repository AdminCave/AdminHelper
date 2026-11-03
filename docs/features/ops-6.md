<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-6 — Betriebsskripte: Compose-Meldungen, .env lesen wie Compose, Admin-Name, Widerrufer-Schlüssel

Roadmap R-1051, R-1049, R-1057, R-1050, R-1048, R-1052, R-1047, R-1058, R-1045 (Zug `tasks/ops-6.md`). Stand
`origin/main@e1944a88`. R-1035 (Postgres 18) fährt nicht mit: das Upgrade-Verfahren für bestehende Installationen
ist eine Datenmigration und Kevins Entscheidung (CLAUDE.md §2); die Zeile wandert in den Zug `tasks/kern-pg-1.md`,
die Frage steht am Gate.

## Problem / Motivation
- **R-1051:** Die Ops-Skripte geben Fehlermeldungen von `docker compose` uneinheitlich aus (`scripts/install.sh`
  `install_state`, `scripts/update.sh`, `scripts/restore.sh` `compose_names`): mal roh per `cat`, mal per `cat -v`.
  Ziel ist ein Weg für alle. Details nur in `tasks/private/`.
- **R-1049:** Überlange Kommentarzeilen im Kopf des gemeinsamen env-check-Blocks (`install.sh`/`update.sh`) und in
  `scripts/backup.sh` (Passphrase-Filter).
- **R-1057:** `install.sh --admin-user` reicht den Namen ungeprüft an `create-admin`; ein Name außerhalb von
  `_USERNAME_PATTERN` (`apps/server/app/modules/users/schemas.py:14`, Länge 3–64 nach `apps/server/app/cli.py:55`)
  scheitert erst nach `docker compose up`.
- **R-1050:** Scheitert in `update.sh` das Backup-first (`./scripts/backup.sh … | tee`), meldet `die` deutsch und ohne
  Test; die `update_test.sh`-Ausgabe trägt eine Job-Meldung („Aufgelegt“) einer Shell-Jobsteuerung.
- **R-1048:** Der Passphrase-Filter in `backup.sh` verliert das schließende Quote eines Werts, wenn es auf einer
  Zeile steht, die wie ein Kommentar aussieht.
- **R-1052:** Die Maskierung einer kaputten `.env` in `backup.sh` maskiert mehr als nötig.
- **R-1047:** `restore.sh` `role_password` (`:268`) liest nur `KEY=` und die erste Anweisung; Compose nimmt jede Form
  (`export KEY=`, `KEY = v`, Quotes) und die letzte.
- **R-1058:** Der Schnitt der Compose-Variablen in `restore.sh` kennt die ES/EE-Erweiterung aus `backup.sh` nicht
  (eine `.env` wie `A="x 'COMPOSE_X=1"` mit mehrzeiligem Folgewert ergibt eine `env.new`, die Compose ablehnt);
  `compose_names` gibt `.compose-err` per `cat` statt `cat -v` aus.
- **R-1045:** `scripts/agent-install.sh` `primary_fprs` (`:178`) erwartet den `fpr`-Datensatz direkt nach `pub`; ein
  Schlüssel mit designiertem Widerrufer (`rvk` dazwischen) ergibt `?`, und der Installer lehnt den legitimen
  Schlüssel ab (scheitert sicher).

## Ziel & Nicht-Ziele
Ziel: jede Zeile behoben, mit einem Test, der ohne den Fix rot ist. Nicht-Ziele: neue Optionen, eine andere
Ausgabesprache der bestehenden deutschen Meldungen, Änderungen an Compose-Dateien.

## Betroffene Komponenten & Dateien
`scripts/install.sh`, `scripts/update.sh`, `scripts/backup.sh`, `scripts/restore.sh`, `scripts/agent-install.sh`;
Tests `scripts/tests/install_test.sh`, `update_test.sh`, `restore_guard_test.sh`, `agent_install_test.sh`;
`changelog.d/ops-6.md`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Docker Compose `.env`-Syntax (https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/),
GnuPG `--with-colons` (doc/DETAILS: `rvk`-Datensatz).

## Trade-offs & Alternativen
- R-1047: `role_password` über den vorhandenen `ENV_TOK`-Tokenizer statt eines eigenen `grep` (eine Lesart für
  Backup und Restore). Empfehlung: Tokenizer.
- R-1045: in `primary_fprs` den ersten `fpr` nach `pub` nehmen, über `rvk` hinweg, aber nie über `sub`/`uid` hinaus.

## Risiken & Rollback
Install, Update, Backup und Restore sind Nutzerpfade; jede Task ist einzeln zurücknehmbar (`git revert`). Der PR
ändert `scripts/install.sh`, `scripts/update.sh` und `scripts/agent-install.sh`: Kevin merged (CLAUDE.md §2).

## Doku-Impact
`docs/admin/installation.html` + EN, falls dort die Form von `--admin-user` steht (T2); sonst nur das
Changelog-Fragment.

## Offene Fragen
Keine im Zug. R-1035: siehe Gate.
