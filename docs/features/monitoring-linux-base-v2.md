<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring Linux-Basis v2 und Proxmox-Ausfall — Spec

Roadmap: R-0423 (FEAT), R-0492 (FEAT). Entscheidungen: Kevin, 2026-10-19 (alle Empfehlungen der Bestandsaufnahme
angenommen, siehe „Entscheidungen“). Stand: `main@6a2b55a4`. Ledger: `tasks/monitoring-linux-base-v2.md`.
Baut auf R-0420 (versionierte Standard-Templates) und R-0419/R-0472 (Ausfall-Blöcke für Docker und ZFS) auf; beide
sind auf `main`. Alert-Qualität (R-0424) ist ein eigenes Vorhaben (`monitoring-alert-quality`).

## Problem / Motivation

Linux-Basis (R-0423):

1. **Was einen Linux-Server umwirft, sieht das Standard-Template nicht:** Swap, Inodes, Load, Zeit-Sync, ein
   ausstehender Neustart, offene Sicherheits-Updates, OOM-Kills. Load schickt der Agent schon
   (`apps/agent/internal/monitor/collector.go:56-69`), der Dienst schreibt sie nach VictoriaMetrics
   (`apps/monitoring/app/routers/agent.py:127-132`) und bewertet sie nie. Swap, Inodes und der Rest fehlen im Report
   (`report.go:22-80`, `DiskInfo` `collector.go:71-78`).
2. **CPU ist Zufall:** eine blockierende 1-s-Stichprobe am Anfang jedes Laufs (`collector.go:33-42`). Unter Linux läuft
   der Agent als Oneshot alle 300 s (`apps/agent/systemd/adminhelper-agent.service:7`, `adminhelper-agent.timer:6`);
   eine Sekunde von 300 entscheidet über `cpu_warn/cpu_crit`.
3. **Nur Prozent:** eine 4-TB-Platte bei 85 % hat 600 GB frei und alarmiert (Template Disk 80/90,
   `apps/monitoring/app/builtin_templates.py:59-77`). Eigene Schwellen oder Ignorieren je Mount gibt es nicht; nur
   Sensoren haben `temp_overrides` (`apps/monitoring/app/check_configs.py:57-71`).
4. **Jede fehlgeschlagene Unit ist critical** (`apps/monitoring/app/checkers/agent.py:556-560`). Der Agent holt
   `failed` aus `systemctl list-units --state=failed` ohne `--type` (`services_linux.go:40-49`), also auch Mounts,
   Timer und Sockets.
5. **Ein Bump eines Standard-Templates verträgt sich nicht mit Altinstallationen:** Eine Zeile von vor R-0420 (ohne
   `builtin_hash`) bekommt beim Start Version 1 und den Hash der *gerade ausgelieferten* Definitionen
   (`builtin_templates.py:358-363`). Liefert ein Release Version 2, gilt jede solche Zeile als angepasst und bekommt nur
   ein Angebot statt des Updates (Hinweis aus dem Review von R-0420 T5). `windows-base` teilt sich die Dicts mit
   `linux-base` (`builtin_templates.py:134`); ein Umbau von `_AGENT_RESOURCES` änderte auch seinen Hash.

Proxmox (R-0492):

6. **Ein Ausfall von `pvesh` ist stumm.** Kann der Agent nicht lesen, fehlt der Block `proxmox`
   (`apps/agent/internal/monitor/plugins.go:231-309`: Hostname `:240-243`, Node-Status still verworfen `:245-260`,
   Backup-Index `:262-269`, VM-Liste `:271-284`, Node leer und keine VMs `:305-307`). Der Checker macht daraus
   `unknown` (`apps/monitoring/app/checkers/plugins.py:60-63`), und `unknown` benachrichtigt nie. Docker und ZFS melden
   denselben Fall als `warning` (`plugins.py:161-174`, `:335-340`). Dokumentiert ist der Zustand als „ohne Daten“
   (`docs/admin/monitoring.html:64`).
7. **Veraltete VM-Liste:** Fehlt der Block, behält die Push-Auswertung die alten Details
   (`apps/monitoring/app/check_engine.py:182-214`, `keep_previous_details_when_absent`); der Desktop zeigt weiter die
   letzte Liste.
8. Template `proxmox-host` steht auf `consecutive_fails` 1 (`builtin_templates.py:151`), Docker und ZFS auf 2.

## Ziel & Nicht-Ziele

Ziel:

- **Agent-Report v3** (`report_version` 3, additiv): CPU als Mittel seit dem letzten Report, Swap, CPU-Anzahl, je
  Platte freie GB und Inode-Belegung, Block `system_state` (Neustart nötig, Zeit-Sync, Sicherheits-Updates, OOM-Kills
  seit dem letzten Report), Proxmox-Block auch im Ausfall.
- **`agent_resources`** bewertet Swap, Inodes und Load je CPU; der Prozent-Alarm einer Platte zählt nur, wenn
  zusätzlich weniger als `disk_min_free_gb` frei sind (Default 20); je Mount eigene Schwellen und Ignorieren.
