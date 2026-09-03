# Dependency-Refresh — Task-Ledger
Status: aktiv (e2e-Entscheidung getroffen: Variante (b); Abschluss-Suiten laufen) · Branch: feature/dependency-refresh · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
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

### T1 — cryptography auf ≥ 50.0.0 (Server + CA-Issuer)  [x] (50.0.1, Locks per Container regeneriert; pip-audit clean, ca-issuer 65 + server 492 passed gegen die neue Version. Review-Korrektur: der CHANGELOG behauptete zunächst, die CVEs träfen CSR-Verarbeitung und mTLS-Identität — falsch, sie betreffen PKCS#7 und den X.509-Verifier, die der Code nicht nutzt; Eintrag sagt das jetzt. Nebenbei DEVELOPMENT.md:48 um apps/ca-issuer ergänzt, das dort fehlte.)
Komponente: apps/server, apps/ca-issuer · Dateien: apps/server/requirements.{in,txt}, apps/ca-issuer/requirements.{in,txt}, CHANGELOG.md
Änderung: In beiden `.in` die Zeile `cryptography>=48.0.0` auf `>=50.0.0` anheben (dokumentiert die Sicherheitsschwelle, statt sie nur zufällig zu treffen). Locks mit dem in DEVELOPMENT.md dokumentierten Verfahren neu erzeugen — je Komponente:
`docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/apps/<komp>:/w" -w /w python:3.12-slim sh -c "pip install -q --user pip-tools && python -m piptools compile --generate-hashes --output-file=requirements.txt requirements.in"`.
`requirements.txt` **nicht** von Hand editieren. Erwartetes Ergebnis: `cryptography==50.0.1`.
Verify: `docker run --rm -v "$PWD:/w" -w /w python:3.12-slim sh -c "pip install -q pip-audit && pip-audit -r apps/server/requirements.txt --disable-pip && pip-audit -r apps/ca-issuer/requirements.txt --disable-pip"` → keine Funde. **Danach zwingend** die Code-Kompatibilität: `source .devenv.sh && AH_ONLY='server ca-issuer' bash scripts/tests/run.sh quick` plus explizit `apps/server/.venv/bin/ruff check apps/server apps/ca-issuer` (run.sh überspringt ruff mangels PATH-Eintrag). Bricht eine cryptography-API weg (CSR-Parsing/Signieren in `apps/ca-issuer/app/{pki,issuer,storage}.py`, `apps/server/app/core/identity.py`), ist das ein echter Code-Fix → nicht raten, `[?]` setzen.
Doku: CHANGELOG (Security) — im selben Commit

### T2 — npm-Lockfiles entschärfen (web, desktop-ui, e2e)  [x] (alle drei melden `found 0 vulnerabilities`. Zunächst nur 2 von 3; die e2e-Frage wurde am 2026-09-03 vom Menschen mit **(b)** entschieden — `overrides` für `deepmerge-ts ^8.0.0` und `@puppeteer/browsers ^3.2.1`, wodurch `extract-zip` durch `modern-tar` ersetzt wird und danach auch dort `npm audit fix` greift. Gate laut Entscheidung: echter GUI-E2E-Lauf auf crabbox. Frühere Notiz: 2 von 3 erledigt und committet — web + desktop-ui melden `found 0 vulnerabilities`. **apps/desktop/e2e braucht eine Entscheidung, siehe unten.** Review-Korrektur: der CHANGELOG nannte zunächst fast-xml-parser und js-yaml als behoben — die liegen ausschließlich im unangetasteten e2e-Lock; jetzt stehen dort die per Lockfile-Diff erhobenen echten Bumps.)

**[?] Entscheidung nötig — `apps/desktop/e2e` ist nicht sauber zu bekommen:**
Nach `npm audit fix` bleiben dort zwei Wurzel-Advisories, 13 high gesamt:
`deepmerge-ts <8.0.0` (GHSA-ggr8-5vv4-36mx) und **`extract-zip`** (GHSA-jmr9-qjv8-65gv)
— letzteres laut GitHub-Advisory mit „Patched versions: **None**", also durch kein
Update lösbar. Beides kommt über `@wdio/utils` (`@puppeteer/browsers` → `extract-zip`,
plus `deepmerge-ts ^7`) in den Baum. `npm audit fix --force` ist keine Option: es stuft
`@wdio/cli` auf 7.40.0 bzw. `@wdio/mocha-framework` auf 8.14.0 **zurück** (package.json
pinnt `^9.19.0`) und erzeugt einen Peer-Konflikt. Drei Wege:

