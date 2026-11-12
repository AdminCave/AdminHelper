### Changed

- **CI: apt-Archiv-Cache strenger geprueft:** vor dem Paket-Download bleiben im Cache nur noch regulaere .deb-Archive,
  die der signierte Paketindex nennt, und ein leeres `partial/`; alles andere wird geloescht.
- **CI: jeder tauri-cli-Pin geprueft:** der Lockstep-Schritt vergleicht alle `cargo install tauri-cli`-Zeilen in
  `ci.yml` und `release.yml`, nicht nur die erste je Datei.