- **`service_process`** (`auto`): fehlgeschlagene Dienste critical, andere fehlgeschlagene Units warning.
- **Neuer Push-Check-Typ `system_state`** („Systemzustand“), höchstens `warning`.
- **`proxmox_backup`**: Ausfall als `warning` mit Benachrichtigung, Schalter `alert_on_unavailable`, ein fehlender
  Block leert die VM-Liste.
- **Standard-Templates:** `linux-base` Version 2 (neue Schwellen, Check „System State“), `proxmox-host` Version 2
  (`consecutive_fails` 2); `windows-base`, `docker-host`, `zfs-storage` bleiben Version 1. Zeilen von vor R-0420
  vergleichen mit dem eingefrorenen Hash der Version 1.
- **Desktop** zeigt die neuen Werte, den Systemzustand und den Proxmox-Ausfall; das Check-Formular stellt alles ein.

Nicht-Ziele (YAGNI):

- Haltezeit, Glocken-Cooldown, Severity-Deckel, Host-Ping, Sammelmeldung (R-0424, `monitoring-alert-quality`).
- Härtung der Report-Zahlen und Agent-Texte (`monitoring-hardening`).
- Netzzugriff des Agents für Updates (kein `apt update`, kein `dnf makecache`), Gesamtzahl aller Updates,
  Paketnamen im Report.
- Neue VictoriaMetrics-Reihen (Swap, Inodes und Systemzustand stehen nur im Check-Ergebnis).
- Swap, Inodes, Load und Systemzustand unter Windows.
- Glob-Muster für Mounts; Kernel-Versionsvergleich für „Neustart nötig“.
- Alembic-Migration, neue API-Route.

## Entscheidungen (Kevin 2026-10-19)

- Schnitt: dieses Vorhaben ist R-0423 + R-0492; R-0424 ist ein eigenes.
- Units: nur fehlgeschlagene `.service` critical; fehlgeschlagene Mounts, Timer, Sockets (jede andere Unit-Art)
  warning; enabled-aber-inaktiv bleibt warning.
- Freie GB: Prozent-Alarm nur, wenn zusätzlich weniger als X GB frei sind (Default 20 GB); je Mount überschreib- oder
  ignorierbar.
- Systemzustand: neuer Check (warning) im Linux-Template: Neustart (`reboot-required` bzw. `needs-restarting`),
  Zeit-Sync (`timedatectl`), Sicherheits-Updates nur aus dem lokalen Cache (apt-Simulation, `dnf -C`), OOM als
  Zähler-Delta aus `/proc/vmstat` seit dem letzten Lauf. Kein Netz.
- Proxmox: jeder Lesefehler (Node-Status, VM-Liste, Backup-Index scheitert oder hängt) ist ein Ausfall; ein
  unvollständiger Backup-Index (inaktiver Storage) hat einen eigenen Code; `alert_on_unavailable` wie Docker/ZFS;
  fehlt der Block, wird die alte VM-Liste geleert; Template `proxmox-host` `consecutive_fails` 2.
- Alte Agents ohne die neuen Felder: nicht bewerten (kein `unknown`). `report_version` 3. CPU-Delta im ersten Lauf:
  Rückfall auf die 1-s-Stichprobe. `windows-base` bleibt Version 1 (geteilte Dicts trennen). v1-Hashes einfrieren.
- Die Defaults für Swap, Inodes, Load je CPU und Severity/`consecutive_fails` des neuen Checks schlägt diese Spec vor
  (Offene Fragen 1–4).

## Betroffene Komponenten & Dateien

**Agent** (`apps/agent`, Go):

- `internal/monitor/collector.go` — CPU-Delta statt Stichprobe (`:33-42`), Swap und CPU-Anzahl (neben `collectMemory`
  `:44-54` und `collectLoad` `:56-69`), `DiskInfo` mit `free_gb` und `inodes_percent` (`:71-106`).
- `internal/monitor/reportstate.go` (neu) — Zustand zwischen zwei Läufen in `.report-state.json` (Vorbild
  `inventory.go:44-66`); Pfad in `internal/config/paths.go` neben `MonitorInventoryStateFile` (`:32-38`).
- `internal/monitor/monitor.go` — `Push` (`:176-212`) liest den Zustand vor dem Sammeln und schreibt ihn nach
  erfolgreichem Push wie den Inventar-Zustand (`:203-209`); `Init` (`:127`) ohne Zustand.
- `internal/monitor/system_linux.go`, `system_other.go`, `updates_linux.go` (neu; `//go:build linux` bzw. `!linux`) —
  Block `system_state`.
- `internal/monitor/report.go` — `report_version` 3 (`:44`), Swap-Felder und Block `system_state` (neben `:23-41` und
  `:63-77`), Indirektion wie `serviceHealthCollector` (`:94-95`).
- `internal/monitor/plugins.go` — `collectProxmox` (`:231-309`), `buildBackupIndex` (`:311-365`), neu
  `proxmoxUnavailable` nach dem Muster `dockerUnavailable`/`zfsUnavailable` (`:144-164`, `:410-425`).

**Monitoring** (`apps/monitoring`, Python):

- `app/checkers/agent.py` — `AgentResourcesChecker.evaluate` (`:271-398`), `ServiceProcessChecker._evaluate_auto`
  (`:513-576`).
