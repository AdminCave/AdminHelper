### Changed

- **CI: Rust-Cache ohne Werkzeug-Binaries:** jeder `rust-cache`-Schritt in `ci.yml` und `release.yml` laeuft mit
  `cache-bin: false`; `tauri-cli` wird in jedem Lauf aus seinem Pin gebaut.
- **CI: Playwright-Cache am Lockfile:** der Browser-Cache des Web-E2E-Jobs hat einen Schluessel aus dem Hash von
  `apps/web/package-lock.json` und keine `restore-keys`; `.github/scripts/cache_settings.sh` prueft beides.
