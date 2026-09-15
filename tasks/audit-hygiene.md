<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Audit-Hygiene — Pins, Lockstep-Check, lokale Audit-Tools — Task-Ledger (Kurz)
Status: aktiv · Branch: feature/audit-hygiene · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: tasks/dependency-refresh-2.md (T5, der govulncheck-Pin) und .github/workflows/audit.yml — Kurz-Ledger, keine eigene Spec
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine; Beweis für T1/T2 ist `gh workflow run audit.yml --ref feature/audit-hygiene` (Kevin) mit vier grünen Jobs plus der PR-CI-Job `frp-consistency`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0036, R-0037, R-0039 · Hängt ab von: — · Reihenfolge: vor tasks/harness-stufe-8a.md (beide ändern ci.yml und DEVELOPMENT.md)
Beabsichtigte Semantik: audit.yml bleibt der wöchentliche CVE-Signalgeber; ein Job darf nie „grün, weil das Werkzeug nicht baute". Versionen: pip-audit 2.10.1, cargo-audit 0.22.2, govulncheck v1.7.0 (Stand 2026-09-14, PyPI/crates.io/Go-Proxy geprüft).

### T1 — audit.yml: pip-audit und cargo-audit pinnen  [x] (pip-audit==2.10.1, cargo-audit --version 0.22.2, je mit Begründungs-Kommentar)
Komponente: .github · Dateien: .github/workflows/audit.yml
Änderung: `pip install pip-audit` → `pip install pip-audit==2.10.1`; `cargo install cargo-audit --locked` → `cargo install cargo-audit --locked --version 0.22.2`; je ein Kommentar im Stil des govulncheck-Pins (warum gepinnt, wie heben). Keine weitere Änderung am Workflow.
Verify: grep -c 'pip-audit==2.10.1' .github/workflows/audit.yml   und   grep -c 'cargo-audit --locked --version 0.22.2' .github/workflows/audit.yml   (je 1) — realer Beweis: Kevins Dispatch (Heavy-Zeile)
Doku: keine (intern; cicd.html beschreibt audit.yml ohne Versionen)

### T2 — Lockstep-Check: govulncheck-Pin ↔ go-version  [ ]
Komponente: scripts · Dateien: scripts/dev/toolchain-lockstep.sh (neu, SPDX), scripts/tests/toolchain_lockstep_test.sh (neu, SPDX), scripts/tests/run.sh (nur `AH_SCRIPT_TESTS_DEFAULT`)
Änderung: Skript liest `go-version` aus `.github/workflows/{ci,release,audit}.yml` (alle drei Vorkommen müssen gleich sein; heute je `"1.25"`) und den `govulncheck@vX.Y.Z`-Pin aus audit.yml, holt `https://proxy.golang.org/golang.org/x/vuln/@v/vX.Y.Z.mod` (curl, 10 s) und prüft, dass die `go`-Direktive (major.minor) ≤ go-version ist; Mismatch ⇒ `::error::`-Zeile + Exit 1; Netz nicht erreichbar ⇒ Exit 75. Hermetischer Test mit Fixture-Workflows und einem Fake-`curl` im PATH (Fälle: gleich ⇒ 0; go-version driftet ⇒ 1; Direktive 1.26 bei go-version 1.25 ⇒ 1; kein Netz ⇒ 75), in `AH_SCRIPT_TESTS_DEFAULT` eingetragen. shellcheck sauber.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T3 trägt den CI-Step ein)

### T3 — CI-Step im Job frp-consistency + DEVELOPMENT.md „Audit-Tools lokal"  [ ]
Komponente: .github · Dateien: .github/workflows/ci.yml, DEVELOPMENT.md, docs/developer/cicd.html + docs/en/developer/cicd.html
Änderung: Step „Toolchain pins in lockstep (go-version ↔ govulncheck)" im Job `frp-consistency`: `bash scripts/dev/toolchain-lockstep.sh`. DEVELOPMENT.md: neuer Unterabschnitt `### Audit-Tools lokal` nach `### Optionale Tools` — die drei Werkzeuge mit denselben Pins wie audit.yml und den drei Aufrufen je Komponente: `GOTOOLCHAIN=local go install golang.org/x/vuln/cmd/govulncheck@v1.7.0` (nach `~/go/bin`, in `.devenv.sh` im PATH), `pip-audit` in einem eigenen venv (Debian-pip ist externally-managed; Beispiel `~/.local/share/ah-tools/pip-audit-venv` + Symlink nach `~/.local/bin`), `cargo install cargo-audit --locked --version 0.22.2`; Aufrufe `govulncheck ./...` in apps/agent, `pip-audit -r requirements.txt` je Python-App, `cargo audit` in apps/desktop/src-tauri; Hinweis, dass Go auf der Dev-Box dieselbe Minor wie `go-version` haben muss (Tarball-Swap unter `~/sdk/go`). cicd.html DE + EN: ein Satz zum Lockstep-Step im Absatz zu `frp-consistency`.
Verify: bash scripts/tests/run.sh unit --strict --only scripts   — plus lokal: `govulncheck -version`, `pip-audit --version`, `cargo audit --version` liefern die gepinnten Versionen (Dev-Box seit 2026-09-14 so eingerichtet)
Doku: DEVELOPMENT.md · docs/developer/cicd.html DE+EN · CHANGELOG Unreleased/Changed
Abhängt von: T2
