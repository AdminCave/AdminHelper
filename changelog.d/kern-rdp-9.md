### Changed

- **Desktop: H.264 im eingebetteten RDP nur auf x86_64:** auf anderen Prozessoren (etwa ARM-Linux) laedt die App
  Ciscos OpenH264 nicht mehr herunter; die Sitzung laeuft ohne H.264 und nennt den Grund im Log.

### Fixed

- **Desktop: eingebettetes RDP fragt nach einem Anmeldefehler neu:** *Neu verbinden* fragt Benutzer und Passwort
  erneut ab, statt das abgelehnte noch einmal zu schicken.
- **Desktop: H.264 aus bleibt aus:** ein beim Ausschalten laufender Download legt Ciscos OpenH264 nicht wieder an.
