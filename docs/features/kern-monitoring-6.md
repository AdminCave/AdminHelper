# Agent: Proxmox-Storage-Abfrage, hängende Netz-Freigaben, Ressourcen-Deckel, Befehls-Freigabeliste (kern-monitoring-6)

Roadmap: R-1219, R-1220, R-1221, R-1222 (Kevin 2026-11-09, diktiert mit dem Monitoring-Konzept; vor dem Release
0.47.0, R-1110). Der Zug ist die Phase P0a/P0e/P0f des Konzepts und läuft vor `arch-monitoring-module` (R-1223), das
denselben Agent-Code erweitert.

## Problem / Motivation
Kevins Vorgabe für das Monitoring: Es darf für Kunden nie spürbar werden; nichts geht kaputt, nichts wird langsamer.
Der heutige Agent verletzt das an drei Stellen, und eine vierte fehlt als Absicherung:

- **R-1219, Proxmox-Collector:** `buildBackupIndex` (`apps/agent/internal/monitor/plugins.go:353`) fragt in jedem
  5-min-Lauf `pvesh get /nodes/<n>/storage --content backup` ab und danach je Backup-Storage dessen Inhalt. Laut
  Quelltext von pve-storage aktiviert die Storage-Liste jeden Storage. Dabei hängt sie eine fehlende NFS/CIFS-Freigabe
  ein, prüft die Verbindung mit 10 s Timeout je Storage und listet auf PBS-Storages alle Snapshots über das Netz. Das
  ist bisher nur aus dem Quelltext belegt und noch nicht an einer Box geprüft.
- **R-1220, Disk-Collector:** `collectDisks` (`apps/agent/internal/monitor/collector.go:249`) ruft `disk.Usage`
  (statfs) für jeden Mount ohne Timeout auf, auch für nfs, nfs4 und cifs. Ein hart gemountetes NFS einer toten Freigabe
  hält den Lauf an, bis systemd ihn nach `TimeoutStartSec=270` abbricht. Damit fällt der ganze Bericht aus. Das ist
  ebenfalls noch nicht an einer Box geprüft.
- **R-1221, Ressourcen-Deckel:** `apps/agent/systemd/adminhelper-agent.service` und das Zwillings-Unit in
  `apps/agent/internal/service/service_linux.go` setzen keine Priorität und keine Grenze. Unter Windows läuft der
  Dienst mit normaler Priorität.
- **R-1222, Freigabeliste:** Die Collectors starten externe Befehle über mehrere Indirektionen (`runTimed`,
  `runWithTimeout`, `runTimedEnv`, `dockerCLI`, `pveshCLI`, `zpoolCLI`, `smartctlCLI`, `systemCLI`, `runSystemctl`,
  `updatesCalls`). Keine Stelle legt fest, welche Befehle mit welchen Argumenten erlaubt sind.

## Ziel & Nicht-Ziele
- **R-1220:** Netz-Dateisysteme fragt der Agent nur in einem eigenen Unterprozess mit Timeout ab. Läuft der Timeout
  ab, fehlt der Mount nicht still, sondern wird als Befund gemeldet: Der Agent schickt ihn in
  `resources.disks_unresponsive`, der Monitoring-Dienst warnt „Network share <mount> not responding“. Der Lauf
  selbst endet weiter pünktlich.
- **R-1219:** Zustand und Typ der Storages kommen aus `/cluster/resources --type storage`, dem Cache von pvestatd,
  der nichts aktiviert. Den Backup-Inhalt fragt der Agent höchstens alle 30 min ab, nur für Storages im Zustand
  `available`, und hält ihn im Report-State zwischen. Vor dem Fix wird der Befund auf einer Pool-VM nachgestellt.
- **R-1221:** Das Linux-Unit (ausgeliefert und dynamisch) bekommt `Nice=19`, `IOSchedulingClass=idle`, `CPUQuota`
  und `MemoryMax`. Der Windows-Dienst setzt seine Prozesspriorität auf „Niedrig“. frpc bleibt unberührt, es ist ein
  eigener Dienst.
