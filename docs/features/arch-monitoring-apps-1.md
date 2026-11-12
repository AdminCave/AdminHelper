# arch-monitoring-apps-1 — Katalog-Module für selbst betriebene Anwendungen

Roadmap: R-1241, R-1242, R-1243 (FEAT, Kevin 2026-11-09, Monitoring-Konzept). Ledger: `tasks/arch-monitoring-apps-1.md`.
Baut auf dem Modul-Katalog aus R-1223 (`docs/features/arch-monitoring-module.md`) und den Fühlern aus R-1225 auf.

## Problem / Motivation
Der Katalog kennt heute `opnsense`, `port` und (auf `feature/kern-monitoring-23`) `frps`. Läuft auf einem Host eine
der verbreiteten selbst betriebenen Anwendungen, erkennt AdminHelper sie nicht als Dienst: ihre Ports werden
`port`-Instanzen mit einer Protokoll-Probe, ihre Health-Endpunkte fragt niemand. Die drei Zeilen verlangen Module
für:

- **R-1241 Apps:** Nextcloud, Zammad, GitLab, Vaultwarden/Bitwarden, Immich, Paperless-ngx, Frigate, 3CX, nativ und
  als Docker, über ihre Health-Endpunkte, mit Zugangsbremse (401/403 → `denied`, der Agent fragt erst nach neuen
  Zugangsdaten wieder).
- **R-1242 Schule/Zusammenarbeit:** Moodle (`checks.php`), BigBlueButton, Jitsi (exakte Pfade, nie
  `move-endpoints`), Matrix Synapse, Mattermost, Rocket.Chat, OnlyOffice, Collabora, Keycloak, OpenLDAP.
- **R-1243 Web-Apps:** WordPress (nie `core check-update`, nie `cron test`), Odoo, Gitea/Forgejo, BookStack,
  Wiki.js, Uptime Kuma, Home Assistant.

Leitplanken aus dem Konzept (Kevin 2026-11-09): der Dienst verliert nie spürbar Leistung; der Agent fragt nur
seinen eigenen Host; der Server schickt nur Parameter; Zugangsdaten bleiben auf dem Host; gefährliche Endpunkte
werden nie gerufen; ein Test-Objekt (der Dienst tut echte Arbeit) höchstens alle 15 min.

## Ziel & Nicht-Ziele
**Ziel:** je Anwendung ein Modul unter `apps/monitoring/app/catalog/modules/` (Daten, keine neue Logik im Server),
das sie erkennt (Container-Image, Unit, Prozess, Marker aus Pfad oder Paket, Port-Hinweise), als Instanz fasst
(Compose-Projekt bzw. Container, sonst Unit) und mit vorhandenen Fühlern prüft: Containerzustand, Unit, HTTP-Health
(GET/HEAD, nur die Pfade aus dem Katalog), TLS-Zertifikat, Dateialter. Jedes Modul hat einen Test mit
Inventar-Fixture (Erkennung, Instanz, gebundene Checks) und je Regel einen Probe-Bericht an der Schwelle. Ein
katalogweiter Test hält die Fallen fern (Pfadliste unten) und prüft die Regeln dieses Zugs für alle App-Module.

**Eine Agent-Änderung:** der HTTP-Fühler bekommt den optionalen Parameter `host` mit dem einzigen Wert `localhost`
(sendet dann `Host: localhost` statt `IP:Port`). Grund, am Quelltext belegt: Nextcloud beantwortet `status.php`
mit einem Host außerhalb von `trusted_domains` mit 400 (`lib/OC.php`, Zweig „Trusted domain error“, Code 15);
`localhost`, `127.0.0.1` und `[::1]` sind immer vertraut (`lib/private/Security/TrustedDomainHelper.php`,
„Always allow access from localhost“). Der Agent fragt einen Container über dessen Netzadresse
(`apps/agent/internal/probe/target_linux.go:58`), der Host-Header wäre also die Container-IP. Nur ein fester Wert,
kein freier Hostname: so verlässt kein vHost-Name des Admins den Server, und der Parameter bleibt eine Wahl aus dem
Katalog.

