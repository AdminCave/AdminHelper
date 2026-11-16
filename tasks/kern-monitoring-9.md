<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Linux-Extras und AdminHelper überwacht sich selbst — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-9 · Review: pro Task
Spec: docs/features/kern-monitoring-9.md (Roadmap R-1234, R-1235)
Heavy: linux-full — neue Ansichten, Fühler und Freigabeliste im Agent (`apps/agent`); kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Gebaut wird nach den Merges von kern-monitoring-8, -30, -14, -11 und -20 (`sensor_host.go`, `allowlist.go`,
`sensors.py`, `sensor_local.go`); vor T1 `origin/main` in den Branch mergen.

### T1 — R-1234: Ansichten systemd_timers und kernel_taint  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/host_linux_extras.go, apps/agent/internal/probe/host_linux_extras_test.go, apps/agent/internal/probe/sensor_host.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ac6ddebce 2026-11-15T18:38:16+01:00
Review: approve (.ah-out/review/kern-monitoring-9/T1.verdict.json)
Änderung: `systemd_timers` (`systemctl list-timers --all`, dann `show -p Id,Result` der auslösenden Dienste; Zahl der
Timer und der gescheiterten letzten Läufe) und `kernel_taint` (`/proc/sys/kernel/tainted` als Bits, Livepatches in
Transition aus `/sys/kernel/livepatch/*/transition`, nur lesend). Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T8

### T2 — R-1234: Ansichten needrestart und apt_state  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/host_linux_extras.go, apps/agent/internal/probe/host_linux_extras_test.go, apps/agent/internal/probe/sensor_host.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @2664f0f72 2026-11-15T18:53:35+01:00
Review: approve (.ah-out/review/kern-monitoring-9/T2.verdict.json)
Änderung: `needrestart` (`needrestart -b`, nur die Zeilen `NEEDRESTART-KSTA`, `-UCSTA`, Zahl der `-SVC`) und
`apt_state` (`dpkg --audit`, `apt-mark showhold` mit `LC_ALL=C`, Zahlen; Log von unattended-upgrades: Alter des
letzten Laufs, Fehler im letzten Lauf). Nie `apt-get check`; ein Test hält fest, dass die Freigabeliste es nicht
kennt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/ ./internal/allowlist/
Doku: → T8
Abhängt von: T1

### T3 — R-1234: Katalog und Module Linux-Extras  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/systemd_timers.py, apps/monitoring/app/catalog/modules/needrestart.py, apps/monitoring/app/catalog/modules/kernel.py, apps/monitoring/app/catalog/modules/apt.py, apps/monitoring/tests/test_catalog_linux_extras.py, apps/monitoring/app/catalog/modules/unattended_upgrades.py, apps/monitoring/tests/test_catalog_sensors.py, apps/agent/internal/probe/host_linux_extras.go, apps/agent/internal/probe/host_linux_extras_test.go
Evidenz: run.sh[quick] monitoring agent: 6 passed, 0 failed, 12 skipped @a71c6f997 2026-11-15T19:16:24+01:00
Review: approve (.ah-out/review/kern-monitoring-9/T3.verdict.json)
Änderung: `HOST_VIEW_FIELDS` um die Ansichten aus T1/T2, gleich wie im Agent. Module nach Konzept §6.14: gescheiterte
Timer > 0 warning; Kernel-Status ≥ 2 warning, Dienste > 0 warning; OOPS/MCE/bad page critical, Livepatch in Transition
warning; `dpkg --audit` > 0 warning, letzter unattended-upgrades-Lauf > 2 Tage warning, Fehler > 0 warning.
Erkennung über Marker (Pfade, Pakete) wie `mdadm.py`. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring agent --strict
Doku: → T8
Abhängt von: T2

