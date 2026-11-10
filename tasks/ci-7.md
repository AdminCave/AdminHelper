# Downloads der CI wiederholen, xrdp-Suite je PR — Task-Ledger
Status: aktiv · Branch: feature/ci-7 · Review: am Ende
Spec: docs/features/ci-7.md (Roadmap R-1130, R-1160, R-1194, R-1142)
Heavy: none — nur `ci.yml`, ein CI-Helfer und Doku; Beweis ist die PR-CI selbst (die geänderten Jobs laufen im PR-Lauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1130, R-1160, R-1194: Downloads mit Frist und Wiederholung  [ ]
Komponente: scripts · Dateien: .github/scripts/retry.sh, .github/workflows/ci.yml
Beweis: R-1130 main@de42e484 Lauf 41888786175 (Desktop-Backend, Schritt-Timeout 10 min); R-1160 Lauf 42171086845 Job 127738815106 @358662df (Download Chrome Headless Shell hängt); R-1194 PR #418 Lauf 42465851987 (504 von github.com)
Dedup-Key: bug:ci:.github/workflows/ci.yml:tauri-deps-apt-step-timeout
Änderung: Neu `.github/scripts/retry.sh <versuche> <sekunden> <befehl…>` (SPDX), jeder Versuch unter `timeout`. Die beiden Schritte „Tauri system dependencies“ laden mit `apt-get update`/`install --download-only` unter `retry.sh 3 180` und `-o Acquire::Retries=3 -o Acquire::http::Timeout=30`, installieren danach aus dem Cache; Schritt-Limit 12 min. `frontend-e2e`: `actions/cache` auf `~/.cache/ms-playwright` (Schlüssel: Version von `playwright-core`), `install-deps chromium` und `install chromium` je unter `retry.sh`; der Kommentar nennt den CDN-Fall. curl an allen vier Stellen mit `--retry 5 --retry-delay 5 --connect-timeout 30`. Beweis ist der PR-Lauf; lokal `shellcheck` des Helfers und die Konsistenz-Tests, die `ci.yml` lesen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T3

### T2 — R-1142: Job rdp-embedded fährt die xrdp-Suite je PR  [ ]
Komponente: scripts · Dateien: .github/workflows/ci.yml
Änderung: Neuer Job `rdp-embedded` („Desktop (embedded RDP vs xrdp)“) auf `ubuntu-26.04`, Limit 45 min: Tauri-Pakete wie in T1, frpc-Sidecar, Rust-Toolchain, `Swatinem/rust-cache`, `cargo install tauri-cli --locked --version "2.12.4"` (Lockstep-Kommentar), dann `bash scripts/tests/desktop_e2e_rdp_embedded.sh`. Der Kommentar am Ende von `ci.yml` (Desktop-E2E bewusst nicht in CI) nennt die Ausnahme. Beweis ist der PR-Lauf des Jobs.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T3
Abhängt von: T1

### T3 — Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-7.md
Änderung: DE und EN in der `ci.yml`-Zeile der Workflow-Tabelle: die Downloads mit Frist und Wiederholung (apt, Playwright mit Browser-Cache, curl), der Job `rdp-embedded` als Ausnahme zum Desktop-E2E-Satz. `changelog.d/ci-7.md` `### Changed`, umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende
Abhängt von: T1, T2

## Entscheidungen
