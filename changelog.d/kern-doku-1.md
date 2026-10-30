### Changed

- **Doku Agent-Deployment: manuelles apt-Rezept installiert nur den gepinnten Signaturschluessel:** Das Rezept
  importiert die geladene Keyring-Datei in ein Wegwerf-Verzeichnis, exportiert nur den Schluessel mit dem
  veroeffentlichten Fingerprint, prueft den Export und installiert nur ihn — wie `agent-install.sh`. Doku:
  Agent-Deployment (DE+EN).
