<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ci-3 — Task-Ledger
Status: bereit · Branch: feature/ci-3 · Review: pro Task
Spec: docs/features/ci-3.md (Roadmap R-1019, R-1020, R-1042, R-1085)
Heavy: none — nur CI-Workflows und ein pytest-Plugin der Server-Tests; die PR-CI fährt die geänderten Jobs selbst, `release.yml` und das Verify von `docker.yml` erst am nächsten Tag (Spec, Risiken)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@03c4068a`. Den PR merged Kevin (`.github/workflows/`, CLAUDE.md §2); jede Task an einem Workflow ist Risikopfad (`security` je Task).

### T1 — Manifest der Shard-Sammlung und Test der Teilung nach -m/-k (R-1019, R-1020)  [x]
Komponente: server · Dateien: apps/server/tests/conftest.py, apps/server/tests/test_shard.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @06febacf 2026-11-03T17:59:10+01:00
Review: approve (.ah-out/review/ci-3/T1.verdict.json)
Änderung: Neue Option `--shard-manifest <pfad>` (nur mit `--shard`): der `trylast`-Hook (`conftest.py:527`) schreibt vor der Teilung JSON mit `shard` (K/N), `count` (Tests nach `-m`/`-k`) und `sha256` der sortierten Node-IDs. Tests: das Manifest zweier Shards derselben Sammlung ist gleich, eine abweichende Sammlung ändert den Hash; ein `-k`/`-m` wirkt vor der Teilung (die Shards zusammen sind genau die gefilterte Menge, über `pytester` oder einen Unterprozess wie `test_an_invalid_shard_ends_pytest_with_a_usage_error`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_shard.py
Doku: → T2

### T2 — CI vergleicht die Sammlung der Shards, fail-fast der Ergebnis-Matrix, cicd-Doku (R-1019, R-1020)  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_shards.py, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-3.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @5fe52645 2026-11-03T18:02:58+01:00
Review: approve (.ah-out/review/ci-3/T2.verdict.json)
Änderung: Die Jobs `server` und `python-lock-server` rufen pytest mit `--shard-manifest` und laden das Manifest als Artefakt (je Leg und Shard benannt); `server-result` (`ci.yml:133`) und `python-lock-server-result` (`ci.yml:317`) laden die Manifeste ihrer Leg und sind rot, wenn eins fehlt oder `count`/`sha256` abweichen; `server-result` bekommt `fail-fast: false`. `test_ci_shards.py` prüft, dass jeder Shard-Job das Manifest schreibt und hochlädt und jeder Ergebnis-Job es vergleicht. Doku: Shard-Abgleich DE+EN, die doppelte Klammer in `docs/en/developer/cicd.html:40`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_shards.py tests/test_shard.py
Doku: docs/developer/cicd.html + EN · changelog.d/ci-3.md
Abhängt von: T1

### T3 — Actions auf das aktuelle Release, tauri-cli 2.12.4 (R-1042, R-1085)  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, .github/workflows/release.yml, .github/workflows/docker.yml, .github/workflows/audit.yml, changelog.d/ci-3.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d4516fb4 2026-11-03T18:26:48+01:00
Review: approve (.ah-out/review/ci-3/T3.verdict.json)
Änderung: Jede `uses:`-Zeile außer `sigstore/cosign-installer` (T5) und `dtolnay/rust-toolchain` auf den SHA des Releases aus der Spec-Tabelle, Kommentar `# vX.Y.Z`; SHAs unmittelbar vor dem Bau mit `gh api repos/<r>/commits/<tag>` neu holen. `cargo install tauri-cli --version` in `ci.yml:734`, `release.yml:59` und `release.yml:261` auf `2.12.4`. Vorher `grep` nach Eingaben, die die Majors entfernt haben (`pip-install`, `NODE_AUTH_TOKEN`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: changelog.d/ci-3.md

### T4 — Runner ubuntu-26.04, Desktop-Release-Build auf 24.04 (R-1042)  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, .github/workflows/release.yml, .github/workflows/docker.yml, .github/workflows/audit.yml, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-3.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6696ba80 2026-11-03T18:47:46+01:00
Review: approve (.ah-out/review/ci-3/T4.verdict.json)
Änderung: `runs-on: ubuntu-latest` wird `ubuntu-26.04`; nur `release.yml` Job `desktop-linux` wird ausdrücklich `ubuntu-24.04` mit Kommentar (glibc des ausgelieferten Binaries, Spec Trade-offs). `windows-latest` bleibt. Doku DE+EN nennt Runner und die Ausnahme.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + EN · changelog.d/ci-3.md
Abhängt von: T3

### T5 — cosign-installer v4 (R-1042)  [~] (verschoben in ci-4 (R-1119): wartet auf Kevins cosign-Entscheidung)
Komponente: scripts · Dateien: .github/workflows/docker.yml, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-3.md
Änderung: `sigstore/cosign-installer` (`docker.yml:83`, `docker.yml:140`) auf v4.1.2 per SHA; je nach Kevins Antwort cosign 3 (Doku-Abschnitt Signaturen nennt die cosign-Version zum Prüfen, nach Lektüre der cosign-3-Release-Notes zum Ablageort der Image-Signatur) oder `cosign-release: v2.6.x`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + EN · changelog.d/ci-3.md
Abhängt von: T3

## Entscheidungen
- T3: der Manifest-Upload aus T2 stand im Job `server` zwischen `Run pytest` und `No test skipped`; `test_release_images.py::test_the_skip_step_follows_pytest_in_the_leg_with_every_base_image` verlangt den Skip-Schritt direkt nach pytest und war rot (T2-Verify fuhr die Datei nicht). T3 setzt den Upload hinter den Skip-Schritt; alle Server-Tests, die die Workflows lesen: 69 passed, 2 skipped (Redis lokal nicht da).
- T4: auch der `tauri-build-smoke` in `ci.yml` bleibt auf `ubuntu-24.04`, nicht nur `release.yml` `desktop-linux`: der Smoke soll das bauen, was das Release ausliefert, sonst prüft die PR-CI einen anderen Build-Host (andere apt-Pakete, andere glibc) als den des Releases.
