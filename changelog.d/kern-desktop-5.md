### Changed

- **Desktop (Windows): Terminal startet Programme ueber den vollen Pfad:** Eine Terminal-Sitzung startet `ssh` bzw.
  `ansible-playbook` und Windows Terminal ueber den vollen Pfad aus den absoluten `PATH`-Eintraegen; `cmd` ueberspringt
  seine AutoRun-Befehle (`/D`).

### Fixed

- **Desktop (Windows): kein eigenes Konsolenfenster mehr:** Der Release-Build startet ohne Konsolenfenster, ebenso das
  Haerten der Zertifikatsdatei (`icacls`) und SFTP-Aktionen.
