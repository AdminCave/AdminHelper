<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Update: Rollback mit Health-Prüfung und Migrationsstand, Image-Pins nach dem Pull, Healthchecks für Gateway, Victoria und Monitoring

Stand des Codes: `origin/main@237b450a`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/update-rollback.md`. Roadmap R-0612, R-0613, R-0614 (update.sh- und Compose-Teil; den install.sh-Teil von
R-0614 trägt `tasks/install-restore.md` T4 auf `feature/install-restore`, zusammen mit R-0665 und R-0668).

**Hängt ab von** (vor dem Bau gemergt; Überschneidungen je Funktion):
- `feature/compose-hardening`: `docker-compose.yml` (T1 setzt `security_opt`/`pids_limit` direkt nach
  `restart: unless-stopped` in gateway, monitoring, victoria; T2 Capabilities des gateway; T6 Secret) — hier kommen
  die `healthcheck:`-Blöcke derselben Dienste dazu; `apps/gateway/nginx.conf` (T3: Zonen im `http`-Block, Grenzen in
  :8444/:8445) — hier ein zusätzlicher `server`-Block; `apps/server/tests/test_gateway_container.py` (legt T2 an) —
  T1 hier ergänzt ihn; `scripts/tests/integration_stack_test.sh` (T8, T13 neue Schritte) — T3 hier dahinter.
- `feature/ops-install-hardening`: `scripts/update.sh` `check_env_templates` (T5) — hier unberührt, nur der Preflight
  danach (`:169-174`); `scripts/tests/update_test.sh` (T5 erweitert Test 32) — hier Stub (`:60-85`) und neue Fälle;
  `docs/admin/installation.html:213` (T5 hängt einen Satz an) — T4 und T6 hier schreiben denselben Absatz um.
- `feature/ops-scripts-hardening`: `scripts/backup.sh` schreibt weiter `[backup] OK -> <archiv>` (dort `:141`) —
  T6 hier liest diese Zeile.

## Problem / Motivation

1. **Erfolg heißt „der Server nimmt TCP an“ (R-0614).** Das Update startet mit `docker compose up -d`
   (`scripts/update.sh:626`) und wartet nur auf einen TCP-Connect an `server:8080` (`wait_for_server`, `:346-356`,
   `:628-632`); ebenso `--redeploy` (`:367-368`). Gateway (`docker-compose.yml:178-210`) und victoria (`:406-421`)
   haben keinen Healthcheck; der von monitoring (`:392-399`) ist ein TCP-Connect, der Kommentar darüber verspricht,
   ein hängender Prozess werde unhealthy. Ein Update, nach dem gateway, ca-issuer, frps oder monitoring in einer
   Restart-Schleife hängen, meldet „Fertig“ (`:629`). Probe (Docker 29.8.1, Compose v5.5.1, zwei Wegwerf-Projekte aus
   `alpine:3.22`, je ein Dienst, der nach 2 s mit 1 endet, `restart: unless-stopped`): `up -d --wait` endet **ohne**
   Healthcheck mit 0 und meldet den Dienst „Healthy“, sobald er läuft; **mit** Healthcheck endet es nach 6 s mit 1
   („container … is unhealthy“). `--wait` erkennt also nur Dienste mit Healthcheck.

2. **Der Rollback nach dem Start prüft nichts und übersieht Migrationen (R-0612).** `rollback_after_deploy`
   (`update.sh:588-618`) spielt Snapshot und Image-Pins zurück, startet mit `docker compose up -d` (`:613`) und meldet
   „zurueckgerollt“ (`:617`), ohne zu prüfen, ob der alte Stand läuft. Hat der neue Server beim Start schon
   `alembic upgrade head` gefahren (`apps/server/docker-entrypoint.sh:43-45`; monitoring
   `apps/monitoring/docker-entrypoint.sh:57-59`), steht in `alembic_version` eine Revision, die die alten Images nicht
   kennen; ihr `alembic upgrade head` bricht ab, der Entrypoint endet (`set -e`), die Container starten im Kreis
   (Code-Lesung, nicht gefahren). Beide `env.py` fahren alle Migrationen in **einer** Transaktion
   (`apps/server/alembic/env.py:68`, `:99`; `apps/monitoring/alembic/env.py:53`, `:81`; kein
   `transaction_per_migration`): Eine gescheiterte Migration lässt die Revision stehen, eine gelungene ändert sie.

3. **Pins vor dem Pull, kein Rollback bei Abbruch (R-0613).** `migrate_env` pinnt die Images auf das Ziel
   (`update.sh:565-570`), bevor `docker compose pull` läuft (`:622`). Das Skript hat nur einen EXIT-Trap (`:415`), der
   `$TMP` samt `env.prev` (`:459`) löscht. Probe (bash 5.2.37): HUP, TERM oder INT an die Prozessgruppe eines
   Skripts mit nur einem EXIT-Trap beenden es, der EXIT-Trap läuft, der Rest nicht. Ein SSH-Abbruch während des Pulls
   (Minuten) hinterlässt neue Laufzeit-Dateien und neue Pins neben den alten Containern; der nächste Lauf liest die
   Version aus dem Pin (`installed_version`, `:205-212`) und meldet „Bereits auf der neuesten Version“ (`:385-387`).

## Ziel & Nicht-Ziele

Ziel:
- gateway, victoria und monitoring haben einen Healthcheck, der einen hängenden oder abstürzenden Dienst erkennt
  (T1, T2); der laufende Stack belegt es (T3).
- `update.sh` startet Update, Re-Deploy und Rollback mit `docker compose up -d --wait`; „zurueckgerollt“ steht nur,
  wenn der alte Stand gesund läuft, sonst „UNVOLLSTAENDIG“ (T4).
- Die Pins wandern erst nach einem erfolgreichen Pull in die `.env`; INT, TERM und HUP nach dem Snapshot rollen
  zurück wie ein Fehler an derselben Stelle (T5).
- Hat die neue Version die Datenbank schon migriert, startet der Rollback die alten Images nicht auf ihr (T6, nach
  Kevins Antwort, Offene Frage 1).

Nicht-Ziele:
- **scheduler ohne Healthcheck.** Er hat keinen Port; ein Healthcheck könnte nur prüfen, ob der Prozess lebt. Eine
  Restart-Schleife des schedulers erkennt `--wait` daher nicht (Probe oben); den Migrationsfall decken server und
  monitoring ab.
- **HTTP-Health-Route im Server.** Der TCP-Healthcheck des servers (`docker-compose.yml:118-126`) greift erst nach
  `alembic upgrade head`; er bleibt.
- **SIGKILL, Stromausfall.** Kein Marker für einen halben Lauf: Snapshot und Backup bleiben unter `backups/`; T5
  verkürzt das Fenster mit neuen Pins auf die Sekunden zwischen Pull und Start.
- **Automatischer Daten-Restore** ohne Kevins Antwort (Offene Frage 1); `--no-rollback` bleibt, wie es ist.
- **install.sh** (Bestandserkennung, `--reset`, `up --wait` beim Install) und **restore.sh**: `tasks/install-restore.md`.

## Betroffene Komponenten & Dateien

- `apps/gateway/nginx.conf` — ein `server` auf `127.0.0.1:8081` nur für den Healthcheck (T1).
- `docker-compose.yml` — `healthcheck:` für gateway (T1), victoria, monitoring (T2).
- `apps/server/tests/test_gateway_container.py` (aus compose-hardening T2) — T1; neu
  `apps/server/tests/test_compose_healthchecks.py` — T2. Beide in der Komponente `server` wie die Compose-Tests von
  compose-hardening.
- `scripts/tests/integration_stack_test.sh` — Stack-Schritt (T3).
- `scripts/update.sh`, `scripts/tests/update_test.sh` — T4, T5, T6.
- `docs/admin/installation.html`, `docs/en/admin/installation.html` — Voraussetzungen (`:84`, EN `:39`) und Absatz
  zum Update (`:213`, EN `:166`).

## Datenmodell / API / Migrationen

Keine API, keine Alembic-Migration, kein Vertrag Server ↔ Web ↔ Desktop ↔ Agent. Der neue nginx-Listener bindet nur
`127.0.0.1` im Container und ist nicht veröffentlicht. `update.sh` setzt neu voraus, dass `docker compose up` die
Flags `--wait` und `--wait-timeout` kennt (Preflight, T4).

## Externe Integrationen

- **Compose `up --wait`** — https://docs.docker.com/reference/cli/docker/compose/up/: „--wait: Wait for services to
  be running|healthy. Implies detached mode.“ · „--wait-timeout: Maximum duration in seconds to wait for the project
  to be running|healthy“. Was `--wait` mit einem Dienst ohne Healthcheck oder einem neu startenden Container tut, sagt
  die Seite nicht; die Probe oben belegt es für Compose v5.5.1. Ab welcher Compose-Version es `--wait` und
  `--wait-timeout` gibt: **nicht verifiziert**; T4 liest es in den Release-Notes von `docker/compose` nach und
  schreibt die Version in die Voraussetzungen.
- **Healthcheck** — https://docs.docker.com/reference/compose-file/services/#healthcheck (`test` als Liste mit
  `CMD`, `interval`, `timeout`, `retries`, `start_period`).
- **Interpolation** — https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/:
  „1. Variables from your shell environment“ vor „3. … variables from an `.env` file in the project directory“. T5
  zieht die Ziel-Images mit `SERVER_IMAGE=… docker compose pull`, ohne die `.env` anzufassen.
- **VictoriaMetrics `/health`** — https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/
  („the server returns non-OK responses from /health page“ während `-http.shutdownDelay`). Probe mit dem gepinnten
  Image (`v1.144.0@sha256:dc030542…`, Alpine 3.23): `wget -q -O - http://127.0.0.1:8428/health` → `OK`, Exit 0;
  `wget` ist busybox, `curl` fehlt.
