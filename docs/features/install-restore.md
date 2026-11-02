<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Install und Restore: bestehende Installation erkennen, `--reset` mit Bestätigung, Start mit `--wait`, Restore auf leerem Host

Stand des Codes: `origin/main@e2304a8b` (für die Dateien dieses Vorhabens gleich `237b450a`). Alle `datei:zeile`
beziehen sich auf diesen Stand. Ledger: `tasks/install-restore.md`. Roadmap R-0665, R-0668 und der install.sh-Teil von
R-0614 (der Rest von R-0614 steht in `tasks/update-rollback.md` auf `feature/update-rollback`).

**Hängt ab von** (vor dem Bau gemergt; Überschneidungen je Funktion):
- `feature/ops-install-hardening`: `scripts/install.sh` (T4: Parser `:56-71`, Datei-Passwort direkt nach dem Parsen,
  Meldung `:223`) — T1 hier prüft direkt nach dem Parsen bzw. nach dem Preflight; `scripts/tests/install_test.sh` (T4:
  neuer Abschnitt nach Test 7, Aufruf-Log des Stubs) — hier Stub `:44-58` und neue Fälle; `docs/admin/installation.html`
  `:97` (+ EN `:75`, Codeblock des Schnell-Install) — T1 und T2 hier ändern denselben Codeblock.
- `feature/ops-scripts-hardening`: `scripts/backup.sh` (`env.sanitized` byte-treu, alle Schlüssel-Formen von
  `CA_ROOT_PASSPHRASE` gefiltert) — T6 hier macht daraus die `.env`; `scripts/tests/restore_guard_test.sh` (neuer
  Abschnitt `backup.sh` mit docker-Stub) — T5 und T6 hier ergänzen die Fälle von `restore.sh`.
- `feature/compose-hardening`: T6 (CA-Passphrase als Compose-Secret aus `environment: CA_ROOT_PASSPHRASE`; fehlt die
  Variable, bricht `docker compose up` ab) — die `.env` aus T6 hier trägt deshalb die Zeile `CA_ROOT_PASSPHRASE=`;
  T7 (`init-secrets.sh` erzeugt die Passphrase nur bei frischer Installation; Satz zu `.env.restored` in
  `docs/admin/betrieb.html:103`) — T6 hier schreibt diesen Satz um.

## Problem / Motivation

1. **install.sh über einer bestehenden Installation (R-0665).** Im Bootstrap-Modus (keine `docker-compose.yml` im
   Arbeitsverzeichnis, `install.sh:149-173`) entpackt das Skript das Bundle in `$TARGET_DIR`, auch wenn dort schon
   eine Installation liegt, und überschreibt Compose-Datei und Skripte. Danach — in beiden Modi — übernimmt es eine
   vorhandene `.env` (`:207`), schreibt `DOMAIN` neu (`:218-221`, `:229`: ohne `--domain` wird `localhost` daraus, mit
   `--yes` ohne Rückfrage), pinnt die Images auf das Ziel (`:239-246`) und startet mit `up -d` (`:269`) — die Server
   migrieren beim Start (`apps/server/docker-entrypoint.sh:43-45`), ohne Backup und ohne Rollback. `create-admin`
   scheitert danach an dem schon vorhandenen Admin (`apps/server/app/cli.py:50-52`, Exit 1, `set -e`), nachdem der
   Stack schon verändert ist. `--reset` macht `docker compose down -v` (`:262-265`, Volumes `postgres-data` und
   `ca-pki` weg) ohne eigene Bestätigung; die allgemeine Rückfrage (`:250-254`) überspringt `--yes`.
2. **install.sh wartet nur auf TCP (R-0614, install.sh-Teil).** Nach `docker compose up -d` (`:269`) wartet das
   Skript auf einen TCP-Connect an `server:8080` (`:276-294`) und meldet Erfolg, auch wenn gateway, ca-issuer, frps
   oder monitoring in einer Restart-Schleife hängen. Probe und Doku zu `up --wait`: `docs/features/update-rollback.md`
   (Problem 1, Externe Integrationen).
3. **restore.sh auf einem leeren Host (R-0668 a).** `restore.sh` startet postgres (`:109-121`) und den Stack (`:163-164`)
   mit der `.env`, die es vorfindet, und legt die `.env` aus dem Backup erst am Ende als `.env.restored` ab
   (`:166-173`). Das postgres-Image setzt `POSTGRES_PASSWORD` nur beim ersten Init eines leeren Datenverzeichnisses
   („any pre-existing database will be left untouched“) und verlangt es dafür („must not be empty or undefined“,
   postgres-Image-Doku). Auf einem frischen Host mit einer neuen `.env` ist `postgres-data` danach mit deren Passwort
   initialisiert; übernimmt der Betreiber `.env.restored`, wie die Doku es sagt (`docs/admin/betrieb.html:104`, EN
   `docs/en/admin/operations.html:71`), scheitert jede Verbindung an `password authentication failed`. Ohne jede
   `.env` initialisiert postgres gar nicht, `restore.sh` bricht nach 60 s ab (`:121`). Code-Lesung, nicht gefahren.