- `app/checkers/system.py` (neu) — `SystemStateChecker`; `app/checkers/__init__.py` (`_REGISTRY` `:30`),
  `app/check_types.py` (`:21-33`).
- `app/checkers/plugins.py` — `ProxmoxBackupChecker.evaluate` (`:60-137`), Code-Liste neben `:20-23`.
- `app/check_configs.py` — `AgentResourcesConfig` (`:62-74`), `ProxmoxBackupConfig` (`:101-104`), neu
  `SystemStateConfig`, `CONFIG_MODELS` (`:134-146`).
- `app/builtin_templates.py` — Dicts (`:43-102`), `BUILTIN_TEMPLATES` (`:104-194`), Baseline in
  `reconcile_builtin_templates` (`:358-363`).
- Nicht geändert: `app/routers/agent.py` (Push-Typen kommen über `PUSH_ONLY_TYPES`; `system_state` braucht keine
  Vorwerte, `_PREV_DETAILS_TYPES` `:63` bleibt), `check_engine.py`, `alerter.py`, `scheduler.py`, Modelle, Alembic.

**Desktop-UI** (`apps/desktop/ui/src`):

- `lib/api/types.ts` — `MonitorCheckType` (`:173`), `MonitorCheckConfig` (`:190`, agent_resources `:205-215`,
  `alert_on_unavailable` `:231-232`), `MonitorResourceDisk`/`MonitorResourceDetails` (`:264-285`),
  `MonitorBackupDetails` (`:317`), neu `MonitorSystemStateDetails`.
- `lib/models/monitoring.ts` — `PUSH_ONLY_CHECK_TYPES` (`:177-184`; Paritätstest
  `apps/monitoring/tests/test_push_only_ui_sync.py`); `lib/models/monitorCheck.ts` — `CHECK_TYPES` (`:22-34`).
- `components/monitoring/CheckConfigFields.svelte` — `RESOURCE_NUM_FIELDS` (`:93-103`), `WARN_CRIT_PAIRS`
  (`:131-143`), `outageField` (`:167-176`), Zweige `:295-296` und `:329-356`; neu `DiskOverridesField.svelte`.
- `components/monitoring/section/SecLive.svelte` (`:52-98`), `SecBackups.svelte` (`:31-49`, `:67-85`),
  `SecServices.svelte` (`:61-69`), neu `SecSystem.svelte`; `MonServerDashboard.svelte` (`:56-69`, `:130-156`).
- `lib/i18n/dictionaries.ts` (DE und EN).

**Doku:** `docs/admin/monitoring.html` + EN, `docs/developer/agent.html` + EN, `docs/developer/monitoring.html` + EN,
`README.md:285`, `CHANGELOG.md`.

**Nicht betroffen:** Server, Web, Gateway, CA-Issuer, Desktop-Rust (das Monitoring-JSON läuft durch den Proxy),
Paketierung (`build-deb.sh`, `build-rpm.sh`, systemd-Units), Install- und Update-Skripte.

## Datenmodell / API / Migrationen

### Agent-Report v3 (additiv)

```json
{
  "report_version": 3,
  "resources": {
    "cpu_percent": 12.3,
    "cpu_count": 8,
    "swap_percent": 4.1, "swap_total_mb": 2048, "swap_used_mb": 84,
    "load_1m": 0.4, "load_5m": 0.6, "load_15m": 0.5,
    "disks": [{"mount": "/", "fstype": "ext4", "percent": 81.0, "total_gb": 98.0,
               "used_gb": 75.4, "free_gb": 17.6, "inodes_percent": 12.0}]
  },
  "system_state": {"reboot_required": false, "time_synchronized": true,
                   "security_updates": 3, "oom_kills": 0},
  "proxmox": {"available": false, "error": "timeout",
              "error_message": "pvesh get /cluster/resources timed out after 15s",
              "node": null, "vms": []}
}
```

- **`cpu_percent`:** Anteil belegter CPU-Zeit seit dem letzten erfolgreich gesendeten Report, aus `cpu.Times(false)`
  mit der Rechnung, die gopsutil intern nutzt (`getAllBusy`/`calculateBusy`, gopsutil v4.26.5 `cpu/cpu.go:106-129`,
  nicht exportiert): gesamt ohne `Guest`/`GuestNice` unter Linux, belegt = gesamt − `Idle` − `Iowait`, begrenzt auf
  0–100. Rückfall auf die bisherige 1-s-Stichprobe, wenn kein brauchbarer Vorwert da ist: kein oder unlesbarer
  Zustand, älter als 15 min, Zeitstempel in der Zukunft, Gesamtzeit nicht gestiegen (Neustart). Unter Windows
  (Dienstschleife, `cmd/adminhelper-agent/run.go:53-78`) derselbe Weg.
- **`cpu_count`** (logische CPUs, `cpu.Counts(true)`) und **`swap_*`** (`mem.SwapMemory()`; ohne Swap
  `swap_total_mb` 0 und kein `swap_percent`): nur Linux, wie Load.
- **`free_gb`:** `disk.Usage().Free` (für Nicht-Root verfügbar, `Bavail`), beide Plattformen. **`inodes_percent`:**
  `InodesUsedPercent`, nur Linux und nur bei `InodesTotal > 0` (btrfs und vfat melden keine Inodes).