- **R-1221, Rücksicht bei Last:** Bei hoher Last misst der Agent nur das Nötigste. Was dann wegfällt und wie der
  Server davon erfährt, ist offen (Frage unten); bis dahin steht die Task auf `[?]`.
- **R-1222:** Jeder externe Befehl der Collectors in `apps/agent/internal/monitor` läuft über genau eine Stelle. Sie
  führt nur Befehle aus einer festen Liste mit festen Argumenten aus; variable Teile (Gerät, Unit, Node, Storage)
  prüft sie gegen ein Muster. Ein Go-Test schlägt fehl, wenn eine andere Datei des Pakets `os/exec` zum Starten nutzt
  oder ein Collector einen Befehl außerhalb der Liste aufruft. Ein Negativtest prüft, dass keine der bekannten Fallen
  (Konzept §3.6) in der Liste steht.
- **Nicht-Ziele:** Takt-Planer, Selbstmessung, Selbstbremse und Erkennung gehören zu R-1223. Ebenso wenig gehören
  hierher Befehle außerhalb der Collectors (`internal/service`, `internal/frpc`: Installation und frpc-Steuerung) und
  der FreeBSD-Agent (R-1247, eigener Branch).

## Betroffene Komponenten & Dateien
- **agent:**
  - `internal/monitor/collector.go`, `plugins.go`, `report.go`, `reportstate.go`, `smart.go`, `system_linux.go`,
    `services_linux.go`, `services_windows.go`, `updates_linux.go`
  - neu: `internal/monitor/netfs.go`, `internal/monitor/allowlist.go`, mit Tests
  - `cmd/adminhelper-agent/` (versteckter Unterbefehl für den statfs-Unterprozess)
  - `systemd/adminhelper-agent.service`, `internal/service/service_linux.go`
  - Windows-Priorität im Dienst-Loop (`cmd/adminhelper-agent/run_windows.go`)
- **monitoring:** `app/checkers/agent.py` (`_grade_disks`) mit Tests.
- **Doku:** `docs/admin/agent-deployment.html`, `docs/admin/monitoring.html`, `docs/developer/agent.html` mit EN-Seiten,
  `changelog.d/kern-monitoring-6.md`.

## Datenmodell / API / Migrationen
- Keine Migration.
- Additiv im Agent-Bericht: `resources.disks_unresponsive: [{"mount", "fstype"}]`. Ältere Server ignorieren das Feld;
  ältere Agenten senden es nicht. Der Monitoring-Dienst bewertet es im Ressourcen-Check als Warnung, ohne Metrik.
- Report-State (lokal, `reportstate.go`): neu der Backup-Index mit Zeitstempel. Ein State ohne dieses Feld
  (älterer Agent) gilt als „noch nie abgefragt“.

