<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Fühler `app` für Anwendungs-Innenleben (`arch-monitoring-app-collector`, Roadmap R-1404)

## Problem / Motivation

Die Katalog-Module für BigBlueButton, OpenLDAP und WordPress (R-1242, R-1243) sehen heute nur, ob der Dienst läuft
und antwortet. Was Betreiber wirklich wissen wollen, liegt eine Ebene tiefer: wie viele Konferenzen und Teilnehmer
BigBlueButton gerade trägt und ob Aufzeichnungen in der Verarbeitung hängen geblieben sind, ob ein OpenLDAP-Replikat
noch mit seinem Provider verbunden ist, welche WordPress-Version ein Container ausliefert. Die Docstrings der Module
nennen diese Lücken ausdrücklich („Not covered: getMeetings …, the *.fail files …“, „replication (contextCSN) and
cn=Monitor“, „its version and cron“).

Das Monitoring-Konzept (privat, `tasks/private/monitoring-module-konzept.md`, Kevin 2026-11-09) setzt die Grenzen:
Monitoring kostet den Dienst keine Leistung; der Server schickt nur Parameter an einkompilierte Fühler, nie Befehle;
ein Agent prüft nur seinen eigenen Host; Zugangsdaten bleiben lokal; zum Server gehen nur Felder einer Allowlist, nie
ganze Ausgaben, Konfigurationsinhalte, Geheimnisse oder Personennamen.

## Ziel & Nicht-Ziele

**Ziel:** ein neuer Agent-Fühler `app` mit dem Pflicht-Parameter `view` (Muster `opnsense`, `sensor_opnsense.go:24`),
der vier fest einkompilierte, rein lesende Ansichten liefert; der Katalog kennt ihre Felder und Ziele; die Module
`bigbluebutton`, `openldap` und `wordpress` steigen auf Version 2 und bringen die neuen Checks mit.

| Ansicht | Ziel | Intervall | Felder | Standard-Regel |
|---|---|---|---|---|
| `bbb_meetings` | `unit` (Port-Hinweis 8090, über `resolve`) | 300 s | `meetings`, `running`, `participants`, `listeners`, `voice`, `video`, `recording` | keine |
| `bbb_recordings` | `unit` | 900 s | `failed`, `archive_failed`, `sanity_failed`, `process_failed`, `publish_failed`, `newest_fail_age_s` | `failed gt 0` → warning |
| `ldap_replication` | `unit` | 300 s | `contexts`, `csn_age_s`, `monitor`, `consumers`, `disconnected`, `refreshing` | `disconnected gt 0` → warning |
| `wordpress_version` | `container` | 3600 s | `version` | keine |

- **`bbb_meetings`:** liest `securitySalt` und `supportedChecksumAlgorithms` lokal aus
  `/etc/bigbluebutton/bbb-web.properties` (Override, zuerst) und sonst aus
  `/usr/share/bbb-web/WEB-INF/classes/bigbluebutton.properties`, bildet die Prüfsumme
  `hex(sha256("getMeetings" + salt))` (sha256, sonst der stärkste erlaubte Algorithmus) und fragt
  `GET /bigbluebutton/api/getMeetings?checksum=…` an bbb-web auf dem Port der Unit (über `resolve` und den
  Ziel-Wächter, wie der HTTP-Fühler). Die Antwort wird gestreamt (`encoding/xml`, `Decoder.Token`) mit einer
  Obergrenze gelesen; gezählt werden nur Zahlen- und Wahrheitsfelder je `<meeting>`. Namen, Passwörter
  (`attendeePW`, `moderatorPW`), Teilnehmer (`fullName`, `userID`) und Metadaten werden nie gelesen, gespeichert oder
  gemeldet. `returncode FAILED` (außer `messageKey noMeetings`) ist ein Fehler mit dem `messageKey`, ohne Body, URL,
  Prüfsumme oder Salt.
- **`bbb_recordings`:** zählt die Marker `status/archived/<id>.fail`, `status/sanity/<id>.fail`,
  `status/processed/<id>-<format>.fail` und `status/published/<id>-<format>.fail` unter
  `/var/bigbluebutton/recording`; `newest_fail_age_s` ist das Alter des jüngsten Markers und fehlt ohne Marker. Fehlt
  das Status-Verzeichnis, ist die Ansicht `ErrUnsupported`. Liest nur Verzeichniseinträge (je Verzeichnis mit
  Obergrenze) und die mtime der `.fail`-Dateien, nie ihren Inhalt.