- **`system_state`** nur Linux; jedes Feld nur, wenn ermittelt; ohne ein einziges Feld fehlt der Block. Der Grund für
  ein fehlendes Feld steht als Warnung im Agent-Log (`diagnostics`), kurz und ohne stderr (`commandFailure`):
  - `reboot_required`: Debian-Familie (`apt-get` im Suchpfad): `/var/run/reboot-required` vorhanden → true, sonst
    false. RPM-Familie (`needs-restarting` im Suchpfad): `needs-restarting -r`, Exit 0 → false, Exit 1 → true,
    sonst kein Feld.
  - `time_synchronized`: `timedatectl show`, Zeile `NTPSynchronized=yes|no`; fehlt das Programm, scheitert der Aufruf
    oder fehlt die Zeile: kein Feld.
  - `security_updates`: Debian-Familie: `apt-get -s dist-upgrade` mit `LC_ALL=C`, gezählt werden `Inst`-Zeilen, deren
    Herkunft in Klammern `security` enthält (Debian `Debian-Security:…/…-security`, Ubuntu `…/<suite>-security`).
    RPM-Familie: `dnf -C -q updateinfo list --security`, gezählt werden die verschiedenen Pakete. Höchstens einmal je
    Stunde; dazwischen schickt der Agent den Wert aus dem Zustand. Scheitert der Aufruf (etwa `dnf -C` ohne Cache),
    fehlt das Feld bis zum nächsten stündlichen Versuch. Liegen `apt-get` und `dnf` vor, gilt `apt-get`.
  - `oom_kills`: Zuwachs von `oom_kill` in `/proc/vmstat` seit dem letzten erfolgreich gesendeten Report; im ersten
    Lauf (kein Vorwert) kein Feld; ist der Zähler kleiner als gespeichert (Neustart), gilt der Zähler selbst.
- **`.report-state.json`** (0600, neben `.inventory-state.json`): `{"cpu": {"unix", "total", "busy"}, "oom_kill": n,
  "updates": {"checked_unix", "security": n|null}}`. Geschrieben nur nach erfolgreichem Push, damit ein verlorener
  Push keinen OOM-Kill verliert; `monitor init` (Test-Push) liest und schreibt ihn nicht.
- **Timeouts:** `timedatectl` und `needs-restarting` unter `pluginTimeout` (15 s, `plugins.go:23-28`), `apt-get` und
  `dnf` unter einem eigenen `updatesTimeout` von 30 s (stündlich). Der Oneshot hat weiter 270 s
  (`adminhelper-agent.service:13`).
- **`proxmox`** kommt immer, wenn `pvesh` im Suchpfad liegt: im Ausfall `{"available": false, "error": <code>,
  "error_message": <Text>, "node": null, "vms": []}`, sonst mit `available: true`, `error: null`, `node` und `vms`
  (auch leer als Liste, nie `null`). Ausfall ist jeder Fehler bei Node-Status, Storage-Liste, Storage-Inhalt oder
  VM-Liste. Codes: `timeout` (ein `pvesh`-Aufruf lief in `pluginTimeout`), `cli_failed` (Exit-Status, startet nicht,
  Hostname unlesbar), `parse_failed` (keine JSON-Antwort der erwarteten Form), `backup_index_incomplete` (ein
  Backup-Storage ist nicht aktiv). `error_message` wie bei Docker: Aufruf und Exit-Status bzw. „backup storage <id> not
  active“, nie stderr.

### Monitoring

**`AgentResourcesConfig`**, neue Schlüssel (Default = Checker-Default = Wert in `linux-base` v2):

| Schlüssel | Default | Grenzen |
|---|---|---|
| `swap_warn` / `swap_crit` | 80 / 95 (%) | 0–100 |
| `inode_warn` / `inode_crit` | 80 / 90 (%) | 0–100 |
| `load_warn` / `load_crit` | 1.5 / 3.0 (je CPU, `load_5m / cpu_count`) | 0–100 |
| `disk_min_free_gb` | 20 (0 schaltet den Riegel ab) | 0–1 000 000 |
| `ignore_mounts` | `[]` (exakte Mount-Pfade) | — |
| `disk_overrides` | `{}`: `{mount: {warn?, crit?, min_free_gb?}}`, exakte Mount-Pfade, `extra="forbid"` | wie oben |

- Swap nur bei `swap_total_mb > 0`; Load nur mit ganzzahligem `cpu_count ≥ 1` und `load_5m`; Inodes je Platte, wenn
  `inodes_percent` da ist. Swap und Inodes mit Hysterese wie die Platten (Schlüssel `swap`, `inode:<mount>`), Load
  ohne (kein Prozentwert; `load_5m` mittelt schon, `consecutive_fails` 3 dämpft; Schlüssel `load`).
- Eine Platte aus `ignore_mounts` wird weder auf Belegung noch auf Inodes bewertet und steht in `_details` mit
  `ignored: true`. Je Platte gelten `warn`, `crit`, `min_free_gb` aus `disk_overrides[mount]`, sonst die globalen.
  Der Prozent-Alarm zählt, wenn `free_gb` fehlt (alter Agent: wie heute), `min_free_gb` 0 ist oder
  `free_gb < min_free_gb`.
