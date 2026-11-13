# Monitoring: Fühler `app` für Anwendungs-Innenleben — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-app-collector · Review: pro Task
Spec: docs/features/arch-monitoring-app-collector.md (Roadmap R-1404)
Heavy: linux-full — apps/agent (neuer Probe-Fühler `app`); die Katalog-Module sind Daten mit Unit-Tests in der PR-CI; geht in den nächtlichen Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für jede Agent-Task gilt: Format und Pfade vor dem Code erneut gegen die Quellen der Spec („Externe Integrationen“)
prüfen; Unbelegtes steht als „nicht verifiziert“ im Commit-Body. Kein exec, keine neue Allowlist-Zeile; Datei-,
Socket- und HTTP-Zugriffe über Seams, damit die Tests ohne echten Host laufen. Jede Ansicht hat einen Test, dass ihre
Werte nur die Felder der Spec tragen, und einen Fehlertest, dessen Text weder Pfadinhalte noch Geheimnisse nennt.
Neue Dateien mit SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`).

### T1 — Agent: Fühler `app` und Ansicht `bbb_recordings`  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/sensor_app_test.go, apps/agent/internal/probe/app_bbb.go, apps/agent/internal/probe/app_bbb_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a25336ceb 2026-11-13T08:54:46+01:00
Review: approve (.ah-out/review/arch-monitoring-app-collector/T1.verdict.json)
Änderung: `sensors["app"]` mit Pflicht-Parameter `view` (`knownParams`, `choiceParam` über die vier Ansichten der
Spec; noch nicht gebaute Ansichten gibt es erst in ihrer Task), Ziel-Art je Ansicht über `targetOf`. Ansicht
`bbb_recordings`: zählt `.fail`-Marker in `status/{archived,sanity,processed,published}` unter
`/var/bigbluebutton/recording`, Felder `failed`, `archive_failed`, `sanity_failed`, `process_failed`,
`publish_failed`, `newest_fail_age_s` (fehlt ohne Marker); fehlendes Status-Verzeichnis ist `ErrUnsupported`;
Obergrenze an Einträgen je Verzeichnis. Tests: unbekannte Ansicht, fremder Parameter, falsche Ziel-Art und fehlendes
Ziel sind `ErrInvalid`; Fixture-Baum mit `.done`- und `.fail`-Dateien je Verzeichnis (auch `<id>-<format>.fail`),
leerer Baum (kein Alter), fehlendes Verzeichnis, Obergrenze überschritten.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7

### T2 — Agent: Ansicht `bbb_meetings`  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_bbb.go, apps/agent/internal/probe/app_bbb_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @bd8d806e1 2026-11-13T09:17:20+01:00
Review: approve (.ah-out/review/arch-monitoring-app-collector/T2.verdict.json)
Änderung: liest `securitySalt` und `supportedChecksumAlgorithms` aus `/etc/bigbluebutton/bbb-web.properties`
(zuerst) und `/usr/share/bbb-web/WEB-INF/classes/bigbluebutton.properties`, Prüfsumme `hex(sha256("getMeetings" +
salt))` (sonst der stärkste erlaubte Algorithmus), `GET /bigbluebutton/api/getMeetings?checksum=…` an den über
`resolve` gefundenen Port der Unit (Hinweis 8090) mit `dialTarget`; Antwort gestreamt mit Obergrenze, gezählt nur
`meetings`, `running`, `participants`, `listeners`, `voice`, `video`, `recording`. `FAILED` außer `noMeetings` ist
ein Fehler mit `messageKey`. Tests: httptest-Server auf Loopback prüft die empfangene Prüfsumme; Fixture mit
Meetingnamen, `attendeePW`/`moderatorPW`, Teilnehmern (`fullName`, `userID`) und Metadaten: keiner dieser Werte und
weder Salt noch Prüfsumme stehen in Werten oder Fehlern (auch bei FAILED, Nicht-XML, zu großem Body); kein Salt
(beide Dateien fehlen oder ohne Schlüssel) ist `ErrUnsupported`; nicht erlaubter Algorithmus; `noMeetings` ergibt
Nullen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7
Abhängt von: T1

### T3 — Agent: Ansicht `ldap_replication`  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_ldap.go, apps/agent/internal/probe/app_ldap_test.go, apps/agent/internal/probe/sensor_proto.go, apps/agent/internal/probe/app_ldap_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ed67f8323 2026-11-13T09:34:19+01:00
Review: approve (.ah-out/review/arch-monitoring-app-collector/T3.verdict.json)
Änderung: `dialUnix` auf den ersten vorhandenen ldapi-Socket (`/var/run/slapd/ldapi`, `/var/run/ldapi`), SASL
EXTERNAL Bind, Search auf das Root-DSE (`namingContexts`), je Kontext (höchstens 16) `contextCSN` mit Scope base,
dann `cn=Monitor` subtree `(objectClass=olmSyncReplInstance)` mit genau `olmSRConnection` und `olmSRSyncPhase`
(höchstens 64). Felder `contexts`, `csn_age_s`, `monitor`, `consumers`, `disconnected`, `refreshing`. BER-Bausteine
für Bind/Search neben die bestehenden in `sensor_proto.go`, falls dort teilbar; sonst in `app_ldap.go`. Tests: ein
Fake-LDAP-Server auf einem Unix-Socket im Testverzeichnis (Seam für die Socket-Kandidaten) beantwortet Bind und
Searches; Fälle: zwei Kontexte, CSN-Parsing (mehrere Werte, kaputtes Format), Monitor fehlt (`noSuchObject`) oder
verweigert (`insufficientAccessRights`) → `monitor=false`, getrennter und refreshender Consumer, Obergrenzen, kein
Socket → `ErrUnsupported`, Bind abgelehnt → Fehler; der Fake-Server prüft, dass nie `olmSRProviderURIList` angefragt
wird.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7
Abhängt von: T1

### T4 — Agent: Ansicht `wordpress_version`  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_wordpress.go, apps/agent/internal/probe/app_wordpress_test.go, apps/agent/internal/probe/app_wordpress_linux_test.go, apps/agent/internal/probe/app_wordpress_linux.go, apps/agent/internal/probe/app_wordpress_other.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @cf1ab1ac3 2026-11-13T10:03:02+01:00
Review: approve (.ah-out/review/arch-monitoring-app-collector/T4.verdict.json)
Änderung: `inspectContainer` des Ziels, laufend mit PID; `os.OpenRoot("/proc/<pid>/root")` (Seam für die Wurzel),
`var/www/html/wp-includes/version.php` mit Obergrenze lesen, `$wp_version = '…';` mit engem Muster prüfen, Feld
`version`. Nicht Linux → `ErrUnsupported`; Container gestoppt → Fehler. Tests: Wurzel-Verzeichnis mit echter
`version.php`-Form (Release, `-beta5-65467`, `-RC1`), fehlende Datei, Wert außerhalb des Musters (Anführungszeichen,
Leerzeichen, überlang), Symlink aus der Wurzel heraus wird nicht gefolgt, gestoppter Container.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7
Abhängt von: T1

### T5 — Katalog: Vertrag des Fühlers `app`  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/model.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_check_configs.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6a9cc54f4 2026-11-13T10:08:46+01:00
Review: approve (.ah-out/review/arch-monitoring-app-collector/T5.verdict.json)
Änderung: `"app"` in `SENSORS`, `APP_VIEW_FIELDS` und `APP_VIEW_TARGETS` je Ansicht, `SENSOR_FIELDS["app"]`,
`SENSOR_TARGETS["app"]`, `AppParams(view: Literal[...])` in `PARAM_MODELS`, `field_allowed` je Ansicht;
`Check._consistent` prüft die Ziel-Art der Ansicht. Tests: jede Ansicht nimmt genau ihre Felder und ihr Ziel, ein
Feld einer anderen Ansicht, eine fremde Ziel-Art, fehlendes `view` und ein unbekannter Parameter werden abgewiesen;
`ProbeConfig` weist dasselbe ab (Gegenprobe über `check_configs`).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_catalog.py tests/test_check_configs.py
Doku: → T7

### T6 — Katalog: Module bigbluebutton, openldap, wordpress Version 2  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/bigbluebutton.py, apps/monitoring/app/catalog/modules/openldap.py, apps/monitoring/app/catalog/modules/wordpress.py, apps/monitoring/tests/test_catalog_bigbluebutton.py, apps/monitoring/tests/test_catalog_openldap.py, apps/monitoring/tests/test_catalog_wordpress.py, apps/monitoring/tests/test_module_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @38a842ebc 2026-11-13T10:20:31+01:00
Review: approve (.ah-out/review/arch-monitoring-app-collector/T6.verdict.json)
Änderung: bigbluebutton: Checks `meetings` (`bbb_meetings`, Unit, Port-Hinweis 8090, 300 s) und `recordings`
(`bbb_recordings`, 900 s, `failed gt 0` warning) mit Karten-Einträgen; openldap: Check `replication`
(`ldap_replication`, Unit, 300 s, `disconnected gt 0` warning), Karte nach Trade-off 6 der Spec; wordpress: Check
`version` (`wordpress_version`, Container, 3600 s) mit Karten-Eintrag; je Version 2, Docstring mit Quellen und
nachgezogenem „Not covered“ (`bbb-conf --check` nie). Tests: `probe_config` bindet die neuen Checks an native
bzw. Container-Instanzen und überspringt sie, wo die Ziel-Art fehlt (openldap im Container); jede neue Regel feuert
an ihrer Schwelle und nicht darunter (`ProbeChecker().evaluate`); Karte wie erwartet; `sync_catalog` legt die neuen
Checks bei einer übernommenen Version-1-Instanz still an.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_bigbluebutton.py tests/test_catalog_openldap.py tests/test_catalog_wordpress.py tests/test_catalog_apps.py tests/test_catalog.py tests/test_module_sync.py
Doku: → T7
Abhängt von: T5

### T7 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/arch-monitoring-app-collector.md
Änderung: Modul-Zeilen BigBlueButton, OpenLDAP, WordPress (neue Checks, Voraussetzungen: Agent-Mindestversion,
cn=Monitor für die Consumer-Zahlen, Grenzen), Liste „Nie aufgerufen“ um `bbb-conf --check`; Fühler `app` mit seinen
Ansichten in der Fühler-Liste der Entwickler-Doku; Changelog `### Added` (ohne Umlaute). Vorher `origin/main`
hineinmergen; doc-smoke lokal fahren.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html · docs/en/admin/monitoring.html · docs/developer/agent.html · docs/en/developer/agent.html · changelog.d/arch-monitoring-app-collector.md
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4, T5, T6

