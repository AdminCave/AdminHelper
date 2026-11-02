### Fixed

- **Backup: gesicherte .env behaelt die Anfuehrungszeichen anderer Werte:** steht `CA_ROOT_PASSPHRASE=` im Wert eines
  anderen Schluessels in Anfuehrungszeichen, entfernt der Filter den Text nur noch bis zum schliessenden
  Anfuehrungszeichen; die `env.sanitized` im Backup bleibt fuer docker compose lesbar.
- **init-secrets.sh liest Schluessel wie docker compose:** ein Wert in der Form `export KEY=…`, `KEY = …` oder
  `KEY: …` gilt als gesetzt und bleibt unveraendert; ein leerer Wert in diesen Formen wird ersetzt, ohne eine zweite
  Zeile fuer denselben Schluessel.
