# Monitoring: Katalog-Module für selbst betriebene Anwendungen — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-apps-1 · Review: pro Task
Spec: docs/features/arch-monitoring-apps-1.md (Roadmap R-1241, R-1242, R-1243)
Heavy: linux-full — apps/agent (HTTP-Fühler, Parameter `host`); die Module sind Katalog-Daten mit Unit-Tests in der PR-CI; geht in den nächtlichen Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für jede Modul-Task gilt: Erkennung (Images, Units, Pakete, Ports), Pfade, Antwortform und Felder vorher in der
offiziellen Doku bzw. im Quelltext des Projekts belegen (WebFetch), Quelle im Docstring des Moduls; Unbelegtes fährt
nicht mit oder steht als „nicht verifiziert“ in der Task. Neue Dateien mit SPDX-Header (`reuse annotate`). Je Modul
ein Test `tests/test_catalog_<id>.py` nach dem Muster von `tests/test_catalog_opnsense.py`: Katalog lädt fehlerfrei,
Inventar-Fixture (Docker und, wo vorgesehen, nativ) ergibt die erwartete Instanz und keine `port`-Instanz für die
beanspruchten Ports, `probe_config` bindet die Checks (nicht bindbare werden übersprungen, mit Grund), jede Regel
feuert an ihrer Schwelle und nicht darunter (`ProbeChecker().evaluate`), Karte wie erwartet.

### T1 — Agent: HTTP-Fühler sendet auf Wunsch `Host: localhost` (R-1241)  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_net_test.go, apps/agent/internal/probe/sensor_unixsocket.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @cd482a5c8 2026-11-12T12:58:33+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T1.verdict.json)
Änderung: optionaler Parameter `host` des Fühlers `http`, einziger erlaubter Wert `localhost` (`knownParams` und
`choiceParam`); gesetzt, trägt die Anfrage `Host: localhost`, sonst bleibt der Host-Header `IP:Port`. Ziel-Wächter,
Weiterleitungen (`sameTarget`) und TLS unverändert. Tests: Server prüft den empfangenen Host-Header mit und ohne
Parameter; ein anderer Wert (`example.org`, leer, `localhost:80`) ist `ErrInvalid`; Weiterleitung auf ein fremdes
Ziel bleibt abgewiesen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T14

### T2 — Katalog: Parameter `host` und katalogweite Regeln für App-Module (R-1241, R-1242, R-1243)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_apps.py, apps/monitoring/tests/test_check_configs.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @60e14420b 2026-11-12T13:05:23+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T2.verdict.json)
Änderung: `HttpParams.host: Literal["localhost"] | None` (fehlt = wie heute; Defaults füllen ihn nicht ins JSON, damit
die Katalog-Version bestehender Module gleich bleibt). Neuer Test `test_catalog_apps.py` (SPDX) über den ganzen
Katalog: kein HTTP-Pfad trifft eine Falle (`move-endpoints`, `/admin`, `cron.php`, `wp-cron.php`, `/api/push/`,
`/internal/cluster/inactive`, `get_server_status`, `/login`), bekannte Test-Objekt-Pfade (`/healthcheck`, `/status`
von BookStack) tragen `test_object`; kein HTTP-Check zielt auf `loopback` (vHost-Regel der Spec); `detect` nennt
keine generischen Namen (`nginx`, `apache2`, `httpd`, `php-fpm`, `postgres`, `redis`, `mariadb`, `node`, `python3`,
`java`). Gegenprobe je Regel mit einem Modul, das sie bricht.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_catalog_apps.py tests/test_catalog.py tests/test_check_configs.py
Doku: → T14

### T3 — R-1241: Module Nextcloud, Paperless-ngx, Immich  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/nextcloud.py, apps/monitoring/app/catalog/modules/paperless.py, apps/monitoring/app/catalog/modules/immich.py, apps/monitoring/tests/test_catalog_nextcloud.py, apps/monitoring/tests/test_catalog_paperless.py, apps/monitoring/tests/test_catalog_immich.py, apps/monitoring/app/discovery.py, apps/monitoring/app/module_sync.py, apps/monitoring/tests/test_catalog_apps.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_module_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @703327a3c 2026-11-12T13:42:57+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T3.verdict.json)
Änderung: Nextcloud: Docker (Image `nextcloud`, AIO) und Snap; `status.php` mit `host: localhost`, Regeln auf
`maintenance` und `needsDbUpgrade`; nativ hinter Webserver nur, was ohne vHost geht; `serverinfo` mit Header
`NC-Token` nur, wenn als festes Feld belegt. Paperless-ngx: Container, `/api/status/` (15 min, Zugang Nutzer mit
`paperless.view_system_monitoring`). Immich: Compose-Projekt, Container je Dienst, `/api/server/ping`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_nextcloud.py tests/test_catalog_paperless.py tests/test_catalog_immich.py tests/test_catalog_apps.py tests/test_catalog.py tests/test_discovery_match.py tests/test_module_sync.py
Doku: → T14
Abhängt von: T2