**Nicht-Ziele (YAGNI):**
- Keine Spezial-Collector (exec, Dateien parsen, Prüfsummen) in diesem Zug, nur Fühler, die der Agent schon hat.
  Betroffen: Moodle `admin/cli/checks.php` als Webserver-Benutzer, BigBlueButton `getMeetings` (Prüfsumme aus
  `securitySalt`), `*.fail`-Dateien und `bbb-conf --check`, OpenLDAP `contextCSN` über `ldapi:///`, WordPress-Version
  aus `version.php` und überfällige Cron-Events, `gitlab-ctl status`. Ob sie in diesen Zug gehören, ist die offene
  Frage an Kevin (T15, unten).
- Kein HTTP-Check für PHP-Anwendungen hinter einem allgemeinen Webserver auf dem Host (Nextcloud, Moodle,
  WordPress, BookStack nativ): eine Anfrage an `127.0.0.1` trifft den Default-vHost von nginx/Apache, nicht sicher
  die Anwendung. Sie bekommen, was ohne vHost geht (Units, Zertifikat, Dateialter); HTTP folgt, sobald R-1231 die
  vHosts kennt (neue Zeile, am Gate angelegt). Docker-Varianten und Anwendungen mit eigenem Server-Prozess
  (Gitea, Synapse, Mattermost, Keycloak, Jitsi, Odoo, Zammad-Railsserver …) fragen ihren Container bzw. ihre Unit
  direkt.
- Keine Platzhalter-Felder je Kamera, Queue oder Raum: Feldnamen sind fest (`FIELD_PATTERN`), dynamische Schlüssel
  (Frigate-Kameras, Immich-Queues) gehen nur als feste Aggregate, sonst als Grenze in die Doku.
- Keine zentralen Checks (Login-Seite von außen, Föderation, TURN): eigene Zeilen (R-1224 und Folgende).
- Kein UniFi (R-1244), kein Elasticsearch-Modul für Zammad (eigene Datenbank-Zeile).

## Betroffene Komponenten & Dateien
| Komponente | Dateien |
|---|---|
| Agent | `apps/agent/internal/probe/sensor_http.go` (`knownParams(p, "path", "method")`, `:201`; Request in `fetch`, `:241`), `apps/agent/internal/probe/sensor_net_test.go` |
| Monitoring-Katalog | `apps/monitoring/app/catalog/sensors.py` (`HttpParams`, `:139`), neu je Modul `apps/monitoring/app/catalog/modules/<id>.py` (26 Dateien, SPDX-Header; Dateiname mit `_` statt `-`, `threecx.py` für `3cx`) |
| Monitoring-Tests | `apps/monitoring/tests/test_catalog_sensors.py`, neu `tests/test_catalog_apps.py` (katalogweite Regeln), neu je Gruppe `tests/test_catalog_<gruppe>.py` |
| Doku | `docs/admin/monitoring.html` (Abschnitt „Module und Erkennung“, neue Unterabschnitte je Gruppe), `docs/developer/monitoring.html` (HTTP-Parameter `host`), beide EN, `changelog.d/arch-monitoring-apps-1.md` |

Module (Erkennung, Endpunkte und Felder sind Annahmen aus dem Konzept §6.7/§6.10; jede Task verifiziert sie in der
offiziellen Doku bzw. im Quelltext der Anwendung und nennt die Quelle im Docstring des Moduls; was sich nicht
belegen lässt, fährt nicht mit oder steht als „nicht verifiziert“ in der Task):

