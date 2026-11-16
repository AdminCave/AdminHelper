<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-28 — Web-Domains aus vHosts, Zertifikate und native PHP-Apps

Roadmap: R-1435 (Domains aus vHosts, Zertifikatsdateien, Datei gegen ausgeliefert; nginx, Apache, HAProxy), R-1378
(PHP-Apps nativ: HTTP-Health über den passenden vHost), R-1422 (Moodle `admin/cli/checks.php` als
Webserver-Benutzer). Kevin 2026-11-09 diktiert (Monitoring-Konzept §6.1, §3.7, §6.10), vor dem Release 0.47.0;
R-1378/R-1422 am 2026-11-13/14 in diesen Zug gelegt. Kevin 2026-11-15: **Domain als Instanz**: Die Namen der vHosts
gehen als Instanz zum Monitoring-Server; das ist eine Ausnahme von der Regel „nur Zahlen, Booleans und Zustände“, die
nur für Web-Domains gilt.

## Problem / Motivation

Die Module nginx, Apache und HAProxy (kern-monitoring-8) prüfen heute die Unit, den Konfigurationstest und die
Statusseite. Was ein Admin bei einem Webserver am häufigsten übersieht, bleibt dagegen ungeprüft:

- ein Zertifikat läuft ab;
- certbot hat das Zertifikat erneuert, aber der Webserver wurde nicht neu geladen und liefert weiter das alte aus
  (Konzept §3.7: „Datei neu, ausgeliefert alt → der Reload fehlt“).

Dazu kommen PHP-Anwendungen, die nativ hinter nginx oder Apache laufen: Nextcloud, Moodle, WordPress und BookStack.
Der Katalog erkennt sie nur als Container. Ohne vHost-Liste weiß das Monitoring nicht, unter welchem Namen und Port
die Anwendung antwortet.

## Ziel & Nicht-Ziele

**Ziel:**

- Die Discovery des Agents liest die vHosts von nginx (`nginx -T`) und Apache (`apachectl -S` und die genannten
  Dateien). Je vHost meldet sie: Server, Name, Port, TLS ja/nein und, falls erkannt, die Anwendung im
  Dokumentverzeichnis.
- Aus jedem TLS-vHost wird eine Instanz `<domain>` des neuen Moduls `web_domain` mit einem Zertifikats-Check:
  - Restlaufzeit der Datei und des ausgelieferten Zertifikats;
  - `reload_missing` (Datei und Auslieferung verschieden, die Datei läuft länger);
  - `hostname_ok` und `chain_ok` des ausgelieferten Zertifikats.
- HAProxy: Restlaufzeit der Zertifikatsdateien aus `bind … crt`, nur als Zahlen am Unit-Modul.
- Native PHP-Apps (R-1378): neue Module je App mit der Instanzart `vhost`. Der `http`-Fühler fragt die App über
  Loopback am Port des vHosts, mit dem vHost-Namen als Host und SNI: Nextcloud `status.php`, Moodle die Login-Seite,
  WordPress `wp-login.php`, BookStack `/status`.
- Moodle (R-1422): die Ansicht `moodle_checks` startet `php admin/cli/checks.php` als Webserver-Benutzer
  (`runuser -u <user> --`). Sie meldet nur den Nagios-Zustand und die Zahl der nicht-OK-Checks.

**Leitplanken** (Konzept §3.13, Kevin 2026-11-09):

- nur feste Lesebefehle der Freigabeliste;
- kein Dienst verliert spürbar Leistung: Zertifikats-Checks laufen stündlich, die App-Health alle 5 Minuten,
  `checks.php` alle 15 Minuten;
- zum Server gehen Zahlen, Booleans, Zustände und, nach Kevins Ausnahme, die Domainnamen der vHosts. Nie zum Server
  gehen Pfade (Dokumentverzeichnis, Zertifikatsdatei), Konfigurationstext und Inhalte. Den Pfad leitet der Agent zur
  Prüfzeit neu aus der Konfiguration ab.