### T4 — R-1241: Module Zammad und GitLab  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/zammad.py, apps/monitoring/app/catalog/modules/gitlab.py, apps/monitoring/tests/test_catalog_zammad.py, apps/monitoring/tests/test_catalog_gitlab.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @fe49ddffc 2026-11-12T14:02:25+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T4.verdict.json)
Änderung: Zammad: Docker (Compose) und Paket `zammad` (Units), `health_check` am Railsserver, Zugang nur in einer
Form, die der Agent übergeben kann (Header/Bearer; ein Query-Token nicht). GitLab: Docker (`gitlab/gitlab-ce`,
`-ee`) und Paket (Unit `gitlab-runsvdir`), `/-/readiness?all=1` und `/-/liveness`, Alter des Backup-Verzeichnisses
(nativ); Grenze Monitoring-Allowlist (Docker: Bridge-Adresse) in den Docstring für die Doku.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_zammad.py tests/test_catalog_gitlab.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T5 — R-1241: Module Vaultwarden, Bitwarden, Frigate, 3CX  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/vaultwarden.py, apps/monitoring/app/catalog/modules/bitwarden.py, apps/monitoring/app/catalog/modules/frigate.py, apps/monitoring/app/catalog/modules/threecx.py, apps/monitoring/tests/test_catalog_vaultwarden.py, apps/monitoring/tests/test_catalog_bitwarden.py, apps/monitoring/tests/test_catalog_frigate.py, apps/monitoring/tests/test_catalog_threecx.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6a82fb96a 2026-11-12T14:30:16+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T5.verdict.json)
Änderung: Vaultwarden `/alive` (nie `/admin`); Bitwarden `/api/alive` (nicht `/alive`); Frigate Container,
`/api/version` und `/api/stats` auf Port 5000 (nie der Login auf 8971), nur feste Felder; 3CX Units (Namen aus der
3CX-Doku, sonst „nicht verifiziert“ und ohne Unit-Check), Zertifikat, Backup-Alter. Acht Dateien: vier kleine Module
mit je einem Test.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_vaultwarden.py tests/test_catalog_bitwarden.py tests/test_catalog_frigate.py tests/test_catalog_threecx.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T6 — R-1242: Module Moodle und BigBlueButton (ohne Spezial-Collector)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/moodle.py, apps/monitoring/app/catalog/modules/bigbluebutton.py, apps/monitoring/tests/test_catalog_moodle.py, apps/monitoring/tests/test_catalog_bigbluebutton.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f301f150e 2026-11-12T14:44:49+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T6.verdict.json)
Änderung: Moodle: Erkennung über Marker/Pakete bzw. Container, was ohne vHost und ohne exec geht (Container,
Dateialter von moodledata, falls belegt); nie `/admin/cron.php`. BigBlueButton: Pakete/Units, `bbb-web`
`/bigbluebutton/api` direkt an der Unit (Status 200), Zertifikat. `checks.php`, `getMeetings`, `*.fail`,
`bbb-conf --check` → T15.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_moodle.py tests/test_catalog_bigbluebutton.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T7 — R-1242: Module Jitsi Meet und Matrix Synapse  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/jitsi.py, apps/monitoring/app/catalog/modules/synapse.py, apps/monitoring/tests/test_catalog_jitsi.py, apps/monitoring/tests/test_catalog_synapse.py, apps/monitoring/app/catalog/modules/jitsi_videobridge.py, apps/monitoring/app/catalog/modules/jitsi_jicofo.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6110e641c 2026-11-12T15:00:35+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T7.verdict.json)
Änderung: Jitsi: Docker (`jitsi/jvb`, `jitsi/jicofo` …) und Pakete; JVB `/about/health` (8080), Jicofo
`/about/health` (8888), `colibri/stats` mit `stress_level` > 0,8 → warning, nur exakte Pfade (nie
`move-endpoints`). Synapse: Docker und Paket, `/health` (8008).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_jitsi.py tests/test_catalog_synapse.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T8 — R-1242: Module Mattermost und Rocket.Chat  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/mattermost.py, apps/monitoring/app/catalog/modules/rocketchat.py, apps/monitoring/tests/test_catalog_mattermost.py, apps/monitoring/tests/test_catalog_rocketchat.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @16c828890 2026-11-12T15:19:35+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T8.verdict.json)
Änderung: Mattermost `/api/v4/system/ping` ohne `get_server_status` (der tiefe Ping schreibt eine Testdatei);
Rocket.Chat `/livez` bzw. der belegte Health-Pfad der Version; Docker und Unit.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_mattermost.py tests/test_catalog_rocketchat.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T9 — R-1242: Module OnlyOffice und Collabora  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/onlyoffice.py, apps/monitoring/app/catalog/modules/collabora.py, apps/monitoring/tests/test_catalog_onlyoffice.py, apps/monitoring/tests/test_catalog_collabora.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @c66e78620 2026-11-12T15:42:38+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T9.verdict.json)
Änderung: OnlyOffice `/healthcheck` als Test-Objekt (15 min, nur GET; nie `/internal/cluster/inactive`), Docker und
Paket `onlyoffice-documentserver`; Collabora `GET /` → Status 200 (Antwort `OK` ist kein JSON), Docker und Unit
`coolwsd`, Schema nach Vorgabe des Images.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_onlyoffice.py tests/test_catalog_collabora.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T10 — R-1242: Module Keycloak und OpenLDAP  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/keycloak.py, apps/monitoring/app/catalog/modules/openldap.py, apps/monitoring/tests/test_catalog_keycloak.py, apps/monitoring/tests/test_catalog_openldap.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @b41cccd58 2026-11-12T16:08:22+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T10.verdict.json)
Änderung: Keycloak `/health/ready` auf dem Management-Port 9000 (nur mit `health-enabled`, sonst 404: Grenze in den
Docstring für die Doku), Feld `status`; OpenLDAP Unit `slapd` bzw. Container, LDAP-Protokoll (`proto` mit
`ldap`), Zertifikat (StartTLS/636). `contextCSN` → T15.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_keycloak.py tests/test_catalog_openldap.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T11 — R-1243: Module WordPress und Odoo  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/wordpress.py, apps/monitoring/app/catalog/modules/odoo.py, apps/monitoring/tests/test_catalog_wordpress.py, apps/monitoring/tests/test_catalog_odoo.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4ae52bf66 2026-11-12T16:23:05+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T11.verdict.json)
Änderung: WordPress: Docker (`wordpress`), `/wp-json/` (Weiterleitung auf `siteurl` belegen; nie `wp-cron.php`, nie
`core check-update`, nie `cron test`), nativ ohne HTTP; Version und Cron → T15. Odoo: Docker und Paket, `/web/health`
(8069; `db_server_status` nur ab der belegten Version).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_wordpress.py tests/test_catalog_odoo.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T12 — R-1243: Module Gitea/Forgejo, BookStack, Wiki.js  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/gitea.py, apps/monitoring/app/catalog/modules/bookstack.py, apps/monitoring/app/catalog/modules/wikijs.py, apps/monitoring/tests/test_catalog_gitea.py, apps/monitoring/tests/test_catalog_bookstack.py, apps/monitoring/tests/test_catalog_wikijs.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @8f5b0ef21 2026-11-12T16:51:28+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T12.verdict.json)
Änderung: Gitea und Forgejo in einem Modul (gleicher Pfad `/api/healthz`, Images und Units beider); BookStack
`/status` als Test-Objekt (legt eine Session an, 15 min); Wiki.js `/healthz`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_gitea.py tests/test_catalog_bookstack.py tests/test_catalog_wikijs.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T13 — R-1243: Module Uptime Kuma und Home Assistant  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/uptime_kuma.py, apps/monitoring/app/catalog/modules/home_assistant.py, apps/monitoring/tests/test_catalog_uptime_kuma.py, apps/monitoring/tests/test_catalog_home_assistant.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @862183a67 2026-11-12T17:09:13+01:00
Review: approve (.ah-out/review/arch-monitoring-apps-1/T13.verdict.json)
Änderung: Uptime Kuma `/api/entry-page` (nie `/api/push/…`); Home Assistant `GET /` ohne Zugangsdaten (eine
401-Antwort erzeugt dort eine dauerhafte Meldung und ggf. eine IP-Sperre), Container auch mit `network_mode: host`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_uptime_kuma.py tests/test_catalog_home_assistant.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T14 — Doku DE+EN und CHANGELOG (R-1241, R-1242, R-1243)  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/arch-monitoring-apps-1.md
Änderung: „Module und Erkennung“ nennt die neuen Module; je Gruppe ein Unterabschnitt (Erkennung, Checks,
Zugangsdaten mit Schlüssel für `monitor credential set`, Grenzen: nativ hinter Webserver ohne HTTP-Check, GitLab-
Allowlist, Keycloak `health-enabled`, Mindestversion des Agents für `host`). Entwickler-Doku: Parameter `host` des
HTTP-Fühlers. Changelog `### Added`. Vorher `origin/main` hineinmergen (Modul-Abschnitt ändert auch
`feature/kern-monitoring-23`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html · docs/en/admin/monitoring.html · docs/developer/monitoring.html · docs/en/developer/monitoring.html · changelog.d/arch-monitoring-apps-1.md
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12, T13

### T15 — R-1242: Spezial-Collector für Moodle checks.php und Verwandte  [?] (Spezial-Collector (Moodle checks.php als Webserver-Benutzer, BBB getMeetings/*.fail/bbb-conf --check, OpenLDAP contextCSN, WordPress Version/Cron) in diesem Zug oder als eigene Arch-Zeile danach? Empfehlung: eigene Zeile, weil exec als Anwendungs-Benutzer eine andere Risikoklasse ist und den Zug über 15 Tasks höbe)
Komponente: agent · Dateien: (nach der Entscheidung)
Änderung: nach Kevins Antwort: entweder `[~] ausgelagert in R-nnnn` oder eigener Plan-Nachtrag mit Agent-Collector,
Allowlist und Sicherheitsprüfung.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T14

## Entscheidungen
- 2026-11-12: Host-Header fest `localhost` statt freiem Namen (Spec, Trade-offs): Nextcloud lehnt die Container-IP
  ab, `localhost` ist dort immer vertraut; kein vHost-Name verlässt den Server.
- 2026-11-12: PHP-Anwendungen hinter einem allgemeinen Webserver auf dem Host bekommen keinen HTTP-Check, bis R-1231
  die vHosts kennt (Folgezeile am Gate); HTTP-Checks zielen nie auf `loopback`.
- 2026-11-12 (T2): `validate_params` lässt ungesetzte (None-)Parameter aus dem JSON (älterer Agent lehnt einen
  unbekannten Parameter ab, Katalog-Version bestehender Module bleibt); ein ausdrückliches `host: null` lehnt das Modell
  ab, weil eine Probe-Prüfung ihre Params ungefiltert an den Agenten gibt (dazu `test_check_configs.py` in T2).
- 2026-11-12 (T3): `probe_config` bindet einen Check mit Container-Ziel und `port_hint` nicht, wenn der letzte Scan den
  Container mit TCP-Ports sah und der Hinweis nicht darunter ist (sonst fragt der Agent den einzigen Port, beim
  fpm-Image von Nextcloud den FastCGI-Port 9000); ohne gesehene Ports entscheidet der Agent.
- 2026-11-12 (T3): `image_matches`: ein Präfix ohne `/` ist ein offizielles Docker-Hub-Image und trifft nur sich selbst
  (`nextcloud` nicht `nextcloud/aio-*`); Präfixe mit `/` bleiben Namensräume.
- 2026-11-12 (T3): Kein AIO-Modul (Backup stoppt die Container, Port/TLS des Apache-Containers undokumentiert, andere
  Images): R-1383 `neu`. `status.php` nur über den Compose-Dienst `app` (README, Beispiel-Compose; `cron` gleichen
  Images ohne Webserver); `docker run` oder andere Dienstnamen: R-1384 `neu`. Snap: nur die Unit
  `snap.nextcloud.apache.service` (HTTP leitet mit HTTPS um). Nativ hinter dem Host-Webserver: R-1378. `serverinfo`
  entfällt (teure Antwort aus Datenbank und Dateisystem).
- 2026-11-12 (T3): Paperless-Port 8000 und Immich-Port 2283 sind Hinweise aus den Dockerfiles; ein anderer Port
  (PAPERLESS_PORT) bleibt dem Agenten (pickPort). Paperless-Zugang als Header `Authorization: Token <token>`.
- 2026-11-12 (T3): 11 Dateien statt etwa acht: Sperre und Image-Abgleich gehören zum Nextcloud-Modul (ohne sie bände es
  am fpm-Image falsch bzw. erkennte AIO-Container) und werden mit dessen Tests geprüft.
- 2026-11-12 (T3, Prüfer-Nits): Nextcloud bekommt die Container-Checks der Spec auf die Dienste `app` und `cron`
  (`status.php` sieht einen toten Cron-Container nicht; ohne Dienst `cron` bleibt der Check ungebunden). Paperless
  erkennt auch das Docker-Hub-Image `paperlessngx/paperless-ngx` (Docker-Hub-Seite des Projekts, über 10 Mio. Pulls).
- 2026-11-12 (T4): GitLab im Image ohne HTTP-Check (Abweichung von Spec-Zeile „Docker: Bridge-Adresse eintragen“):
  Port 80 des Containers leitet bei https-`external_url` auf HTTPS um, dem der Agent nicht folgt (`sameTarget`), und
  die Bridge-Adresse steht nicht in der Standard-Allowlist; der HEALTHCHECK des Images (`gitlab-healthcheck`, 60 s)
  trägt die Gesundheit in den Container-Check. Paket: Readiness und Liveness an Puma `127.0.0.1:8080` über die Unit,
  nur `status_code` (die 404-Seite der Allowlist ist kein JSON); 5xx kritisch, sonst ungleich 200 Warnung.
- 2026-11-12 (T4): GitLab-Backup-Alter wandert nach R-1233 (App-Backups): `file_age` hat kein Ziel und bände auch an
  Docker-Instanzen (dauerhaft `unknown`), das Konzept will „neueste Datei < 26 h“ statt Verzeichnis-mtime.
- 2026-11-12 (T4): Zammad-Zugang als Header `Authorization: Token token=<token>` (API-Doku; `Bearer` nur OAuth2),
  Nutzer mit `admin.monitoring`, API-Token-Zugang an; Container- und Paket-Check in eigenen Slots (`default`, `web`),
  weil ein Slot einem Ziel gehört. `healthy: false` Warnung (von KI-Provider bis Scheduler, die Meldung sagt was),
  keine Antwort bzw. 5xx kritisch. Paket nur über `zammad-web-1.service` (pkgr; `zammad`/`zammad-web` halten nur einen
  Platzhalter). `amount_check` und die tägliche Status-Abfrage des Konzepts nicht in diesem Zug (Spec-Umfang).
- 2026-11-12 (T5): Vaultwarden im Image ohne HTTP-Check: der HEALTHCHECK des Images (`/healthcheck.sh`, 60 s) fragt
  `/alive` mit ROCKET_PORT, dem Pfad aus DOMAIN und ROCKET_TLS richtig, der Container-Check trägt das (`unhealthy`
  kritisch). Systemd-Dienst: Unit-Check und `/alive` auf Rockets Standardport 8000 über die Unit; ein DOMAIN mit Pfad
  macht `/alive` dort zu 404 (kritisch, im Test belegt). `/admin` nie.
- 2026-11-12 (T5): Bitwarden ohne HTTP-Check (Abweichung vom Plan „`/api/alive`“): der HEALTHCHECK des api-Images fragt
  `http://localhost:5000/alive` alle 30 s, die Route hinter `/api/alive`; ein HTTP-Check am api-Container wäre
  erreichbar (lokal auf Docker 29.9.2 geprüft: der Host erreicht einen Container im `internal: true`-Netz), brächte
  aber nichts darüber hinaus; nginx leitet 8080 auf 8443 um, dem ein einzelner `port_hint` nicht folgt (R-1387 `neu`).
  Container-Checks je Dienst auf nginx, api, identity, mssql; Lite (kein HEALTHCHECK) nur den Zustand, in der
  Standardinstallation ungebunden.
- 2026-11-12 (T5): Frigate ohne `/api/version` (der HEALTHCHECK fragt den Dienst alle 15 s); `/api/stats` auf dem
  internen Port 5000 über den Container, nie der Login auf 8971 (Ratenbremse, Hinweis). Zwei Checks auf denselben
  gecachten Pfad: `stats` (Statuscode ungleich 200 kritisch; Version, Laufzeit, Detektor-FPS und freier Platz der
  Aufnahmen ohne Regel, Frigate löscht alte Aufnahmen selbst) und `cameras` (Gesamt-`camera_fps` unter 0,1 Warnung;
  vor 0.17 fehlt das Feld, dann `unknown`). Keine Werte je Kamera (freie Namen, keine festen Felder);
  `listen.internal` auf 127.0.0.1 lässt die Stats-Checks `unknown` (Docstring).
- 2026-11-12 (T5): 3CX-Unit-Namen aus dem Paket 3cxpbx 20.0.10 des offiziellen apt-Repos (`3cxpbx.conf`,
  `3CXStartServices`, nur gelesen, nie ausgeführt) plus `3CXFirewall.service` (oneshot, bleibt `active`); jede Unit
  eine eigene Instanz (die Meldung nennt den Dienst), `active_state` ungleich `active` kritisch. Kein
  Zertifikats-Check (nginx auf 443, 5001 oder eigenem Port: R-1387 `neu`), Backup-Alter nach R-1233 (Ordner frei
  wählbar, auch Fernziel).
- 2026-11-12 (T6): Moodle nur aus Images, die Moodle vollständig fahren: `erseco/alpine-moodle` (Docker Hub,
  ghcr.io; erbt den HEALTHCHECK `/fpm-ping` seines Basis-Images) und Bitnamis `bitnami/moodle` bzw.
  `bitnamilegacy/moodle` (ohne HEALTHCHECK); nur der Container-Check. `moodlehq/moodle-php-apache` ist eine
  Entwicklungs-Basis ohne Moodle und zählt nicht. Ein Moodle auf dem Host bleibt unerkannt (Verzeichnis und
  dataroot stehen nur in `config.php`, kein Paket, kein fester Pfad); kein Dateialter in moodledata (die letzte
  Cron-Ausführung steht in der Datenbank, nicht belegt als Datei); keine Login-Seite (Moodle leitet einen fremden
  Host auf wwwroot um, `initialise_fullme()`). `checks.php` → T15.
- 2026-11-12 (T6): BigBlueButton mit `bbb-web.service` als einziger Instanz (Unit-Check) und `GET
  /bigbluebutton/api` auf bbb-webs eigenem Port 8090 per HTTP (`bbb-web.env` 3.0.40 und 4.0.2: 127.0.0.1:8090;
  `ApiController.index` antwortet SUCCESS ohne Checksumme); geprüft wird nur `status_code`. Die übrigen Units
  (graphql, webrtc-sfu, livekit, coturn …) bleiben bei Service Health aus linux-base: eine Unit-Instanz je Dienst
  bände den API-Check an jede. Kein Zertifikat (nginx-vHost, Hostname unbekannt → R-1231); `getMeetings`,
  `*.fail`, `bbb-conf --check` → T15.
- 2026-11-12 (T7): Jitsi als zwei Module, `jitsi-videobridge` und `jitsi-jicofo` (Dateien `jitsi_videobridge.py`,
  `jitsi_jicofo.py` statt `jitsi.py`): eine Bridge läuft oft auf einem eigenen Host, und ein Modul mit beiden
  Paket-Units fände keine eindeutige Unit (Stellvertreter mit zwei `unit:`-Treffern bindet keinen Unit-Check).
  Images `ghcr.io/jitsi/{jvb,jicofo}` (Compose-Standard von docker-jitsi-meet) und die alten `jitsi/{jvb,jicofo}`;
  Units `jitsi-videobridge2.service` und `jicofo.service` (Paket startet `/etc/init.d/jicofo`, systemd erzeugt die
  Unit; auf einer Box nicht verifiziert). Je Ziel nur `GET /about/health` mit `status_code` ≠ 200 → critical:
  Bridge auf 8080 (Paket 127.0.0.1, Image 0.0.0.0 im Container; das Image hat keinen HEALTHCHECK, daher auch der
  HTTP-Check am Container), Jicofo auf 8888 nur am Paket: im Image bleibt Jicofos REST ohne `JICOFO_ENABLE_REST`
  auf der Container-Loopback, der Agent meldete „listens on no TCP port“ und damit critical bei jeder
  Standard-Installation. Jicofos Health schlägt ohne operative Bridge hart fehl (`JicofoHealthChecker`), das deckt
  „keine aktive Bridge → crit“. Kein `colibri/stats`/`stress_level` (aus ohne `videobridge.apis.rest.enabled`,
  Paket und Image; `/metrics` ist Prometheus-Text) → R-1388 `neu`. Nie `/move-endpoints`, `/debug`, `/pin`, `/stats`.
- 2026-11-12 (T7): Synapse wie Vaultwarden: Images `matrixdotorg/synapse` und `ghcr.io/element-hq/synapse`
  (`docker.yml`) mit eigenem HEALTHCHECK (`curl localhost:8008/health`, 15 s), daher nur der Container-Check; Paket
  `matrix-synapse.service` mit Unit-Check und `GET /health` auf 8008 per HTTP (generierte Konfig: `::1`,
  `127.0.0.1`). `/health` antwortet immer 200, prüft die Datenbank nicht. Worker (mehrere Container des Images in
  einem Projekt) binden keinen Container-Check; Föderation zentral, nicht im Agent.
- 2026-11-12 (T8): Mattermost wie Synapse: die Images `mattermost/mattermost-enterprise-edition` und
  `-team-edition` haben einen eigenen HEALTHCHECK (heute `mmctl system status --local`, in v9 `curl
  /api/v4/system/ping`), daher nur der Container-Check; Paket und Tarball-Install `mattermost.service` mit Unit-Check
  und `GET /api/v4/system/ping` auf 8065 (200 oder 500 bei überschrittenem `GoroutineHealthThreshold`, Standard aus).
  Nie `get_server_status=true` (schreibt und löscht eine Zeile in der Datenbank, testet den Dateispeicher).
  `mattermost/mattermost-preview` bleibt draußen (Testinstanz mit eingebauter Datenbank).
- 2026-11-12 (T8): Rocket.Chat fragt `/livez` (seit 7.11.0) am Container und an der Unit, Port 3000; kein Image
  (`registry.rocket.chat/rocketchat/rocket.chat`, `rocketchat/rocket.chat`, offizielles `rocket.chat`) hat einen
  HEALTHCHECK. Units: Snap `snap.rocketchat-server.rocketchat-server.service` und `rocketchat.service` (manuelle
  Installation, `rocketchatctl`). Bewertet werden die drei Felder `data.checks.{mongo,memory,eventLoop}.status`,
  nicht der Statuscode: jedes `degraded` macht 503, aber nur Mongo ist ein Ausfall (critical); Heap über 85 % und
  Event-Loop-Lag p99 über 70 ms sind Last (warning). Bis 8.0 misst der Heap-Test gegen den belegten Heap
  (`heapUsed/heapTotal`) und schlägt auf gesunden Servern zwischen zwei GCs an, ab 8.1.0 gegen das Limit
  (f12402e2d8, in 8.1.0 enthalten, in 8.0.0 nicht). Vor 7.11.0 gibt es `/livez` nicht; dort ist die Antwort kein
  JSON-Objekt und die Probe schlägt fehl statt grün zu melden. `/health` (in allen Versionen, ab 7.11 immer 200)
  prüft weniger, daher `/livez`.
- 2026-11-12 (T9): OnlyOffice abweichend vom Plan ohne `/healthcheck` am Container: die Images
  (`onlyoffice/documentserver`, `-de`, `-ee`) exponieren nur nginx 80/443, und `module_sync._lacks_port` bindet
  keinen Container-Check auf dem Docservice-Port 8000 (nicht in der Port-Map) → R-1393 `neu`. Über nginx geht es
  nicht: mit Zertifikat leitet 80 von außen auf HTTPS um (`ds-ssl.conf.tmpl`), ohne lauscht 443 nicht. Ab 10.0.0.1
  fragt der HEALTHCHECK des Images `/healthcheck` alle 30 s und vergleicht mit `true`; die Container-Gesundheit
  trägt es, 9.x hat keinen (nur der Zustand). Paket: `ds-docservice.service` (gleich in -de/-ee) mit Unit-Check und
  `GET /healthcheck` auf 8000 per HTTP (`server.host ''`, `port 8000` in `default.json`), Test-Objekt, 900 s. Die
  Antwort ist immer 200 mit `true`/`false` (kein JSON) → bewertet wird nur der Status → R-1392 `neu`.
- 2026-11-12 (T9): Collabora mit dem proto-Fühler `auto` statt `GET /` mit festem Schema: `ssl.enable` steht im
  Paket und im Image (`collabora/code`) auf an, hinter einem Proxy oft aus. `HEAD /` antwortet 200 `OK`
  (`isGetOrHead("/")`, `handleRootRequest`). Neben `ok eq false` ist `detail in [unknown, tls]` kritisch: ein
  coolwsd, der annimmt und weder im Klartext noch in TLS HTTP antwortet, wäre sonst grün (`recognizeOn` meldet dann
  `ok` mit `unknown`). Ab 26.04 hat das Image einen HEALTHCHECK (`coolwsd --probe` → `/livez`), 25.04 keinen.
  `nextcloud/aio-collabora` und `nextcloud/aio-onlyoffice` bleiben draußen (eigene Images).
- 2026-11-12 (T10): Keycloak abweichend vom Plan mit dem Feld `status_code` statt `status`: `/health/ready` antwortet
  200 mit `UP` und 503 mit `DOWN`, der Code trägt die Aussage, und `fetch` liest JSON nur bei einem `data.*`-Feld; bei
  einem 404 (ohne `health-enabled`) verdeckte die JSON-Fehlermeldung den Code. Port 9000, Schema fest `http` wie bei
  Vaultwarden, Mattermost und GitLab: das Management erbt TLS vom Hauptserver (`http-management-scheme`) und den Pfad
  von `http-relative-path`; beides steht als Grenze im Docstring, Schema-Erkennung → R-1395 `neu`. Images
  `quay.io/keycloak/keycloak` und `keycloak/keycloak` (beide nötig, `image_repo` streift nur Docker-Hub-Präfixe),
  ab 25.0 `EXPOSE 9000`, kein HEALTHCHECK; vor 25.0 bindet `_lacks_port` die Prüfung nicht. Keycloak liefert keine
  Unit, `keycloak.service` ist die übliche Benennung (nicht verifiziert gegen eine Distribution). `bitnami/keycloak`
  und `jboss/keycloak` sind eingestellt und bleiben draußen.
- 2026-11-12 (T10): OpenLDAP mit anonymem WhoAmI (proto `ldap`) auf 389 an Container und Unit, jede LDAP-Antwort zählt
  (auch ein Ergebniscode der ACL), `busy`/`unavailable` und Verbindungsfehler sind kritisch. Zertifikat abweichend vom
  Plan nur per StartTLS auf 389 und nur am Paket: `osixia/openldap` 1.5.0 verlangt im TLS ein Client-Zertifikat
  (`LDAP_TLS_VERIFY_CLIENT: demand`), ein Prüfer auf 636 träfe bei einem slapd ohne LDAPS über `pickPort` den
  Klartext-Port. Schwellen fest 22/9 Tage (25/10 % der 90 Tage eines ACME-Zertifikats, Konzept §5), weil der
  Agent-Fühler nur `days_left` kennt → R-1394 `neu`; Intervall 3600 s. Ohne TLS (Debian-Standard) ist die Prüfung
  kritisch, der Docstring sagt das. Dazu `sub_state eq exited` kritisch: die aus dem Init-Skript erzeugte
  `slapd.service` (ohne `pidfile:` `RemainAfterExit=yes`, keine Main-PID; systemd v257 `sysv-generator.c:163-170`,
  `service.c` `service_good_except_bus_name`, `service_enter_exited_or_stop`) steht im Betrieb auf `running` und
  nach dem Tod von slapd auf `active (exited)`; eine native Unit kommt dort nicht hin.
  contextCSN und cn=Monitor bleiben bei T15.
- 2026-11-12 (T11): WordPress fragt abweichend vom Plan `/?rest_route=/` statt `/wp-json/` (gleicher Handler, gleiche
  Kosten): `rest_api_init` registriert die öffentliche Query-Var `rest_route`, `rest_api_loaded` beendet die Anfrage in
  `parse_request` (`default-filters.php`), vor `redirect_canonical` auf `template_redirect`. Ohne Pretty-Permalinks ist
  `rewrite_rules()` leer (`class-wp-rewrite.php`), `/wp-json/` läuft in die Seite, und `redirect_canonical` leitet auf
  den Port aus `home_url` um (`canonical.php`), dem der Agent nicht folgt (`sameTarget` → `not_allowed` → unbekannt).
  Nur Docker (`wordpress`, Port 80 des apache-Images aus `php:8.3-apache`); fpm (9000) bleibt ohne HTTP-Check, ein
  `wordpress:cli`-Container im selben Projekt macht das Ziel mehrdeutig (`_target_name`), beides im Docstring. 500
  (`dead_db`) und 503 (`wp_maintenance`) sind kritisch, 401/403 eines Plugins die Zugangsbremse.
- 2026-11-12 (T11): Odoo fragt `/web/health?db_server_status=1` an Image und Paket in jeder Version, weil ein Modul die
  Version nicht kennt: ab 16 öffnet der Parameter einen Cursor des Pools auf die Datenbank `postgres` (500 bei
  `psycopg2.Error`), 15 hat die Route ohne Parameter und loggt ihn je Prüfung auf `info` (`http.py:544`), vor 15 fehlt
  die Route (404, kritisch). Unit `odoo.service` aus dem Debian-Paket 15–19 (`Type=simple`); `odoo18.service`,
  `bitnami/odoo` und `/websocket/health` nicht abgedeckt.
- 2026-11-12 (T12): Gitea und Forgejo `/api/healthz` (vor der Session-Middleware, ab Installation DB-Ping und Cache:
  200, sonst 424; vor der Installation 200) an Image und Units `gitea.service`/`forgejo.service`; beide Units auf einem
  Host binden keinen Unit-Check (mehrdeutig). Runner-Images und -Units nicht. `PROTOCOL = https` antwortet 400
  (kritisch, Check abschalten), im Docstring.
- 2026-11-12 (T12): BookStack `/status` als Test-Objekt alle 15 min (`StatusController::show`: `migrations` zählen,
  `Cache::add`/`pull`, `Session::put`; ohne Cookie je Aufruf eine Session). Zwei Checks je Image-Port (linuxserver.io
  80, solidnerd 8080), der Port, den der Container nicht hat, bindet nicht (`_lacks_port`); im Host-Netz binden beide:
  bei linuxserver.io (80, 443) bleibt `status_8080` `ambiguous_target` → unbekannt; solidnerd lauscht nur auf 8080,
  das nimmt der Agent für jeden Hinweis (`pickPort`), dann fragen beide Checks `/status` (zweimal je 15 min). Nur
  `status_code`: ein `data.`-Feld ließe `fetch` bei Nicht-JSON scheitern (`sensor_http.go`).
- 2026-11-12 (T12): Wiki.js fragt `/favicon.ico` statt `/healthz` (Abweichung von der Task-Zeile): Wiki.js 3 (Tag `3`
  desselben Images, seit 3.1.0 released) hat kein `/healthz`, die App-Shell antwortet dort 404 (`helpers/appShell.ts`),
  seine Proben heißen `/_live`/`/_ready` (`@gquittet/graceful-server`); der Katalog vergleicht Images ohne Tag
  (`discovery.image_matches`). `/favicon.ico` liefern 2 (`serve-favicon`, vor Session und SSL-Umleitung) und 3
  (`fastify-favicon`, kein Seitenpfad: `RESERVED_ROOT_FILES`, keine Umleitung) aus `assets/` ohne Session und
  Datenbank: nur ein Lebenszeichen. Tag-Auswahl je Check: R-1397. Images `requarks/wiki`,
  `ghcr.io/requarks/wiki` und linuxserver.io (`Requarks/wiki-v2`, 3000).
- 2026-11-12 (T13): Uptime Kuma fragt `/api/entry-page` an 3001 ohne Login, die Anfrage seiner Seite bei jedem Aufruf
  (`api-router.js`, `trustProxy` aus einem Cache von 60 s), in Version 1 und 2; `data.type` `setup-database` (Version
  2 wartet auf die Wahl seiner Datenbank und überwacht nichts) ist eine Warnung, alles außer 200 kritisch; nie
  `/api/push/`. Images `louislam/uptime-kuma` und `ghcr.io/louislam/uptime-kuma`; ohne Image (node, pm2) und eigenes
  HTTPS (`SSL_KEY`/`SSL_CERT`) nicht abgedeckt. Belegt aus dem Quelltext von 2.5.11 und 1.23.16, nicht live gefahren.
- 2026-11-12 (T13): Home Assistant fragt GET `/` an 8123 ohne Token (`IndexView.get`: Seite aus dem Template-Cache,
  vor dem Onboarding 302 auf `/onboarding.html`, dem der Agent folgt); keine API-Route, weil jede 401
  `process_wrong_login` (`http/ban.py`) auslöst: dauerhafte Meldung, mit `login_attempts_threshold` Zählung zur
  IP-Sperre. 403 heißt Agent-Adresse gesperrt (`ip_bans.yaml`), kritisch. Container laut Installationsanleitung mit
  `network_mode: host`: der Scan sieht keine Ports, der Agent findet 8123 unter den Sockets des Containers. Images von
  Home Assistant (ghcr.io, Docker Hub) und linuxserver.io; OS/Supervised (Image je Maschine), Core im venv und HTTPS
  auf 8123 nicht abgedeckt. Belegt aus dem Quelltext von 2026.11.1, nicht live gefahren.
