<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI: apt-Schritt der Desktop-Jobs mit Deckel und Retry — Task-Ledger
Status: bereit · Branch: feature/ci-1 · Review: am Ende
Spec: Roadmap R-0825
Heavy: none — nur der Schritt `Tauri system dependencies` zweier Jobs in `.github/workflows/ci.yml`; kein Stack-, Gateway-, PKI- oder Install-Pfad; den Beweis liefert die PR-CI selbst
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Der PR ändert `.github/workflows/`: Kevin merged (CLAUDE.md §2).

### T1 — Tauri-apt-Schritt: Schritt-Deckel 10 min, apt-Retry und Netz-Timeout  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f77ea379 2026-10-30T07:46:03+01:00
Review: am Ende (Branch-Review)
Änderung: Der Schritt `Tauri system dependencies` in `rust` (`ci.yml:594`) und `tauri-build-smoke` (`ci.yml:664`) bekommt `timeout-minutes: 10` (wie der Playwright-Install aus R-0808, `ci.yml:574`), und `apt-get update`/`install` laufen mit `-o Acquire::Retries=3 -o Acquire::http::Timeout=30`. Laut apt.conf(5) wiederholt `Acquire::Retries` fehlgeschlagene Dateien, laut apt-transport-http(1) gilt `Acquire::http::Timeout` für Verbindung und Daten; ein stehender Mirror bricht so nach 30 s ab und wird erneut versucht, statt den Job 45 min zu blockieren. Gemessen auf den letzten sechs main-Läufen (2026-10-30): 21–70 s je Schritt. `release.yml` installiert dieselben Pakete, bleibt aber außerhalb (die Zeile nennt nur die PR-CI; kein Fund dort).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (CI-intern)
Beweis: PR #270 Lauf 39776102278: Job Desktop (tauri build smoke, Linux) cancelled im Schritt Tauri system dependencies nach 45m19s; derselbe Job auf #271 grün in 5m45s
Dedup-Key: bug:ci:tauri-smoke-apt (Roadmap: flaky:ci:tauri-smoke-apt)
HEAD: 29c94b43
Semantik: keine Stelle in docs/ — gesucht nach `Tauri system dependencies`, `timeout-minutes` und apt in docs/developer (DE+EN)
