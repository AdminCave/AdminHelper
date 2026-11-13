### Added

- **Monitoring: Module fuer Speicher, Hardware, USV, Proxmox und Ceph:** die Erkennung findet Software-RAID
  (`mdadm`), LVM-Thin-Pools (`lvm-thin`), Hardware-RAID von Broadcom, Dell und HPE (`hwraid`), die lokalen
  IPMI-Sensoren (`ipmi`), NUT (`nut`, `nut-monitor`), apcupsd, Proxmox VE (Quorum, HA, Replikation, Backup-Laeufe,
  Updates), Proxmox Backup Server (Fuellstand, Wartungsmodus, fehlgeschlagene GC-, Verify-, Sync- und Prune-Jobs), Ceph
  (Health, Pool-Belegung, nur auf Monitor-Hosts) und die Snapshot-Frische von sanoid. Der Agent liest dafuer nur
  Dateien des Kernels oder startet feste Lesekommandos (neuer Sensor `host` fuer Teile des Hosts ohne Unit) und meldet
  nur Zahlen und Zustaende, nie Namen oder Seriennummern; schreibende Aufrufe (etwa `mdadm`, `pvesh set`,
  `proxmox-backup-manager`, `ceph ... set`, `sanoid --cron`, `ipmitool sel`) stehen nicht auf seiner Freigabeliste.
  Die Checks brauchen einen Agent in der Version des Monitoring-Dienstes. Doku: Monitoring, Abschnitte "Speicher,
  Hardware und USV" und "Proxmox, Ceph und sanoid" (DE+EN).

### Changed

- **Monitoring: ZFS Health bewertet Scrub-Alter und vdev-Fehler:** ein Pool, dessen letzter abgeschlossener Scrub
  35 Tage alt ist, warnt, ab 60 Tagen ist er kritisch; ein vdev mit Lese-, Schreib- oder Pruefsummenfehlern warnt.
  Bestehende Installationen koennen nach dem Update dadurch neue Warnungen sehen.
