# ci-9: CI-Caches ohne Werkzeug-Binaries, Browser-Cache am Lockfile

Roadmap: R-1275 (Kevin 2026-11-11).

## Problem / Motivation

- **Rust-Werkzeuge im Cache:** `Swatinem/rust-cache` speichert per Default `~/.cargo/bin` samt `.crates.toml` und
  `.crates2.json` (`cache-bin: true`). Ein wiederhergestelltes `cargo-tauri` gilt dann für
  `cargo install tauri-cli --locked --version …` als installiert und wird nicht neu gebaut. Das betrifft vier Jobs
  in `ci.yml` (`rust`, `rust-windows`, `tauri-build-smoke`, `rdp-embedded`) und die beiden Build-Jobs in
  `release.yml`.
- **Browser-Cache:** Der Schlüssel des Playwright-Caches im Web-E2E-Job hängt an der Version, die
  `playwright-core/package.json` nach `npm ci` meldet. Er soll fest am Lockfile hängen.

Einzelheiten stehen in `tasks/private/`.

## Ziel & Nicht-Ziele

- **Ziel:**
  - Jeder `rust-cache`-Schritt in `ci.yml` und `release.yml` setzt `cache-bin: false`. `tauri-cli` wird in jedem
    Lauf mit dem gepinnten `cargo install` gebaut.
  - Der Playwright-Cache hat den Schlüssel `playwright-<os>-<hashFiles(apps/web/package-lock.json)>-chromium`,
    ohne `restore-keys`.
  - Das neue Skript `.github/scripts/cache_settings.sh` prüft beides im Job `ops-scripts` und meldet jeden
    Verstoß mit Datei und Zeile. Sein hermetischer Test ist `.github/scripts/cache_settings_test.sh`, wie `tauri_cli_pins_test.sh`; er läuft im Job `ops-scripts`.
- **Nicht-Ziele:**
  - `~/.cargo/registry`, `~/.cargo/git` und `target/`: Restrisiko, von Kevin am 2026-11-11 hingenommen.
  - Der apt-Archiv-Cache und das Entpacken von Caches allgemein (R-1288, eigener Zug).
  - Der npm-Cache von `setup-node`.

## Betroffene Komponenten & Dateien

- `.github/workflows/ci.yml`:
  - `rust-cache` bei Z. 773, 797, 850 und 923.
  - Playwright-Cache Z. 694–701; der Schritt „Playwright version“ fällt weg.
  - Neuer Prüfschritt im Job `ops-scripts`, neben `tauri_cli_pins_test.sh` (Z. 1178).
- `.github/workflows/release.yml`: `rust-cache` bei Z. 49 und 251.
- Neu, mit SPDX-Header: `.github/scripts/cache_settings.sh` und `.github/scripts/cache_settings_test.sh`.
- Doku: `docs/developer/cicd.html`, `docs/en/developer/cicd.html`, `changelog.d/ci-9.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

- `Swatinem/rust-cache` v2.9.3 (`src/config.ts`):
  - Mit `cache-bin` = `true` kommen `bin`, `.crates.toml` und `.crates2.json` unter `CARGO_HOME` dazu.
  - Sonst werden nur `registry` und `git` gesichert.
  - Gelesen am 2026-11-11.
- `actions/cache` v6.1.0: Schlüssel mit `hashFiles()`, ohne `restore-keys` nur exakte Treffer.

## Trade-offs & Alternativen

- **Kosten:** `cargo install tauri-cli` baut in drei CI-Jobs und zwei Release-Jobs je Lauf neu, einige Minuten je Job.
  Kevin hat das am 2026-11-11 so entschieden.
- **Playwright:** Ein Schlüssel am Lockfile verfällt bei jeder Änderung an `package-lock.json`. Das kostet einen
  Browser-Download mehr, ist aber vom Inhalt des Checkouts bestimmt, nicht von einem Wert, den `npm ci` erst
  erzeugt.

## Risiken & Rollback

- Ein vergessener `rust-cache`-Schritt in einem künftigen Job: Das Prüfskript macht `ops-scripts` rot.
- Längere Laufzeit der Tauri-Jobs: Deren `timeout-minutes` vor dem Bau gegenprüfen.
- **Rollback:** Revert des Task-Commits. Den Merge macht Kevin (`.github/workflows/`).

## Doku-Impact

`docs/developer/cicd.html` (DE und EN): Die Browser liegen in einem Cache je Lockfile-Stand; `tauri-cli` wird je Lauf
gebaut, und der Rust-Cache hält keine Werkzeug-Binaries. Dazu kommt ein neutraler CHANGELOG-Eintrag.

## Offene Fragen

Keine für diese Zeile. R-1288 fährt nicht mit: Die Frage dazu geht ans Gate.