- `_details` neu: `swap`, `swap_total_mb`, `swap_used_mb`, `cpu_count`, `load_per_cpu`; je Platte `free_gb`,
  `inodes_percent`, `ignored`. `problems` (`:371-375`) trägt die neuen Schlüssel; der Desktop nimmt daraus die Ampel.
- Fehlt ein neues Feld (alter Agent, Windows), bleibt die Metrik unbewertet, ohne `unknown`.

**`service_process`** (`auto`): Die fehlgeschlagenen Units teilen sich nach der Endung: `.service` oder ohne bekannte
Unit-Endung (Windows-Dienste) → critical; jede andere Endung aus `_UNIT_TYPES` (`checkers/agent.py:454-466`) →
warning. Meldung `Failed: a.service; Failed units: data.mount; Inactive (autostart): b.service`. `ignore` greift
vorher wie heute; `_details` bleibt (`failed` enthält weiter alle).

**Neuer Typ `system_state`** (push_only; `CHECK_TYPES` und die Desktop-Kopie `PUSH_ONLY_CHECK_TYPES` gleichzeitig):

- `SystemStateConfig`: `check_reboot`, `check_time_sync`, `check_security_updates`, `check_oom` (je `StrictBool`,
  Default true). Der Checker schaltet einen Punkt nur bei einem echten `false` ab (wie `alert_on_unavailable`).
- `warning`, wenn ein eingeschalteter Punkt ein Problem zeigt: `reboot_required` true; `time_synchronized` false bei
  `uptime_seconds` ≥ 900 oder fehlender Uptime (der NTP-Client braucht nach dem Booten eine Weile);
  `security_updates` > 0; `oom_kills` > 0. Sonst `ok`. Kein Block (alter Agent, Windows): `ok` mit
  `Not evaluated: no system state in report`. Werte zählen nur als JSON-Bool bzw. ganze JSON-Zahl (`agent_number`),
  alles andere als fehlend. Nie `critical`; `unknown` nur aus `run()` („Waiting for agent data“).
- Meldungen englisch, mit `; ` verbunden: `Reboot required`, `Clock not synchronized`, `3 security updates pending`,
  `2 OOM kills since last report`; sonst `System state OK`.
- `_details`: `{reboot_required, time_synchronized, security_updates, oom_kills, problems: [reboot | time_sync |
  security_updates | oom]}`; nicht ermittelt = `null`.

**`proxmox_backup`:** `ProxmoxBackupConfig.alert_on_unavailable` (`StrictBool`, Default true). Kein Block → `unknown`
„No Proxmox data in report“ mit `_details {"vms": []}` (leert die Liste wie ZFS, `plugins.py:163-166`). Ausfall
(`available` JSON-`false` oder `error` gesetzt) → `warning`, mit Schalter aus `unknown`, Meldung über
`_outage_message("Proxmox", …)` mit der Code-Liste `{timeout, cli_failed, parse_failed, backup_index_incomplete}`,
`_details {"available": false, "error": code, "vms": []}`. Lesbar ohne VMs → `ok` mit `_details {"available": true,
"error": null, "vms": []}`; sonst `available: true` und `error: null` neben `vms`.

**Templates** (R-0420-Versionierung):

- `linux-base` Version 2: eigenes Resources-Dict (bisherige Werte plus `swap_*`, `inode_*`, `load_*`,
  `disk_min_free_gb` 20), neue Definition `system-state` (`system_state`, Config `{}`, `5m`, severity `warning`,
  `consecutive_fails` 1), `service-health` mit angepasster Beschreibung, sonst unverändert. `windows-base` behält die
  bisherigen Dicts; sein Hash bleibt `4be77f8b…` (`tests/test_seed.py:217`).
- `proxmox-host` Version 2: `consecutive_fails` 2.
- Eingefrorene v1-Hashes je Slug (Werte aus `tests/test_seed.py:215-221`). `reconcile_builtin_templates` gibt einer
  Zeile ohne Hash den eingefrorenen v1-Hash (Rückfall für einen Slug ohne Eintrag: der Hash der ausgelieferten
  Definitionen). Eine unveränderte Altzeile folgt damit Version 2, eine damals angepasste bleibt angepasst.
- Angepasste Checks: Die Konfiguration ist ein einziges Override-Feld (`template_sync.py:101-110`). Ein Check mit
  angepasster Konfiguration bekommt die neuen Schlüssel nicht; weil die Checker-Defaults den Template-Werten gleichen,
  bewertet er Swap, Inodes, Load und den GB-Riegel trotzdem gleich.

**API/OpenAPI:** `config` bleibt `dict` (`tests/openapi.snapshot.json`), keine Route ändert sich; neu sind ein Wert für
`check_type` und Schlüssel in `config` und `details`. Keine Alembic-Migration.

**Versionsmatrix:**

