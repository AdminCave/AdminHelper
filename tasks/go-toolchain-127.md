<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Go-Toolchain auf 1.27 vor dem Support-Ende von 1.26 — Task-Ledger
Status: aktiv · Branch: feature/go-toolchain-127 · Review: am Ende
Spec: Roadmap R-0352
Heavy: linux-full — der Agent baut mit neuem Toolchain, und die Boxen backen Go aus `scripts/vm/bootstrap_linux.sh`; läuft im Sammellauf (`/feature-build` §5)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-13 hatte die Zeile „bis zum ersten Go-1.28-RC“ zurückgestellt; am 2026-10-15 zum Planen gewählt.
Harness-Pfade (`.github/`, `scripts/`): den PR merged Kevin, sofern er es nicht anders sagt (CLAUDE.md §2).

### T1 — Go-Pins in Gleichschritt auf 1.27.2, Doku nachziehen  [ ]
Komponente: agent · Dateien: .github/workflows/ci.yml, .github/workflows/release.yml, .github/workflows/audit.yml, scripts/vm/bootstrap_linux.sh, DEVELOPMENT.md, docs/developer/index.html, docs/en/developer/index.html, CHANGELOG.md
Änderung: Jedes `go-version: "1.26"` (`ci.yml:358`, `:402`, `release.yml:99`, `audit.yml:72`) wird `"1.27"`, `check-latest: true` bleibt; in `bootstrap_linux.sh:19` wird `GO_VERSION` `1.27.2` und `GO_SHA256_LINUX_AMD64` (`:22`) die offizielle SHA-256 aus `https://go.dev/dl/?mode=json`. Die Kommentare, die „1.26.9“ als Grund nennen (`ci.yml:360`, `release.yml:101`, `audit.yml:74`, `:81`), werden allgemein oder auf 1.27 gezogen. `bash scripts/dev/toolchain-lockstep.sh` muss Exit 0 geben (Prüfungen 1, 1b, 1c, 3; govulncheck v1.9.0 deklariert `go 1.26.0` ≤ 1.27). `go.mod` bleibt bei `go 1.25.0`. Doku: DEVELOPMENT.md (Go-Installation `:631-636`, Patch-Hinweis `:711`), `docs/developer/index.html:56` und `docs/en/developer/index.html:41` nennen Go 1.27; CHANGELOG unter Changed. Meldet `gofmt` oder `go vet` von 1.27 im Agent etwas (Release Notes: gofmt-Whitespace, `stdversion`-vet, `%w` mit Pointer), zieht die Task es mit `ledger.sh set-files` nach.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: DEVELOPMENT.md · docs/developer/index.html + docs/en/developer/index.html · CHANGELOG
Beweis: https://go.dev/doc/devel/release (abgerufen 2026-10-15) — „Each major Go release is supported until there are two newer major releases.“; go1.27.0 2026-08-19, go1.27.2 2026-10-08; 1.26 fällt mit Go 1.28 heraus, dann wird `audit.yml` (govulncheck auf der Toolchain) rot. Pins heute: `git grep -n 'go-version: "1.26"' .github` → `ci.yml:358`, `:402`, `release.yml:99`, `audit.yml:72`
Dedup-Key: rel:agent:go-toolchain:1.27
HEAD: c18098a4
Semantik: DEVELOPMENT.md:711 — „den neuesten Patch (1.26.9 oder neuer), sonst weicht der lokale Befund von CI ab“: CI, Release, Audit und Boxen bauen mit derselben, unterstützten Go-Version
