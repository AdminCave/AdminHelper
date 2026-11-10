# Downloads der CI wiederholen, xrdp-Suite je PR — Task-Ledger
Status: erledigt · Branch: feature/ci-7 · Review: am Ende
Spec: docs/features/ci-7.md (Roadmap R-1130, R-1160, R-1194, R-1142)
Heavy: none — nur `ci.yml`, ein CI-Helfer und Doku; Beweis ist die PR-CI selbst (die geänderten Jobs laufen im PR-Lauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1130, R-1160, R-1194: Downloads mit Frist und Wiederholung  [x]
Komponente: scripts · Dateien: .github/scripts/retry.sh, .github/workflows/ci.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1a157292f 2026-11-10T07:44:17+01:00
Review: am Ende (Branch-Review)
Beweis: R-1130 main@de42e484 Lauf 41888786175 (Desktop-Backend, Schritt-Timeout 10 min); R-1160 Lauf 42171086845 Job 127738815106 @358662df (Download Chrome Headless Shell hängt); R-1194 PR #418 Lauf 42465851987 (504 von github.com)
Dedup-Key: bug:ci:.github/workflows/ci.yml:tauri-deps-apt-step-timeout
Änderung: Neu `.github/scripts/retry.sh <versuche> <sekunden> <befehl…>` (SPDX), jeder Versuch unter `timeout`. Die beiden Schritte „Tauri system dependencies“ laden mit `apt-get update`/`install --download-only` unter `retry.sh 3 180` und `-o Acquire::Retries=3 -o Acquire::http::Timeout=30`, installieren danach aus dem Cache; Schritt-Limit 12 min. `frontend-e2e`: `actions/cache` auf `~/.cache/ms-playwright` (Schlüssel: Version von `playwright-core`), `install-deps chromium` und `install chromium` je unter `retry.sh`; der Kommentar nennt den CDN-Fall. curl an allen vier Stellen mit `--retry 5 --retry-delay 5 --connect-timeout 30`. Beweis ist der PR-Lauf; lokal `shellcheck` des Helfers und die Konsistenz-Tests, die `ci.yml` lesen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T3

### T2 — R-1142: Job rdp-embedded fährt die xrdp-Suite je PR  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @9995ddb7f 2026-11-10T07:54:19+01:00
Review: am Ende (Branch-Review)
Änderung: Neuer Job `rdp-embedded` („Desktop (embedded RDP vs xrdp)“) auf `ubuntu-26.04`, Limit 45 min: Tauri-Pakete wie in T1, frpc-Sidecar, Rust-Toolchain, `Swatinem/rust-cache`, `cargo install tauri-cli --locked --version "2.12.4"` (Lockstep-Kommentar), dann `bash scripts/tests/desktop_e2e_rdp_embedded.sh`. Der Kommentar am Ende von `ci.yml` (Desktop-E2E bewusst nicht in CI) nennt die Ausnahme. Beweis ist der PR-Lauf des Jobs.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T3
Abhängt von: T1

### T3 — Doku und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-7.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @31abf8d84 2026-11-10T08:03:59+01:00
Review: am Ende (Branch-Review)
Änderung: DE und EN in der `ci.yml`-Zeile der Workflow-Tabelle: die Downloads mit Frist und Wiederholung (apt, Playwright mit Browser-Cache, curl), der Job `rdp-embedded` als Ausnahme zum Desktop-E2E-Satz. `changelog.d/ci-7.md` `### Changed`, umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende
Abhängt von: T1, T2

### T4 — Abschlussprüfung: Test für retry.sh, install-deps ohne Abbruch, shellcheck-Gate  [x]
Komponente: scripts · Dateien: .github/scripts/retry.sh, .github/scripts/retry_test.sh, .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1bc5ae3f8 2026-11-10T08:22:37+01:00
Review: am Ende (Branch-Review)
Änderung: Neu `.github/scripts/retry_test.sh` (SPDX, hermetisch: Erfolg sofort, Erfolg im n-ten Versuch, Exit des letzten Versuchs, 124 nach Frist, Usage 2), als Schritt im Job `ops-scripts`; `retry.sh` liest die Pause aus `RETRY_PAUSE` (Standard 5 s). `npx playwright install-deps chromium` läuft ohne `retry.sh` (dpkg), mit einem apt-Drop-in `Acquire::Retries`/`Acquire::http::Timeout`. `.github/scripts/*.sh` in die shellcheck-Zeile von `ops-scripts`. Doku DE+EN zum Playwright-Schritt nachgezogen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html
Abhängt von: T1

## Entscheidungen
- T4 (Abschlussprüfung): `retry_test.sh` läuft als eigener Schritt in `ops-scripts`, nicht über `run.sh` (Harness-Pfad); lokal belegt mit `retry_test.sh: 10 passed, 0 failed` und drei Mutanten von `retry.sh`, die je rot werden.
