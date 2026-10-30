### Security

- **Update: die .env-Pruefung gibt weniger aus der Datei wieder:** ihre Meldungen nennen nur noch die Zeile.

### Changed

- **Update: Meldungen der .env-Pruefung englisch:** sie nennen die Zeile des Eintrags in `.env`.

### Fixed

- **Update: auskommentierter Pflichtschluessel in .env:** steht ein Schluessel aus `.env.example` (etwa
  `CA_ROOT_PASSPHRASE`) nur als Kommentar in `.env`, haengt das Update ihn wieder aktiv an, statt dass
  `docker compose up` danach abbricht. Ein Schluessel mit `export`, Leerzeichen vor dem `=` oder `:` bekommt keine
  zweite Zeile mehr.