| Agent | Monitoring | Ergebnis |
|---|---|---|
| alt (v2) | neu | neue Metriken und Systemzustand unbewertet (`ok`); Platten wie heute (kein `free_gb`); Proxmox-Ausfall weiter `unknown`, jetzt mit leerer VM-Liste |
| neu (v3) | alt | neue Felder ignoriert; Proxmox-Ausfall als `vms: []` → „No VMs/CTs found“ (`ok`), dieselbe Lage wie bei Docker/ZFS (`docs/developer/monitoring.html:134`) |
| neu | neu | volle Bewertung |

Ein älterer Desktop zeigt einen `system_state`-Check ohne Sektion in der Liste und einen Proxmox-Ausfall als „—“.

## Externe Integrationen

- **gopsutil v4.26.5** (`apps/agent/go.mod:6`), im Modul-Cache gelesen: `disk.UsageStat` (`Free` = `Bavail·Bsize`,
  `InodesTotal`, `InodesUsedPercent`, `disk/disk_unix.go:25-50`), `mem.SwapMemoryStat`, `cpu.Times`, `cpu.Counts`, die
  interne Rechnung `getAllBusy`/`calculateBusy` (`cpu/cpu.go:106-129`). Verifiziert am Quelltext.
- **`apt-get(8)`** (https://manpages.debian.org/bookworm/apt/apt-get.8.en.html): `-s` simuliert ohne Sperre
  („Locking will be disabled (Debug::NoLocking)“), die Ausgabe hat je dpkg-Operation eine Zeile `Inst`, `Conf` oder
  `Remv`; `dist-upgrade` behandelt geänderte Abhängigkeiten. Verifiziert. **Nicht verifiziert:** das Format der
  Herkunft in Klammern hinter `Inst` (etwa `Debian-Security:12/stable-security [amd64]`); die Manpage beschreibt es
  nicht. Parser gegen Fixtures, Probe auf der Debian-Box (`scenario`).
- **`timedatectl(1)`** (https://www.freedesktop.org/software/systemd/man/latest/timedatectl.html): `show` zeigt
  dieselben Informationen wie `status` maschinenlesbar, seit systemd 239. **`org.freedesktop.timedate1(5)`**
  (https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.timedate1.html): „NTPSynchronized shows
  whether the kernel reports the time as synchronized (c.f. adjtimex(3))“. Verifiziert. **Nicht verifiziert:** dass
  `show` die Eigenschaft als Zeile `NTPSynchronized=yes` ausgibt (kein Beispiel in der Manpage). `-p`/`--value`
  beschreibt die Manpage nur für `show-timesync`; deshalb ohne `-p`, die Zeile wird gesucht.
- **`/proc/vmstat`** (https://man7.org/linux/man-pages/man5/proc_vmstat.5.html): je Zeile ein Paar `name value`,
  durch Leerraum getrennt. Verifiziert. **Nicht verifiziert:** der Zähler `oom_kill` (in der Manpage nicht aufgeführt;
  nach der Kernel-Quelle seit Linux 4.13). Fehlt die Zeile, fehlt das Feld.
- **`/var/run/reboot-required`:** nicht verifiziert. Weder das Debian-Wiki (UnattendedUpgrades) noch
  `unattended-upgrade(8)` nennen die Datei. Ubuntu legt sie über `update-notifier-common` an; ob Debian und Proxmox VE
  sie bei einem Kernel-Update anlegen, ist offen → Lücke, in der Doku benannt.
- **`needs-restarting -r`** (dnf-plugins-core) und **`dnf -C updateinfo list --security`:** nicht verifiziert (keine
  offizielle Fedora-Seite gefunden; Verhalten unter dnf5 offen). Parser gegen Fixtures; der Pool hat keinen RPM-Host
  mit Paket-Cache, der RPM-Weg bleibt in Doku und CHANGELOG „nicht verifiziert“.
- **`pvesh(1)`** (https://pve.proxmox.com/pve-docs/pvesh.1.html): `--output-format <json | json-pretty | text |
  yaml>`. Verifiziert. Exit-Status und Fehlerverhalten nennt die Seite nicht (nicht verifiziert); die Codes folgen dem
  bestehenden Muster (`runTimed`, `commandFailure`).

## Trade-offs & Alternativen

1. **Neue Werte in `agent_resources` statt eigener Typen** (Empfehlung). Swap, Inodes und Load sind Ressourcen mit
   Warn/Crit-Paar und Hysterese; ein eigener Typ hieße eigene Sektion, Template-Definition und Formular für drei
   Werte. Nachteil: ein angepasster Check bekommt die neuen Template-Werte nicht (abgefangen durch Punkt 2). Nur der
   Systemzustand (kein Schwellenpaar, andere Severity) ist ein eigener Typ (Kevin).
2. **Checker-Default = Template-Wert für die neuen Schlüssel** (Empfehlung) statt „aus, solange nicht konfiguriert“.
   Jeder `agent_resources`-Check eines v3-Linux-Agents bewertet Swap, Inodes und Load, auch handgebaute und
   angepasste. Opt-in nur über das Template ließe angepasste Checks ohne die neuen Werte. Folge: der GB-Riegel gilt
   auch für Windows-Hosts mit v3-Agent (Offene Frage 5).
3. **Ein Zustandsfile für CPU, OOM und Update-Cache, geschrieben nach erfolgreichem Push** (Empfehlung, wie das
   Inventar). Ein verlorener Push verliert keinen OOM-Kill; die CPU mittelt dann über zwei Intervalle. Alternative:
   den CPU-Zustand bei jedem Lauf schreiben — genaueres Fenster, aber zwei Schreibzeitpunkte und OOM-Verlust.
4. **Updates stündlich statt bei jedem Lauf** (Empfehlung). `dnf` lädt bei jedem Aufruf die Metadaten (CPU, RAM); ein
   Sicherheits-Update eilt nicht auf fünf Minuten. Folge: nach dem Patchen bleibt die Warnung bis zu einer Stunde
   stehen. Alternative: neu prüfen, sobald sich `/var/lib/dpkg/status` bzw. die RPM-Datenbank geändert hat — genauer,
   aber Pfade je Distribution; später nachrüstbar.
5. **Load je CPU über `load_5m`** (Empfehlung): passt zum 5-Minuten-Takt; `load_1m` rauscht, `load_15m` verzögert
   zusätzlich zu `consecutive_fails` 3.
6. **Zeit-Sync erst ab 15 min Uptime** (Empfehlung): sonst meldet jeder Neustart kurz einen Zeit-Sync-Fehler.
   Alternative ohne Schonfrist: einfacher, aber laut.
7. **`system_state` mit `consecutive_fails` 1** (Empfehlung, nötig für OOM): der OOM-Zuwachs steht in genau einem
   Report; mit 2 meldete er nie. Alternative: OOM serverseitig über ein Zeitfenster halten — mehr Zustand, kein Gewinn
   neben der Haltezeit aus R-0424.
8. **Mounts exakt statt Glob** (Empfehlung, wie `ignore_devices`/`ignore_containers`).
9. **Ignorierte Mounts bleiben in `_details` (`ignored: true`)** (Empfehlung): der Desktop zeigt die Belegung weiter,
   nur ohne Ampel. Alternative: weglassen — weniger Code, aber die Platte verschwindet aus der Anzeige.
10. **Desktop-Ampel aus `_details.problems`** (Empfehlung) statt eigener Rechnung aus der Konfiguration
    (`SecLive.svelte:52-98`): GB-Riegel, Schwellen je Mount und Hysterese kennt nur der Checker. Ohne `problems`
    (ältere Details) bleibt die eigene Rechnung.
11. **Neustart über Datei bzw. `needs-restarting`** (Kevin) statt Kernel-Vergleich (`uname -r` gegen das neueste
    installierte Kernel-Paket): letzterer fände den Debian/Proxmox-Fall, ist aber je Distribution anders; eigene
    Roadmap-Zeile, falls die Lücke stört.

## Risiken & Rollback

- **Laufzeitbudget des Oneshots:** stündlich bis 30 s für Updates, je Lauf bis 15 s für `timedatectl` und
  `needs-restarting`, zusätzlich zu Docker (10 s je Aufruf), smartctl (30 s je Platte) und Push-Retry;
  `TimeoutStartSec=270` bleibt. Ein hängender Aufruf kostet nur sein Feld. Beleg: grüne `run --once` im Sammellauf und
  in `scenario`.
- **Mehr Meldungen nach dem Update** (Swap, Inodes, Load, Systemzustand), weniger bei großen Platten (GB-Riegel).
  Erwartet; Schwellen am Gate (Offene Fragen 1–4).
- **Lücke „Neustart nötig“ auf Debian/Proxmox** (Datei nicht verlässlich): kein falscher Alarm, nur eine fehlende
  Meldung; die Doku sagt es.
- **Alter Monitoring-Dienst + neuer Agent:** Proxmox-Ausfall als `ok` (Versionsmatrix), dieselbe hingenommene Lage
  wie bei Docker/ZFS; Agent und Monitoring kommen im selben Release.
- **Template-Versionen und `monitoring-alert-quality` (R-0424):** beide ändern `app/builtin_templates.py` (dort ein
  neues Template „Host-Ping“) und die gepinnten Hashes in `tests/test_seed.py:209-225`. Wer zuerst merged, setzt die
  Versionen; das andere Vorhaben zieht nach dem Hereinholen von `origin/main` Hashes und Version nach. Ändert R-0424
  Definitionen von `linux-base`, braucht es Version 3. Ein neues Schema-Feld mit Default ändert keinen Hash
  (`_without_defaults`, `builtin_templates.py:197-207`), die eingefrorenen v1-Hashes bleiben gültig.
- **Datei-Überschneidungen mit parallel geplanten Vorhaben** (Reihenfolge abstimmen, kein geteilter Inhalt):
  - `monitoring-hardening`: `apps/monitoring/app/check_configs.py` (Zahlenfelder; die neuen Felder hier übernehmen das
    Muster, das `main` zum Baustart hat), `apps/monitoring/app/checkers/agent.py` (Zahl- und Text-Helfer,
    `AgentResourcesChecker`, `ServiceProcessChecker`), `apps/monitoring/app/checkers/plugins.py` (Proxmox-Felder),
    `apps/monitoring/app/routers/agent.py` (hier unverändert), `tests/test_check_configs.py`,
    `tests/test_plugin_checkers.py`, `tests/test_agent_resources_checker.py`, `tests/test_checker_messages.py`,
    `CHANGELOG.md`. Empfehlung: `monitoring-hardening` zuerst mergen; dieses Vorhaben holt danach `origin/main`
    herein, bevor T8 startet.
  - `monitoring-alert-quality` (R-0424): `app/builtin_templates.py`, `tests/test_seed.py`,
    `tests/test_template_overrides.py`, `docs/admin/monitoring.html` + EN, `CHANGELOG.md`, Desktop `types.ts`,
    `dictionaries.ts`, ggf. `CheckConfigFields.svelte`. Keine Überschneidung in `check_engine.py`, `alerter.py`,
    Modellen, Alembic (hier nicht berührt).
  - aktiv: `agent-windows-datadir` (`apps/agent/internal/monitor/monitor.go:58-62` in `Init`,
    `docs/developer/agent.html` + EN; hier `Push` `:176-212`) und `desktop-workspaces` (`dictionaries.ts`). Konflikte
    nur textuell.
- **Paritätstest Desktop ↔ Monitoring:** `test_push_only_ui_sync.py` liest `monitoring.ts`; die Task, die den Typ
  einführt, ändert beide Dateien im selben Commit.
- **Rollback:** Revert des Merge-Commits. In der DB stehen dann Templates mit Version 2; ein älterer Dienst bietet
  dafür kein Update an (`builtin_update_available` vergleicht `>`). `system_state`-Checks kennt er nicht: Der Scheduler
  plant sie als Pull-Check, `get_checker` scheitert, der Check steht auf `unknown` ohne Benachrichtigung
  (`check_engine.py:247-260`). Ein zurückgerollter Agent lässt `.report-state.json` liegen; sie wird ignoriert.

## Doku-Impact

Sichtbares Verhalten, DE+EN: `docs/admin/monitoring.html` (Typ-Tabelle `:45-48`, Plugin-Hinweis `:60` und `:64`,
Dienste-Check `:70` und `:73`, Ausfall-Abschnitt `:100-112` wird „Ausfall von Docker, ZFS und Proxmox“, neuer
Abschnitt Systemzustand, Konfig-Tabelle `:128-136`, Hysterese `:141`, Alert-Verhalten `:143`, Standard-Templates
`:232-249`), `README.md:285`, `CHANGELOG.md` unter `## [Unreleased]`. Entwickler-Doku DE+EN:
`docs/developer/agent.html` (Collectors `:108-119`), `docs/developer/monitoring.html` (Payload `:97-134`, Checker
`:149`, `:154-158`).

## Offene Fragen

1. **Swap-Schwellen 80/95 %** (Vorschlag, Kevin am Gate): Linux lagert ruhende Seiten aus; erst hohe Belegung droht
   in den OOM-Killer zu laufen.
2. **Inode-Schwellen 80/90 %** (Vorschlag): dieselben Werte wie die Platten im Template.
3. **Load je CPU 1,5 / 3,0 auf `load_5m`, ohne Hysterese** (Vorschlag). 1,5 je CPU ist die Warnschwelle, die gängige
   Linux-Templates nutzen (nicht verifiziert); 3,0 heißt dauerhaft dreifach überbuchte CPUs.
4. **Systemzustand: severity `warning`, `consecutive_fails` 1, Zeit-Sync erst ab 15 min Uptime, Updates stündlich**
   (Vorschlag; `consecutive_fails` 1 ist für OOM nötig, siehe Trade-off 7).
5. **GB-Riegel auch unter Windows?** Der Agent schickt `free_gb` auf beiden Plattformen, der Checker-Default 20 gilt
   dann auch für `windows-base`-Checks (Template bleibt Version 1). Empfehlung: ja, gleiche Semantik auf beiden
   Plattformen. Alternative: `free_gb` nur unter Linux; Windows-Platten bleiben reine Prozent-Alarme.
6. **`scenario --agents 1` vor dem Merge?** Empfehlung: ja, als Plattform-Beweis auf einem echten Debian-Host mit
   systemd (`timedatectl`, `apt-get -s` gegen echte Paketlisten, `/proc/vmstat`, Zustandsdatei über mehrere
   `run --once`, Laufzeit unter `TimeoutStartSec`). Paketierung, Install, FRP und PKI ändern sich nicht; ohne den Lauf
   bleiben diese Punkte im PR-Text „nicht verifiziert“.

## Entscheidungen am Gate

Entscheidungen am Gate (Kevin 2026-10-19): Standardwerte wie vorgeschlagen: Swap 80/95 %, Inodes 80/90 %, Load je CPU 1,5/3,0 auf `load_5m` ohne Hysterese; `system_state` mit severity warning und `consecutive_fails` 1, Zeit-Sync erst ab 15 min Uptime, Sicherheits-Updates stündlich; die Freie-GB-Grenze gilt auch unter Windows. `scenario --agents 1` läuft vor dem Merge (Kevins Ja). Aus monitoring-alert-quality: Checks der mitgelieferten Templates mit Intervall ab 1 h (SMART, Prognose) bekommen `consecutive_oks` 1; wer als Zweiter mergt, zieht Hashes und Versionen in `test_seed.py` nach. Gebaut wird nach dem Merge von monitoring-hardening (`origin/main` vor T8 hereinholen).
