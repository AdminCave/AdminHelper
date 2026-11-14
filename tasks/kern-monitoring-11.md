<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module Mail, Verzeichnis und Schule — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-11 · Review: pro Task
Spec: docs/features/kern-monitoring-11.md (Roadmap R-1239, R-1240)
Heavy: linux-full — neue Ansichten und Freigabeliste im Agent (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird nach den Merges von kern-monitoring-8, -30 und -14 (`sensor_app.go`, `allowlist.go`, `sensors.py`; dns
mit Ziel und `lifetime_pct` aus -30); vor T1 `origin/main` in den Branch mergen.

### T1 — R-1239: Ansichten Postfix und Dovecot  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_mail.go, apps/agent/internal/probe/app_mail_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @afb60a64f 2026-11-14T15:20:23+01:00
Review: approve (.ah-out/review/kern-monitoring-11/T1.verdict.json)
Änderung: `postfix_queue` (`readdir` der vier Queues ohne Datei zu öffnen; `postqueue -j` nur unter 5000 Mails,
nur Alter und Zahl) und `dovecot_status` (`doveadm service status`, `doveadm log errors -s`). Neue Dateien mit
SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T7

### T2 — R-1239: Ansichten Mailcow, MailPiler, ClamAV, SpamAssassin, OpenDKIM  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_mail.go, apps/agent/internal/probe/app_mail_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/app_mail_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @78da35d24 2026-11-14T15:45:39+01:00
Review: approve (.ah-out/review/kern-monitoring-11/T2.verdict.json)
Änderung: `mailcow_watchdog` (Redis `WATCHDOG_LOG` auf Loopback, `REDISPASS` aus `mailcow.conf`, nie in einer
Meldung), `mailcow_queue`, `piler_status` (DB-Zugang aus `piler.conf`, nur das Alter), `clamav_db` (CVD-Kopf),
`spamd_ping` (`spamc -K`), `opendkim_keys` (`opendkim-testkey`). Tests mit Stubs und Fixtures.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T7
Abhängt von: T1

### T3 — R-1240: Ansichten Samba und linuxmuster  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_samba.go, apps/agent/internal/probe/app_samba_test.go, apps/agent/internal/probe/app_lmn.go, apps/agent/internal/probe/app_lmn_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/probe/app_lmn_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @800af9c40 2026-11-14T16:11:13+01:00
Review: approve (.ah-out/review/kern-monitoring-11/T3.verdict.json)
Änderung: `samba_drs`, `samba_fsmo`, `samba_member`, `lmn_devices`, `lmn_linbo` (Spec, Tabelle). Neue Dateien mit
SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T7

### T4 — Katalog: Felder und Ziele der neuen Ansichten  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/tests/test_catalog_sensors.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f71fe8782 2026-11-14T18:16:52+01:00
Review: approve (.ah-out/review/kern-monitoring-11/T4.verdict.json)
Änderung: `APP_VIEW_FIELDS` und `APP_VIEW_TARGETS` um die Ansichten aus T1–T3, gleich wie im Agent.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py
Doku: → T7
Abhängt von: T1, T2, T3

### T5 — R-1239: Mail-Module  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/postfix.py, apps/monitoring/app/catalog/modules/dovecot.py, apps/monitoring/app/catalog/modules/mailcow.py, apps/monitoring/app/catalog/modules/mailpiler.py, apps/monitoring/app/catalog/modules/clamav.py, apps/monitoring/app/catalog/modules/rspamd.py, apps/monitoring/app/catalog/modules/spamassassin.py, apps/monitoring/app/catalog/modules/opendkim.py, apps/monitoring/tests/test_catalog_mail.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @67c82ddf8 2026-11-14T18:28:31+01:00
Review: approve (.ah-out/review/kern-monitoring-11/T5.verdict.json)
Änderung: Module nach Konzept §6.2 und §6.14 mit den Schwellen von dort (ClamAV-Datenbank > 2 / 5 Tage). Neun
Dateien, weil jedes Modul eine kleine eigene Datei ist und ein gemeinsamer Test sie prüft. Neue Dateien mit
SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_mail.py
Doku: → T7
Abhängt von: T4

### T6 — R-1240: Module Samba, linuxmuster  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/samba_ad_dc.py, apps/monitoring/app/catalog/modules/samba_member.py, apps/monitoring/app/catalog/modules/linuxmuster.py, apps/monitoring/tests/test_catalog_directory.py, tasks/kern-monitoring-11.md, docs/features/kern-monitoring-11.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @e7ab5de1f 2026-11-14T18:35:52+01:00
Review: approve (.ah-out/review/kern-monitoring-11/T6.verdict.json)
Änderung: Module nach Konzept §6.3: DRS-Fehler > 0 warning, letzter Erfolg > 12 h critical; FSMO-Rollen;
LDAPS-Zertifikat relativ zur Laufzeit; Samba-Mitglied (testparm, smbstatus, winbind, Vertrauensstellung);
linuxmuster-Units, Server-Zertifikat, Geräte-Import, LINBO. Nicht in T6 (Entscheidungen): smbd/nmbd/winbind auf
einem DC (R-1487), SRV-Einträge (R-1488), edulution (R-1489).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_directory.py
Doku: → T7
Abhängt von: T4

### T7 — Doku DE+EN und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-11.md, docs/features/kern-monitoring-11.md, tasks/kern-monitoring-11.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ace6fd213 2026-11-14T18:46:40+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: App-Module Mail, Verzeichnis, Schule; Ansichten; Katalog; `changelog.d/kern-monitoring-11.md` unter
`### Added`, ohne Umlaute.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T5, T6

## Entscheidungen
- Mailcow und MailPiler lesen den Zugang aus der Konfiguration des Dienstes, wie das Konzept §6.2 es nennt; das
  Passwort verlässt den Host nicht.
- T1: `postfix_queue` (readdir, billig, 5 min) und `postfix_queue_age` (`postqueue -j` nur unter 5000 Mails,
  15 min) sind zwei Ansichten, damit der Katalog beide Intervalle der Spec setzen kann; die Queue-Wurzel nennt
  `postconf -h queue_directory`. `dovecot_status` zählt Fehler und Warnungen der letzten Stunde (`-s` jetzt − 3600)
  statt „seit dem letzten Lauf“: die Ansicht bleibt zustandslos. `doveadm service status` und die Feldnamen sind
  für Dovecot 2.4 belegt, für 2.3 nicht verifiziert (der Kopf wird gelesen, fehlende Felder sind ein Fehler).
- T2: `mailcow_watchdog` verbindet sich mit der Container-Adresse von `redis-mailcow` (Port 6379, `secretGuard`),
  nicht mit dem veröffentlichten `127.0.0.1:7654`: so prüft der Guard den Lauscher des Containers selbst. Den
  Projektordner nennt das Compose-Label `com.docker.compose.project.working_dir`; ohne `REDISPASS` (ältere Mailcow)
  geht kein `AUTH`. Je Dienst zählt der neueste Eintrag der letzten 500; Dienstnamen bleiben auf dem Host.
- T2: `piler_status` fragt nur über den Socket aus `piler.conf` (`--no-defaults`, Passwort als `MYSQL_PWD`); ein
  `piler.conf` ohne Socket ist „nicht unterstützt“. Fehler melden nur den Code (`ERROR 1045`), nie Nutzer oder Host.
  `MYSQL_PWD` unter MySQL 9 nicht verifiziert.
- T2: `clamav_db` liest nur die 512 Byte des Kopfs von `daily.cld`/`daily.cvd` unter `/var/lib/clamav` (fester Ort);
  Feld 9 als Epoch ist aus dem Format gefolgert, für `.cld` nicht verifiziert. `spamd_ping` nimmt Host und Port aus
  `spamc.conf` des Admins; erreichbar nur bei Exit 0 und der Antwort `SPAMD/<ver> 0` (der sichere Rückfall von
  spamc gilt für `-K` nicht, belegt an `spamc.c`/`libspamc.c`), sonst `reachable: false`. `opendkim_keys` liest nur
  die Summenzeile von `opendkim-testkey -v` (stdout); Schlüssel und Domains (stderr) bleiben auf dem Host, Exit 78
  (keine KeyTable) ist „nicht unterstützt“. Die DNS-Abfrage des Werkzeugs ist eine Resolver-Abfrage, keine LAN-Sonde
  (Konzept §10 Nr. 4); Intervall täglich im Katalog (T5).
- T3: Samba-Werkzeuge laufen mit `LC_ALL=C TZ=UTC`, damit `last success` von `drs showrepl --json`
  (`strftime("%a %b %e %X %Y %Z")`, lokale Zeit, `lib/util/time.c`) fest lesbar ist; `NTTIME(0)` heißt nie: eingehend ein
  fehlschlagender Link (der Pull läuft je Partition nach Plan), ausgehend nicht (Samba benachrichtigt nur nach einer
  Änderung der Partition, `drepl_notify.c`), dort zählen nur `consecutive failures`; `--summary` taugt nicht als
  Vorbild (sein Vergleich `== 0` trifft den String nie). Links zu gelöschten DCs fallen heraus. Fehler der Werkzeuge melden nur
  den Exit-Code, nie stderr (dort stehen DC-Namen, DNs, Freigaben). `samba_trust` (`wbinfo -t`) ist eine eigene View,
  damit der Katalog sie täglich fahren kann; `samba_member` fragt `wbinfo -P` nur, wenn `-p` antwortet. Ein
  FSMO-Besitzer mit `\0ADEL:` gilt als gelöscht (MS-ADTS), wie Samba ihn druckt, nicht verifiziert.
- T3: linuxmuster.net nur für `default-school` (`devices.csv`); `import_pending` vergleicht seine mtime mit der von
  `/etc/dhcp/devices/default-school.conf`, die nur ein Import dieser Schule neu schreibt (`devices.conf` schreibt
  jeder Import, es gilt nur, wo die Schul-Datei fehlt). `import_completed`/`import_errors` nur, wenn
  `import-devices.log` (neuere base7) einen Lauf-Beginn trägt, gelesen aus den letzten 256 KiB. `lmn_linbo` zählt
  wie `linbo-torrent` Images in `/srv/linbo/images` und eine Ebene tiefer, ohne Punkt-Verzeichnisse (`.incoming`)
  und höchstens 4096 Einträge je Verzeichnis; `linbo-torrent` selbst bleibt draußen (sein `status` chownt).
- T5: Schwellen der Mail-Module (eigene Wahl): Postfix mehr als 100 `deferred` oder gekappte Zählung Warnung,
  älteste Mail über 1 d Warnung, über 4 d kritisch (vor `maximal_queue_lifetime` 5 d), `age_read: false` (ab 5000
  Mails) Warnung; Dovecot Dienst am Prozesslimit oder ein Fehler der letzten Stunde Warnung; Mailcow-Watchdog ein
  Dienst unter voller Gesundheit Warnung, keine Regel aufs Alter; MailPiler neueste Mail über 2 d Warnung, ein leeres
  Archiv bleibt `unknown`; ClamAV über 2 d Warnung, über 5 d kritisch (Spec); Rspamd nur `GET /ping` mit `expect`
  `pong` auf 11334; OpenDKIM täglich. Mailcow wird am Postfix-Image erkannt (`ghcr.io/mailcow/postfix`, ältere
  `mailcow/postfix`); ClamAV unter RHEL (`clamd@scan`) und der Socket von clamd bleiben draußen (Unitname nicht
  verifiziert, der Sensor `unixsocket` spricht kein zPING).
- T6: Katalog bindet je Unit eine Instanz und eine `unit`-Prüfung nur an deren Unit; darum ohne Befund „smbd/nmbd/winbind
  aktiv auf einem DC“ und ohne SRV-Abfrage (der Katalog kennt den Realm nicht), R-1487 und R-1488. edulution
  entfällt in diesem Zug: Image-Namen und `/edu-api/health/check` sind an keiner öffentlichen Quelle belegbar (Repo
  privat, 2026-11-14), Erkennung wäre geraten; R-1489. linuxmuster: `server.cert.pem` aus base7 `certs.py`,
  Verzeichnis `/etc/linuxmuster/ssl` aus dem Konzept (Wert nicht verifiziert); linbo-multicast/linbo-torrent sind
  oneshots mit `RemainAfterExit` (linbo7 `src/serverfs`), ihre Unit sagt nichts; linuxmuster-api (:8001, https)
  verlangt für jeden Pfad ein Token, bleibt draußen. Schwellen: DRS-Link-Fehler Warnung, letzter Erfolg > 12 h
  kritisch (Konzept), FSMO ohne Inhaber Warnung, LDAPS wie OpenLDAP (25/10 %, 12 h), Server-Zertifikat 30/7 Tage,
  Import ausstehend und veraltete Torrents Warnung, winbind ohne Antwort kritisch, DC/Trust Warnung.
