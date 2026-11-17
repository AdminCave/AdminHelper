### Added

- **Monitoring HAProxy: Zertifikate ohne Reload:** das Modul `haproxy` warnt, wenn eine Zertifikatsdatei ein
  länger gültiges Zertifikat hält als HAProxy geladen hat (erneuert, aber nicht neu geladen); nur mit einem
  Stats-Socket der Stufe `operator` oder `admin`.
- **Monitoring Moodle: Belegung von moodledata:** `moodle_native` prüft alle 15 Minuten das Dateisystem des
  dataroot (ab 80 % warning, ab 90 % critical, Inodes ab 90 % warning).
