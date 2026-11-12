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

### T3 — R-1241: Module Nextcloud, Paperless-ngx, Immich  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/nextcloud.py, apps/monitoring/app/catalog/modules/paperless.py, apps/monitoring/app/catalog/modules/immich.py, apps/monitoring/tests/test_catalog_nextcloud.py, apps/monitoring/tests/test_catalog_paperless.py, apps/monitoring/tests/test_catalog_immich.py
Änderung: Nextcloud: Docker (Image `nextcloud`, AIO) und Snap; `status.php` mit `host: localhost`, Regeln auf
`maintenance` und `needsDbUpgrade`; nativ hinter Webserver nur, was ohne vHost geht; `serverinfo` mit Header
`NC-Token` nur, wenn als festes Feld belegt. Paperless-ngx: Container, `/api/status/` (15 min, Zugang Nutzer mit
`paperless.view_system_monitoring`). Immich: Compose-Projekt, Container je Dienst, `/api/server/ping`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_nextcloud.py tests/test_catalog_paperless.py tests/test_catalog_immich.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T4 — R-1241: Module Zammad und GitLab  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/zammad.py, apps/monitoring/app/catalog/modules/gitlab.py, apps/monitoring/tests/test_catalog_zammad.py, apps/monitoring/tests/test_catalog_gitlab.py
Änderung: Zammad: Docker (Compose) und Paket `zammad` (Units), `health_check` am Railsserver, Zugang nur in einer
Form, die der Agent übergeben kann (Header/Bearer; ein Query-Token nicht). GitLab: Docker (`gitlab/gitlab-ce`,
`-ee`) und Paket (Unit `gitlab-runsvdir`), `/-/readiness?all=1` und `/-/liveness`, Alter des Backup-Verzeichnisses
(nativ); Grenze Monitoring-Allowlist (Docker: Bridge-Adresse) in den Docstring für die Doku.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_zammad.py tests/test_catalog_gitlab.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T5 — R-1241: Module Vaultwarden, Bitwarden, Frigate, 3CX  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/vaultwarden.py, apps/monitoring/app/catalog/modules/bitwarden.py, apps/monitoring/app/catalog/modules/frigate.py, apps/monitoring/app/catalog/modules/threecx.py, apps/monitoring/tests/test_catalog_vaultwarden.py, apps/monitoring/tests/test_catalog_bitwarden.py, apps/monitoring/tests/test_catalog_frigate.py, apps/monitoring/tests/test_catalog_threecx.py
Änderung: Vaultwarden `/alive` (nie `/admin`); Bitwarden `/api/alive` (nicht `/alive`); Frigate Container,
`/api/version` und `/api/stats` auf Port 5000 (nie der Login auf 8971), nur feste Felder; 3CX Units (Namen aus der
3CX-Doku, sonst „nicht verifiziert“ und ohne Unit-Check), Zertifikat, Backup-Alter. Acht Dateien: vier kleine Module
mit je einem Test.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_vaultwarden.py tests/test_catalog_bitwarden.py tests/test_catalog_frigate.py tests/test_catalog_threecx.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T6 — R-1242: Module Moodle und BigBlueButton (ohne Spezial-Collector)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/moodle.py, apps/monitoring/app/catalog/modules/bigbluebutton.py, apps/monitoring/tests/test_catalog_moodle.py, apps/monitoring/tests/test_catalog_bigbluebutton.py
Änderung: Moodle: Erkennung über Marker/Pakete bzw. Container, was ohne vHost und ohne exec geht (Container,
Dateialter von moodledata, falls belegt); nie `/admin/cron.php`. BigBlueButton: Pakete/Units, `bbb-web`
`/bigbluebutton/api` direkt an der Unit (Status 200), Zertifikat. `checks.php`, `getMeetings`, `*.fail`,
`bbb-conf --check` → T15.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_moodle.py tests/test_catalog_bigbluebutton.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T7 — R-1242: Module Jitsi Meet und Matrix Synapse  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/jitsi.py, apps/monitoring/app/catalog/modules/synapse.py, apps/monitoring/tests/test_catalog_jitsi.py, apps/monitoring/tests/test_catalog_synapse.py
Änderung: Jitsi: Docker (`jitsi/jvb`, `jitsi/jicofo` …) und Pakete; JVB `/about/health` (8080), Jicofo
`/about/health` (8888), `colibri/stats` mit `stress_level` > 0,8 → warning, nur exakte Pfade (nie
`move-endpoints`). Synapse: Docker und Paket, `/health` (8008).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_jitsi.py tests/test_catalog_synapse.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T8 — R-1242: Module Mattermost und Rocket.Chat  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/mattermost.py, apps/monitoring/app/catalog/modules/rocketchat.py, apps/monitoring/tests/test_catalog_mattermost.py, apps/monitoring/tests/test_catalog_rocketchat.py
Änderung: Mattermost `/api/v4/system/ping` ohne `get_server_status` (der tiefe Ping schreibt eine Testdatei);
Rocket.Chat `/livez` bzw. der belegte Health-Pfad der Version; Docker und Unit.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_mattermost.py tests/test_catalog_rocketchat.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T9 — R-1242: Module OnlyOffice und Collabora  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/onlyoffice.py, apps/monitoring/app/catalog/modules/collabora.py, apps/monitoring/tests/test_catalog_onlyoffice.py, apps/monitoring/tests/test_catalog_collabora.py
Änderung: OnlyOffice `/healthcheck` als Test-Objekt (15 min, nur GET; nie `/internal/cluster/inactive`), Docker und
Paket `onlyoffice-documentserver`; Collabora `GET /` → Status 200 (Antwort `OK` ist kein JSON), Docker und Unit
`coolwsd`, Schema nach Vorgabe des Images.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_onlyoffice.py tests/test_catalog_collabora.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T10 — R-1242: Module Keycloak und OpenLDAP  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/keycloak.py, apps/monitoring/app/catalog/modules/openldap.py, apps/monitoring/tests/test_catalog_keycloak.py, apps/monitoring/tests/test_catalog_openldap.py
Änderung: Keycloak `/health/ready` auf dem Management-Port 9000 (nur mit `health-enabled`, sonst 404: Grenze in den
Docstring für die Doku), Feld `status`; OpenLDAP Unit `slapd` bzw. Container, LDAP-Protokoll (`proto` mit
`ldap`), Zertifikat (StartTLS/636). `contextCSN` → T15.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_keycloak.py tests/test_catalog_openldap.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T11 — R-1243: Module WordPress und Odoo  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/wordpress.py, apps/monitoring/app/catalog/modules/odoo.py, apps/monitoring/tests/test_catalog_wordpress.py, apps/monitoring/tests/test_catalog_odoo.py
Änderung: WordPress: Docker (`wordpress`), `/wp-json/` (Weiterleitung auf `siteurl` belegen; nie `wp-cron.php`, nie
`core check-update`, nie `cron test`), nativ ohne HTTP; Version und Cron → T15. Odoo: Docker und Paket, `/web/health`
(8069; `db_server_status` nur ab der belegten Version).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_wordpress.py tests/test_catalog_odoo.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T12 — R-1243: Module Gitea/Forgejo, BookStack, Wiki.js  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/gitea.py, apps/monitoring/app/catalog/modules/bookstack.py, apps/monitoring/app/catalog/modules/wikijs.py, apps/monitoring/tests/test_catalog_gitea.py, apps/monitoring/tests/test_catalog_bookstack.py, apps/monitoring/tests/test_catalog_wikijs.py
Änderung: Gitea und Forgejo in einem Modul (gleicher Pfad `/api/healthz`, Images und Units beider); BookStack
`/status` als Test-Objekt (legt eine Session an, 15 min); Wiki.js `/healthz`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_gitea.py tests/test_catalog_bookstack.py tests/test_catalog_wikijs.py tests/test_catalog_apps.py tests/test_catalog.py
Doku: → T14
Abhängt von: T2

### T13 — R-1243: Module Uptime Kuma und Home Assistant  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/uptime_kuma.py, apps/monitoring/app/catalog/modules/home_assistant.py, apps/monitoring/tests/test_catalog_uptime_kuma.py, apps/monitoring/tests/test_catalog_home_assistant.py
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