**Nicht-Ziele (je eine neue Roadmap-Zeile am Gate):**

- zentrale Domain-Checks für vHost-Domains: Auflösung gegen Baseline, Delegation, DNSSEC, CAA, RDAP (Konzept §6.1,
  Zeile „Domains“);
- HAProxy: Datei gegen ausgeliefert (ohne SNI liefert HAProxy nur das Standard-Zertifikat);
- vHosts von nginx oder Apache im Container;
- Moodle: Platz und Inodes in moodledata.

Sperrliste: `/admin/cron.php` und `scheduled_task.php --execute` (Konzept §6.10), nginx `-s`, `apachectl
graceful|restart`. Der private Schlüssel eines Zertifikats wird nie geöffnet.

## Betroffene Komponenten & Dateien

**Agent** (`apps/agent/`):

- neu `internal/probe/web_vhosts.go` und `web_vhosts_test.go` (SPDX), exportiert `WebVhosts`. Der Parser nutzt
  `splitNginxDump`/`nginxTokens` aus `app_web.go` und `apacheIncludes`, für Apache dazu `apachectl -S`;
- `internal/discovery/discovery.go`: neuer Block `vhosts`;
- `internal/probe/target.go`, `probe.go`: Zielart `vhost`. Sie wird zum Loopback-Endpunkt am Port des vHosts, durch
  den Wächter, mit dem Namen als SNI und Host;
- `internal/probe/sensor_app.go`: Ansichten `web_vhost_cert`, `haproxy_certs`, `moodle_checks`;
- `internal/probe/sensor_http.go`, `sensor_tls.go`: Zielart `vhost`;
- `internal/allowlist/allowlist.go`: `apache2ctl -S` und `apachectl -S`, dazu `runuser -u <user> -- php
  <wurzel>/admin/cli/checks.php`.

**Monitoring** (`apps/monitoring/app/`):

- `discovery.py`: `clean_inventory` um `vhosts` (MAX_VHOSTS, Name als DNS-Name), Instanzart `vhost` in `_instances`;
- `catalog/model.py`: `Detect.vhost_apps`, `vhost_tls`, Instanzart und Zielart `vhost`;
- `catalog/sensors.py`: Ziele und Ansichten;
- `module_sync.py` (`_target_name`) und `check_configs.py`: Zielart `vhost` braucht einen Namen;
- neue Module `web_domain`, `nextcloud_native`, `moodle_native`, `wordpress_native`, `bookstack_native`
  (SPDX), dazu `haproxy.py` (Zertifikats-Check);
- Tests `test_discovery_match.py`, `test_catalog_web.py`, `test_catalog_apps.py`, `test_catalog_moodle.py`.

**Doku:** `docs/developer/agent.html` und `docs/en/…` (Ansichten, Zielart), die Monitoring-Seite mit den Modulen
(DE+EN), `changelog.d/kern-monitoring-28.md`.

## Datenmodell / API / Migrationen

- **Agent → Monitoring:** neues Feld `vhosts` im Discovery-Block, eine Liste von `{server, name, port, tls, app}`.
  Ältere Agents senden das Feld nicht; `clean_inventory` nimmt dann `[]`. Ein älterer Monitoring-Dienst verwirft das
  unbekannte Feld (bestehendes Verhalten von `clean_inventory`).
- **Monitoring → Agent:** neue Zielart `vhost` mit `name` = Domain und `port_hint` = Port. Ein älterer Agent meldet für
  sie `invalid` (bestehendes Verhalten von `resolve`). Er bekommt die Checks erst, wenn sein Discovery-Block `vhosts`
  trägt, also nie.
- Keine Alembic-Migration: Instanzen und Funde liegen in den bestehenden Tabellen.
- Kein Vertrag mit Web oder Desktop: `ProbeTarget.kind` ist dort ein freier Text, und die OpenAPI ändert sich nicht.

