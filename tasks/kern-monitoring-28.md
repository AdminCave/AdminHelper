<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web-Domains aus vHosts, Zertifikate und native PHP-Apps — Task-Ledger
Status: geplant · Branch: feature/kern-monitoring-28 · Review: pro Task
Spec: docs/features/kern-monitoring-28.md (Roadmap R-1435, R-1378, R-1422)
Heavy: linux-full — neue Discovery, Zielart, Ansichten und Freigabeliste im Agent (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vor T1 `origin/main` in den Branch mergen. Domainnamen dürfen als Instanz zum Server (Kevin 2026-11-15); Pfade,
Konfigurationstext und Inhalte nie.

### T1 — R-1435: vHosts von nginx in der Discovery  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhosts.go, apps/agent/internal/probe/web_vhosts_test.go, apps/agent/internal/probe/app_web.go, apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_test.go
Änderung: `WebVhosts` liest aus `nginx -T` je `server` die Namen, den Port, ob `ssl`, und, falls erkannt, die App im
`root`: Nextcloud (`occ` und `status.php`), Moodle (`admin/cli/checks.php`), WordPress (`wp-login.php`), BookStack
(`../artisan` mit `bookstack` in `../composer.json`). Die Discovery meldet daraus den Block `vhosts` mit `{server,
name, port, tls, app}`, gedeckelt (maxVhosts). Wildcards, `_`, `localhost` und IP-Adressen werden ausgelassen. Neue
Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/discovery/
Doku: → T8

### T2 — R-1435: vHosts von Apache  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhosts.go, apps/agent/internal/probe/web_vhosts_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `apache2ctl -S` / `apachectl -S` in die Freigabeliste. `WebVhosts` liest `namevhost` und `alias` mit Port
und der Datei:Zeile, dort `SSLEngine on`, `SSLCertificateFile` und `DocumentRoot` des `<VirtualHost>`. Die Form der
Ausgabe gegen ein echtes httpd 2.4 (Docker `httpd:2.4`) prüfen und die Version im Kommentar nennen. Fixture aus
dieser Ausgabe.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T8
Abhängt von: T1

### T3 — R-1435: Zielart vhost und Zertifikats-Ansichten  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go, apps/agent/internal/probe/probe.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/web_vhosts.go, apps/agent/internal/probe/web_vhost_cert.go, apps/agent/internal/probe/web_vhost_cert_test.go, apps/agent/internal/probe/app_haproxy.go, apps/agent/internal/probe/app_haproxy_test.go
Änderung: Zielart `vhost` (Name = Domain, `port_hint` = Port). `resolve` macht daraus Loopback am Port durch den
Wächter. Ansicht `web_vhost_cert`: sucht zur Prüfzeit über `WebVhosts` den vHost und dessen Zertifikatsdatei
(Cache 60 s), liest die Datei (nur das Zertifikat, nie den Schlüssel) und schüttelt mit SNI die Hand. Felder:
`file_days_left`, `served_days_left`, `reload_missing`, `hostname_ok`, `chain_ok`. Ansicht `haproxy_certs` an die
Unit: Dateien aus `bind … crt` (Datei oder Verzeichnis, höchstens 256), Felder `certs`, `min_days_left`,
`expiring_14d`. Neue Dateien mit SPDX-Header; der Test hat ein eigenes Test-Zertifikat und einen Loopback-Server.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8
Abhängt von: T2

### T4 — R-1435: Instanz vhost und Modul web_domain  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/app/catalog/model.py, apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/check_configs.py, apps/monitoring/app/catalog/modules/web_domain.py, apps/monitoring/app/catalog/modules/haproxy.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_catalog_web.py
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

### T5 — R-1378: http- und tls-Fühler über den vHost  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_http_test.go, apps/agent/internal/probe/sensor_tls.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go
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