4. **Volume-Präfix von Hand (R-0668 b).** `restore.sh:29` (und `uninstall.sh:58`) bilden den Projektnamen aus
   `COMPOSE_PROJECT_NAME` der Umgebung oder dem Verzeichnisnamen; Compose liest `COMPOSE_PROJECT_NAME` auch aus der
   `.env`. Probe (Compose v5.5.1, `docker compose config` mit der `docker-compose.yml` dieses Stands): `.env` mit
   `COMPOSE_PROJECT_NAME=ah-prod` → `name: ah-prod`, Volume `ah-prod_ca-pki`; `restore.sh` schriebe die CA in
   `<verzeichnis>_ca-pki`, ein verwaistes Volume, und spielte die Datenbank in das echte — CA und Datenbank aus
   verschiedenen Ständen. Der Label-Sweep von `uninstall.sh` (`:130-135`) träfe kein Objekt des Projekts.
5. **Ungepinntes `alpine` als root über dem CA-Volume (R-0668 c).** `restore_volume` (`restore.sh:68`) und der
   Restore von `./data` (`:102`) laufen in `alpine` ohne Tag und Digest — das Image, das Docker Hub gerade liefert,
   als root mit dem CA-Volume eingehängt. Alle anderen Images der Compose-Datei sind per Digest gepinnt.

## Ziel & Nicht-Ziele

Ziel:
- `install.sh` bricht über einer bestehenden Installation ab und nennt `update.sh` (T1); `--reset` löscht nur nach
  getippter Bestätigung, die die Volumes nennt, auch mit `--yes` (T2); ohne `--domain` bleibt die `DOMAIN` der
  vorhandenen `.env` (T3); Start mit `docker compose up -d --wait` (T4).
- `restore.sh` nimmt Projekt- und Volume-Namen von Compose und das gepinnte postgres-Image statt `alpine` (T5); auf
  einem Host ohne Datenbank-Volume und ohne `.env` wird die `.env` aus dem Backup vor dem Start von postgres
  angelegt (T6); `uninstall.sh` nimmt den Projektnamen von Compose (T7); der Restore auf einem leeren Host läuft
  einmal gegen echte Container (T8).

Nicht-Ziele:
- **update.sh**, Healthchecks in `docker-compose.yml`: `tasks/update-rollback.md`.
- **`alpine` in `uninstall.sh:146`** (`nuke_path`): es berührt Host-Pfade, nicht das CA-Volume, und läuft nach
  `down --rmi all`, das ein gepinntes Image gerade gelöscht hätte. Bleibt.
- **Labels der von `restore.sh` angelegten Volumes.** `docker run -v <name>:/dst` legt ein fehlendes Volume ohne
  Compose-Labels an (heute schon so); ob Compose dazu warnt, ist nicht geprüft. Nicht Teil der Zeile.
- **Ein `.env`-Merge** aus `.env.restored` in eine vorhandene `.env`: bleibt Handarbeit, die Doku sagt, welcher Wert
  stehen bleibt.

## Betroffene Komponenten & Dateien

- `scripts/install.sh`, `scripts/tests/install_test.sh` — T1–T4.
- `scripts/restore.sh`, `scripts/tests/restore_guard_test.sh` — T5, T6.
- `scripts/uninstall.sh`, `scripts/tests/uninstall_test.sh` — T7.
- `scripts/tests/backup_restore_test.sh` — T8 (Stack, `run.sh integration`).
- Doku: `docs/admin/installation.html` + EN (Codeblock Schnell-Install `:94-99` / EN `:72-77`, Satz zur Migration
  alter Installs `:214` / EN `:167`), `docs/admin/troubleshooting.html:38-46` + EN `:36-44`,
  `docs/admin/betrieb.html:103-104` + `docs/en/admin/operations.html:70-71`.

## Datenmodell / API / Migrationen

Keine API, keine Migration. Sichtbar: `install.sh` bricht in Fällen ab, in denen es heute weiterlief (T1), `--reset`
fragt auch mit `--yes` (T2), `install.sh` setzt `docker compose up --wait` voraus (T4); `restore.sh` legt auf einem
leeren Host die `.env` an (T6).

## Externe Integrationen

- **`docker compose config`** — gibt das aufgelöste Modell aus, die erste Zeile ist `name: <projekt>`; `--images
  <dienst>` gibt das Image eines Dienstes aus, `--volumes` die Volume-Schlüssel; `--env-file` wählt die Datei für die
  Interpolation (https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/: „Passing the
  `--env-file` argument overrides the default file path“). Probe Compose v5.5.1: `config --images postgres` →
  `postgres:17-alpine@sha256:979c4379…`; ohne `.env` warnt `config` je fehlender Variable und endet mit 0.
- **`docker compose up --wait`** — wie in `docs/features/update-rollback.md` (Doku-Zitat und Probe): ein Dienst ohne
  Healthcheck gilt, sobald er läuft.