## Entscheidungen
- 2026-11-13: ein Fühler `app` mit Ansichten im Paket `probe`, kein exec (Spec, Trade-offs 1–3).
- 2026-11-13: Moodle `checks.php`, WordPress-Cron und OpenLDAP-Verzug über Hosts fahren nicht mit (`neu`-Zeilen);
  `bbb-conf --check` nie (Spec, Nicht-Ziele). Kevin bestätigt am Gate (offene Frage 1).
- 2026-11-13: T2 (Salt) bekommt zusätzlich den Prüfer `security`, obwohl `apps/agent/internal/probe` kein Risikopfad
  ist: die Task verarbeitet ein Geheimnis.
- 2026-11-13 (T2): `bbb_meetings` fragt nur die Unit `bbb-web.service`: die Prüfsumme von getMeetings ohne Parameter
  ist je Salt fest und öffnet jedem, der sie hält, Meetingnamen und Passwörter; sie gilt als Geheimnis, kein Fehler
  zitiert URL oder Antwort (`url.Error` ausgepackt, ein Text mit der Prüfsumme wird ein fester Text).
- 2026-11-13 (T2): Schlüssel wie `get_bbb_web_config_value` in `bbb-conf`: je Schlüssel der erste nicht leere Wert,
  erst `/etc/bigbluebutton/bbb-web.properties`, dann die paketierte Datei. Ohne `supportedChecksumAlgorithms` nimmt
  die Ansicht sha256 (für Versionen vor dem Schlüssel nicht verifiziert); sonst sha256, sha512, sha384, sha1 in dieser
  Reihenfolge, wie `GetChecksumValidator` die Länge zuordnet.
