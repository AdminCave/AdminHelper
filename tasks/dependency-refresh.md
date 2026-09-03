# Dependency-Refresh — Task-Ledger
Status: aktiv · Branch: feature/dependency-refresh · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/dependency-refresh.md
Fast-Suite: lokal · Warm-Profil: desktop
Abschluss: multibox --agents 1 --enforce
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hinweis: Ein Task pro Ökosystem, damit ein Fehlgriff per `git revert` genau eine
Lockfile trifft. **Keine Ignore-Einträge** — ein nicht lösbarer Fund wird `[?]`,
nicht stummgeschaltet. Werkzeuglage (verifiziert): nach `source .devenv.sh` sind
node 22.23.1, npm 10.9.8, cargo und docker lokal da — nur `pip-compile` fehlt,
weshalb T1 den in DEVELOPMENT.md dokumentierten Container-Weg nutzt. **Achtung:
`run.sh` findet `ruff` nicht im PATH und überspringt das Python-Lint-Gate
stillschweigend** — bei T1 deshalb `apps/server/.venv/bin/ruff` direkt aufrufen
(vom Repo-Root aus). `Abschluss: multibox` steht, weil T1 den mTLS-/PKI-Pfad
berührt (CLAUDE.md: Cross-Host-Pfad) — der Lauf bleibt ask-first.

## Phase 1 — Die Locks

### T1 — cryptography auf ≥ 50.0.0 (Server + CA-Issuer)  [ ]
Komponente: apps/server, apps/ca-issuer · Dateien: apps/server/requirements.{in,txt}, apps/ca-issuer/requirements.{in,txt}, CHANGELOG.md
Änderung: In beiden `.in` die Zeile `cryptography>=48.0.0` auf `>=50.0.0` anheben (dokumentiert die Sicherheitsschwelle, statt sie nur zufällig zu treffen). Locks mit dem in DEVELOPMENT.md dokumentierten Verfahren neu erzeugen — je Komponente:
`docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/apps/<komp>:/w" -w /w python:3.12-slim sh -c "pip install -q --user pip-tools && python -m piptools compile --generate-hashes --output-file=requirements.txt requirements.in"`.
`requirements.txt` **nicht** von Hand editieren. Erwartetes Ergebnis: `cryptography==50.0.1`.
Verify: `docker run --rm -v "$PWD:/w" -w /w python:3.12-slim sh -c "pip install -q pip-audit && pip-audit -r apps/server/requirements.txt --disable-pip && pip-audit -r apps/ca-issuer/requirements.txt --disable-pip"` → keine Funde. **Danach zwingend** die Code-Kompatibilität: `source .devenv.sh && AH_ONLY='server ca-issuer' bash scripts/tests/run.sh quick` plus explizit `apps/server/.venv/bin/ruff check apps/server apps/ca-issuer` (run.sh überspringt ruff mangels PATH-Eintrag). Bricht eine cryptography-API weg (CSR-Parsing/Signieren in `apps/ca-issuer/app/{pki,issuer,storage}.py`, `apps/server/app/core/identity.py`), ist das ein echter Code-Fix → nicht raten, `[?]` setzen.
Doku: CHANGELOG (Security) — im selben Commit

### T2 — npm-Lockfiles entschärfen (web, desktop-ui, e2e)  [ ]
Komponente: apps/web, apps/desktop/ui, apps/desktop/e2e · Dateien: die drei `package-lock.json`
Änderung: Nach `source .devenv.sh` (bringt node 22 / npm 10 via nvm) in allen drei Projekten `npm audit fix --package-lock-only` **ohne** `--force` (nur semver-kompatibel). Betrifft brace-expansion, PostCSS, fast-xml-parser, js-yaml — durchweg Dev-/Build-Werkzeug. Verlangt ein Fund `--force` (Major-Bump einer Build-Abhängigkeit), NICHT erzwingen → `[?]`.
Verify: je Projekt `npm audit --audit-level=high` ohne Fund, danach `source .devenv.sh && AH_ONLY='web desktop-ui desktop-e2e' bash scripts/tests/run.sh quick` — svelte-check, eslint und die Unit-Suiten müssen grün bleiben.
Doku: CHANGELOG (Security) — im selben Commit

### T3 — Cargo.lock aktualisieren (quick-xml, rkyv)  [ ]
Komponente: apps/desktop/src-tauri · Dateien: apps/desktop/src-tauri/Cargo.lock, CHANGELOG.md
Änderung: `cargo update` im Verzeichnis `apps/desktop/src-tauri` (semver, **kein** `--aggressive`). Laut Dry-Run bewegt das `plist 1.8.0 → 1.10.0` und `tauri-winrt-notification 0.7.2 → 0.7.3` (beide ziehen dann `quick-xml 0.41.0`) und entfernt `rust_decimal` samt `rkyv 0.7.46` aus dem Baum; `Cargo.toml` bleibt unangetastet.
Verify: `cargo audit` im selben Verzeichnis meldet 0 Vulnerabilities (die unmaintained-GTK3-Warnungen dürfen bleiben), dann `source .devenv.sh && AH_ONLY='desktop-rs' bash scripts/tests/run.sh quick` — `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test` grün.
Doku: CHANGELOG (Security) — im selben Commit

## Phase 2 — Nachweis

### T4 — Audit-Workflow auf dem Branch grün fahren  [ ]
Komponente: .github/workflows · Dateien: keine (reiner Nachweis)
Änderung: Keine Code-Änderung. Nach T1–T3 den Branch pushen und den Audit real auslösen: `gh workflow run audit.yml --ref feature/dependency-refresh`, Lauf mit `gh run watch <id> --exit-status` bis zum Ende verfolgen (CLAUDE.md: CI nach dem Auslösen immer überwachen). Rot heißt: Ursache verstehen, nicht ignorieren.
Verify: Alle vier Jobs (`pip-audit`, `cargo audit`, `npm audit`, `govulncheck`) mit `conclusion: success`. Das ist das eigentliche Erfolgskriterium des Vorhabens — lokale Einzel-Checks zählen nur als Vorstufe.
Doku: keine (Nachweis)
Abhängt von: T1, T2, T3
