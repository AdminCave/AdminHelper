# kern-agent-22 — Agent: Last-Tor, Zustand nach Push-Fehler, FreeBSD-Platten, Self-Update-TLS, Kleinkram

Roadmap: R-1688, R-1693, R-1700, R-1701, R-1702, R-1704, R-1705. R-1706 fährt nicht mit (s. Offene Fragen).

## Problem / Motivation

- **R-1688:** Das Last-Tor rechnet den verfügbaren Speicher als `100 - memory_percent`
  (`internal/monitor/loadgate.go:121`, Grenze `shedMemAvailPercent` 10, `loadgate.go:19`). gopsutil zählt den
  ZFS-ARC als belegt. Ein PVE-Host mit ZFS oder ein FreeBSD-Host mit warmem ARC liegt deshalb dauerhaft unter 10 %,
  und der Agent setzt ab dem zweiten Lauf Docker, Proxmox, ZFS, SMART, Fehlerzeilen, Proben und Erkennung aus.
- **R-1700:** Nach einem gescheiterten Push übernimmt der Fehlerzweig (`internal/monitor/monitor.go:230-236`)
  Probes, Throttle, Brake, Bindings, Cursors und LoadShed aus dem neuen Stand. Updates und ProxmoxBackups fallen
  aber auf den alten Stand zurück. Dadurch laufen die Stunden- und 30-Minuten-Zählungen bis zum nächsten
  erfolgreichen Push in jedem 5-Minuten-Lauf.
- **R-1701:** Unter FreeBSD ruft `collectDisks` (`internal/monitor/collector.go:304-321`) für jede Partition
  `disk.Usage` auf, also `statfs`. gopsutil liest die Partitionen dort mit `Getfsstat(MNT_WAIT)`. Ein hängender
  NFS- oder SMB-Mount hält den ganzen Lauf an. Unter Linux schützt seit R-1267 die Share-Prüfung davor.
- **R-1693:** Das Windows-Self-Update (`internal/selfupdate/apply_windows.go:131`) prüft TLS gegen `cfg.CACert`.
  Hat der Host eine enrollte Identität, kennt er die Server-CA aus `enroll.CAPath`. Der Server-Push nutzt sie
  bereits (`enroll.ServerClient`), das Self-Update nicht.
- **R-1702:** Der Listener-Schnappschuss (`internal/probe/listen_linux.go:29`, `:122`) parst `/proc/net/tcp` und
  `tcp6` vollständig, auch jede bestehende Verbindung. Auf einem Host mit vielen Verbindungen sind das Megabytes
  Text je Probe-Lauf. `NETLINK_SOCK_DIAG` mit Zustandsfilter `TCP_LISTEN` liefert nur die Listener. Der Agent
  nutzt das schon für die Peer-Prüfung (`peer_linux.go`).
- **R-1704:** `frpc.Sync` loggt bei fehlender `adminhelper.conf` in jedem Lauf auf Info „provision this host once
  more“ (`internal/frpc/sync.go:61-62`). Auf einem Host, der bewusst ohne Tunnel provisioniert ist, ist das Rauschen.
- **R-1705:** Die Ausgaben von `provision` (`internal/provision/provision.go`) und einige cobra-Hilfen in
  `cmd/adminhelper-agent/main.go` sind deutsch. Die übrigen Agent-Texte sind englisch.

## Ziel & Nicht-Ziele

Ziel: Das Last-Tor sieht ZFS-Cache nicht mehr als Last. Nach einem Push-Fehler bleiben die teuren Zählungen
gedrosselt. FreeBSD hängt nicht an Netz-Mounts. Das Self-Update vertraut der enrollten CA. Der Listener-Schnappschuss
liest nur Listener. Ein Host ohne Tunnel loggt kein Rauschen. Die CLI spricht englisch.

Nicht-Ziele:
- `memory_percent` im Report und die Grenzen `memory_warn`/`memory_crit` bleiben unverändert. Ein anderer
  gemeldeter Wert wäre sichtbares Verhalten (Frage an Kevin, eigene Zeile).
- Keine PSI-Auswertung.
- Kein Umbau der `/proc/<pid>/fd`-Suche nach den Haltern eines Sockets (R-1702). Netlink liefert keine PID.
- Keine Übersetzung der Log-Zeilen außerhalb der genannten Dateien.

