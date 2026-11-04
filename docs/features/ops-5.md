<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-5 — Betriebsskripte: .env-Übernahme beim Restore, Schlüssel lesen wie Compose, Update ohne Terminal, Install-Prüfung der .env

Roadmap R-1017, R-1028, R-1002, R-1003, R-1027, R-1008 (Zug `tasks/ops-5.md`).

## Problem / Motivation
- **R-1017:** Der Passphrase-Filter von `scripts/backup.sh` (`:254-287`) liest jede Stelle hinter einem
  Anführungszeichen auch als Zeilenanfang (Über-Maskierung, ops-4). Steht dort `CA_ROOT_PASSPHRASE=` im
  geschlossenen Wert eines anderen Schlüssels, schneidet er bis zum Zeilenende ab und nimmt den schließenden Quote
  mit: aus `A="x 'CA_ROOT_PASSPHRASE=geheim"` wird `A="x '` (Probe auf `origin/main@f03bbf14`). Compose liest die
  gesicherte `.env` dann über die folgenden Zeilen hinweg als einen Wert.
- **R-1028:** Härtung der automatischen `.env`-Übernahme auf einem frischen Host (`scripts/restore.sh:52-61`,
  `:151-156`): übernommen werden nur Schlüssel der Anwendung; die
  Image-Werte der übernommenen `.env` stehen vor der Rückfrage. Details nur in `tasks/private/`.
- **R-1002:** `is_set_safely` und `upsert` in `scripts/init-secrets.sh` (`:37`, `:53`) erkennen einen Schlüssel nur
  als `^KEY=`. `export KEY=v` oder `KEY = v` (Compose liest beide) gelten als ungesetzt; `upsert` hängt eine zweite,
  neu erzeugte Zeile an. Bei `POSTGRES_PASSWORD` passt das Passwort danach nicht mehr zum Volume.
- **R-1003:** `scripts/update.sh` ohne Terminal (`ssh host ./scripts/update.sh`): bricht die Verbindung ab, kommt
  kein SIGHUP, und das nächste Schreiben beendet das Skript per SIGPIPE, in jeder Phase, auch mitten im Tausch oder
  Rollback, ohne Log. Die Doku sagt (`docs/admin/installation.html:227`): „Ein Abbruch per Strg-C, `kill` oder eine
  getrennte SSH-Sitzung rollt ebenso zurück; nach einer getrennten Sitzung steht die Ausgabe in
  `backups/update-<zeit>.log`.“
- **R-1027:** `scripts/install.sh` gibt stderr von `docker compose config` (`:262-263`) und `pull` (`:414`)
  ungefiltert aus. Eine vorab geschriebene `.env` (wird übernommen) mit Syntaxfehler lässt Compose eine Zeile samt
  Wertfragment zitieren. `update.sh` prüft die `.env` vorher (`check_env_templates`, `:194`) und nennt nur die
  Zeilennummer.
- **R-1008:** Der Kopfkommentar von `scripts/agent-install.sh` (`:9-11`) zeigt den Einzeiler mit
  `--token <provision-token>` auf der Kommandozeile; die Doku (`docs/admin/agent-deployment.html:51`) nennt als Weg
  des Desktop-Einzeilers, `--token` wegzulassen (verdeckte Abfrage über `/dev/tty`).

## Ziel & Nicht-Ziele
- Die gesicherte `.env` behält jeden Quote eines anderen Schlüssels, die Passphrase geht weiter in jeder Form.
- Die übernommene `.env` eines Restores trägt nur Schlüssel der Anwendung; vor der Rückfrage steht, welche Images
  sie setzt.
- `init-secrets.sh` liest und ersetzt Schlüssel in jeder Form, die Compose liest (wie `migrate_env`, ops-3).
- `update.sh` behandelt ein gescheitertes Schreiben auf stdout/stderr wie eine getrennte Sitzung (Doku-Semantik oben).
- `install.sh` prüft eine vorhandene `.env` wie `update.sh`, bevor es Compose aufruft.
- Nicht: eigene Maskierung der Compose-Ausgabe, neue Flags, Änderungen am Tokenizer-Verhalten außerhalb von R-1017.

## Betroffene Komponenten & Dateien
`scripts/backup.sh`, `scripts/restore.sh`, `scripts/diagnostics.sh` (nur wenn T1 den gemeinsamen Tokenizer-Text
ändert), `scripts/init-secrets.sh`, `scripts/update.sh`, `scripts/install.sh`, `scripts/agent-install.sh`; Tests
`restore_guard_test.sh`, `diagnostics_test.sh` (Test (r): gleiche Kopien), `init-secrets_test.sh`, `update_test.sh`,
`install_test.sh`, `agent_install_test.sh`.

## Datenmodell / API / Migrationen
Keine. Keine neuen Flags; neue Meldungen englisch.

## Externe Integrationen
compose-go dotenv-Parser (wie ops-4 gelesen); Compose-Umgebungsvariablen
https://docs.docker.com/compose/how-tos/environment-variables/envvars/ (vor T2 per WebFetch nachlesen, welche
Präfixe Compose aus der `.env` des Projekts übernimmt).

## Trade-offs & Alternativen
- **R-1028 lesen:** `restore.sh` bekommt eine dritte Kopie des Tokenizer-Texts (Marker wie in `backup.sh`, Test (r)
  hält alle drei gleich) statt eines `grep`: ein Schlüssel in einem mehrzeiligen Wert darf nicht als Zeile fallen.
  Alternative gemeinsame Datei unter `scripts/lib/` verworfen wie in ops-4 (`RUNTIME_FILES`, `release.yml`).
- **R-1027:** die Prüfung von `update.sh` als markierte, byte-gleiche Kopie in `install.sh` (Test hält sie gleich)
  statt die Compose-Ausgabe zu filtern: ein Filter müsste die `.env` selbst parsen und nähme auch nützliche
  Fehlermeldungen (Daemon, Netz). Nach bestandener Prüfung zitiert Compose keine `.env`-Zeile mehr.
- **R-1003:** SIGPIPE wird ignoriert; ein Schreibfehler in `log`/`die` und der direkten Ausgabe leitet die Ausgabe
  ins Log (`hup_to_log`) und läuft ab dem Tausch wie SIGHUP in den Rollback, davor endet das Skript ohne Änderung,
  mit der Meldung im Log. Alternative „weiterlaufen bis zum Ende“ widerspräche der Doku.

## Risiken & Rollback
`update.sh`, `install.sh` und `agent-install.sh` im Diff: Kevin merged den PR. Restore und Backup sind
Datenpfade: `security` je Task bei T1, T2, T4, T5. Fehler zeigen sich als abgebrochenes Update/Install oder als
falsche `.env`; die hermetischen Tests decken jede Form. Rollback: Revert des Merges.

## Doku-Impact
`docs/admin/betrieb.html:107` + `docs/en/admin/operations.html:74` (Restore auf frischem Host: welche Schlüssel
übernommen werden, Images vor der Rückfrage, neutral); `docs/admin/installation.html:227` + EN `:180` (getrennte
Sitzung auch ohne Terminal); `docs/admin/installation.html` + EN (install prüft eine vorhandene `.env`); CHANGELOG
über `changelog.d/ops-5.md`.

## Offene Fragen
Keine. Die Semantik von R-1003 legt die Doku fest; R-1028 und R-1027 folgen den Vorschlägen ihrer Zeilen.
