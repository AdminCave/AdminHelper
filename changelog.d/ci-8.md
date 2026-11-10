### Changed

- **CI: apt-Archiv-Cache strenger geprueft:** vor dem Paket-Download bleiben im Cache nur noch regulaere .deb-Archive,
  die der signierte Paketindex nennt, und ein leeres `partial/`; alles andere wird geloescht.
