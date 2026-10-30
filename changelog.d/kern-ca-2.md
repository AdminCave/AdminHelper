### Added

- **CA: Rotation nach einem Leck:** `rotate-intermediates --compromised <scope>` behaelt fuer diesen Scope kein
  abgeloestes Zwischenzertifikat; danach gelten dort nur neu ausgestellte Zertifikate (Betrieb, CA-Rotation).

### Fixed

- **CA: Rotation trotz fremdem Zertifikat:** liegt unter `<scope>.crt` ein Zertifikat, das kein Zwischenzertifikat
  dieses Scopes ist, ersetzt die Rotation es auch dann, wenn es nach der Uhr des Hosts noch nicht gilt.