- 2026-11-13 (T2): `running`/`recording` zählen Meetings mit `true`; gezählt wird nur ein direktes Kind von
  `response/meetings/meeting`, gleichnamige Elemente in Metadaten oder `customdata` nicht. Körper bis 1 MiB (Grenze
  des Guards), ein gelesener Wert bis 64 Byte, sonst Fehler.
- 2026-11-13 (T2): HTTP über `NewGuard(ep.extra...).HTTPClient(nil)` wie der Fühler `http` statt `dialTarget` (die
  Task nannte es; derselbe Guard, Weiterleitungen nur zum selben Ziel).
- 2026-11-13 (T3): Die Consumer-Suche geht auf `cn=Databases,cn=Monitor` statt auf ganz `cn=Monitor`: back-monitor
  hängt die `olmSyncReplInstance`-Einträge unter die Datenbanken (enger, weniger Einträge). `noSuchObject`,
  `insufficientAccessRights` und `referral` ergeben `monitor=false` ohne die Consumer-Felder, jeder andere Code ist
  ein Fehler; `sizeLimitExceeded` und mehr als 64 Antworten auch.
- 2026-11-13 (T3): Ein `contextCSN`, das nicht die Form von OpenLDAP 2.4+ hat (`lutil_csnstr`), ist ein Fehler statt
  still übergangen; kein Fehler zitiert DN oder Wert. `timeLimit` 0: die Frist der Probe beendet die Sitzung.
- 2026-11-13 (T3): BER-Bausteine (`berTLV`, Bind, Search) in `app_ldap.go`; `sensor_proto.go` bleibt unverändert,
  seine Leser (`berMessage`, `berNext`, `berInt`, `ldapUnbind`) werden geteilt. Die Ziel-Unit wird nicht benutzt
  (wie `bbb_recordings`): der Socket-Guard prüft den Prozess hinter dem ldapi-Socket.
