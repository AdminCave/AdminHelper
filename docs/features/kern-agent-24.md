# kern-agent-24 — RAM ohne rückforderbaren ARC, Self-Update-TLS, Netz-Mounts unter FreeBSD

Roadmap: R-1760 (FEAT), R-1769 (REF), R-1772 (BUG). Heavy: linux-full (apps/agent).

## Problem / Motivation
- **R-1760:** `collectMemory` (`apps/agent/internal/monitor/collector.go:117`) meldet `memory_percent` und
  `memory_used_mb`, wie gopsutil sie liest (`Used = Total - Available`, gopsutil v4.26.10 `mem/mem_linux.go:323`,
  `mem/mem_freebsd.go:77`). Den ZFS-ARC zählt das als belegt, obwohl der Kernel ihn unter Druck bis auf `c_min`
  freigibt. Auf PVE-Hosts mit ZFS lösen `memory_warn`/`memory_crit` (80/95) von `agent_resources` deshalb dauerhaft
  aus. Das Last-Tor rechnet den ARC schon heraus (`loadReadingOf`, `loadgate.go:120`, R-1688), der Report nicht.
  Kevin 2026-11-25: bereinigen, der ARC über `c_min` zählt als frei, und die Doku nennt die Abweichung von `free`.
- **R-1769:** Nachlese der Prüfung von kern-agent-22 zum Self-Update-Client (`apps/agent/internal/selfupdate/client.go`)
  und zum Re-Provisioning-Hinweis (`apps/agent/internal/frpc/sync.go:603`). Einzelheiten stehen in der privaten Nachlese.
- **R-1772:** Nachlese der Prüfung von kern-agent-23 zum Plattensammler unter FreeBSD (`disks_bounded.go`,
  `disks_freebsd.go`). Ein hängender Netz-Mount bindet je Lauf eine weitere Goroutine, und ein lokaler Mount
  unterhalb eines Netz-Mounts wird ohne Frist gelesen.

## Ziel & Nicht-Ziele
- Ziel R-1760: Unter Linux und FreeBSD, außerhalb eines Containers, sind `memory_used_mb` und `memory_percent`
  um den ARC über `c_min` bereinigt (höchstens bis auf 0). Das Last-Tor nimmt den bereinigten Wert und rechnet den
  ARC nicht ein zweites Mal ein. Windows, Container und Hosts ohne ZFS bleiben unverändert.
- Ziel R-1769: Der Self-Update-Client eines enrollten Hosts prüft das Serverzertifikat wie der Server-Push.
  Ein Test belegt, dass ein enrollter Host die Einstellungen `insecure` und `cacert` übergeht.
- Ziel R-1772: Für einen Mount gibt es höchstens eine offene statfs-Abfrage über Läufe hinweg. Ein lokaler Mount
  unterhalb eines Netz-Mounts wird wie ein Netz-Mount mit Frist gelesen.
- Nicht-Ziele: keine neuen Schwellen, kein neues Report-Feld, keine Server- oder Monitoring-Änderung.
  `memory_total_mb` bleibt. Die Prozessliste ab 80 % folgt dem bereinigten Wert.

## Betroffene Komponenten & Dateien
`apps/agent/internal/monitor/collector.go`, `loadgate.go`, `collector_test.go`, `loadgate_test.go`, `disks_bounded.go`,
`disks_freebsd.go`, `disks_test.go`; `apps/agent/internal/selfupdate/client.go`, `client_test.go`;
`apps/agent/internal/httpclient/httpclient.go`, `httpclient_test.go`; Doku `docs/developer/agent.html`,
`docs/admin/monitoring.html` (DE+EN).

## Datenmodell / API / Migrationen
Keine. Die Form des Reports bleibt, nur der Wert von `memory_percent`/`memory_used_mb` sinkt auf ZFS-Hosts
(sichtbare Änderung, von Kevin entschieden). Keine Migration und kein Vertrag zwischen Server, Web, Desktop und Agent.

## Externe Integrationen
Keine neuen. Gelesen werden weiter OpenZFS `arcstats` (`/proc/spl/kstat/zfs/arcstats`, Sysctls unter FreeBSD) über
das bestehende `arcReclaimable`.

## Trade-offs & Alternativen
- R-1760: im Monitoring-Dienst bereinigen statt im Agent? Abgelehnt: Der Dienst kennt den ARC nicht, und der Agent
  hat die Zahl schon für das Last-Tor. Ein eigenes Feld `arc_reclaimable_mb` wäre eine API-Erweiterung, YAGNI.
- R-1772: Eine Abfrage je Mount über Läufe hält der Zustand im Paket fest (eine Menge offener Mounts). Im Einmal-Lauf
  aus cron ist sie leer, im Dauerlauf `run` begrenzt sie die Threads auf einen je hängendem Mount.

## Risiken & Rollback
Auf ZFS-Hosts sinkt `memory_percent`; ein Alarm, der heute nur wegen des ARC steht, endet. Rollback ist das Revert
der Task. Der Self-Update-Pfad ist ein Risikopfad (`security` je Task).

## Doku-Impact
`docs/developer/agent.html` DE+EN (`collectMemory`, Last-Tor, Platten unter FreeBSD),
`docs/admin/monitoring.html` DE+EN (RAM von `agent_resources` ohne rückforderbaren ARC, Abweichung von `free`),
`changelog.d/kern-agent-24.md`.

## Offene Fragen
Keine. R-1760 ist von Kevin entschieden (2026-11-25).
