### Fixed

- **Diagnose-Bundle: .env-Zeilen wie compose gelesen:** `diagnostics.sh` erkennt in der `.env` jede Zuweisung so, wie
  compose sie liest, auch mehrere Anweisungen auf einer Zeile und auskommentierte Werte ueber mehrere Zeilen; die
  Maskierung in Logs und `env.sanitized` folgt dem.