- 2026-11-13 (T3): Nicht verifiziert: `olmSyncReplInstance` und `olmSRSyncPhase` unter OpenLDAP 2.5/2.6 auf einem
  echten Host (Quelle: syncrepl.c), der ldapi-Pfad unter FreeBSD.
- 2026-11-13 (T4): `version.php` (rund 1 KiB in WordPress 6 und 7) wird mit 16 KiB Obergrenze gelesen; die Datei muss
  `$wp_version` genau einmal am Zeilenanfang setzen, und der Wert muss dem engen Muster
  `X.Y[.Z][-(alpha|beta|RC)N[-Build]]` folgen (Build höchstens 8 Ziffern, Zeile endet nach `';`), sonst ein Fehler
  ohne Inhalt der Datei.
- 2026-11-13 (T4): Der Weg zur Datei: `inspectContainer`, laufend mit PID, dann `os.OpenRoot("/proc/<pid>/root")`
  (Seam `containerRoot`, Pfad als Seam `wpVersionFile`). `os.Root` folgt keinem Link aus der Wurzel; Fehler nennen
  die Datei, nie ein Linkziel (`cause`). Das Fenster zwischen Inspect und Öffnen (PID-Wiederverwendung) wird
  hingenommen: eine fremde Wurzel ohne `version.php` ist ein Fehler, keine Fehlmeldung über den Container.
- 2026-11-13 (T4): Die Datei wird zuerst nur als Pfad geöffnet (`O_PATH`, `os.Root` setzt `O_NOFOLLOW`), am Pfad-fd
  als reguläre Datei außerhalb der Dateisysteme des Kernels geprüft (`refuseKernelFile`) und dann genau sie über
  `/proc/self/fd/<n>` zum Lesen geöffnet (Seam `reopenChecked`), mit `O_NONBLOCK`, damit ein Lease das Öffnen nicht
  aufhält. Ein Link an `version.php` selbst wird darum nie gefolgt, auch nicht in der Wurzel; Verzeichnis-Links auf
  dem Weg nur innerhalb der Wurzel. Nur Linux (`app_wordpress_other.go`: `ErrUnsupported`), die lesenden Tests
  liegen in `app_wordpress_linux_test.go`. Gegenprobe: Mutanten W1–W7, W12, W14–W17, L1–L8 rot.
- 2026-11-13 (T4): Nicht verifiziert: auf einem echten Docker-Host mit dem offiziellen Image (`/var/www/html` als
  Volume); geprüft gegen `wp-includes/version.php` aus WordPress/WordPress (Master `7.2-beta5-65467`, 6.8 `6.8.12`).
- 2026-11-13 (T5): `SENSOR_TARGETS["app"]` ist die Vereinigung der Ziel-Arten der Ansichten; `Check._consistent`
  verengt sie auf die eine Art der Ansicht (`APP_VIEW_TARGETS`), `ProbeConfig` erbt das über `Check.model_validate`.
  Die Felder je Ansicht stehen im Test wörtlich (Vertrag mit `sensor_app.go`), sonst überlebte ein fehlendes Feld.
  Gegenprobe: Mutanten S1–S8, M1 rot.
- 2026-11-13 (T6): Die Karte von openldap zeigt die Replikation statt der Container-Health (Trade-off 6): das Image
  osixia/openldap 1.5.0 hat keinen eigenen HEALTHCHECK (Dockerfile geprüft), die Health-Kachel bliebe leer. Ohne
  cn=Monitor meldet der Agent `monitor` false ohne Consumer-Zahlen, die Regel auf `disconnected` greift nicht, der
  Check bleibt `unknown`; das ist der Debian-Standard (`slapd.init.ldif` lädt nur `back_mdb`, geprüft), die Doku
  (T7) nennt cn=Monitor als Voraussetzung oder das Abschalten des Checks.
- 2026-11-13 (T6): Meetings und WordPress-Version werden angezeigt, nicht bewertet (keine Regel): eine Schwelle für
  Teilnehmer oder eine „richtige“ Version kennt der Katalog nicht. `meetings` trägt `port_hint` 8090, damit die
  Prüfsumme nur an den Port von bbb-web.service geht; `recordings` liest Dateien und braucht keinen Port.
- 2026-11-13 (T6): Die Version bindet auch an die fpm-Variante: deren Entrypoint kopiert WordPress ebenso nach
  `/var/www/html` und prüft `wp-includes/version.php` (docker-library `docker-entrypoint.sh` geprüft).
- 2026-11-13 (T6): Der Test, dass die neuen App-Checks auf vorher übernommenen Instanzen still starten, steht in
  `tests/test_module_sync.py` (dort liegen die DB-Fixtures des Abgleichs); per `set-files` aufgenommen, das
  `Verify:` um die Datei erweitert. Gegenprobe: Mutanten B1–B8, O1–O6, W1–W5, S1–S2 rot.