- **`ldap_replication`:** verbindet sich über `dialUnix` (Ziel-Wächter für Unix-Sockets) mit dem ldapi-Socket
  (`/var/run/slapd/ldapi`, Debian/Ubuntu; `/var/run/ldapi`), bindet SASL EXTERNAL, liest aus dem Root-DSE die
  `namingContexts` und je Kontext `contextCSN` (Format `YYYYmmddHHMMSS.ffffffZ#count#sid#mod`): `contexts` zählt die
  Kontexte mit CSN, `csn_age_s` ist das Alter des jüngsten CSN. Ist `cn=Monitor` eingerichtet und lesbar, zählt die
  Ansicht die Einträge `(objectClass=olmSyncReplInstance)` (`cn=Consumer NNN`): `consumers`, `disconnected` (leeres
  `olmSRConnection`), `refreshing` (`olmSRSyncPhase` ungleich `Persist`); sonst `monitor=false`. Nie angefragt wird
  `olmSRProviderURIList` (Adressen anderer Hosts), nie ein Eintrag außer Root-DSE, Kontext-Wurzel und Monitor-Zweig.
  Obergrenzen: 16 Kontexte, 64 Consumer, `maxBERBytes` je Nachricht.
- **`wordpress_version`:** holt mit `inspectContainer` die PID des laufenden Containers, öffnet `/proc/<pid>/root` mit
  `os.OpenRoot` und liest höchstens wenige KiB von `var/www/html/wp-includes/version.php`; `version` ist der Wert von
  `$wp_version`, nur wenn er auf ein enges Muster passt (Ziffern, Punkte, optional `-beta…`/`-RC…`/`-alpha…` mit
  Build-Nummer). Symlinks, die aus dem Container-Root führen, lehnt `os.Root` ab. Nur Linux; sonst `ErrUnsupported`.

**Nicht-Ziele** (mit Begründung, als `neu`-Zeilen in der Roadmap, wo sie später kommen können):
- **`bbb-conf --check`** wird nie ausgeführt: es schreibt und löscht als root `/tmp/t`, fragt einen externen
  STUN-Server, greppt alle BBB-Logs und gibt Freitext aus. Kommt in die Liste „Nie aufgerufen“ der Doku.
- **Moodle `admin/cli/checks.php`**: kein bindbares Ziel. Nativ braucht es die vHost-Erkennung (R-1231, nicht
  gebaut), im Container `docker exec`, das das Konzept nur dem Scan erlaubt. Neue Zeile, hängt von R-1231 ab.
- **WordPress-Cron:** braucht die Site-Datenbank (Option `cron`, Zugangsdaten aus `wp-config.php`, die Datenbank im
  Nachbar-Container). Neue Zeile.
- **OpenLDAP-Verzug über Hosts** (contextCSN von Provider und Consumer vergleichen): geht nur auf dem Server über die
  Werte zweier Agents; der Agent selbst fragt nie einen anderen Host. Neue Zeile.
- **ldapi im Container** (osixia/openldap): der Socket liegt im Container-Dateisystem; v1 bindet die Ansicht an die
  Unit des Pakets.
- **Kein exec, keine neue Allowlist-Zeile, keine Zugangsdaten-Slots:** alle Ansichten lesen Dateien, die
  Loopback-API und den ldapi-Socket.

## Betroffene Komponenten & Dateien

**Agent** (`apps/agent/internal/probe`, Paket `probe`, damit `resolve` (`target.go:105`), `targetOf`
(`target.go:51`), `inspectContainer` (`sensor_local.go:222`), `dialUnix` (`sensor_local_linux.go:137`) und die
BER-Helfer aus `sensor_proto.go` (`ldapExtended` :540, `berLength` :605, `berNext` :624, `berInt` :637,
`maxBERBytes` :37) ohne Export wiederverwendet werden):
- neu `sensor_app.go`: Registrierung `sensors["app"]`, `knownParams(p, "view")`, `choiceParam` über die vier
  Ansichten, Ziel-Art je Ansicht (`targetOf(p, kind)`), Verteilung.
- neu `app_bbb.go` (beide BBB-Ansichten), `app_ldap.go`, `app_wordpress.go`, je mit `_test.go`; SPDX-Header über
  `reuse annotate`. Datei-Zugriffe über Seams (`statPath`, neue `readFileCapped`/`readDirNames` bzw. ein
  Wurzel-Seam), damit Tests ohne echten Host laufen.

