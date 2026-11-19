# kern-agent-11 — Agent-Daten für stabile Objektschlüssel (Monitoring-Neuordnung P1e)

Roadmap: R-1639. Grundlage: ADR 0004 §4 (Objekte und stabile Schlüssel) und §11 (Datenlücken im Agent).

## Problem / Motivation
Die Neuordnung (P1a, R-1559) gibt jedem Objekt einen Schlüssel, der Neustart, Umbenennung und Neuanlage übersteht.
Für drei Objektarten liefert der Agent die nötigen Daten nicht. Der Monitoring-Dienst greift deshalb auf
Rückfall-Schlüssel zurück und markiert sie als instabil (`stable = false`):
- **Platte:** Schlüssel ist die WWN. Der Agent sendet Modell und Seriennummer, die WWN nicht.
- **Container:** Schlüssel ist Projekt/Dienst/Nummer. Der Agent sendet Compose-Projekt und -Dienst, das Label
  `com.docker.compose.container-number` nicht (ADR §12.6).
- **Gast-Backup:** Schlüssel ist Cluster + VMID. Der Agent sendet keinen Cluster (R-0519).

Der Windows-Starttyp der Dienste, die vierte Lücke aus dem Titel von R-1639, ist bereits geliefert:
`serviceStartStates` (`apps/agent/internal/monitor/services_windows.go`) mit R-1583 / PR #574. Dafür gibt es keine Task.

## Ziel & Nicht-Ziele
- **Ziel:** Der Agent meldet drei zusätzliche Felder. Es kommen keine zusätzlichen Prozesse dazu, auch kein weiterer `pvesh`-Aufruf:
  - `wwn` je Platte,
  - `compose_number` je Container,
  - `cluster_name` im Proxmox-Block, nur auf einem Cluster-Node.
- **Ziel:** Fehlt eines der Felder, lässt der Agent es weg. Ein alter Agent bleibt damit lesbar, der Dienst fällt
  wie in P1a auf den bisherigen Schlüssel zurück.
- **Nicht-Ziel:** Bewertung oder Schlüsselbildung im Monitoring-Dienst. Die Neuordnung liest `wwn` schon
  (`apps/monitoring/app/checkers/smart.py` auf `feature/arch-monitoring-neu-p1`). `compose_number` und
  `cluster_name` übernimmt die Arch-Session in ihre Schlüssel, die Feldnamen gehen ihr am Gate zu.
- **Nicht-Ziel:** Die übrigen Punkte aus ADR §11 kommen in eigene Zeilen: Pool-GUID, `finished_at`, Sensor-Gerätepfad,
  Mount-Gerät und SSD-Verschleiß.

## Betroffene Komponenten & Dateien
- `apps/agent/internal/monitor/smart.go`:
  - `SmartDisk` (:18) bekommt `WWN string \`json:"wwn,omitempty"\``.
  - `smartctlJSON` (:264) liest `wwn{naa,oui,id}` (ATA), `nvme_namespaces[0].eui64{oui,ext_id}` (NVMe) und
    `logical_unit_id` (SCSI/SAS).
  - Der Aufbau in `querySmartDevice` (:193) setzt das Feld.
- `apps/agent/internal/monitor/plugins.go`:
  - `putDockerDetails` (:148) liest `com.docker.compose.container-number`.
  - `collectProxmox` (:350, Rückgabe :411) liest den Clusternamen aus `/etc/pve/corosync.conf`.
- Tests: `smart_test.go`, `plugins_test.go`.
- Doku: `docs/developer/agent.html` und `docs/en/developer/agent.html` (Collector-Liste :133, :135, :146), dazu
  `changelog.d/kern-agent-11.md`.

## Datenmodell / API / Migrationen
Der Agent-Report bekommt drei zusätzliche, optionale Felder, sonst keine Änderung am Vertrag. Es gibt keine Migration
und kein Server-Schema.
- **`smart.disks[].wwn`:** Text, Form wie `lsblk -o WWN`.
  - ATA: `0x` und 16 Hex-Ziffern aus `naa<<60 | oui<<36 | id`, nach `ata_get_wwn`
    (smartmontools `lib/atacmds.cpp`).
  - NVMe: `eui.` und 16 Hex-Ziffern aus `oui<<40 | ext_id`.
  - SCSI: `logical_unit_id` unverändert.
  - Fehlt eine Kennung oder ist sie null, lässt der Agent das Feld weg.
- **`docker.containers[].compose_number`:** positive Ganzzahl aus dem Label. Ist das Label leer, keine Zahl oder
  ≤ 0, lässt der Agent das Feld weg.
- **`proxmox.cluster_name`:** Text bis 255 Zeichen ohne Steuerzeichen, aus `cluster_name:` im Block `totem` von
  `/etc/pve/corosync.conf`. Ein Einzel-Node hat diese Datei nicht und meldet das Feld nicht; nach ADR §4 ist er
  dann sein eigener Cluster.

## Externe Integrationen
- smartctl-JSON, geprüft an der Quelle `smartmontools/smartmontools@main`:
  - `src/ataprint.cpp`: `jglb["wwn"]["naa"|"oui"|"id"]`
  - `src/nvmeprint.cpp`: `jglb["nvme_namespaces"][0]` mit `["eui64"]["oui"|"ext_id"]`, nur bei EUI-64 ≠ 0
  - `src/scsiprint.cpp`: `jglb["logical_unit_id"]`
- Proxmox: `pve-docs/pvecm.adoc` beschreibt `/etc/pve/corosync.conf` mit `totem { cluster_name: … }`. Beim Trennen
  eines Nodes wird die Datei gelöscht. Die API-Alternative `/cluster/status`, Eintrag `type = cluster` mit `name`,
  ginge nur über einen weiteren `pvesh`-Aufruf je Report.

## Trade-offs & Alternativen
- **Clustername aus der Datei statt aus `pvesh get /cluster/status`:** Ein Dateilesen statt eines Perl-Starts je
  Report. Das folgt ADR §11 („auf dem Host entsteht keine Zusatzlast“) und Kevins Vorgabe vom 2026-11-09, dass
  Monitoring keine Dienst-Leistung kosten darf. Nachteil: Die Datei ist ein Konfigurationsformat, kein API-Vertrag;
  der Parser liest nur `totem.cluster_name` und lässt alles andere liegen.
  **Empfehlung: Datei.**
- **Clustername statt einer Cluster-UUID:** Proxmox hat keine UUID über die API. Der Name ist im Cluster eindeutig
  und ändert sich praktisch nie; eine Umbenennung braucht eine Neuinstallation.
- **WWN als Text in `lsblk`-Form statt als drei Zahlen:** Der Dienst schlüsselt mit Text (`cap_agent_text`), und
  die Form ist die, die ein Admin in `lsblk` sieht.

## Risiken & Rollback
Die Felder sind rein additiv. Ein älterer Monitoring-Dienst ignoriert sie, weil die Checker `_details` aus einer
festen Liste bauen. Rollback ist ein Revert der Agent-Commits. Ein falsch gelesener Clustername würde Objekte nur
anders schlüsseln, nicht falsch bewerten. Weil der Parser nur `cluster_name` im Block `totem` akzeptiert, kann er
keinen Wert aus einem anderen Abschnitt greifen.

## Doku-Impact
`docs/developer/agent.html` (DE+EN): In der Collector-Liste stehen bei Docker, Proxmox und SMART die neuen Felder
und ihre Quelle. CHANGELOG über `changelog.d/kern-agent-11.md` (Added).

## Offene Fragen
Keine. Die Feldnamen stimmt die Session am Gate mit der Arch-Session ab, weil P1a sie liest.
