<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-9 — Linux-Extras und AdminHelper überwacht sich selbst

Roadmap: R-1234 (Linux-Extras), R-1235 (AdminHelper selbst). Kevin 2026-11-09 diktiert (Monitoring-Konzept §6.14,
§3.11), vor dem Release 0.47.0.

## Problem / Motivation

- **R-1234:** Der Agent meldet fehlgeschlagene Units (`monitor/services_linux.go`) und `reboot-required`
  (`monitor/system_linux.go`), aber nicht: Timer, deren letzter Lauf scheiterte; Dienste, die noch alte Bibliotheken
  nutzen (`needrestart -b`); Kernel-Taint (OOPS, MCE, bad page) und hängende Livepatches; kaputte oder gehaltene
  Pakete (`dpkg --audit`, `apt-mark showhold`); das Ergebnis von unattended-upgrades.
- **R-1235:** AdminHelper sieht seine eigenen Dienste nicht. Ob Monitoring, CA-Issuer und Gateway antworten, wie
  lange ihre Zertifikate halten, ob das DB-Backup frisch ist und ob die VictoriaMetrics-Platte voll läuft, muss der
  Admin heute von Hand prüfen.

## Ziel & Nicht-Ziele

**Ziel:**

1. Host-Ansichten `systemd_timers`, `kernel_taint`, `needrestart`, `apt_state` und Module dazu, nach Konzept §6.14:
   - Timer: Zahl der Timer, Zahl der auslösenden Dienste mit `Result` ≠ `success` (5 min).
   - `needrestart -b` stündlich: Kernel-Status (`NEEDRESTART-KSTA`), Microcode (`NEEDRESTART-UCSTA`), Zahl der
     Dienste mit alten Bibliotheken. Nur `-b`: das startet nie etwas neu.
   - Kernel: Bits aus `/proc/sys/kernel/tainted` (OOPS/`D`, MCE/`M`, bad page/`B` → critical); Livepatches in
     Transition (`/sys/kernel/livepatch/*/transition`). Beides nur lesend geöffnet.
   - Pakete: `dpkg --audit` (Zahl der Befunde), `apt-mark showhold` (Zahl), aus
     `/var/log/unattended-upgrades/unattended-upgrades.log` Alter des letzten Laufs und Fehler im letzten Lauf;
     Befehle mit `LC_ALL=C`. **Nie `apt-get check`** (aktualisiert den Paket-Cache).
2. Modul `adminhelper` (Erkennung: Images `ghcr.io/admincave/adminhelper/*`, Instanz `compose_project`):
   - jeder Container läuft (gateway, server, scheduler, ca-issuer, monitoring, frps, victoria, postgres, redis);
   - `GET /health` des Monitoring-Dienstes und `GET /healthz` des CA-Issuers über die Container-Adresse;
   - Restlaufzeit des Gateway-Zertifikats (`tls` auf Port 443), des frps-Zertifikats und der CA (Datei im Volume);
   - Alter des letzten DB-Backups (optionaler Dienst `pg-backup`, Verzeichnis `/backups`);
   - Füllstand der VictoriaMetrics-Platte (`/victoria-metrics-data`).
3. Dafür lernen `certfile` und `file_age` ein Ziel `container`: der Pfad gilt **im Container**, der Agent bildet ihn
   über die Mounts aus `docker inspect` auf den Host-Pfad ab (nur Bind- und Volume-Mounts, nie über `/proc/<pid>/root`).
   Neuer Fühler `fs` (`statfs` eines Pfades, optional im Container): `used_pct`, `free_bytes`, `inodes_used_pct`.
4. **Scheduler-Verzug und Mailzustellung** brauchen Zahlen, die nur der Monitoring-Dienst kennt (Offene Frage 1).

**Nicht-Ziele:** der Totmann-Ping an eine externe URL und die Desktop-Warnung „Monitoring seit X min ohne Ergebnis“
(Konzept §3.11, nicht im Titel von R-1235; bei Bedarf eigene Zeile); RPM-Pakete (`dnf`, `needs-restarting`);
`needrestart` ohne `-b`, `unattended-upgrade` selbst, beschreibbare Livepatch-Dateien (Sperrliste Konzept §3.6);
der `/healthz` des Gateways (er hört nur auf `127.0.0.1:8081` im Container; das Gateway prüft der `tls`-Check auf 443
und der Container-Zustand).

## Betroffene Komponenten & Dateien