**Monitoring** (`apps/monitoring`):
- `app/catalog/sensors.py`: `"app"` in `SENSORS` (:25), `APP_VIEW_FIELDS` und `APP_VIEW_TARGETS` neben
  `OPNSENSE_VIEW_FIELDS` (:44), `SENSOR_FIELDS["app"]` als Vereinigung, `SENSOR_TARGETS["app"] = {"unit",
  "container"}` (:108), `AppParams(view: Literal[...])` neben `OpnsenseParams` (:206) und in `PARAM_MODELS`,
  `field_allowed` (:228) je Ansicht.
- `app/catalog/model.py`: `Check._consistent` (:172) prüft für `app` die Ziel-Art der Ansicht (`APP_VIEW_TARGETS`);
  `ProbeConfig._fits_the_catalog` (`app/check_configs.py:216`) erbt das über `Check.model_validate`.
- `app/catalog/modules/{bigbluebutton,openldap,wordpress}.py`: Version 2, neue Checks und Karten-Einträge,
  Docstrings („Not covered“ nachgezogen).
- Tests: `tests/test_catalog_sensors.py`, `tests/test_check_configs.py`, `tests/test_catalog_bigbluebutton.py`,
  `tests/test_catalog_openldap.py`, `tests/test_catalog_wordpress.py`.

**Doku:** `docs/admin/monitoring.html` + `docs/en/admin/monitoring.html` (Modul-Zeilen, Liste „Nie aufgerufen“,
Voraussetzungen), `docs/developer/agent.html` + `docs/en/developer/agent.html` (Fühler-Liste), bei Bedarf
`docs/developer/monitoring.html` + en, `changelog.d/arch-monitoring-app-collector.md`.

Web- und Desktop-UI ändern sich nicht: ein neuer Probe-Fühler braucht dort nichts (der OPNsense-Fühler, Commit
1eec01481, änderte nur Agent, `model.py`, `sensors.py` und Tests).

## Datenmodell / API / Migrationen

- **Keine Alembic-Migration, keine neue Route.** Neue Checks entstehen aus dem Katalog: `sync_catalog`
  (`app/module_sync.py:307`) legt sie bei übernommenen Instanzen still an und setzt den Fund auf „changed“, der Admin
  übernimmt sie (bestehender Weg).
- **Vertrag Server ↔ Agent:** neuer Fühlername `app` mit `params.view`. Ein alter Agent kennt den Fühler nicht und
  meldet den Check als nicht unterstützt (unknown), wie beim OPNsense-Fühler; die Doku nennt die Mindestversion.
- **Felder:** nur Zahlen, Wahrheitswerte und die geprüfte Versionszeichenkette; die Katalog-Allowlist
  (`APP_VIEW_FIELDS`) lässt nichts anderes zu.
- **Katalog-Version:** bigbluebutton, openldap, wordpress → 2; `catalog.version` ändert sich dadurch.

## Externe Integrationen

Belegt im Quelltext der Projekte (Stand der Recherche 2026-11-13; Quellen im Docstring der Module):
- **BigBlueButton 3.0/4.0** (`bigbluebutton/bigbluebutton`, `bbb-common-web` `GetChecksumValidator`,
  `bbb-web` `get-meetings.ftlx`, `bigbluebutton-config/bin/bbb-conf`, `record-and-playback/core/scripts/*.rb`):
  Prüfsumme, Properties-Pfade, Antwortform von getMeetings, `.fail`-Marker, Verhalten von `bbb-conf --check`.
- **OpenLDAP 2.6** (`servers/slapd/syncrepl.c` für `olmSyncReplInstance` und `olmSR*`; Debian-Patch
  `ldapi-socket-place` für `/var/run/slapd/ldapi`; RFC 4513 §5.2.1.2 für SASL EXTERNAL; RFC 4511 für Search).
- **WordPress** (`wp-includes/version.php`, `$wp_version`); offizielles Image mit `VOLUME /var/www/html`.
- Vor jeder Agent-Task werden die konkreten Formate erneut gegen diese Quellen geprüft; Unbelegtes steht als „nicht
  verifiziert“ in Task und Commit (etwa der ldapi-Pfad unter FreeBSD).

## Trade-offs & Alternativen

