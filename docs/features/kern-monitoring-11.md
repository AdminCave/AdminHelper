<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-11 — Monitoring-Module für Mail, Verzeichnis und Schule

Roadmap: R-1239 (Postfix, Dovecot, Mailcow ohne API-Key, MailPiler, ClamAV, rspamd, SpamAssassin, OpenDKIM),
R-1240 (Samba AD DC, Samba-Datei/Mitglied, linuxmuster 7.x, edulution.io). Kevin 2026-11-09 diktiert
(Monitoring-Konzept §6.6, §6.7, §6.14), vor dem Release 0.47.0.

## Problem / Motivation

Der Katalog kennt keinen Mailserver und kein Verzeichnis außer OpenLDAP. Gerade in Schulen und kleinen Firmen sind
Postfix/Dovecot oder Mailcow sowie Samba AD und linuxmuster die Dienste, deren Ausfall alle merken. Heute meldet das
Monitoring höchstens, dass der Dienst läuft, nicht dass die Queue wächst, die Replikation steht oder die
Virensignaturen alt sind.

## Ziel & Nicht-Ziele

**Ziel:** Module mit den Checks aus dem Konzept. Es gelten die Leitplanken (Konzept §3.13, Kevin 2026-11-09):

- nur feste Lesebefehle mit festen Argumenten aus der Freigabeliste;
- kein Dienst verliert spürbar Leistung: die Postfix-Queue wird per `readdir` gezählt, ohne eine Datei zu öffnen;
  `postqueue -j` läuft nur unter 5000 Mails;
- zum Server gehen nur Zahlen, Booleans und Zustände: keine Adressen, Domains, Benutzer- oder Freigabenamen.

**Nicht-Ziele (Sperrliste, Konzept §3.6):** `postfix check` (legt Verzeichnisse an), Dovecot `log reopen`/`log
test`, `stats dump -r`, ClamAV `RELOAD`/`SCAN`, `freshclam`, `sigtool -i`, `rspamc stat_reset`, `samba-tool dbcheck`,
`sophomorix-check`, `linbo-torrent status`. Mailcow-API (später, mit Key). Hashes von `postconf -n`/`doveconf -n`
(eine Zeichenkette, kein Zustand; die Konfigurationsprüfung ist ein eigenes Thema). Der Sophomorix-Rückstand (im
Konzept ohne Leseweg).

## Betroffene Komponenten & Dateien

- **Agent** (`apps/agent/internal/probe/`): neue Ansichten in `app_mail.go`, `app_samba.go`, `app_lmn.go` (je mit
  Test, SPDX-Header), Registrierung in `sensor_app.go`; Freigabeliste `internal/allowlist/allowlist.go`.
- **Monitoring** (`apps/monitoring/app/catalog/`): `sensors.py` (Felder und Ziele), neue Module `postfix`, `dovecot`,
  `mailcow`, `mailpiler`, `clamav`, `rspamd`, `spamassassin`, `opendkim`, `samba_ad_dc`, `samba_member`,
  `linuxmuster`, `edulution`.
- **Doku:** `docs/admin/monitoring.html`, `docs/developer/agent.html`, `docs/developer/monitoring.html`, je DE+EN;
  `changelog.d/kern-monitoring-11.md`.

## Datenmodell / API / Migrationen

Keine Migration, keine REST-Änderung. Neue Ansichten des Sensors `app`; ein älterer Agent meldet sie `invalid`, der
Check steht dann auf `unknown`.

## Ansichten (Agent)