### T4 — R-1235: Pfad im Container für certfile und file_age, Fühler fs  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/sensor_fs.go, apps/agent/internal/probe/sensor_fs_test.go, apps/agent/internal/probe/sensor_local_test.go, apps/agent/internal/probe/sensor_fs_unix.go, apps/agent/internal/probe/sensor_fs_windows.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @9b6129938 2026-11-16T13:24:10+01:00
Review: approve (.ah-out/review/kern-monitoring-9/T4.verdict.json)
Änderung: `certfile` und `file_age` nehmen optional das Ziel `container`: der Pfad gilt im Container und wird über
`Mounts` aus `docker inspect` (Bind/Volume, längster passender Ziel-Präfix) auf den Host abgebildet; ohne passenden
Mount `invalid`, kein Pfad in einer Meldung. Neuer Fühler `fs` (`statfs`, ohne Ziel oder mit Ziel `container`):
`used_pct`, `free_bytes`, `inodes_used_pct`. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T8

### T5 — R-1235: Katalog: Container-Ziel, Fühler fs, Modul adminhelper  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/adminhelper.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_adminhelper.py, apps/monitoring/tests/test_catalog.py, scripts/pg-backup.sh
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @db691cca9 2026-11-16T13:41:48+01:00
Review: approve (.ah-out/review/kern-monitoring-9/T5.verdict.json)
Änderung: `SENSOR_TARGETS` erlaubt `container` für `certfile`/`file_age`/`fs`, `FsParams`. Modul `adminhelper`
(`compose_project`, Images `ghcr.io/admincave/adminhelper/*`): Container laufen; `http` `/health` (monitoring:8080),
`/healthz` (ca-issuer:8090); `tls` Gateway 443 und `certfile` frps-/CA-Zertifikat relativ zur Laufzeit; `file_age`
`/backups` am Dienst `pg-backup` (> 26 h warning, > 50 h critical); `fs` `/victoria-metrics-data` 80/90 %. Pfade
und Ports gegen `docker-compose.yml` und den CA-Issuer prüfen. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_sensors.py tests/test_catalog_adminhelper.py tests/test_catalog.py
Doku: → T8
Abhängt von: T4

### T6 — R-1235: Monitoring-Dienst meldet Scheduler-Verzug und Mailzustellung  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/main.py, apps/monitoring/tests/test_health.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/app/scheduler.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @d671ae404 2026-11-16T13:47:37+01:00
Review: approve (.ah-out/review/kern-monitoring-9/T6.verdict.json)
Änderung: nach Kevins Antwort (Spec, Offene Fragen 1): neue Route `GET /health/detail` (Scheduler-Verzug, fehlgeschlagene
Alarm-Mails in 24 h, Alter der letzten zugestellten Mail), `/health` bleibt unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_health.py tests/test_openapi_snapshot.py
Doku: → T8

### T7 — R-1235: Modul adminhelper prüft Scheduler-Verzug und Mailzustellung  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/adminhelper.py, apps/monitoring/tests/test_catalog_adminhelper.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @7fe7eb4cf 2026-11-16T13:48:56+01:00
Review: approve (.ah-out/review/kern-monitoring-9/T7.verdict.json)
Änderung: `http` auf `/health/detail` mit `data.scheduler_lag_s` (> 600 s warning, > 1800 s critical) und
`data.mail_failed_24h` > 0 warning; Modulversion hoch.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_adminhelper.py
Doku: → T8
Abhängt von: T5, T6

### T8 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-9.md
Änderung: Linux-Extras, Modul „AdminHelper selbst“, Fühler `fs`, Container-Ziel für `certfile`/`file_age`, Ansichten;
`changelog.d/kern-monitoring-9.md` unter `### Added`, ohne Umlaute. `doc-smoke --env` lokal fahren.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T3, T5

## Entscheidungen
- Fehlgeschlagene Units meldet der Agent schon (`monitor/services_linux.go`, Systemcheck); der Zug ergänzt nur die
  Timer.
- Der `/healthz` des Gateways hört nur im Container auf `127.0.0.1:8081`; das Gateway prüfen `tls` auf 443 und der
  Container-Zustand.