- **nginx** — `listen` (http://nginx.org/en/docs/http/ngx_http_core_module.html#listen), `return`
  (http://nginx.org/en/docs/http/ngx_http_rewrite_module.html#return). Im gepinnten Basis-Image (`nginx:1.29-alpine`,
  `apps/gateway/Dockerfile:1`) gibt es `wget` und `curl` (Probe).
- **bash-Signale** — https://www.gnu.org/software/bash/manual/html_node/Signals.html: Wartet bash auf einen
  Vordergrundbefehl, führt es einen Trap erst aus, wenn der Befehl endet; „The shell exits by default upon receipt of
  a SIGHUP.“ Ein SSH-Abbruch schickt HUP an die Vordergrund-Prozessgruppe, also auch an `docker compose pull`.
- **postgres-Image** — https://raw.githubusercontent.com/docker-library/docs/master/postgres/README.md: „`trust`
  authentication for Unix socket connections made inside the container“ — T6 liest `alembic_version` per
  `docker compose exec -T postgres psql` ohne Passwort.

## Trade-offs & Alternativen

1. **Healthcheck des Gateways.** (a) Eigener HTTP-Listener auf `127.0.0.1:8081` mit `location = /healthz`
   (Empfehlung): eine Antwort heißt, nginx hat die ganze Konfiguration samt der TLS-Listener geladen (nginx bindet
   beim Start alle Listener oder keinen), ohne TLS, ohne Client-Zertifikat, ohne Log-Rauschen (`access_log off`).
   (b) TLS-Anfrage an `:8445` mit `--no-check-certificate`: Antwort 404 (`nginx.conf:196-198`), `wget` endet dann mit
   Fehler, man müsste den Statuscode aus `-S` parsen. (c) Prozess-Check: erkennt keinen hängenden nginx.
2. **Warten.** `docker compose up -d --wait` (Empfehlung): Compose kennt die Dienste und ihre Healthchecks, ein Aufruf.
   Alternative: eigene Schleife über `docker inspect … .State.Health.Status` je Dienst — mehr Code, dieselbe Aussage.
   Grenze beider: Dienste ohne Healthcheck gelten, sobald sie laufen.
3. **Ein Aufruf statt zwei.** `up -d --wait` ersetzt `up -d` + `wait_for_server`; die zwei Meldungen „Stack-Neustart
   fehlgeschlagen“ und „Server nicht rechtzeitig bereit“ werden eine. Welcher Container scheiterte, sagt die Ausgabe
   von Compose, die sichtbar bleibt.
4. **Pins und Abbruch.** (a) Pull mit den Ziel-Images aus der Umgebung, Pins danach, dazu Traps für INT/TERM/HUP
   (Empfehlung). (b) Marker-Datei für „Update läuft“, die der nächste Lauf auswertet: deckt auch SIGKILL, braucht aber
   Zustand über Läufe hinweg und eine eigene Aufräum-Logik (YAGNI). (c) HUP ignorieren und weiterlaufen (`nohup`):
   der Betreiber sieht das Ergebnis nicht, und die Zeile verlangt den Rollback.
5. **Ausgabe nach HUP.** Das Terminal ist weg; die erste Ausgabe der Rücknahme kann scheitern und unter `set -e`
   die Rücknahme abbrechen. Deshalb leitet der Handler nach HUP stdout/stderr in `backups/update-<UTC-Zeit>.log`
   (0600) um; nach INT/TERM bleibt die Ausgabe am Terminal.
6. **Rollback bei migrierter Datenbank** — Offene Frage 1.

## Risiken & Rollback

- Ein zu strenger Healthcheck lässt ein Update zurückrollen, obwohl der Stack liefe: `start_period` großzügig
  (gateway wartet bis 120 s auf seine Zertifikate, `apps/gateway/docker-entrypoint.sh:12-25`), victoria lädt große
  Datenbestände langsam.
- Eine alte Compose-Version ohne `--wait`/`--wait-timeout` bricht das Update ab — vor jeder Änderung, mit Meldung.
- Signal-Handler, die selbst unterbrochen werden: der Handler ignoriert INT/TERM/HUP während der Rücknahme; die Tests
  schicken echte Signale an die Prozessgruppe.
- Rücknahme dieses Vorhabens: Revert des PR; die Healthchecks sind additiv, `update.sh` kehrt zum alten Ablauf zurück.

## Doku-Impact

`docs/admin/installation.html` + `docs/en/admin/installation.html`: Voraussetzung `docker compose up --wait` (`:84`,
EN `:39`); Absatz zum Update (`:213`, EN `:166`): Healthcheck aller Dienste mit Healthcheck, „zurückgerollt“ nur bei
gesundem altem Stand, Abbruch per Signal, Rollback bei migrierter Datenbank (T6). CHANGELOG unter `### Fixed`.

## Offene Fragen

1. **Rollback, wenn die neue Version die Datenbank schon migriert hat (T6, Kevins Bereich: Datenmigration,
   Restrisiko).**
   - **A — nur ohne Migration automatisch (Empfehlung).** `update.sh` liest vor dem Start die Revisionen in
     `alembic_version` beider Datenbanken und nach einem Fehler erneut. Gleich → Dateien und Pins zurück, Start mit
     `--wait`, „zurueckgerollt“ nur bei Erfolg. Verändert oder nicht lesbar → Dateien und Pins zurück,
     `docker compose stop`, kein Start der alten Images; die Meldung nennt `./scripts/restore.sh <Backup dieses
     Laufs>` (zurück auf den alten Stand) und `./scripts/update.sh --ref <Ziel>` (erneut vorwärts). Trade-off: kein
     automatischer Datenverlust; bei einer Migration steht der Stack, bis der Betreiber einen der zwei Befehle fährt.
   - **B — Backup dieses Laufs automatisch einspielen.** Wie A, aber bei veränderter Revision fährt `update.sh`
     selbst `restore.sh <Archiv> --yes` und prüft danach die Health. Trade-off: kein Handgriff, aber alles, was seit
     dem Backup geschrieben wurde (Minuten: Agent-Reports, Logins, Audit), geht ohne Rückfrage verloren; `restore.sh`
     ist destruktiv und lief nie unbeaufsichtigt in `update.sh`; mit `--skip-backup` fällt es auf A zurück.
   - **C — kein Rollback nach dem Start.** Jeder Fehler nach `up` lässt den Stand stehen und nennt beide Wege.
     Trade-off: am wenigsten Code, aber auch ein Update ohne Migration (die meisten Patch-Releases) rollt nicht mehr
     von selbst zurück.
   Empfehlung A: Sie rollt zurück, wo es gefahrlos geht — eine gescheiterte Migration lässt die Revision stehen
   (eine Transaktion, Problem 2) —, und überlässt den Datenverlust dem Betreiber. Betroffen: nur T6; T4 und T5 sind
   davon unabhängig.
2. **Heavy.** Kein `multibox.sh`-Flag und kein `box_*.sh` ruft `update.sh` auf (`grep -n 'update\.sh'
   scripts/tests/multibox.sh scripts/tests/box_*.sh`: kein Treffer); ein `scenario`-Lauf prüft dieses Vorhaben nicht.
   `upgrade_path_test.sh` (Schritt 4, `:206-293`) startet die `update.sh` dieses Stands nur bis zur Übergabe an die des
   Release, mit `--skip-backup --no-rollback`. Den Deploy- und Rollback-Pfad gegen echte Container fährt also keine
   Suite; belegt wird er durch `update_test.sh` (echte Signale, Docker-Stub) und T3 (echte Healthchecks). Empfehlung:
   `linux-full`, kein `scenario`; Kevin entscheidet, ob er einen einmaligen VM-Lauf des Rollbacks will.