| Ansicht | Ziel | Leseweg | Felder |
|---|---|---|---|
| `postfix_queue` | Unit postfix | `readdir` in `incoming`, `active`, `deferred`, `hold` unter `queue_directory` (5 min); unter 5000 Mails `postqueue -j` (15 min) | Zahl je Queue, Alter der ältesten Mail |
| `dovecot_status` | Unit dovecot | `doveadm service status`, `doveadm log errors -s` | Dienste am Prozesslimit, Fehlerzeilen seit dem letzten Lauf |
| `mailcow_watchdog` | Compose-Projekt mailcowdockerized | Redis `WATCHDOG_LOG` auf 127.0.0.1:7654, Passwort `REDISPASS` aus `mailcow.conf` (Konzept: verlässt den Host nicht) | Zahl der Dienste im Fehler je Lauf, Alter des letzten Eintrags |
| `mailcow_queue` | Compose-Projekt mailcowdockerized | `readdir` im Postfix-Spool-Volume | wie `postfix_queue` ohne `postqueue` |
| `piler_status` | Unit piler | Zeitpunkt der letzten archivierten Mail aus der Piler-DB, DB-Zugang aus `piler.conf` (Konzept) | Alter der letzten Mail |
| `clamav_db` | Unit clamav-daemon | Kopf von `daily.cvd`/`daily.cld` (512 Byte) | Alter der Datenbank |
| `spamd_ping` | Unit spamd | `spamc -K` | erreichbar |
| `opendkim_keys` | Unit opendkim | `opendkim-testkey` (täglich) | Schlüssel ok / fehlerhaft (Zahl) |
| `samba_drs` | Unit samba-ad-dc | `samba-tool drs showrepl --json` (15 min) | Partner, Fehler, Alter des letzten Erfolgs |
| `samba_fsmo` | Unit samba-ad-dc | `samba-tool fsmo show` (täglich) | Rollen ohne gültigen Inhaber |
| `samba_member` | Unit smbd/winbind | `testparm -s` (Exit), `smbstatus --json --fast`, `wbinfo -p`, `-P`, täglich `-t` | Konfiguration ok, Sitzungen, Sperren, winbind und Vertrauensstellung ok |
| `lmn_devices` | Unit linuxmuster-webui | mtime von `devices.csv` gegen `devices.conf`, Fehler in `import-devices.log` | Import ausstehend, Fehler |
| `lmn_linbo` | Unit linbo-multicast | `.torrent` gegen Image unter `/srv/linbo` | Images mit veraltetem Torrent |

rspamd (`/ping`, `/stat` über localhost), ClamAV `zPING` (Unix-Socket), die SRV-Einträge des DC (dns mit Ziel aus
kern-monitoring-30), das LDAPS-Zertifikat (tls mit `lifetime_pct`), edulution (Container-Health, `/edu-api/health/check`,
Keycloak `/health/ready`) und die Units laufen über die vorhandenen Fühler, ohne neue Ansicht.

## Externe Integrationen

postfix.org (postqueue(1), QSHAPE_README), doc.dovecot.org 2.4 (doveadm-service, doveadm-log),
github.com/mailcow/mailcow-dockerized (watchdog, `WATCHDOG_LOG`), github.com/jsuto/piler, docs.clamav.net (CVD-Kopf),
docs.rspamd.com (Controller), wiki.samba.org (`drs showrepl --json`, ab 4.x), docs.linuxmuster.net, edulution-io.
Vor jeder Ansicht an der Quelle prüfen; Unbelegtes steht als „nicht verifiziert“ im Code und im Docstring.

## Trade-offs & Alternativen

- **Postfix-Queue per `readdir` statt `postqueue -p`/`mailq`:** `postqueue` liest jede Queue-Datei. Bei großen Queues
  kostet das spürbar I/O. `readdir` zählt nur Einträge (Konzept).
- **Mailcow-Watchdog aus Redis vs. Mailcow-API:** ein falscher API-Key führt zur netfilter-Sperre des
  AdminHelper-Servers (Konzept); Redis bleibt lokal.
- **Zugang aus der Konfiguration des Dienstes:** Für Mailcow und MailPiler nennt das Konzept ausdrücklich diesen Weg.
  Das Passwort verlässt den Host nicht und steht nie in einer Meldung. Anders als bei den Backup-Repos aus
  kern-monitoring-8, dort verlangt das Konzept ein lokal hinterlegtes Passwort.

## Risiken & Rollback

- linuxmuster-Pfade und -Units sind gegen docs.linuxmuster.net zu prüfen; ein Lab-Test ist nicht Teil dieses Zugs.
- `samba-tool` startet Python und braucht Sekunden CPU; darum 15 min bzw. täglich.
- Rollback: Revert des Merges, keine Daten.

## Doku-Impact

App-Module (Mail, Verzeichnis, Schule) in `docs/admin/monitoring.html`, Ansichten in `docs/developer/agent.html`,
Katalog in `docs/developer/monitoring.html`, je DE+EN; CHANGELOG-Fragment.

## Offene Fragen

Keine aus Kevins Bereich. Der Zugang für Mailcow und MailPiler folgt dem Konzept (siehe Trade-offs).
