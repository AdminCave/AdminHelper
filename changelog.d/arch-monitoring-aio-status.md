### Added

- **Monitoring: Nextcloud All-in-One prueft status.php:** Das Modul `nextcloud-aio` (Version 2) fragt `status.php`
  am Container `nextcloud-aio-apache` (Port 8000) und meldet einen Fehlschlag oder einen Statuscode ausser 200
  (critical), den Wartungsmodus und ein ausstehendes Datenbank-Upgrade (warning) wie das Modul `nextcloud`. Solange
  das Backup von AIO laeuft, ruht der Check (`ok`, Meldung `Resting (aio.backup = true): ...`); die Karte zeigt die
  Version. Schon uebernommene Instanzen bekommen den Check mit dem Katalog-Update still, erst das Uebernehmen macht
  ihn meldend.

### Changed

- **Monitoring: Bewertung nach Abhaengigkeit:** Ein Report bewertet die Probe-Checks, deren Bedingung einen anderen
  Check des Moduls nennt, nach allen uebrigen; das Ergebnis des anderen Checks aus demselben Report zaehlt damit
  unabhaengig von den Check-IDs.
