### Added

- **Agent: WWN je Platte:** Der SMART-Report traegt `wwn` je Platte (ATA, NVMe-EUI-64, SCSI-LU-ID, in der Form von
  `lsblk`). Die Monitoring-Neuordnung schluesselt Platten damit stabil; aeltere Agents ohne das Feld bleiben lesbar.