- Kevin 2026-11-14: T6/T7 wie empfohlen: neue Route `GET /health/detail` nur im Compose-Netz, `/health` bleibt unverändert; übrige Monitoring-Entscheidungen wie im Ledger vorgeschlagen.
- T1: Timer über `systemctl list-units --type=timer --all --full --plain` statt `list-timers --all`: die Spalten von
  `list-timers` sind Zeitangaben mit Leerzeichen, die JSON-Ausgabe braucht ein neueres systemd. Gezählt werden geladene,
  aktive Timer; die ausgelösten Units fragt ein `show -p Id,Triggers`, ihr Ergebnis ein `show -p Id,Result`.
- T2: Felder `apt_state`: `audit`, `held`, `uu_last_run_age_s`, `uu_errors` (Sekunden wie `check_age_s`, statt
  `last_run_age_h` der Spec; ohne Log fehlen beide `uu_`-Felder). Die Startzeile von unattended-upgrades ist übersetzt
  (gettext), darum trennt eine Pause von über einer Stunde zwei Läufe; Format `%(asctime)s %(levelname)s %(message)s`
  aus `_setup_logging` (u-u 2.12, trixie) gelesen. `needrestart -b` mit `LC_ALL=C` und 30 s Timeout, dem Höchstwert des Katalogs (`timeout_s`): die Prüfung in T3
  setzt `timeout_s: 30`.
- T3: unattended-upgrades als eigenes Modul (`unattended-upgrades`, Marker Paket `unattended-upgrades`) neben `apt`,
  beide auf der Ansicht `apt_state`: eine Warnregel auf ein fehlendes Feld macht den Check `unknown`, so bliebe `apt`
  auf Hosts ohne u-u nie grün. Warnung ab 2 Tagen ohne Lauf (der Timer läuft täglich) und bei einem ERROR im letzten
  Lauf. needrestart warnt zusätzlich bei veraltetem Microcode (`microcode_status` ≥ 2), über den Ledger-Text hinaus;
  KSTA/UCSTA 0 (unbekannt) bleibt still. Gehaltene Pakete stehen nur auf der Karte (Halten ist eine Entscheidung).
- T3 (Prüfer Runde 1): needrestart 3.11 lässt im Container die Kernel-, im Container und in der VM die
  Microcode-Prüfung aus und druckt dann keine KSTA-/UCSTA-Zeile; der Agent (T2-Datei, in T3 nachgezogen) liest eine
  fehlende als 0 (unbekannt) statt als Fehler, eine Antwort ohne `NEEDRESTART-VER` ist von anderer Form. Verify darum
  über `monitoring agent` (Zusatzargumente gehen nur an eine Komponente).
- T4: Unter dem Container-Pfad liest der Agent nur durch ein `os.Root` an der Mount-Quelle: ein Link im Volume führt
  nie zu einer Host-Datei außerhalb. `certfile` folgt relativen Links innerhalb des Mounts selbst (certbots
  `live/` → `archive/`), absolute (ein Pfad des Containers, evtl. auf einem anderen Mount) lehnt es ab; die Datei
  öffnet `openRegular` (O_PATH, kein Gerät, keine FIFO). Ein Container-Pfad muss sauber sein (kein `..`), weil er
  über den Präfix abgebildet wird. Lesen im Container nur auf Linux (`openRegular`), `fs` auf Linux und FreeBSD
  (`statfs` über ein als Verzeichnis geöffnetes fd), Windows `unsupported`. `fs` nimmt nur Verzeichnisse;
  `used_pct` wie df (ohne Root-Reserve), `inodes_used_pct` 0 ohne feste Inode-Zahl (btrfs). Keine Meldung nennt
  den Host-Pfad; ohne passenden Bind-/Volume-Mount `invalid` ohne Pfad.
- T4 (Review): Ein Bind einer einzelnen Datei (`-v ./fullchain.pem:/etc/nginx/cert.pem`) öffnet der Agent über den
  Ordner, der sie hält, mit der Datei als Pfad. Eine Quelle, die ein Link ist (docker inspect nennt sie, wie sie
  angegeben wurde), löst er auf wie docker beim Mounten; danach muss sie Ordner oder reguläre Datei sein, sonst
  Fehler ohne Pfad. `fs` auf einem Datei-Bind ist `no directory`. Grenze für T8: ein Datei-Bind hängt an der Inode;
  ersetzt der Host die Datei per rename, sieht der Container die alte, der Agent die neue; Doku empfiehlt Ordner-Binds.