| Zeile | Modul-IDs | Checks (Entwurf) | Zugang |
|---|---|---|---|
| R-1241 | `nextcloud` | Container; `status.php` mit `host: localhost` (`maintenance`, `needsDbUpgrade`); Snap-Unit; nativ nur Units/Zertifikat | `serverinfo` mit `NC-Token` (Header) optional |
| R-1241 | `zammad` | Container bzw. Units `zammad-*`; `health_check` am Railsserver | Token (Form verifizieren: Query-Token geht nicht, nur Header/Bearer) |
| R-1241 | `gitlab` | Container bzw. Unit `gitlab-runsvdir`; `/-/readiness?all=1`, `/-/liveness`; Backup-Verzeichnis-Alter (nativ) | Monitoring-Allowlist (Docker: Bridge-Adresse eintragen, sonst 404, Doku) |
| R-1241 | `vaultwarden`, `bitwarden` | `/alive` bzw. `/api/alive` (nie `/admin`), Container | – |
| R-1241 | `immich` | Compose-Projekt: Container je Dienst, `/api/server/ping` | Queue-Zähler mit Key `queue.read`, falls als festes Aggregat lesbar |
| R-1241 | `paperless` | Container, `/api/status/` (15 min) | Nutzer mit `paperless.view_system_monitoring` |
| R-1241 | `frigate` | Container, `/api/version`, `/api/stats` (Port 5000, nie Login auf 8971) | – |
| R-1241 | `3cx` | Units (Namen verifizieren), Zertifikat, Backup-Alter | – |
| R-1242 | `moodle` | Marker/Pakete, Units ohne HTTP (siehe oben); `checks.php` → T15 | – |
| R-1242 | `bigbluebutton` | Units, `bbb-web` `/bigbluebutton/api` (Status 200) direkt am Dienst | – |
| R-1242 | `jitsi` | JVB `/about/health` (8080), Jicofo `/about/health` (8888), `colibri/stats` `stress_level` (nie `move-endpoints`) | – |
| R-1242 | `synapse` | `/health` (8008) | – |
| R-1242 | `mattermost`, `rocketchat` | `/api/v4/system/ping` (ohne `get_server_status`) bzw. `/livez` | – |
| R-1242 | `onlyoffice`, `collabora` | `/healthcheck` (Test-Objekt, 15 min, nur GET) bzw. `GET /` | – |
| R-1242 | `keycloak`, `openldap` | `/health/ready` (9000, nur mit `health-enabled`); `slapd`-Unit, LDAP-Protokoll, Zertifikat | – |
| R-1243 | `wordpress`, `odoo` | Container, `/wp-json/` (nur Docker); `/web/health` (8069) | – |
| R-1243 | `gitea`, `bookstack`, `wikijs` | `/api/healthz`; `/status` (Test-Objekt, legt eine Session an); `/healthz` | – |
| R-1243 | `uptime-kuma`, `home-assistant` | `/api/entry-page` (nie `/api/push/…`); `GET /` (nie mit Token, 401 erzeugt Meldungen) | – |

## Datenmodell / API / Migrationen
Keine Migration, keine neue Route, kein Schema der Check-API. Neu ist nur der Fühler-Parameter `host`
(`Literal["localhost"]`, fehlt = wie heute): Katalog (`HttpParams`) und Agent prüfen ihn beide. Vertrags-Drift
Agent ↔ Katalog: ein Agent vor diesem Release lehnt den Parameter ab (`knownParams`), der Check steht dort auf
`unknown` mit „invalid parameters“, bis der Agent aktualisiert ist; die Doku nennt die Mindestversion. Die
Katalog-Version (SHA-256 über alle Module) ändert sich mit jedem Modul; übernommene Instanzen betrifft das nicht
(neue Module erzeugen nur neue Funde).

## Externe Integrationen
Je Modul die offizielle Doku bzw. der Quelltext des Projekts (in der Task per WebFetch gelesen, Link im Docstring).
Bereits belegt: Nextcloud `status.php` und Trusted-Domain-Prüfung (github.com/nextcloud/server, `status.php`,
`lib/OC.php`, `lib/private/Security/TrustedDomainHelper.php`, Stand master 2026-11-12). Alles andere aus der
Tabelle ist bis zur Task **nicht verifiziert**.

