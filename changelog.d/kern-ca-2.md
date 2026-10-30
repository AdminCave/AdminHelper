### Added

- **CA: Rotation nach einem Leck:** `rotate-intermediates --compromised <scope>` behaelt fuer diesen Scope kein
  abgeloestes Zwischenzertifikat im Trust-Bundle und erneuert keine Zertifikate des alten mehr. Die Geraete des Scopes
  sind danach zu widerrufen und neu einzurichten; ganz geschlossen ist ein Leck erst mit einer neuen Root (Betrieb,
  CA-Rotation).

### Fixed

- **CA: Rotation trotz fremdem Zertifikat:** liegt unter `<scope>.crt` ein Zertifikat, das kein Zwischenzertifikat
  dieses Scopes ist, ersetzt die Rotation es auch dann, wenn es nach der Uhr des Hosts noch nicht gilt.
- **Agent: Server-Zertifikat nur vom Gateway:** nach dem Enrollment nimmt der Agent fuer seine Aufrufe an den Server
  nur ein Zertifikat an, das das `access`-Zwischenzertifikat ausgestellt hat.