- T4: dritte Prüfrunde (nur das Delta seit Runde 2) durch einen frischen Prüfer, weil Runde 2 eine Regression des
  Fixes fand und der erste Prüfer kompaktiert war (Kevin 2026-11-16, einmalige Ausnahme von CLAUDE.md §6).
- T5: `fs` nimmt `PathParams` (ein absoluter Pfad) wie `certfile`, kein eigenes `FsParams`. Pfad-Fühler ohne Ziel
  lesen den Host, mit Ziel `container` im Container; `test_catalog.py::test_target_must_fit_the_sensor` erwartet für
  `file_age` + `loopback` deshalb „only ['container']“ statt „takes no target“ (gewollte Änderung).
- T5: Modul `adminhelper`: die Backup-Prüfung bindet nur, wo `pg-backup` läuft (sonst „no container for this
  instance“ beim Übernehmen); `newest_in` sieht nur die jüngste Datei, ein Ausfall nur eines der beiden Dumps bleibt
  unbemerkt. Der frps-Container gehört dem Modul `frps`, `db-init` hat keinen Container-Check. `tls` am Gateway ohne
  Hostname-Regel (Ziel ist der Container). Der CA-Issuer hängt nur am internen Netz `pki`; der Host erreicht es
  (Docker 29.9.2 lokal geprobt). Kachel höchstens 6: kein Server-Zustand (der Container-Check alarmiert).
- T5 (Prüfer): `pg_dump` legt die Ausgabedatei vor dem Verbindungsaufbau an; ein Fehllauf ließ jeden Tag ein
  frisches `.dump.tmp` in `/backups`, das `newest_in` als jüngste Datei zählte. `pg-backup.sh` schreibt Teil-Dumps
  jetzt nach `/backups/.partial` (gleiches Dateisystem, `mv` bleibt atomar), `newest_in` übergeht Verzeichnisse.
- T6: `scheduler_lag_s` ist je Intervall die Zeit seit dem jüngsten Lauf irgendeiner Prüfung dieses Intervalls über
  das Intervall hinaus, das späteste Intervall zählt: eine einzelne hängende Prüfung macht kein Intervall spät. Eine
  Änderung (`updated_at`, Anlegen oder Wieder-Einschalten) zählt als Lauf, damit eine neue Prüfung nicht sofort als
  Verzug gilt; ein Bearbeiten kann einen echten Verzug so für ein Intervall verdecken. Gepushte (`PUSH_ONLY_TYPES`) und
  abgeschaltete Prüfungen zählen nicht. Ohne zählbare Prüfung 0, nicht `null` (eine Regel auf `null` wäre dauerhaft
  unknown). Nach dem Prüfer: der Start des Schedulers (`scheduler.loaded_at`, gesetzt in `load_all_checks`) zählt als
  Lauf jeder Prüfung, denn ein `IntervalTrigger` ohne `start_date` feuert erst eine Periode nach dem Start; sonst
  meldete jeder Neustart bis zu einer Periode Verzug.
- T6: `mail_failed_24h` zählt Sendungen (Regel und Zeitpunkt), nicht Zeilen je Prüfung; nur Regeln mit Kanal `email`.
  Ohne Auth wie `/health`: nur Zahlen; weder Gateway noch der Monitoring-Proxy des Servers (`_ALLOWED_PATH_PREFIXES`
  ohne `health`) leiten den Pfad weiter, erreichbar nur aus dem Compose-Netz und vom Host. OpenAPI-Snapshot neu
  aufgenommen.
- T7: eigene Prüfung `monitoring_scheduler` (http auf `/health/detail`, Port 8080) neben `monitoring_health`: `/health`
  bleibt der billige Lebenszeichen-Check, die Detail-Abfrage fragt die DB. `mail_last_ok_age_s` wird nur gemeldet,
  ohne Regel (ohne Mail-Regel bliebe es `null`). Modulversion bleibt 1: das Modul entsteht auf diesem Branch und war
  nie ausgeliefert. Kachel unverändert (6 von 6).
