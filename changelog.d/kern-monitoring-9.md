### Added

- **Monitoring: Linux-Host im Blick:** neue Module `systemd-timers` (gescheiterte Timer-Laeufe), `kernel`
  (OOPS, Machine Check, Bad Page, haengender Livepatch), `needrestart` (ausstehender Kernel, Microcode, Dienste auf
  alten Bibliotheken), `apt` (kaputte und gehaltene Pakete) und `unattended-upgrades` (Alter und Fehler des letzten
  Laufs); der Agent liest nur und meldet nur Zahlen.
- **Monitoring: AdminHelper ueberwacht sich selbst:** Modul `adminhelper` mit den Containern des Stacks, den
  Health-Endpunkten, dem Verzug des Schedulers und fehlgeschlagenen Alarm-Mails (neue Route `GET /health/detail`,
  nur im Compose-Netz), den Zertifikaten von Gateway, frps und CA, dem Alter des Datenbank-Backups und der Platte
  von VictoriaMetrics.
- **Agent: Dateien im Container und Fuehler `fs`:** `certfile` und `file_age` lesen mit dem Ziel `container` einen
  Pfad im Container ueber dessen Mounts; der neue Fuehler `fs` meldet Belegung, freien Platz und Inodes eines
  Verzeichnisses.

### Fixed

- **pg-backup: gescheiterter Lauf sieht nicht mehr frisch aus:** halbe Dumps liegen in `/backups/.partial` statt
  in `/backups`.
