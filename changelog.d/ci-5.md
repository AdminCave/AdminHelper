### Changed

- **ruff 0.17.4:** Lint und Format der Python-Komponenten laufen mit ruff 0.17.4 (CI, Test-Boxen,
  `requirements-dev.txt`); `ruff.toml` waehlt den bisherigen Regelsatz ausdruecklich, weil ruff 0.16 den
  Standard-Regelsatz stark erweitert hat. Lokal zieht `pip install -r apps/server/requirements-dev.txt` das neue ruff.