## Trade-offs & Alternativen
- **Host-Header:** (a) fester Wert `localhost` (Empfehlung, gewählt): minimal, kein Name verlässt den Server;
  Grenze: eine Anwendung, die `localhost` ablehnt (Django mit eigener `ALLOWED_HOSTS`-Liste), bleibt bei 400 und
  die Doku sagt es. (b) freier Hostname je Instanz: bräuchte eine Eingabe des Admins und ein Feld im Fund (API),
  erst sinnvoll mit den vHosts aus R-1231. (c) veröffentlichten Port auf `127.0.0.1` fragen: nicht jeder Container
  veröffentlicht, und der Host-Header wäre `127.0.0.1:<Port>` (bei Nextcloud vertraut, sonst gleich (a)).
- **Ein Modul je Anwendung statt eines Moduls „Web-App“:** eigene Erkennung, eigene Karte, Checks einzeln
  abschaltbar; mehr Dateien, aber jede klein und einzeln testbar.
- **Gruppen-Tasks (2–3 Module je Task):** hält den Zug unter 15 Tasks; jede Task bleibt eine Komponente und ein
  Verify.

## Risiken & Rollback
- Ein falscher Pfad oder eine falsche Regel wäre ein Dauer-Alarm nach dem Übernehmen: jede Task belegt Pfad, Port
  und Antwortform an der Quelle und testet jede Regel an ihrer Schwelle.
- Falle getroffen (Endpunkt mit Nebenwirkung): der katalogweite Test lehnt bekannte Fallen-Pfade ab
  (`move-endpoints`, `/admin`, `cron.php`, `wp-cron.php`, `/api/push/`, `/internal/cluster/inactive`,
  `get_server_status`, Frigate-Login) und verlangt `test_object` für die bekannten Test-Objekt-Pfade.
- Lastschonung: Intervalle 5 min für billige Health-Pfade, 15 min für teure und Test-Objekte, `timeout_s` klein.
- Erkennung zu breit (ein generisches Image oder eine Unit wie `nginx` würde fremde Dienste beanspruchen): nur
  anwendungseigene Images, Units und Pakete; der katalogweite Test verbietet eine Liste generischer Namen.
- Rollback: jedes Modul ist eine Datei; ein Revert entfernt es, übernommene Checks bleiben stehen, wie R-1223 es für
  entfernte Module vorsieht. Der `host`-Parameter ist optional, ein Revert der Agent-Task macht Checks mit `host`
  wieder `unknown`.

## Doku-Impact
`docs/admin/monitoring.html` + EN: „Module und Erkennung“ nennt die neuen Module, je Gruppe ein Unterabschnitt mit
Erkennung, Checks, Zugangsdaten (Schlüssel für `monitor credential set`), Grenzen (nativ ohne HTTP, Allowlist bei
GitLab, `health-enabled` bei Keycloak, Mindestversion des Agents für `host`). `docs/developer/monitoring.html` + EN:
Parameter `host` des HTTP-Fühlers. `changelog.d/arch-monitoring-apps-1.md` (`### Added`).

## Offene Fragen
1. **Spezial-Collector (Kevin, T15 `[?]`):** Moodle `checks.php` (genannt in R-1242), BBB `getMeetings`/`*.fail`/
   `bbb-conf --check`, OpenLDAP `contextCSN`, WordPress-Version und -Cron brauchen Agent-Collector mit exec bzw.
   Datei- und LDAP-Zugriff (Allowlist, Sicherheitsprüfung, Agent-Release). Empfehlung: eigene Arch-Zeile nach
   diesem Zug, weil sie eine andere Risikoklasse sind (Code der Anwendung als deren Benutzer ausführen) und den Zug
   über 15 Tasks höben; dieser Zug liefert die Module ohne sie. Alternative: in diesem Zug, dann fährt ein zweiter
   Zug den Rest der Module.
