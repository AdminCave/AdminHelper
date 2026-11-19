# Agent-Daten für stabile Objektschlüssel (P1e) — Task-Ledger
Status: erledigt · Branch: feature/kern-agent-11 · Review: am Ende
Spec: docs/features/kern-agent-11.md (Roadmap R-1639)
Heavy: linux-full — apps/agent (Report-Felder); geht in den nächtlichen Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — SMART: WWN je Platte (R-1639)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/smart.go, apps/agent/internal/monitor/smart_test.go, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-agent-11.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @b2c8661db 2026-11-19T16:18:24+01:00
Review: am Ende (Branch-Review)
Änderung: `smartctlJSON` liest `wwn{naa,oui,id}` (ATA), `nvme_namespaces[0].eui64{oui,ext_id}` (NVMe) und `logical_unit_id` (SCSI); `SmartDisk.WWN` (`json:"wwn,omitempty"`) bekommt die `lsblk`-Form (`0x%016x` aus naa<<60|oui<<36|id, `eui.%016x` aus oui<<40|ext_id, SCSI-Text unverändert und gekappt), ohne Kennung oder bei 0 leer. Tests je Protokoll, ohne Kennung, schlafende Platte ohne Feld.
Verify: bash scripts/dev/verify.sh agent --strict -- -run Smart
Doku: docs/developer/agent.html DE+EN (collectSmart) · changelog.d/kern-agent-11.md

### T2 — Docker-Compose-Nummer und Proxmox-Clustername (R-1639)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-agent-11.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @9dc5a64fe 2026-11-19T16:20:23+01:00
Review: am Ende (Branch-Review)
Änderung: `putDockerDetails` setzt `compose_number` aus `com.docker.compose.container-number`, nur als positive Ganzzahl. `collectProxmox` setzt `cluster_name` aus `totem { cluster_name: … }` in `/etc/pve/corosync.conf` (Pfad als Testnaht, nur dieser Schlüssel in genau diesem Block, ≤ 255 Zeichen ohne Steuerzeichen); ohne Datei oder Schlüssel fehlt das Feld (Einzel-Node). Tests: Label gültig/ungültig/fehlend, Datei mit/ohne Cluster, Schlüssel in fremdem Block, fehlende Datei.
Verify: bash scripts/dev/verify.sh agent --strict -- -run 'Docker|Proxmox'
Doku: docs/developer/agent.html DE+EN (collectDocker, collectProxmox) · changelog.d/kern-agent-11.md
