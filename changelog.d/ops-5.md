### Fixed

- **Backup: gesicherte .env behaelt die Anfuehrungszeichen anderer Werte:** steht `CA_ROOT_PASSPHRASE=` im Wert eines
  anderen Schluessels in Anfuehrungszeichen, entfernt der Filter den Text nur noch bis zum schliessenden
  Anfuehrungszeichen; die `env.sanitized` im Backup bleibt fuer docker compose lesbar.
