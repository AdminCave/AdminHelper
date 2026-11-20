### Added

- **Agent: Kennungen fuer stabile Monitoring-Objekte:** Der Report traegt `wwn` je Platte (ATA, NVMe-EUI-64,
  SCSI-LU-ID, wie `smartctl` sie liefert), `compose_number` je Compose-Container und auf einem Proxmox-Cluster-Node
  `cluster_name` (aus `/etc/pve/corosync.conf`, ohne zusaetzlichen `pvesh`-Aufruf). Die Monitoring-Neuordnung
  schluesselt Objekte damit stabil; aeltere Agents ohne die Felder bleiben lesbar.
