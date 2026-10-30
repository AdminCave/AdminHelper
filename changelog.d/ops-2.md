### Fixed

- **Diagnose-Bundle: .env-Zeilen wie compose gelesen:** `diagnostics.sh` erkennt in der `.env` jede Zuweisung so, wie
  compose sie liest, auch mehrere Anweisungen auf einer Zeile und auskommentierte Werte ueber mehrere Zeilen; die
  Maskierung in Logs und `env.sanitized` folgt dem.
- **Backup: .env-Filter wie compose:** `backup.sh` entfernt `CA_ROOT_PASSPHRASE` aus `env.sanitized` auch hinter
  anderen Anweisungen derselben Zeile und auskommentiert ueber mehrere Zeilen; die anderen Anweisungen der Zeile
  bleiben erhalten.
