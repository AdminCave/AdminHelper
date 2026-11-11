# CI: Caches ohne Werkzeug-Binaries, Browser-Cache am Lockfile — Task-Ledger
Status: aktiv · Branch: feature/ci-9 · Review: am Ende
Spec: docs/features/ci-9.md (Roadmap R-1275)
Heavy: none — nur Workflow-Einstellungen und ein Prüfskript; kein Stack-, Gateway-, PKI- oder Install-Pfad, die PR-CI fährt alles
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1275: rust-cache ohne bin, Playwright-Cache am Lockfile, Prüfskript  [ ]
Komponente: scripts · Dateien: .github/workflows/ci.yml, .github/workflows/release.yml, .github/scripts/cache_settings.sh, scripts/tests/ci_cache_settings_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-9.md
Änderung: Jeder `Swatinem/rust-cache`-Schritt in `ci.yml` (4×) und `release.yml` (2×) bekommt `cache-bin: false`. Der Playwright-Cache nutzt den Schlüssel `playwright-${{ runner.os }}-${{ hashFiles('apps/web/package-lock.json') }}-chromium`, der Schritt „Playwright version“ fällt weg. Das neue `cache_settings.sh <workflow>…` (SPDX) meldet jeden `rust-cache`-Schritt ohne `cache-bin: false` und jeden Cache auf `ms-playwright` ohne `hashFiles(` im Schlüssel oder mit `restore-keys` als `::error::` mit Datei und Zeile und endet dann mit 1. Der hermetische Test `scripts/tests/ci_cache_settings_test.sh` (SPDX) prüft rot mit veränderten Kopien und grün mit den echten Workflows; er läuft im Job `ops-scripts` und lokal über `verify.sh … -- ci_cache_settings_test` (die Liste `AH_SCRIPT_TESTS_DEFAULT` in `run.sh` ist Harness und bleibt unverändert).
Verify: bash scripts/dev/verify.sh scripts --strict -- ci_cache_settings_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-9.md

## Entscheidungen
