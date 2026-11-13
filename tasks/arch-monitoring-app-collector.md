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

### T3 — Agent: Ansicht `ldap_replication`  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_ldap.go, apps/agent/internal/probe/app_ldap_test.go, apps/agent/internal/probe/sensor_proto.go
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

### T4 — Agent: Ansicht `wordpress_version`  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_wordpress.go, apps/agent/internal/probe/app_wordpress_test.go
Änderung: `inspectContainer` des Ziels, laufend mit PID; `os.OpenRoot("/proc/<pid>/root")` (Seam für die Wurzel),
`var/www/html/wp-includes/version.php` mit Obergrenze lesen, `$wp_version = '…';` mit engem Muster prüfen, Feld
`version`. Nicht Linux → `ErrUnsupported`; Container gestoppt → Fehler. Tests: Wurzel-Verzeichnis mit echter
`version.php`-Form (Release, `-beta5-65467`, `-RC1`), fehlende Datei, Wert außerhalb des Musters (Anführungszeichen,
Leerzeichen, überlang), Symlink aus der Wurzel heraus wird nicht gefolgt, gestoppter Container.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T7
Abhängt von: T1

### T5 — Katalog: Vertrag des Fühlers `app`  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/model.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_check_configs.py
Änderung: `"app"` in `SENSORS`, `APP_VIEW_FIELDS` und `APP_VIEW_TARGETS` je Ansicht, `SENSOR_FIELDS["app"]`,
`SENSOR_TARGETS["app"]`, `AppParams(view: Literal[...])` in `PARAM_MODELS`, `field_allowed` je Ansicht;
`Check._consistent` prüft die Ziel-Art der Ansicht. Tests: jede Ansicht nimmt genau ihre Felder und ihr Ziel, ein
Feld einer anderen Ansicht, eine fremde Ziel-Art, fehlendes `view` und ein unbekannter Parameter werden abgewiesen;
`ProbeConfig` weist dasselbe ab (Gegenprobe über `check_configs`).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_catalog.py tests/test_check_configs.py
Doku: → T7

### T6 — Katalog: Module bigbluebutton, openldap, wordpress Version 2  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/bigbluebutton.py, apps/monitoring/app/catalog/modules/openldap.py, apps/monitoring/app/catalog/modules/wordpress.py, apps/monitoring/tests/test_catalog_bigbluebutton.py, apps/monitoring/tests/test_catalog_openldap.py, apps/monitoring/tests/test_catalog_wordpress.py
Änderung: bigbluebutton: Checks `meetings` (`bbb_meetings`, Unit, Port-Hinweis 8090, 300 s) und `recordings`
(`bbb_recordings`, 900 s, `failed gt 0` warning) mit Karten-Einträgen; openldap: Check `replication`
(`ldap_replication`, Unit, 300 s, `disconnected gt 0` warning), Karte nach Trade-off 6 der Spec; wordpress: Check
`version` (`wordpress_version`, Container, 3600 s) mit Karten-Eintrag; je Version 2, Docstring mit Quellen und
nachgezogenem „Not covered“ (`bbb-conf --check` nie). Tests: `probe_config` bindet die neuen Checks an native
bzw. Container-Instanzen und überspringt sie, wo die Ziel-Art fehlt (openldap im Container); jede neue Regel feuert
an ihrer Schwelle und nicht darunter (`ProbeChecker().evaluate`); Karte wie erwartet; `sync_catalog` legt die neuen
Checks bei einer übernommenen Version-1-Instanz still an.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_bigbluebutton.py tests/test_catalog_openldap.py tests/test_catalog_wordpress.py tests/test_catalog_apps.py tests/test_catalog.py
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
