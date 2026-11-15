# kern-monitoring-35 — WordPress-Cron aus der Site-Datenbank

Roadmap: R-1423 (FEAT). Zug `tasks/kern-monitoring-35.md`. Kevin 2026-11-14: „ja, eng begrenzt (nur lesende feste
Abfragen, Zugang verlässt den Host nie)“.

## Problem / Motivation

Das Modul `wordpress` (Katalog v2) prüft Container, REST-API und Version, aber nicht, ob die geplanten Ereignisse
von WordPress (WP-Cron) noch laufen. Bleiben sie liegen (`DISABLE_WP_CRON` ohne System-Cron, kaputtes Plugin, kein
Besucher), veralten Updates, Mails und Aufräumjobs still. Der Stand steht nur in der Datenbank der Site: Option
`cron` in `<prefix>options`, ein PHP-serialisiertes Array `Zeitstempel → Hook → …` plus `version`.

## Ziel & Nicht-Ziele

Ziel:
- Neue Ansicht `wordpress_cron` des `app`-Sensors am Container des Images `wordpress`: liest die Option `cron`
  einmal je Lauf mit einer festen Abfrage und meldet nur Zahlen: `events` (Ereignisse gesamt), `overdue` (fällig
  seit mehr als 10 Minuten) und `oldest_overdue_s` (wie lange das älteste überfällige schon wartet, 0 ohne).
- Der Katalog `wordpress` bekommt v3 mit dem Check `cron` (alle 15 Minuten; `oldest_overdue_s` > 3600 warn,
  > 86400 crit).

Nicht-Ziele (YAGNI):
- Keine TCP-Verbindung zur Datenbank, keine Ausnahme im Wächter (`blockedPort` 3306, `blockedProcesses`). Der Agent
  spricht nur über das Unix-Socket des Datenbank-Containers.
- Kein WordPress ohne Container (`wordpress_native` aus kern-monitoring-28): dort bestimmt `php.ini` das Socket;
  eigene Zeile, wenn gewünscht.
- Keine Datenbank außerhalb dieses Hosts (`WORDPRESS_DB_HOST` mit Adresse oder fremdem Namen bleibt `unsupported`;
  keine LAN-Sonde, Konzept §10 Nr. 4).
- Keine Hook-Namen, keine Argumente, kein Text der Option zum Server; nie `wp cron test`, nie `wp-cron.php`.
- `WORDPRESS_DB_PASSWORD_FILE` (Docker-Secrets) und `bitnami/wordpress`: `unsupported`.
- R-1424 (OpenLDAP-Verzug über Hosts) und R-1434 (keepalived-VIP über Hosts) fahren nicht mit: beide brauchen einen
  Vergleich über Hosts auf dem Server, den es heute nicht gibt (`_evaluate_push_check` wertet je Host,
  `checkers/probe.py` kennt nur Skalare). Das ist Architektur (CLAUDE.md §2) und geht als Frage an Kevin.

## Betroffene Komponenten & Dateien

- Agent `apps/agent/internal/probe/`: neu `app_wordpress_cron.go` (+ `_linux.go`/Tests), Eintrag in `sensor_app.go`
  (`appViews`), Felder `Config.Env` und `NetworkSettings.Networks[*].Aliases`/`DNSNames` in `containerInfo`
  (`target.go`); `go.mod`/`go.sum` (MySQL-Treiber).
- Monitoring `apps/monitoring/app/catalog/modules/wordpress.py` (v3), Katalog-Tests.
- `THIRD_PARTY_LICENSES.md`, Doku Admin + Entwickler DE+EN, `changelog.d/kern-monitoring-35.md`.

## Ablauf der Ansicht

1. `inspectContainer` des WordPress-Containers: aus `Config.Env` nur `WORDPRESS_DB_HOST`, `_USER`, `_PASSWORD`,
   `_NAME`, `WORDPRESS_TABLE_PREFIX` (Voreinstellungen des Images: `mysql`, `example username` … nicht raten:
   fehlt eine, `unsupported`). Name/Benutzer/Präfix nur `[A-Za-z0-9_]`, Präfix ≤ 20 Zeichen.
2. `WORDPRESS_DB_HOST` muss ein Name ohne Port oder mit `:3306` sein. Gesucht wird der Container auf diesem Host,
   der in einem gemeinsamen Netz des WordPress-Containers diesen Namen als Alias oder DNS-Namen trägt (`docker
   network inspect`, dann `docker inspect` der Kandidaten); genau ein Treffer, läuft, Image `mariadb` oder `mysql`,
   sonst `unsupported`.