## Externe Integrationen

- nginx: `nginx -T` (nginx.org/en/docs/switches.html), Direktiven `server_name`, `listen … ssl`, `ssl_certificate`,
  `root`.
- Apache: `apachectl -S` (httpd.apache.org/docs/2.4/programs/apachectl.html, „-S: show the settings as parsed from
  the config file“). Die Form der Ausgabe ist **nicht dokumentiert**; T2 prüft sie gegen ein echtes httpd 2.4
  (Docker-Image `httpd`) und hält die Version fest.
- Moodle `admin/cli/checks.php` (docs.moodle.org, Check API; Nagios-Exitcodes 0–3). Die Optionen liest T6 per
  WebFetch nach, bevor gebaut wird: **nicht verifiziert**.
- Nextcloud `status.php` (JSON `installed`, `maintenance`, `needsDbUpgrade`), wie im bestehenden Container-Modul.

## Trade-offs & Alternativen

- **Ein Parser für Discovery und Prüfzeit** (empfohlen): `WebVhosts` liegt im Paket `probe`, und die Discovery ruft
  ihn auf. Der Pfad der Zertifikatsdatei verlässt den Host nie; der Check sucht ihn zur Prüfzeit neu. Das kostet ein
  `nginx -T` je Stunde und Domain. Bei vielen vHosts liest ein Cache je Lauf die Konfiguration nur einmal (60 s).
- **Instanz nur für TLS-vHosts:** Ein vHost ohne TLS und ohne erkannte App hätte keinen Check. Er würde nur den
  Funde-Eingang füllen.
- **Native Apps als eigene Module** statt einer zweiten Instanzart je Modul: Ein Modul hat genau eine Instanzart.
  Gleiche Checks in zwei Modulen sind einfacher als ein Umbau des Modells.
- **HAProxy nur als Zahlen am Unit-Modul:** HAProxy kennt keinen `server_name`; die Namen stecken in den
  Zertifikaten. Sie aus den SANs zu ziehen, ginge über Kevins Ausnahme hinaus, die nur vHost-Namen nennt.

## Risiken & Rollback

- **Domainnamen in der Monitoring-DB** (Kevins Ausnahme): Sie stehen im Funde-Eingang und an den Instanzen. Interne
  Namen (`intranet.schule.lan`) gehen mit. Wildcards, `_`, `localhost`, IP-Adressen und Namen über 120 Zeichen
  werden ausgelassen.
- **Allowlist:** `apachectl -S` startet nichts; es ist `-t -D DUMP_VHOSTS`. `php checks.php` führt Code der App aus,
  und zwar ausdrücklich so, wie das Konzept es vorsieht. Das Argument ist genau ein Pfad, der auf
  `/admin/cli/checks.php` endet und den der Agent aus der Konfiguration des Webservers liest; laufen darf es nur als
  der `user` aus nginx bzw. `APACHE_RUN_USER`, nie als root. Ein `security`-Review je Task mit Freigabeliste.
- **Last:** pro Domain zwei Handshakes je Stunde (je Check einer) an der Adresse, auf der der Webserver lauscht, meist Loopback, pro App ein HTTP-Abruf je 5 Minuten.
- **Rollback:** einzelne Task-Commits zurücknehmen; der Block `vhosts` ist optional.

## Doku-Impact

Agent-Entwicklerseite (Ansichten, Zielart `vhost`, Freigabeliste) und Monitoring-Modulseite (neue Module, die
Ausnahme für Domainnamen), DE+EN, dazu das CHANGELOG-Fragment; gebündelt in T8.

## Offene Fragen

Keine aus Kevins Bereich. Die Ausnahme für Domainnamen hat Kevin am 2026-11-15 entschieden. Nicht verifiziert bis
zur Task: die Ausgabe von `apachectl -S` (T2) und die Optionen von `checks.php` (T6).
