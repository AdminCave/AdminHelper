<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-18 — Betriebsskripte: Snapshot, Restore-Herkunft, Env-Prüfung, Backup-Rolle

Zug der Kern-Session (Roadmap R-1782, R-1786, R-1821, R-1783). Kevin 2026-11-27: alle vier angenommen, die Session
merged selbst („du darfst alles mergen“), obwohl der Zug `scripts/install.sh` und `scripts/update.sh` ändert.

## Problem je Zeile

- **R-1782** `scripts/update.sh:858`: Den Laufzeit-Snapshot für den Rollback schreibt `update.sh` unter einem
  vorhersagbaren Namen direkt nach `backups/`, und der Rollback liest ihn dort wieder (`:909`). Ziel: Der Snapshot
  entsteht in einem Verzeichnis, das nur dieser Lauf anlegt, und erhält dann seinen Namen, so wie es `backup.sh`
  schon macht. Vor dem Auspacken prüft der Rollback, ob der Snapshot noch der ist, den dieser Lauf geschrieben hat.
  Einzelheiten stehen nur in `tasks/private/`.
- **R-1786** `scripts/restore.sh:20,48`: `restore.sh` spielt jedes Archiv ein, egal wem es gehört und wer es ändern
  konnte. Ziel (Kevin 2026-11-27): Abgelehnt wird ein Archiv,
  - das weder dem Aufrufer noch root gehört,
  - das für Gruppe oder andere beschreibbar ist,
  - oder das in einem Ordner liegt, den andere beschreiben können (ohne Sticky-Bit).

  Für eine bewusst fremde Kopie gibt es den Schalter `--allow-foreign`. Die Prüfung gilt für die geöffnete Datei.
  `restore.sh` arbeitet danach nur noch mit seiner eigenen Kopie unter `$STAGE`, sodass sich das Archiv zwischen
  Prüfung und Lesen nicht mehr tauschen lässt. Die Argumente werden unabhängig von der Reihenfolge gelesen
  (`--yes`, `--allow-foreign`).
- **R-1821** `check_env_templates`, in `scripts/update.sh:280` und `scripts/install.sh:470`: Ist C.UTF-8 nicht
  erkannt und die Locale des Aufrufers UTF-8, endet eine Zeile `export <U+2003>=wert` mit `bad array subscript`
  (`ENV_SEEN[$key]`, update.sh:328, install.sh:518), statt sauber abgelehnt zu werden. Der Abbruch kommt auch dann
  vor jeder Änderung. Ziel: Ein leerer Schlüssel nach dem Trimmen wird wie jeder andere ungültige Schlüssel mit
  Zeilennummer abgelehnt.
- **R-1783** `pg-backup` (`docker-compose.yml:675`, `scripts/pg-backup.sh:35,40`): sichert mit den Dienst-Rollen,
  die Schreib- und DDL-Rechte haben. Ziel (Kevin 2026-11-27):
  - Eine fünfte Rolle `ah_backup` in `apps/server/app/db_roles.py` `setup`, mit CONNECT auf beide Datenbanken und
    je Datenbank SELECT auf das Schema `public` samt Default-Privilegien, sonst nichts. Nicht `pg_read_all_data`:
    das liest auch die System-Kataloge (Entscheidung T5 im Ledger).
  - Das Passwort `BACKUP_DB_PASSWORD` erzeugt `scripts/init-secrets.sh:129` wie die übrigen, wenn es fehlt. Ein
    normales Update holt die Rolle also nach (update.sh ruft init-secrets.sh auf, db-init setzt die Rolle bei
    jedem Start).
  - `pg-backup` sieht nur noch dieses Passwort.
  - `restore.sh` bleibt bei den Dienst-Rollen. Die Datenbanken brauchen keine Migration.

## Nicht-Ziele

- Keine neue Backup-Strategie.
- `backup.sh` bleibt unverändert.
- Keine Prüfung der Signatur oder des Inhalts eines Archivs über das hinaus, was `restore.sh` heute prüft.

## Risiken & Rollback

- Jede Task lässt sich einzeln revertieren.
- R-1786 kann einen Restore ablehnen, der heute durchläuft, etwa ein Archiv, das ein anderer Nutzer kopiert hat.
  Die Meldung nennt dann `--allow-foreign`.
- R-1783: Wird nach dem Update auf eine ältere Version zurückgerollt, bleibt die Rolle `ah_backup` bestehen. Das
  schadet nicht, weil sie nur lesen darf. Scheitert ein Dump als `ah_backup`, zeigt das der Live-Block in
  `backup_restore_test.sh`.

## Heavy

`linux-full` über den Sammellauf: Der Zug ändert `scripts/install.sh`, `scripts/update.sh`, `scripts/restore.sh` und
`docker-compose.yml`, und dort laufen `backup_restore` und `upgrade_path`.

## Doku-Impact

- `docs/admin/installation.html` und `docs/en/admin/installation.html`: neues `BACKUP_DB_PASSWORD`.
- `docs/admin/betrieb.html` und `docs/en/admin/operations.html`:
  - Restore prüft die Herkunft, mit dem Schalter `--allow-foreign`.
  - pg-backup liest als `ah_backup`.
- `changelog.d/ops-18.md`, SEC-Punkte neutral formuliert.

## Offene Fragen

Keine. Die Einrichtung der Rolle hat Kevin am 2026-11-27 entschieden.