3. Socket unter der Wurzel seines Prozesses (`/proc/<pid>/root`): `run/mysqld/mysqld.sock`, sonst
   `var/run/mysqld/mysqld.sock`; über `os.Root` aufgelöst (kein Link aus der Wurzel heraus), muss ein Socket sein.
4. Verbindung mit dem Go-Treiber über dieses Socket, Benutzer/Passwort aus Schritt 1, `timeout`/`readTimeout` 5 s,
   eine feste Abfrage: `SELECT option_value FROM <prefix>options WHERE option_name = 'cron' AND
   LENGTH(option_value) <= 1048576` (MariaDB mit `SET STATEMENT max_statement_time=5 FOR`).
5. Kleiner Parser für das serialisierte Array (nur `a:`, `i:`, `s:`, `b:`, `N;`, verschachtelt, Tiefe- und
   Längengrenzen); gezählt werden die ganzzahligen Schlüssel der obersten Ebene.

Passwort und Benutzer stehen nie in einem Fehler, einem Log oder einem Wert; Fehler nennen nur Container und Art.

## Datenmodell / API / Migrationen

Keine Alembic-Migration, keine OpenAPI-Änderung: neue Ansicht und neue Felder im bestehenden `app`-Sensor, neue
Katalog-Version (Angebot statt Auto-Rollout, Kevin 2026-11-11 zu R-1264).

## Externe Integrationen

- Image `wordpress`: `WORDPRESS_DB_*`-Variablen und `wp-config-docker.php`
  (https://github.com/docker-library/wordpress, README „Environment Variables“) — beim Bau nachlesen.
- Images `mariadb`/`mysql`: Socket-Pfad (`/run/mysqld/mysqld.sock`; nicht verifiziert für `mysql`).
- Go-Treiber `github.com/go-sql-driver/mysql` (MPL-2.0, mit GPL-3.0 verträglich), Unix-Socket per `unix(...)`.
- Format der Option `cron`: PHP `serialize()`; `_get_cron_array()` in `wp-includes/cron.php`.

## Trade-offs & Alternativen

- **Unix-Socket (gewählt)** statt TCP zum Container: keine Wächter-Ausnahme, kein `max_connect_errors`-Risiko, kein
  Netzweg. Kosten: der Agent braucht Lesezugriff unter `/proc/<pid>/root` (hat er schon für `wordpress_version`).
  Offen und beim Bau real zu prüfen (Docker auf der Dev-Box): ob `'user'@'%'` des Images über das Socket
  angenommen wird (nicht verifiziert).
- **Go-Treiber (gewählt)** statt `mariadb`-Client des Hosts: auf Docker-Hosts fehlt der Client meist; `docker exec`
  in den Datenbank-Container führte Code im Container aus. Neue Abhängigkeit (Kevin hat sie mit der Frage
  angenommen).
- `wp-config.php` im Container lesen statt Env: das offizielle `wp-config.php` liest selbst die Env; ein eigenes
  `wp-config.php` mit Literalen deckt der Zug nicht ab (`unsupported`).

## Risiken & Rollback

- Zugangsdaten im Speicher des Agents: nur für die eine Verbindung, nie persistiert oder gesendet.
- Socket-Pfad unter fremder Wurzel: Link-Auflösung nur über `os.Root`; `security` je Task mit Freigabeliste.
- Last: eine Abfrage per Primär-/Unique-Index alle 15 Minuten.
- Rollback: Revert des Merges; der Katalog v3 bleibt Angebot, v2 läuft weiter.

## Doku-Impact

Admin-Doku Monitoring (Modul `wordpress`: Check, Grenzen, Zugangsdaten) und Entwickler-Doku Agent (Ansicht,
Freigaben), DE+EN; `THIRD_PARTY_LICENSES.md`; Changelog.

## Offene Fragen

- An Kevin: R-1424 und R-1434 brauchen einen Vergleich über Hosts auf dem Monitoring-Server (neuer Mechanismus,
  neue Wertform). Empfehlung: eigenes Architektur-Vorhaben (`start-session.sh arch`); bis dahin geplant in
  `tasks/kern-monitoring-36.md`.
