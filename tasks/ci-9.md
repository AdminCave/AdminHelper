# CI: Caches ohne Werkzeug-Binaries, Browser-Cache am Lockfile — Task-Ledger
Status: erledigt · Branch: feature/ci-9 · Review: am Ende
Spec: docs/features/ci-9.md (Roadmap R-1275)
Heavy: none — nur Workflow-Einstellungen und ein Prüfskript; kein Stack-, Gateway-, PKI- oder Install-Pfad, die PR-CI fährt alles
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1275: rust-cache ohne bin, Playwright-Cache am Lockfile, Prüfskript  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, .github/workflows/release.yml, .github/scripts/cache_settings.sh, .github/scripts/cache_settings_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-9.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @72bc4f398 2026-11-11T09:45:45+01:00
Review: am Ende (Branch-Review)
Änderung: Jeder `Swatinem/rust-cache`-Schritt in `ci.yml` (4×) und `release.yml` (2×) bekommt `cache-bin: false`. Der Playwright-Cache nutzt den Schlüssel `playwright-${{ runner.os }}-${{ hashFiles('apps/web/package-lock.json') }}-chromium`, der Schritt „Playwright version“ fällt weg. Das neue `cache_settings.sh <workflow>…` (SPDX) meldet jeden `rust-cache`-Schritt ohne `cache-bin: false` und jeden Cache auf `ms-playwright` ohne `hashFiles(` im Schlüssel oder mit `restore-keys` als `::error::` mit Datei und Zeile und endet dann mit 1. Der hermetische Test `.github/scripts/cache_settings_test.sh` (SPDX) prüft rot mit veränderten Kopien und grün mit den echten Workflows; er läuft im Job `ops-scripts` wie `tauri_cli_pins_test.sh` (ci-8). Lokal zählt `verify.sh scripts --strict` (shellcheck der ops-Skripte); den Test fährt die Session zusätzlich direkt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-9.md

## Entscheidungen