- **Agent:** `internal/probe/host_linux_extras.go` (+Test, neu), `sensor_host.go` (Registrierung),
  `internal/allowlist/allowlist.go` (+Test: `needrestart -b`, `dpkg --audit`, `apt-mark showhold`,
  `systemctl list-timers …`, `systemctl show -p Id,Result …`); `sensor_local.go`, `sensor_local_linux.go`,
  `target.go` (Container-Mounts), neuer `sensor_fs.go` (+Test).
- **Monitoring:** `app/catalog/sensors.py` (`HOST_VIEW_FIELDS`, `SENSOR_TARGETS` für `certfile`/`file_age`/`fs`,
  `FsParams`), `app/catalog/modules/` neu `systemd_timers.py`, `needrestart.py`, `kernel.py`, `apt.py`,
  `adminhelper.py`; Tests `test_catalog_linux_extras.py`, `test_catalog_adminhelper.py`; bei Ja zu Frage 1
  `app/main.py` (+Test).
- **Doku:** `docs/admin/monitoring.html`, `docs/developer/agent.html`, `docs/developer/monitoring.html`, je DE+EN;
  `changelog.d/kern-monitoring-9.md`.

## Datenmodell / API / Migrationen

Keine Migration. Neue Host-Ansichten, ein neuer Fühler `fs` und das Ziel `container` für `certfile`/`file_age`: ein
älterer Agent meldet sie `invalid`, der Check steht auf `unknown`. Eine REST-Änderung nur mit Kevins Ja zu Frage 1.

## Externe Integrationen

needrestart `README.batch` (Ausgabeformat `-b`), docs.kernel.org „Tainted kernels“ (Bits), Kernel-Doku „Livepatch“
(`transition`), dpkg(1) `--audit`, apt-mark(8), unattended-upgrades (Log-Format: nicht normiert, im Code als „nicht
verifiziert“ markiert, wo die Quelle es nicht belegt), Docker Engine API `ContainerInspect` (`Mounts`). Vor jeder
Ansicht an der Quelle prüfen.

## Trade-offs & Alternativen

- **Pfad im Container statt Host-Pfad im Modul:** Volume-Pfade hängen vom Compose-Projektnamen, vom Docker-Root und
  vom Installationsverzeichnis ab (`./backups`). Die Mount-Abbildung im Agent macht das Modul unabhängig davon und
  nützt jedem Container-Modul (Empfehlung). Alternative: Pfad-Parameter je Installation — Handarbeit für jeden Admin.
- **`fs` als eigener Fühler statt Feld von `file_age`:** `statfs` ist ein Systemaufruf ohne Dateiinhalt, billig;
  ein eigener Fühler hält die Felder klar.
- **Backup-Alter über das Verzeichnis:** `pg-backup.sh` legt täglich eine neue Datei an; das mtime des Verzeichnisses
  ändert sich damit. Ohne `pg-backup` bindet der Check an keinen Container und bleibt `unknown`: das Modul legt ihn
  nur an, wenn der Dienst im Fund steht (Muster wie bei anderen Compose-Modulen, sonst Abweichung in
  `## Entscheidungen`).

## Risiken & Rollback

- `needrestart -b` liest `/proc` aller Prozesse: stündlich, Timeout wie andere Ansichten.
- Das Log-Format von unattended-upgrades ist nicht stabil: unbekannte Zeilen zählen nicht, ein fehlendes Log heißt
  `last_run_age_h` fehlt (Feld fehlt → `unknown`).
- frps spricht auf 7000 eigenes TLS mit Client-Zertifikat; darum die Datei im Volume statt eines Handshakes.
- Rollback: Revert des Merges, keine Daten.

## Doku-Impact

Linux-Extras und das Modul „AdminHelper selbst“ in `docs/admin/monitoring.html`, Ansichten, `fs` und das
Container-Ziel in `docs/developer/agent.html`, Katalog in `docs/developer/monitoring.html`, je DE+EN;
CHANGELOG-Fragment.

## Offene Fragen

1. **Scheduler-Verzug und Mailzustellung (API, Kevins Bereich):** Beide Zahlen kennt nur der Monitoring-Dienst.
   Empfehlung: eine neue Route `GET /health/detail` im Monitoring-Dienst, nur im Compose-Netz erreichbar (das Gateway
   leitet sie nicht weiter), mit `scheduler_lag_s` (Alter des jüngsten Check-Laufs), `mail_last_ok_age_s` und
   `mail_failed_24h`; nur Zahlen. `/health` bleibt unverändert (Docker-Healthcheck, billig). Alternative: Felder in
   `/health` (jeder Healthcheck fragt dann die DB). T6 und T7 stehen auf `[?]`.
