<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module Mail, Verzeichnis und Schule — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-11 · Review: pro Task
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

### T2 — R-1239: Ansichten Mailcow, MailPiler, ClamAV, SpamAssassin, OpenDKIM  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_mail.go, apps/agent/internal/probe/app_mail_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `mailcow_watchdog` (Redis `WATCHDOG_LOG` auf Loopback, `REDISPASS` aus `mailcow.conf`, nie in einer
Meldung), `mailcow_queue`, `piler_status` (DB-Zugang aus `piler.conf`, nur das Alter), `clamav_db` (CVD-Kopf),
`spamd_ping` (`spamc -K`), `opendkim_keys` (`opendkim-testkey`). Tests mit Stubs und Fixtures.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T7
Abhängt von: T1

### T3 — R-1240: Ansichten Samba und linuxmuster  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/app_samba.go, apps/agent/internal/probe/app_samba_test.go, apps/agent/internal/probe/app_lmn.go, apps/agent/internal/probe/app_lmn_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: `samba_drs`, `samba_fsmo`, `samba_member`, `lmn_devices`, `lmn_linbo` (Spec, Tabelle). Neue Dateien mit
SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T7

### T4 — Katalog: Felder und Ziele der neuen Ansichten  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/tests/test_catalog_sensors.py
Änderung: `APP_VIEW_FIELDS` und `APP_VIEW_TARGETS` um die Ansichten aus T1–T3, gleich wie im Agent.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py
Doku: → T7
Abhängt von: T1, T2, T3

### T5 — R-1239: Mail-Module  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/postfix.py, apps/monitoring/app/catalog/modules/dovecot.py, apps/monitoring/app/catalog/modules/mailcow.py, apps/monitoring/app/catalog/modules/mailpiler.py, apps/monitoring/app/catalog/modules/clamav.py, apps/monitoring/app/catalog/modules/rspamd.py, apps/monitoring/app/catalog/modules/spamassassin.py, apps/monitoring/app/catalog/modules/opendkim.py, apps/monitoring/tests/test_catalog_mail.py
Änderung: Module nach Konzept §6.6 und §6.14 mit den Schwellen von dort (ClamAV-Datenbank > 2 / 5 Tage). Neun
Dateien, weil jedes Modul eine kleine eigene Datei ist und ein gemeinsamer Test sie prüft. Neue Dateien mit
SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_mail.py
Doku: → T7
Abhängt von: T4

### T6 — R-1240: Module Samba, linuxmuster, edulution  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/samba_ad_dc.py, apps/monitoring/app/catalog/modules/samba_member.py, apps/monitoring/app/catalog/modules/linuxmuster.py, apps/monitoring/app/catalog/modules/edulution.py, apps/monitoring/tests/test_catalog_directory.py
Änderung: Module nach Konzept §6.7: DRS-Fehler > 0 warning, letzter Erfolg > 12 h critical; smbd/nmbd/winbind
aktiv auf einem DC ist ein Befund; LDAPS-Zertifikat relativ zur Laufzeit; SRV-Einträge über dns mit Ziel;
linuxmuster-Units, Server-Zertifikat, Geräte-Import, LINBO; edulution über Container-Health und HTTP.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_directory.py
Doku: → T7
Abhängt von: T4

### T7 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-11.md
Änderung: App-Module Mail, Verzeichnis, Schule; Ansichten; Katalog; `changelog.d/kern-monitoring-11.md` unter
`### Added`, ohne Umlaute.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T5, T6

## Entscheidungen
- Mailcow und MailPiler lesen den Zugang aus der Konfiguration des Dienstes, wie das Konzept §6.6 es nennt; das
  Passwort verlässt den Host nicht.
- T1: `postfix_queue` (readdir, billig, 5 min) und `postfix_queue_age` (`postqueue -j` nur unter 5000 Mails,
  15 min) sind zwei Ansichten, damit der Katalog beide Intervalle der Spec setzen kann; die Queue-Wurzel nennt
  `postconf -h queue_directory`. `dovecot_status` zählt Fehler und Warnungen der letzten Stunde (`-s` jetzt − 3600)
  statt „seit dem letzten Lauf“: die Ansicht bleibt zustandslos. `doveadm service status` und die Feldnamen sind
  für Dovecot 2.4 belegt, für 2.3 nicht verifiziert (der Kopf wird gelesen, fehlende Felder sind ein Fehler).