- **postgres-Image** — https://raw.githubusercontent.com/docker-library/docs/master/postgres/README.md:
  `POSTGRES_PASSWORD` „must not be empty or undefined“; „the Docker specific variables will only have an effect if you
  start the container with a data directory that is empty“.

## Trade-offs & Alternativen

1. **Was ist eine bestehende Installation?** (a) Bootstrap: `.env` oder `docker-compose.yml` im Zielordner;
   Checkout und nach dem Bootstrap: Container des Compose-Projekts oder eines der Volumes `<projekt>_postgres-data`,
   `<projekt>_ca-pki` (Empfehlung). (b) Jede vorhandene `.env`: blockiert den Fall, den `install.sh:207` bewusst
   zulässt (eine vorab angelegte und angepasste `.env`), und die Fälle 4–7 von `install_test.sh`, die genau das
   prüfen. Die Zeile sagt „.env/Volumes“; (a) liest das als „eine `.env` mit Daten dahinter“. Nach dem Bootstrap greift
   (a) auch die Stolperfalle aus `docs/admin/troubleshooting.html:45` (zweiter Ordner gleichen Namens, altes Volume).
2. **Bestätigung für `--reset`.** Eingabe des Projektnamens am Terminal (Empfehlung; die Volumes stehen darüber).
   Alternative `--reset=<projekt>` für Automatisierung: nicht verlangt, kein Aufrufer im Repo nutzt `--reset`
   (`grep -rn -- '--reset' scripts .github`: nur `install.sh` selbst), YAGNI.
3. **Leerer Host für `restore.sh`.** Entscheidend ist das Datenbank-Volume, nicht die `.env`: Fehlt
   `<projekt>_postgres-data`, initialisiert postgres mit dem Passwort, das Compose ihm gibt. (a) Volume fehlt und
   keine `.env` → `env.sanitized` wird die `.env` (Empfehlung). (b) Volume fehlt, `.env` vorhanden → sie bleibt
   (postgres initialisiert mit ihrem Passwort, alles passt zusammen), `.env.restored` wie heute; die Doku sagt, dass
   `POSTGRES_PASSWORD` beim Übernehmen aus der aktuellen `.env` bleibt. (c) Volume vorhanden, aber
   `POSTGRES_PASSWORD` weder in der Umgebung noch in der `.env` → Abbruch vor jeder Änderung: `pg_restore` fiele
   sonst an der Anmeldung, nachdem `ca-pki`, `monitoring-data` und `./data` schon überschrieben sind. (d) sonst wie
   heute. `backup_restore_test.sh` liegt in (d): Volume vorhanden, Variablen exportiert (`:59-64`).
4. **Hilfs-Image.** Das gepinnte postgres-Image der Compose-Datei (Empfehlung, wie die Zeile): liegt auf jedem Host
   mit laufendem Stack schon vor, hat `sh`, `tar`, `find`. Alternative `docker compose run` der jeweils besitzenden
   Dienste: hängt an den Werkzeugen jedes Images (victoria ist Alpine, ca-issuer Debian) und an deren Nutzern.

## Risiken & Rollback

- Ein Betreiber, der `install.sh` absichtlich über eine laufende Installation fährt (etwa die Einmal-Migration vor
  0.34.0, `docs/admin/installation.html:214`), bekommt einen Abbruch mit dem Hinweis auf `update.sh`; die Doku
  streicht diesen Weg (der über `update.sh --ref v0.34.0` bleibt).
- `--reset` ohne Terminal ist nicht mehr möglich.
- `restore.sh` schreibt auf einem leeren Host eine `.env` mit Secrets: 0600, über eine Kopie daneben und `mv`.
- Rücknahme: Revert des PR; keine Daten- oder Formatänderung.

## Doku-Impact

DE + EN: Schnell-Install-Codeblock (`--reset`, erneuter Lauf), Satz zur Migration alter Installs, Troubleshooting
„Installation bricht ab“, Restore-Absatz in Betrieb. CHANGELOG unter `### Fixed` bzw. `### Changed` (`--reset`).

## Offene Fragen

1. **Erkennung (T1), nicht blockierend.** Die Zeile sagt „Abbruch bei vorhandener .env/Volumes“; T1 baut Trade-off 1
   (a): eine `.env` allein ist im Checkout keine Installation. Widerspricht Kevin, ändert sich nur die Bedingung in T1.
2. **Heavy.** `install.sh` und `uninstall.sh` fährt keine Suite gegen echte Container (`install_test.sh`,
   `uninstall_test.sh` sind hermetisch; kein `multibox.sh`-Flag und kein `box_*.sh` ruft sie auf). `restore.sh` fährt
   `backup_restore_test.sh` (linux-full) und T8. Empfehlung `linux-full`, kein `scenario`; Kevin entscheidet, ob er
   einen einmaligen VM-Lauf von `install.sh` (Install, zweiter Lauf → Abbruch, `--reset` mit Eingabe) will.
