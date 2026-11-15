<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web-Domains aus vHosts, Zertifikate und native PHP-Apps — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-28 · Review: pro Task
Spec: docs/features/kern-monitoring-28.md (Roadmap R-1435, R-1378, R-1422)
Heavy: linux-full — neue Discovery, Zielart, Ansichten und Freigabeliste im Agent (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vor T1 `origin/main` in den Branch mergen. Domainnamen dürfen als Instanz zum Server (Kevin 2026-11-15); Pfade,
Konfigurationstext und Inhalte nie.

### T1 — R-1435: vHosts von nginx in der Discovery  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhosts.go, apps/agent/internal/probe/web_vhosts_test.go, apps/agent/internal/probe/app_web.go, apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @3422d0759 2026-11-15T03:58:34+01:00
Review: approve (.ah-out/review/kern-monitoring-28/T1.verdict.json)
Änderung: `WebVhosts` liest aus `nginx -T` je `server` die Namen, den Port, ob `ssl`, und, falls erkannt, die App im
`root`: Nextcloud (`occ` und `status.php`), Moodle (`admin/cli/checks.php`), WordPress (`wp-login.php`), BookStack
(`../artisan` mit `bookstack` in `../composer.json`). Die Discovery meldet daraus den Block `vhosts` mit `{server,
name, port, tls, app}`, gedeckelt (maxVhosts). Wildcards, `_`, `localhost` und IP-Adressen werden ausgelassen. Neue
Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/discovery/
Doku: → T8

### T2 — R-1435: vHosts von Apache  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhosts.go, apps/agent/internal/probe/web_vhosts_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/probe/web_vhosts_apache_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @40e1e44ff 2026-11-15T04:20:04+01:00
Review: approve (.ah-out/review/kern-monitoring-28/T2.verdict.json)
Änderung: `apache2ctl -S` / `apachectl -S` in die Freigabeliste. `WebVhosts` liest `namevhost` und `alias` mit Port
und der Datei:Zeile, dort `SSLEngine on`, `SSLCertificateFile` und `DocumentRoot` des `<VirtualHost>`. Die Form der
Ausgabe gegen ein echtes httpd 2.4 (Docker `httpd:2.4`) prüfen und die Version im Kommentar nennen. Fixture aus
dieser Ausgabe.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T8
Abhängt von: T1

### T3 — R-1435: Zielart vhost und Zertifikats-Ansichten  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/web_vhosts.go, apps/agent/internal/probe/web_vhosts_apache_linux_test.go, apps/agent/internal/probe/web_vhost_cert.go, apps/agent/internal/probe/web_vhost_cert_linux_test.go, apps/agent/internal/probe/app_proxy.go, apps/agent/internal/probe/app_haproxy.go, apps/agent/internal/probe/app_haproxy_certs_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @2d11d2952 2026-11-15T04:37:08+01:00
Review: approve (.ah-out/review/kern-monitoring-28/T3.verdict.json)
Änderung: Zielart `vhost` (Name = Domain, `port_hint` = Port). `resolve` macht daraus Loopback am Port durch den
Wächter. Ansicht `web_vhost_cert`: sucht zur Prüfzeit über `WebVhosts` den vHost und dessen Zertifikatsdatei
(Cache 60 s), liest die Datei (nur das Zertifikat, nie den Schlüssel) und schüttelt mit SNI die Hand. Felder:
`file_days_left`, `served_days_left`, `reload_missing`, `hostname_ok`, `chain_ok`. Ansicht `haproxy_certs` an die
Unit: Dateien aus `bind … crt` (Datei oder Verzeichnis, höchstens 256), Felder `certs`, `min_days_left`,
`expiring_14d`. Neue Dateien mit SPDX-Header; der Test hat ein eigenes Test-Zertifikat und einen Loopback-Server.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8
Abhängt von: T2

### T4 — R-1435: Instanz vhost und Modul web_domain  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/app/catalog/model.py, apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/check_configs.py, apps/monitoring/app/catalog/modules/web_domain.py, apps/monitoring/app/catalog/modules/haproxy.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_catalog_web.py, apps/monitoring/tests/test_catalog_sensors.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @a9529b788 2026-11-15T04:51:57+01:00
Review: approve (.ah-out/review/kern-monitoring-28/T4.verdict.json)
Änderung: `clean_inventory` um `vhosts` (MAX_VHOSTS, Name als DNS-Name kleingeschrieben, `app` aus fester Menge).
Dazu kommen Instanzart und Zielart `vhost` sowie `Detect.vhost_tls` und `vhost_apps`. `_target_name` liefert für
`vhost` den Schlüssel und als `port_hint` den Port aus der Zusammenfassung. Neues Modul `web_domain`: je TLS-vHost
den Check `web_vhost_cert` stündlich, mit diesen Regeln:
- `served_days_left` < 14 → warning, < 3 → critical;
- `reload_missing` → warning;
- `hostname_ok` falsch → critical.

HAProxy bekommt den Check `haproxy_certs` täglich. Neue Datei mit SPDX-Header; Ober- und Untergrenzen im Test.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py tests/test_catalog_web.py tests/test_catalog_sensors.py tests/test_catalog.py
Doku: → T8
Abhängt von: T3

### T5 — R-1378: http- und tls-Fühler über den vHost  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_http_test.go, apps/agent/internal/probe/sensor_tls.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @872bb3c19 2026-11-15T04:57:00+01:00
Review: approve (.ah-out/review/kern-monitoring-28/T5.verdict.json)
Änderung: `http` und `tls` nehmen die Zielart `vhost`: Loopback am Port, `Host` und SNI sind der vHost-Name;
`https` bei `tls`. Es gibt keine Umleitung auf einen anderen Host. Der Test hat einen Loopback-Server mit zwei Namen
und prüft, dass der richtige antwortet.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8
Abhängt von: T3

### T6 — R-1422: Ansicht moodle_checks  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_moodle.go, apps/agent/internal/probe/app_moodle_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: Vorher die Optionen von `admin/cli/checks.php` in der Moodle-Doku nachlesen (WebFetch) und im Kommentar
belegen. `moodle_checks` an die Zielart `vhost` liest so: Wurzel und Webserver-Benutzer zur Prüfzeit aus
`WebVhosts` (nginx `user`, Apache `APACHE_RUN_USER` aus `envvars`), dann `runuser -u <user> -- php
<wurzel>/admin/cli/checks.php`. Die Freigabeliste nimmt nur einen absoluten Pfad, der auf `/admin/cli/checks.php`
endet, und nie root als Benutzer. Felder: `state` (ok/warning/critical/unknown aus dem Exitcode), `not_ok` (Zahl der
nicht-OK-Zeilen), nie Text. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T8
Abhängt von: T3

### T7 — R-1378, R-1422: native PHP-App-Module  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/nextcloud_native.py, apps/monitoring/app/catalog/modules/moodle_native.py, apps/monitoring/app/catalog/modules/wordpress_native.py, apps/monitoring/app/catalog/modules/bookstack_native.py, apps/monitoring/app/catalog/sensors.py, apps/monitoring/tests/test_catalog_apps.py, apps/monitoring/tests/test_catalog_moodle.py, apps/monitoring/tests/test_discovery_match.py
Änderung: Je App ein Modul mit Instanzart `vhost` und `detect.vhost_apps`, alle 5 Minuten:
- Nextcloud: `status.php`, `installed`/`maintenance`/`needsDbUpgrade` wie das Container-Modul;
- Moodle: `/login/index.php` 200;
- WordPress: `/wp-login.php` 200;
- BookStack: `/status`.

Moodle zusätzlich `moodle_checks` alle 15 Minuten, `state` critical → critical, warning → warning. Die Erkennung ist
im Test belegt: dieselbe Domain in zwei Modulen (`web_domain` und App) ergibt zwei Funde. Neue Dateien mit
SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_apps.py tests/test_catalog_moodle.py tests/test_discovery_match.py tests/test_catalog_sensors.py tests/test_catalog.py
Doku: → T8
Abhängt von: T4, T5, T6

### T8 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-28.md
Änderung: Agent-Seite: Block `vhosts`, Zielart `vhost`, Ansichten `web_vhost_cert`, `haproxy_certs`,
`moodle_checks`, Freigabeliste. `docs/admin/monitoring.html` und `docs/developer/monitoring.html`: neue Module, Instanzart `vhost` und die
Ausnahme für Domainnamen, DE+EN. `changelog.d/kern-monitoring-28.md` unter `### Added`, ohne Umlaute.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende
Abhängt von: T7

## Entscheidungen
- 2026-11-15 Kevin: Domain als Instanz (Domainnamen der vHosts gehen zum Monitoring-Server).
- Nicht in diesem Zug (neue Zeilen am Gate): zentrale Domain-Checks für vHost-Domains, HAProxy Datei gegen
  ausgeliefert, vHosts im Container, Moodle moodledata Platz/Inodes.
- T1: BookStack wird an `../artisan` und `../app/Entities/Models/Bookshelf.php` erkannt statt an `bookstack` in
  `../composer.json` (kein Dateiinhalt lesen; je App alle Merkdateien). `app_web.go` bleibt unverändert. Ein Name
  steht einmal in `vhosts`: TLS-Port vor Klartext, der niedrigere Port zuerst.
- T2: Apache heißt in `vhosts` `server: apache` (Debian apache2 und RHEL httpd gleich). Erst `apache2ctl -S`, fehlt
  es, `apachectl -S`. Ein `<VirtualHost *>` (`port *` in `-S`) nennt keinen Port und wird ausgelassen. Namen aus `-S`
  (Name, `alias`) und `ServerAlias` des Blocks (`-S` nennt Aliase nur bei namensbasierten vHosts). Steht an der
  Zeile aus `-S` kein `<VirtualHost` mehr, bleibt der vHost ohne TLS, Wurzel und Zertifikat. Den Webserver-Benutzer
  (`User:` in `-S`) liest erst T6. `Include`/`IncludeOptional` im Block wird eine Ebene tief gelesen (certbot legt
  `SSLEngine on` in `options-ssl-apache.conf`), nur feste Pfade, relativ zu `ServerRoot` aus `-S`, keine Muster.
  Ein Block ohne eigenes `ServerName` meldet den von `-S` geerbten Namen nicht. Jede Datei wird je Lauf einmal
  gelesen (höchstens 512 Dateien, je `maxApacheFileBytes`).
- T3: Ein Ziel `vhost` löst wie ein Ziel `port` auf (Port des Hosts durch den Wächter); der Name geht nur als SNI
  und Host in die Anfrage. Ein vHost ohne bekannte Zertifikatsdatei (keine im Block, kein fester Pfad) meldet nur
  die ausgelieferten Werte. Aus einer Datei mit Schlüssel und Zertifikat (HAProxy, `combined`) liest der Agent nur
  den ersten `CERTIFICATE`-Block, andere Blöcke parst er nicht; eine eigene Schlüsseldatei öffnet er nie. HAProxy:
  `crt` mehrfach je `bind`, relativ zu `crt-base`, ein Verzeichnis wie HAProxy (ohne `.key .issuer .ocsp .sctl` und
  Punkt-Dateien, höchstens 256); eine fehlende Datei fällt aus (Bundles `.rsa`/`.ecdsa`), `crt-list` und
  `crt-store` liest der Agent nicht. Prüfer-Nit aus T2 mitgenommen: `IncludeOptional` auf eine fehlende Datei und
  `Include` eines Verzeichnisses machen die Discovery nicht mehr dauerhaft unvollständig (das Verzeichnis wird nicht
  gelesen). Die Tests mit Dateien liegen in `_linux_test.go`: die Ansichten lesen nur feste Unix-Pfade.
- T4: Ein fehlendes Feld im Ergebnis bewertet `_rate` als `unknown`; darum ist der Vergleich Datei gegen
  ausgeliefert ein eigener Check `reload`, und eine unbekannte Datei lässt nur ihn `unknown`. `chain_ok` steht auf der
  Karte, wird aber nicht bewertet (interne CA). HAProxy bekommt keine Regel auf `min_days_left`: das Feld fehlt bei
  null Zertifikaten. HAProxy-Modul auf Version 2 wie bei früheren Check-Zugängen. Der Port des vHost-Ziels kommt aus
  der Zusammenfassung der Instanz; ohne Port wird der Check nicht gebunden.
- T5: `http` und `tls` nehmen `vhost` über eine eigene Liste (`vhostTargets`); `dns` und `proto` bleiben ohne. Der
  Parameter `host` ist an einem vHost nicht erlaubt, ebenso ein `server_name`, der vom vHost-Namen abweicht, und
  `scheme: auto` (der Handshake von `speaksTLS` nennt keinen Namen; das Schema liefert der Server aus der Instanz).
  Eine Umleitung auf den eigenen Namen ist eine auf ein anderes Ziel (`sameTarget`), denn verbunden wird mit
  Loopback. Die Tests liegen in `sensor_net_test.go` bei den übrigen Netz-Fühlern statt in einer neuen Datei.