1. **Ein Fühler mit Ansichten statt eines Fühlers je Anwendung** (empfohlen): ein Name im Vertrag, eine
   Allowlist-Tabelle im Katalog, dasselbe Muster wie `opnsense`. Alternative: `bbb`, `ldap_repl`, `wp_version` als
   eigene Fühler; mehr Vertragsfläche ohne Gewinn.
2. **Im Paket `probe` statt eigenem Paket** wie `internal/opnsense`: die Ansichten brauchen `resolve`, den
   Ziel-Wächter, `dialUnix`, `inspectContainer` und die BER-Helfer; ein eigenes Paket müsste sie exportieren oder
   kopieren.
3. **Kein exec:** `bbb-conf --check`, `wp core version` (wp-cli) und `ldapsearch` wären bequemer, laufen aber als
   fremde Programme mit Seiteneffekten (Schreiben, Netz, Laufzeit) und bräuchten Allowlist-Zeilen. Dateien, Loopback-
   API und ldapi liefern dieselben Zahlen ohne Prozessstart.
4. **getMeetings statt der Redis-Daten von BBB:** die API ist der dokumentierte Weg; Redis-Schlüssel sind intern.
5. **WordPress-Version aus der Datei statt aus der REST-API:** die REST-Antwort nennt die Version nicht; `generator`
   im HTML hängt von Theme und Plugins ab und ist abschaltbar.
6. **Karte openldap (6 Einträge, voll, `model.py:206`):** Empfehlung: „Container health“ durch „Replication“
   (`disconnected`) ersetzen; das Image osixia/openldap bringt keinen eigenen HEALTHCHECK mit (bei der Task
   gegenprüfen), der Wert ist dort meist `none`.

## Risiken & Rollback

- **Geheimnisse:** Salt und getMeetings-Body. Gegenmaßnahme: der Salt verlässt die Funktion nur als Prüfsumme in der
  Loopback-URL; Fehlertexte nennen nie URL, Body, Salt oder Prüfsumme; der XML-Leser liest nur die gezählten
  Elemente. Negativ-Test: ein Fixture mit Namen, Passwörtern, Teilnehmern und Metadaten, das weder in Werten noch in
  Fehlern auftaucht.
- **Leistung:** getMeetings alle 5 min ist eine In-Memory-Liste in bbb-web; der Recording-Scan liest nur
  Verzeichnisse alle 15 min (Obergrenze je Verzeichnis); ldapi-Searches lesen ein bis 16 Einträge plus den
  Monitor-Zweig; die Versionsdatei einmal je Stunde. Kein Check startet einen Prozess.
- **Fremde Hosts:** `olmSRProviderURIList` wird nie angefragt; kein Netzwerkziel außer der eigenen Unit.
- **Container-Wurzel:** `/proc/<pid>/root` mit `os.OpenRoot`; eine zwischen Inspect und Open neu vergebene PID liest
  höchstens eine fremde Datei an demselben Pfad und meldet nur eine geprüfte Versionszeichenkette.
- **Rollback:** Revert des Merges; Katalog-Version fällt zurück, `sync_catalog` legt nichts neu an, bestehende
  `app`-Checks bleiben (sie werden beim alten Agent unknown) und lassen sich abschalten.

## Doku-Impact

Admin-Doku DE+EN: Modul-Zeilen BigBlueButton, OpenLDAP, WordPress (neue Checks, Voraussetzungen: Agent-Mindestversion,
cn=Monitor für die Consumer-Zahlen, Grenzen), Liste „Nie aufgerufen“ um `bbb-conf --check`; Entwickler-Doku DE+EN:
Fühler `app` und seine Ansichten in der Fühler-Liste; CHANGELOG `### Added`.

## Offene Fragen

1. **Schnitt bestätigen (Kevin):** v1 baut die vier Ansichten oben; Moodle `checks.php`, WordPress-Cron,
   OpenLDAP-Verzug über Hosts und `bbb-conf --check` fahren nicht mit (Gründe unter Nicht-Ziele). Empfehlung: ja;
   die ersten drei als `neu`-Zeilen, `bbb-conf --check` dauerhaft „nie“.
2. **Standard-Regeln (Kevin, sichtbares Verhalten):** `bbb_recordings` warnt ab einem `.fail`-Marker,
   `ldap_replication` warnt ab einem getrennten Consumer; Meetings und Version ohne Regel. Empfehlung: so, weil ein
   `.fail` eine verlorene Aufzeichnung bedeutet und ein getrennter Consumer veraltete Daten liefert; Schwellen für
   Teilnehmerzahlen kennt nur der Betreiber.
