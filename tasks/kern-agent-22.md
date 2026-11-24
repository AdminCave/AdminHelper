# kern-agent-22 — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-22 · Review: pro Task
Spec: docs/features/kern-agent-22.md (Roadmap R-1688, R-1700, R-1701, R-1693, R-1702, R-1704, R-1705)
Heavy: linux-full — apps/agent (Sammler, Self-Update, Probe-Listener); Windows-Teil über die CI-Jobs
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1688: Last-Tor zählt rückforderbaren ZFS-ARC als verfügbar  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/loadgate.go, apps/agent/internal/monitor/loadgate_test.go, apps/agent/internal/monitor/arc_linux.go, apps/agent/internal/monitor/arc_freebsd.go, apps/agent/internal/monitor/arc_other.go, apps/agent/internal/monitor/arc_test.go, apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-22.md, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @582accaff 2026-11-24T16:37:00+01:00
Review: approve (.ah-out/review/kern-agent-22/T1.verdict.json)
Beweis: main@4c8173e06 apps/agent/internal/monitor/loadgate.go:19,121 (100 - memory_percent, ARC zählt als belegt) · Dedup-Key: bug:agent:loadgate.go:zfs-arc-counts-as-used
Änderung: `loadReadingOf` addiert `max(0, size - c_min)` des ARC (Linux `/proc/spl/kstat/zfs/arcstats`, FreeBSD Sysctl `kstat.zfs.misc.arcstats.*`) als Anteil am Gesamtspeicher zum verfügbaren Speicher, über eine Naht für die Tests; ohne ZFS unverändert. `memory_percent` im Report bleibt. Test erst rot: ein Host mit 95 % belegt, davon 40 % ARC über c_min, löst das Tor nicht aus; Parser der arcstats mit Fixture. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html (Schonung unter Last), docs/developer/agent.html, docs/en/developer/agent.html (Last-Tor), changelog.d/kern-agent-22.md

### T2 — R-1700: Updates und ProxmoxBackups bleiben nach einem gescheiterten Push gedrosselt  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/monitor.go, apps/agent/internal/monitor/reportstate_test.go
Beweis: main@4c8173e06 apps/agent/internal/monitor/monitor.go:230-236 (Fehlerzweig übernimmt Updates und ProxmoxBackups nicht) · Dedup-Key: aus der Zeile R-1700
Änderung: Der Fehlerzweig übernimmt `Updates` und `ProxmoxBackups` aus dem neuen Stand wie die übrigen Zählungen; Kommentar dazu. Test erst rot: nach einem Push gegen 502 trägt der gespeicherte Stand die gerade gelesenen Updates und den Backup-Index, der nächste Lauf liest sie nicht erneut. `reportstate_test.go` (Schritt 3) erwartet das.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: changelog.d/kern-agent-22.md

### T3 — R-1701: FreeBSD liest die Platten ohne Mount-Zugriff (MNT_NOWAIT)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/disks_freebsd.go, apps/agent/internal/monitor/disks_other.go, apps/agent/internal/monitor/disks_test.go
Beweis: main@4c8173e06 apps/agent/internal/monitor/collector.go:304-321 (disk.Usage je Mount), gopsutil v4.26.10 disk/disk_freebsd.go:27,33 (Getfsstat MNT_WAIT) · Dedup-Key: aus der Zeile R-1701
Änderung: Unter FreeBSD baut `collectDisks` die Liste aus einem `unix.Getfsstat(MNT_NOWAIT)` (Belegung aus dem Kernel-Cache, kein statfs je Mount); die Umrechnung `Statfs_t` → `DiskInfo` ist eine reine Funktion ohne Build-Tag und wird auf Linux getestet (Skip-Regeln, Rundung, Free = Bavail). Andere Systeme unverändert. Nicht auf FreeBSD gefahren (keine Box im Pool), Cross-Build in der Verify. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: changelog.d/kern-agent-22.md

### T4 — R-1693: Windows-Self-Update vertraut der enrollten CA  [ ]
Komponente: agent · Dateien: apps/agent/internal/selfupdate/apply_windows.go, apps/agent/internal/selfupdate/client.go, apps/agent/internal/selfupdate/client_test.go
Beweis: main@4c8173e06 apps/agent/internal/selfupdate/apply_windows.go:131 (httpclient.New(cfg.CACert, …) auch mit enrollter Identität) · Dedup-Key: aus der Zeile R-1693
Änderung: Eine Funktion ohne Build-Tag wählt den Client des Self-Updates: mit enrollter Identität (`enroll.Provisioned`) die CA aus `enroll.CAPath`, sonst wie bisher `cfg.CACert`/`cfg.Insecure`; `check` nutzt sie. Test erst rot auf Linux: ein TLS-Server mit einem Zertifikat der enrollten CA wird mit Identität akzeptiert, ohne passende CA abgelehnt. Windows prüft die CI. Neue Dateien mit SPDX-Header. `security` prüft die Task.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/selfupdate/
Doku: changelog.d/kern-agent-22.md

### T5 — R-1702: Listener-Schnappschuss über NETLINK_SOCK_DIAG  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/listen_linux.go, apps/agent/internal/probe/peer_linux.go, apps/agent/internal/probe/listen_linux_test.go
Änderung: `listenTCP` und `osTakerOwners` holen die Listener (Adresse, Port, uid, inode) per sock_diag mit `idiag_states = 1<<TCP_LISTEN` für IPv4 und IPv6 statt `/proc/net/tcp*` zu parsen; die Halter-Suche über `/proc/*/fd` bleibt. Vorher und nachher messen (Benchmark mit vielen offenen Verbindungen, Zahlen in `## Entscheidungen`); bringt es nichts Messbares, `[~]`. Test: ein eigener Listener auf 127.0.0.1 und ::1 erscheint mit eigener uid und PID, eine bestehende Verbindung nicht.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: keine (internes Verhalten)

### T6 — R-1704: Hinweis „provision this host once more“ nur noch, wo er hilft  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_test.go
Änderung: Fehlt `adminhelper.conf`, loggt `Sync` den Hinweis auf Info nur, wenn `monitor.conf` fehlt oder FRP-Reste da sind (frpc-Konfiguration oder -Dienst), sonst auf Debug. Test für beide Fälle. `security` prüft die Task (Risikopfad).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/
Doku: keine (Log-Stufe)

### T7 — R-1705: CLI-Ausgaben von provision und cobra-Hilfen englisch  [ ]
Komponente: agent · Dateien: apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, apps/agent/cmd/adminhelper-agent/main.go, changelog.d/kern-agent-22.md
Änderung: Die deutschen Ausgaben und Fehlertexte in `provision.go` und die deutschen cobra-Hilfen und Warnungen in `main.go` werden englisch; `provision_test.go` erwartet die neuen Texte. Vorher geprüft: kein Skript, keine Doku-Seite und kein E2E-Test greppt sie (nur `provision_test.go:1036`). `security` prüft die Task (Risikopfad).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/provision/ ./cmd/adminhelper-agent/
Doku: changelog.d/kern-agent-22.md

## Entscheidungen
- 2026-11-24 Plan: R-1706 fährt nicht mit. Die Zeile verlangt zuerst einen Messwert von einer FreeBSD- oder OPNsense-Box, eine solche Box gibt es im Pool nicht. Sie wandert nach kern-agent-23, Kevin wird nach dem Wert gefragt.
- 2026-11-24 Plan: R-1688 ändert nur das Last-Tor. Ob `memory_percent` den ARC auch als verfügbar zählt, ist sichtbares Verhalten und geht als eigene Zeile zu Kevin.