## Betroffene Komponenten & Dateien

Agent (Go):
- `internal/monitor/loadgate.go`, neu `arc_linux.go`, `arc_freebsd.go`, `arc_other.go`
- `internal/monitor/monitor.go`, `internal/monitor/collector.go`, neu `disks_freebsd.go`, `disks_other.go`
- `internal/selfupdate/apply_windows.go`, neu `client.go`
- `internal/probe/listen_linux.go`
- `internal/frpc/sync.go`
- `internal/provision/provision.go`, `cmd/adminhelper-agent/main.go`
- dazu die jeweiligen Tests

## Datenmodell / API / Migrationen

Keine. Wire-Format des Reports unverändert.

## Externe Integrationen

- ZFS-ARC: Linux `/proc/spl/kstat/zfs/arcstats` (Felder `size`, `c_min`), FreeBSD-Sysctl
  `kstat.zfs.misc.arcstats.size` und `.c_min`. Die Feldnamen werden vor der Umsetzung an der OpenZFS-Quelle
  geprüft.
- Linux `sock_diag(7)`: `inet_diag_req_v2` mit `idiag_states = 1 << TCP_LISTEN`. Die Struktur ist in
  `peer_linux.go` schon abgebildet.
- FreeBSD `getfsstat(2)` mit `MNT_NOWAIT`: liefert die zwischengespeicherte `statfs`-Information aller Mounts,
  ohne einen Mount anzufragen.

## Trade-offs & Alternativen

- **R-1688, ARC über c_min statt PSI:** PSI gibt es nicht auf FreeBSD und nicht in jedem Kernel. ARC oberhalb
  `c_min` gibt der Kernel unter Druck frei. Die Empfehlung ist deshalb `verfügbar += max(0, size - c_min)`, nur im
  Last-Tor.
- **R-1701, eigener FreeBSD-Weg statt Unterprozess wie unter Linux:** `MNT_NOWAIT` liefert Belegung und Typ in einem
  Systemaufruf ohne Mount-Zugriff. Ein Unterprozess je Lauf wäre teurer. Die Werte können veraltet sein, bis der
  Kernel den Mount wieder fragt. Für Belegungsprozente reicht das.
- **R-1702:** Die Halter-Suche über `/proc/*/fd` bleibt. Der Gewinn liegt nur beim Lesen der Socket-Tabelle. Die
  Task misst vorher und nachher. Bringt der Umbau messbar nichts, wird die Task `[~]`.

## Risiken & Rollback

- R-1693 berührt die TLS-Prüfung des Self-Updates. Die Echtheit eines Releases sichert weiter die Signatur über
  `SHA256SUMS`. `security` prüft die Task.
- R-1704 und R-1705 berühren `internal/frpc` und `internal/provision` (Risikopfad, nur Texte und Log-Stufe).
  `security` prüft die Tasks.
- FreeBSD-Code (R-1701, ARC unter FreeBSD) wird hier nur gebaut und mit reinen Funktionen getestet. Eine
  FreeBSD-Box gibt es im Pool nicht. Das bleibt „nicht auf FreeBSD gefahren“.
- Windows-Code (R-1693) prüft die CI (go-windows).
- Rollback: `git revert` je Task.

## Doku-Impact

- `docs/admin/monitoring.html` und `docs/en/admin/monitoring.html`, Abschnitt „Schonung unter Last“: ZFS-ARC über
  `c_min` zählt als verfügbar.
- `docs/developer/agent.html` und EN, sofern sie das Last-Tor, die Platten unter FreeBSD oder den
  Listener-Schnappschuss beschreiben.
- `changelog.d/kern-agent-22.md`.

## Offene Fragen

- **R-1706** (FreeBSD `service status` je rc.d-Skript): Die Zeile verlangt zuerst eine Messung
  (`self.collectors.services.cpu_ms` eines FreeBSD- oder OPNsense-Reports). Eine FreeBSD-Box gibt es im Pool nicht.
  Die Zeile wandert nach `kern-agent-23`, Kevin wird nach dem Messwert gefragt.
- **`memory_percent` auf ZFS-Hosts** (Rest von R-1688): Soll der gemeldete Wert den rückforderbaren ARC auch als
  verfügbar zählen? Das ändert, was Nutzer sehen und wann `memory_warn` auslöst. Als eigene Zeile zur Triage.