- **(a) So lassen, `npm audit`-Job bleibt rot.** Ehrlich, aber T4 („alle vier Jobs grün")
  ist dann nicht erreichbar, und das Signal bleibt dauerhaft rot — genau der Zustand,
  den dieses Vorhaben beseitigen sollte.
- **(b) Overrides erzwingen:** `deepmerge-ts: ^8.0.0` **plus** `@puppeteer/browsers: ^3.2.1`
  ergibt nachweislich `found 0 vulnerabilities` (vom Review verifiziert). Preis: zwei
  Majors über die deklarierten Ranges von `@wdio/utils` hinweg erzwungen, davon einer in
  einen Baum, in dem der Browser-Download-/Entpack-Pfad komplett ausgetauscht wurde
  (`extract-zip` → `modern-tar`). Kein Unit-Test fängt einen Bruch ab — nur der echte
  GUI-E2E-Lauf auf crabbox (Display nötig) würde es zeigen.
- **(c) Den e2e-Lockfile aus `audit.yml` nehmen.** Widerspricht dem Nicht-Ziel „keine
  Ignore-Einträge" der Spec und macht das Gate blind.

Einschätzung: Das Risiko ist real begrenzt — es ist reines Test-Werkzeug, wird nie
ausgeliefert und verarbeitet nur selbstgeschriebene wdio-Configs bzw. von uns
angestoßene Browser-Downloads. Ich tendiere zu **(b) mit anschließendem echten
E2E-Lauf auf crabbox als Gate**; ohne diesen Lauf wäre (b) ein ungedeckter Scheck.
Entscheidung gehört zum Menschen.
Komponente: apps/web, apps/desktop/ui, apps/desktop/e2e · Dateien: die drei `package-lock.json`
Änderung: Nach `source .devenv.sh` (bringt node 22 / npm 10 via nvm) in allen drei Projekten `npm audit fix --package-lock-only` **ohne** `--force` (nur semver-kompatibel). Betrifft brace-expansion, PostCSS, fast-xml-parser, js-yaml — durchweg Dev-/Build-Werkzeug. Verlangt ein Fund `--force` (Major-Bump einer Build-Abhängigkeit), NICHT erzwingen → `[?]`.
Verify: je Projekt `npm audit --audit-level=high` ohne Fund, danach `source .devenv.sh && AH_ONLY='web desktop-ui desktop-e2e' bash scripts/tests/run.sh quick` — svelte-check, eslint und die Unit-Suiten müssen grün bleiben.
Doku: CHANGELOG (Security) — im selben Commit

### T3 — Cargo.lock aktualisieren (quick-xml, rkyv)  [x] (vier gezielte `-p`-Bumps, 26 statt 246 bewegte Pakete; `cargo audit` Exit 0, fmt/clippy/test grün. Kurskorrektur während der Umsetzung: der volle `cargo update` bewegt tokio/hyper/rustls/rand-0.10 und einen signal-hook-Major — zu viel Fläche vor einem Release; Spec-Prämisse als widerlegt markiert. Review fand drei Ungenauigkeiten, u. a. dass tauri-winrt-notification quick-xml gar nicht hebt, sondern streicht.)
Komponente: apps/desktop/src-tauri · Dateien: apps/desktop/src-tauri/Cargo.lock, CHANGELOG.md
Änderung: **Gezielte** `-p`-Bumps in `apps/desktop/src-tauri` statt eines vollen `cargo update` — `cargo update -p plist -p tauri-winrt-notification -p byte-unit -p tauri-plugin-log`. Das hebt `plist 1.8.0 → 1.10.0` (zieht `quick-xml 0.41.0` statt 0.37.5/0.38.4) und `tauri-winrt-notification 0.7.2 → 0.7.3` (streicht seine quick-xml-Abhängigkeit ganz) und entfernt über `tauri-plugin-log 2.8.0 → 2.9.1` den Teilbaum `byte-unit` → `rust_decimal` → `rkyv 0.7.46`; `Cargo.toml` bleibt unangetastet. **Nicht** der volle Lauf: der bewegt real 246 Zeilen inkl. tokio/hyper/rustls/rand-0.10 und signal-hook-Major (die gegenteilige Annahme der Spec war aus einer gefilterten Dry-Run-Ausgabe entstanden und ist widerlegt).
Verify: `cargo audit` im selben Verzeichnis meldet 0 Vulnerabilities (die unmaintained-GTK3-Warnungen dürfen bleiben), dann `source .devenv.sh && AH_ONLY='desktop-rs' bash scripts/tests/run.sh quick` — `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test` grün.
Doku: CHANGELOG (Security) — im selben Commit

## Phase 2 — Nachweis

### T4 — Audit-Workflow auf dem Branch grün fahren  [x] (**alle vier Jobs grün** gegen den Endstand f8d4376, Lauf 33749518192: pip-audit, npm audit, cargo audit, govulncheck je `success`. Dazu CI-Lauf 33749521184 vollständig grün — inkl. Windows-cargo-test (einziger Ort, an dem tauri-winrt-notification 0.7.3 kompiliert), der vier Image-Builds mit `pip install --require-hashes` gegen die neuen Locks und des Lockstep-Checks. Zwischenstand vorher: 3 von 4, npm rot am e2e-Lockfile — durch die (b)-Entscheidung aufgelöst.)
Komponente: .github/workflows · Dateien: keine (reiner Nachweis)
Änderung: Keine Code-Änderung. Nach T1–T3 den Branch pushen und den Audit real auslösen: `gh workflow run audit.yml --ref feature/dependency-refresh`, Lauf mit `gh run watch <id> --exit-status` bis zum Ende verfolgen (CLAUDE.md: CI nach dem Auslösen immer überwachen). Rot heißt: Ursache verstehen, nicht ignorieren.
Verify: Alle vier Jobs (`pip-audit`, `cargo audit`, `npm audit`, `govulncheck`) mit `conclusion: success`. Das ist das eigentliche Erfolgskriterium des Vorhabens — lokale Einzel-Checks zählen nur als Vorstufe.
Doku: keine (Nachweis)
Abhängt von: T1, T2, T3