## Externe Integrationen
- Proxmox VE API `GET /cluster/resources` (`type=storage`: Felder `storage`, `node`, `status`, `content`,
  `plugintype`) und `GET /nodes/{node}/storage/{storage}/content`. Die Felder werden vor dem Bau im API-Viewer
  (https://pve.proxmox.com/pve-docs/api-viewer/) nachgelesen und an der Pool-Box gegengeprüft.
- systemd.exec(5) / systemd.resource-control(5): `Nice=`, `IOSchedulingClass=`, `CPUQuota=`, `MemoryMax=`. Die
  Wirkung von `idle` hängt vom IO-Scheduler ab (bfq ja, mq-deadline/none nein); in der Doku als „unverifiziert je
  Scheduler“ vermerkt.
- Windows `SetPriorityClass` mit `IDLE_PRIORITY_CLASS` (Task-Manager „Niedrig“), golang.org/x/sys/windows.
- nfs(5): `hard` ist Standard, Anfragen werden endlos wiederholt.

## Trade-offs & Alternativen
- **R-1220, Unterprozess (gewählt, Konzept §3.6):** Ein statfs auf einer toten harten Freigabe kann im Zustand D
  hängen. Ein Unterprozess lässt sich töten oder zurücklassen, ohne den Agent-Lauf zu halten. Alternative Goroutine
  mit Timeout: einfacher, aber der Faden bliebe im Agent-Prozess hängen, und der Windows-Dauerdienst sammelte solche
  Fäden an.
- **R-1220, Befund als eigenes Feld (gewählt):** Würde ein Disk-Eintrag ohne Prozent mitgeschickt, läse der
  heutige Server ihn als 0 % und meldete „ok“. Das eigene Feld bleibt für alte Server unsichtbar und für neue
  eindeutig.
- **R-1219:** Der Backup-Inhalt wird alle 30 min abgefragt (Konzept: 30–60 min). Das bleibt unter dem kleinsten
  sinnvollen Backup-Alter-Schwellwert und wird im Report-State gecacht, weil der Agent als oneshot läuft.
- **R-1221, Werte:**
  - `CPUQuota=25%`: ein Viertel eines Kerns, für die serielle Collector-Kette reichlich.
  - `MemoryMax=256M`: Die Größe gemessener Läufe liegt bei wenigen 10 MB. Der Deckel fängt nur einen Ausreißer
    ab, etwa `docker inspect` vieler Container.
  - Ein Abbruch durch den Deckel kostet einen Messpunkt, nicht den Kundendienst (Kevin: „ein fehlender Messpunkt
    ist besser“).
- **R-1222, eine Ausführungsstelle mit Liste (gewählt):** Prüfbar per Test. Alternative statische Analyse aller
  Argumente: bricht bei zusammengesetzten Argumenten (Gerätepfade aus `smartctl --scan`, Unit-Namen).

## Risiken & Rollback
- **Ressourcen-Deckel:** Ein zu enger `MemoryMax` beendet den Lauf. Das zeigt sich als fehlender Bericht und als
  `OOMKilled` im Journal. Die Doku nennt die Stelle für den Override (`systemctl edit`).
- **Freigabeliste:** Ein vergessener Befehl würde abgelehnt, und ein Collector läge still. Der Tabellentest führt
  jeden bestehenden Aufruf einmal durch die Liste.
- **Merge-Reihenfolge:** `feature/arch-freebsd-agent` ändert `skipFSTypes` in `collector.go` und bringt eigene
  Befehle mit (`rcservice.go`). Wer zuerst merged, zwingt den anderen zum Nachziehen. Neue Collector-Befehle
  brauchen ab diesem Zug einen Listeneintrag; das gilt auch für `arch-monitoring-module`.
- **Rollback:** Revert je Task.
- **Heavy `linux-full`** (apps/agent): Solange der Sammellauf vom 2026-11-09 rot ist, merged die Session den Zug
  nicht.

## Doku-Impact
- Agent-Seite DE+EN: Ressourcen-Deckel mit Override, Netz-Freigaben mit Timeout, Freigabeliste.
- Monitoring-Seite DE+EN: Warnung „Freigabe antwortet nicht“, Backup-Inhalt alle 30 min.
- Entwickler-Agent-Seite: neue Befehle nur über die Liste.
- CHANGELOG über `changelog.d/kern-monitoring-6.md`.

## Offene Fragen
1. **R-1221, Rücksicht bei Last** (Task T6, `[?]`): Was lässt der Agent bei hoher Last aus, und wie erfährt der
   Server davon?
   - Heute wären SMART, Docker-Inspect, der Backup-Index und die Update-Zählung die Kandidaten. Lässt der Agent sie
     einfach weg, liest der Server das als „SMART: keine Daten“ bzw. als verschwundene Container.
   - **Empfehlung:** in `arch-monitoring-module` verschieben. Takt-Planer und Selbstbremse legen dort ohnehin fest,
     wie „übersprungen“ im Datenvertrag aussieht. Die Erkennung, die verschoben werden soll, gibt es erst dort.
