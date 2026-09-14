<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Dependency-Refresh 2 (audit.yml rot seit 2026-09-07) — Task-Ledger (Kurz)
Status: aktiv · Branch: feature/dependency-refresh-2 · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: tasks/dependency-refresh.md (Vorgänger, gleiche Mechanik) — Kurz-Ledger, keine eigene Spec
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine; der nächste Wochenlauf und der CI-Lauf `audit.yml` (per `gh workflow run audit.yml --ref <branch>`, Kevin) sind der Beweis
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0017 · Hängt ab von: —
Beabsichtigte Semantik: keine Verhaltensänderung; nur Versionsstände. Jede Task endet mit der Schnellsuite der Komponente unter `--strict`.
Befund (Dependency Audit, Lauf 2026-09-07): pip-audit `cryptography 48.0.1` (PYSEC-2026-3552/3553/3554, Fix 49.0.0 bzw. 50.0.0) in server, monitoring, ca-issuer (monitoring: Fehlzuordnung, s. T1) · cargo audit `quick-xml` (RUSTSEC-2026-0194/0195, Fix ≥ 0.41.0) · npm audit: undici, postcss, postcss-selector-parser, brace-expansion, nanoid, deepmerge-ts, extract-zip, fast-xml-parser, ip-address (web, desktop-ui, desktop/e2e).

### T1 — Python: cryptography ≥ 50.0.0 in server, monitoring, ca-issuer  [~] (hinfällig: bereits geschlossen)
Komponente: apps/server, apps/monitoring, apps/ca-issuer · Dateien: apps/*/requirements*.txt bzw. requirements.in (die Pin-Dateien der drei Komponenten)
Änderung: `cryptography` auf die Version heben, die alle drei PYSEC-Einträge schließt (50.0.0 oder neuer); transitive Pins nachziehen, falls die Lock-/Pin-Dateien es verlangen. Keine anderen Pakete anfassen.
Verify: `bash scripts/dev/verify.sh server --strict` und `… monitoring --strict` und `… ca-issuer --strict` grün; `pip-audit -r apps/server/requirements-dev.txt` (im Venv) → `No known vulnerabilities found`, analog monitoring und ca-issuer
Ergebnis 2026-09-14: **keine Änderung nötig.** `cryptography==50.0.1` steht seit `df820cb6` (Vorgänger-Ledger T1, über PR #8 am 2026-09-08 in `main`) in `apps/server/requirements.txt` und `apps/ca-issuer/requirements.txt`; `apps/monitoring` hängt gar nicht von `cryptography` ab (weder direkt in `requirements.in` noch transitiv im Lock) — der Befund hat die Komponente falsch zugeordnet. `pip-audit -r <lock> --disable-pip` (2.10.1) meldet für alle drei Locks `No known vulnerabilities found`. **Abweichung vom Verify-Wortlaut:** geprüft wurden die `requirements.txt`-Locks statt `requirements-dev.txt` — die Locks sind das, was `audit.yml` prüft, und `requirements-dev.txt` existiert nur im server (monitoring und ca-issuer haben keins, die Zeile war dort nicht erfüllbar); der Review hat das server-`requirements-dev.txt` zusätzlich geprüft, ebenfalls sauber. Nebenbefund, **nicht** im Repo: die drei lokalen `.venv` tragen `pip 26.1.2` (PYSEC-2026-3721, Fix 26.2) — Dev-Box-Hygiene, kein Lock-Eintrag, von `audit.yml` nicht erfasst.
Doku: CHANGELOG Unreleased (Changed: Dependency-Refresh)

### T2 — Rust: quick-xml ≥ 0.41 im Desktop-Backend  [~] (hinfällig: bereits geschlossen)
Komponente: apps/desktop/src-tauri · Dateien: apps/desktop/src-tauri/Cargo.lock (ggf. Cargo.toml, wenn ein direkter Pin nötig ist)
Änderung: `cargo update -p quick-xml` (transitiv über Tauri/plist); reicht das nicht, prüfen, welcher Abhängigkeitspfad die alte Version hält, und `[?]` melden statt Major-Bumps von Tauri zu erzwingen.
Verify: `cargo audit` in `apps/desktop/src-tauri` → 0 Vulnerabilities (die bekannten unmaintained-GTK3-Warnungen dürfen bleiben); `bash scripts/dev/verify.sh desktop-rs --strict` grün
Ergebnis 2026-09-14: **keine Änderung nötig.** `Cargo.lock:3407` steht auf `quick-xml 0.41.0` (Vorgänger-Ledger T3, `ee873cfa`, über PR #8 in `main`); RUSTSEC-2026-0194/0195 sind damit geschlossen. `cargo audit` gegen 626 Crates: Exit 0, 0 Vulnerabilities, 12 allowed warnings (unmaintained/unsound GTK3, fxhash, proc-macro-error, rand 0.7/0.8, yanked fastrand) — genau die Menge, die der Verify zulässt.
Doku: CHANGELOG (in T1 gesammelt)

### T3 — npm: Advisories in web, desktop-ui und desktop/e2e schließen  [~] (hinfällig am Gate; ein Rest unter der Gate-Schwelle, siehe unten)
Komponente: apps/web, apps/desktop/ui, apps/desktop/e2e · Dateien: die drei package-lock.json (package.json nur, wo ein direkter Pin nötig ist)
Änderung: `npm audit fix` je Projekt ohne `--force`; bleiben Funde mit Level high oder critical, den Pfad benennen und `[?]` melden statt Major-Bumps zu erzwingen (Vite/Svelte/wdio-Majors sind eigene Vorhaben).
Verify: `npm audit --audit-level=high` in allen drei Projekten ohne Fund; `bash scripts/tests/run.sh quick --strict --only web desktop-ui desktop-e2e` → Exit 0
Ergebnis 2026-09-14: **keine Änderung nötig.** `npm audit --audit-level=high` → Exit 0 in allen dreien; `apps/desktop/e2e` meldet `found 0 vulnerabilities`. Keiner der Befund-Einträge (undici, postcss, postcss-selector-parser, brace-expansion, nanoid, deepmerge-ts, extract-zip, fast-xml-parser, ip-address) existiert noch — alle über den Vorgänger (`390d7852` + die (b)-Overrides) erledigt.
**Neu und unter der Gate-Schwelle:** `apps/web` (3×) und `apps/desktop/ui` (4×) melden GHSA-82fw-gwwq-j7x9 — `@vitest/mocker ≤ 4.1.10`, Severity **moderate**, Fix `vitest 4.1.11` (liegt in den deklarierten Ranges `^4.1.8`/`^4.1.4`, also ein reiner Patch). `audit.yml` prüft `--audit-level=high` und bleibt davon grün. Der Bump ist hier **nicht** machbar: `npm audit fix`, `npm audit fix --package-lock-only` und `npm install --package-lock-only vitest@4.1.11` brechen alle drei mit `TypeError: Cannot read properties of null (reading 'edgesOut')` in `@npmcli/arborist/build-ideal-tree.js:1289` ab (npm 10.9.8 / node 22.23.1, beim Auflösen des vitest-Peer-Sets). Lockfiles blieben unangetastet. → eigener Roadmap-Eintrag, nicht hier erzwingen.
Doku: CHANGELOG (in T1 gesammelt)

### T4 — Audit-Workflow als Beweis  [ ] (Lauf `34814783778`: 3 von 4 grün, `govulncheck` rot → T5; der grüne Branch-Lauf steht noch aus)
Komponente: .github · Dateien: keine Änderung
Änderung: `gh workflow run audit.yml --ref feature/dependency-refresh-2` (wie geplant — die zwischenzeitliche Überlegung, `--ref main` genüge, ist mit T5 hinfällig: `main` trägt den govulncheck-Pin nicht und bleibt rot); alle vier Jobs grün ⇒ Ledger `[x]` mit Run-Id. Der nächste Wochenlauf schließt den `deps-audit`-Eintrag in `seen.md` (nach harness-stufe-3b T3).
Verify: `gh run view <id> --json conclusion --jq .conclusion` → `success`
Doku: keine
Abhängt von: T1, T2, T3
Stand 2026-09-14: **der rote Lauf ist ein veraltetes Signal.** Lauf `34121945020` (2026-09-07, schedule) lief gegen `d4562067` — den Stand *vor* PR #8 (`790bf551`, 2026-09-08), der genau diese Funde geschlossen hat. Seither ist `audit.yml` nicht mehr gelaufen (der für heute 06:17 UTC geplante Lauf hatte um 06:45 noch nicht gefeuert — GitHub verzögert Schedules, der 09-07-Lauf startete auch erst 12:27 UTC). Lokal sind alle vier Dimensionen gegen den aktuellen Baum sauber: pip-audit 3×, cargo audit Exit 0, npm audit 3× Exit 0, govulncheck ohne Repo-Fund. Lauf `34814783778` (2026-09-14 06:45 UTC, `workflow_dispatch` gegen `main` @ `0611ec77`) auf Kevins Ansage real ausgelöst und bis zum Ende verfolgt: **3 von 4 grün** — `pip-audit`, `cargo audit`, `npm audit` je `success`, damit ist der Abhängigkeits-Teil dieses Ledgers (T1–T3) auch in CI belegt. `govulncheck` rot, aber **nicht** wegen eines Befunds: der Job baut sein Werkzeug nicht mehr → neue Task T5.
Nebenbefund `govulncheck`: lokal 5 „affected" + 4 informational, **alle aus der Standardbibliothek** der lokalen Toolchain `go1.25.11` (GO-2026-6218/6090/5972/5856/5026, Fix `go1.25.13`); kein Repo-Modul betroffen, `go.mod` pinnt nur `go 1.25.0` ohne `toolchain`, und CI zieht über `go-version: "1.25"` den neuesten Patch — der CI-Job war und bleibt davon grün. → Dev-Box: Go auf ≥ 1.25.13 heben.

## Abschluss-Notiz (2026-09-14)

**Ergebnis: am Abhängigkeitsstand nichts zu tun — der war beim Start schon in Ordnung.** Der Befund
dieses Ledgers stammt aus Audit-Lauf `34121945020` (2026-09-07), und der lief gegen
`d4562067` — den `main`-Stand *vor* PR #8 (`790bf551`, 2026-09-08), mit dem der
Vorgänger `tasks/dependency-refresh.md` genau diese Funde geschlossen hat. Seitdem hat
`audit.yml` nicht mehr getickt, deshalb steht das rote Signal noch. Kein einziger
Befund-Eintrag existiert heute noch, und **keine Lockfile wurde angefasst**. Der
Branch-Diff gegen `main` umfasst zwei Dateien: dieses Ledger und `.github/workflows/audit.yml`
— letzteres nicht wegen einer Abhängigkeit, sondern wegen T5, das der Beweislauf aufgedeckt hat.

**Gegenprobe gegen den aktuellen Baum, alle vier Dimensionen von `audit.yml`:**

| Job | Befehl | Ergebnis |
|---|---|---|
| pip-audit | `pip-audit -r apps/{server,monitoring,ca-issuer}/requirements.txt --disable-pip` | 3× `No known vulnerabilities found` |
| cargo audit | `cargo audit` in `apps/desktop/src-tauri` | Exit 0 · 0 Vulnerabilities · 12 allowed warnings |
| npm audit | `npm audit --audit-level=high` in `apps/web`, `apps/desktop/ui`, `apps/desktop/e2e` | 3× Exit 0 |
| govulncheck | `govulncheck ./...` in `apps/agent` | kein Repo-Modul betroffen (nur lokale stdlib, s. T4) |

Schnellsuite: `bash scripts/tests/run.sh quick --strict` → `13 passed, 0 failed, 0 skipped, 5 test-skips, 0 reruns` (Exit 0).

**Zwei Nebenbefunde, die hier bewusst nicht erzwungen wurden** (beide eigene
Roadmap-Zeilen wert, keiner macht `audit.yml` rot):
1. `vitest ≤ 4.1.10` (GHSA-82fw-gwwq-j7x9, moderate) in `apps/web` + `apps/desktop/ui`.
   Fix `4.1.11` liegt in den deklarierten Ranges, ist aber mit npm 10.9.8 nicht
   einspielbar — arborist bricht am vitest-Peer-Set ab (Details in T3).
2. Die Audit-Werkzeuge sind nach `source .devenv.sh` nicht erreichbar: `pip-audit` ist auf der Box gar nicht installiert (beide Läufe brauchten ein Wegwerf-Venv), `govulncheck` landet in `$(go env GOPATH)/bin` und liegt nicht im PATH. Die `Verify:`-Zeilen dieses Ledgers sind damit nicht ohne Vorarbeit nachspielbar — eigener Harness-Punkt.
3. Die Dev-Box läuft auf `go1.25.11`; die 9 govulncheck-Treffer sind ausnahmslos
   stdlib-Advisories mit Fix `go1.25.13`. CI zieht über `go-version: "1.25"` den
   neuesten Patch und ist davon nicht betroffen.

**Beweis:** `gh workflow run audit.yml --ref feature/dependency-refresh-2` →
`gh run watch <id> --exit-status`. Gegen `main` genügt es seit T5 nicht mehr — dort fehlt
der govulncheck-Pin, der Job bliebe rot. Grün auf dem Branch schließt R-0017, sobald der
PR gemergt ist.

### T5 — `audit.yml`: govulncheck-Job baut sein Werkzeug nicht mehr  [x] (auf `@v1.7.0` gepinnt)
Komponente: .github · Dateien: .github/workflows/audit.yml
Befund (neu, aus Lauf `34814783778`): Schritt *Install govulncheck* bricht ab mit
`golang.org/x/vuln@v1.8.0 requires go >= 1.26.0 (running go 1.25.14; GOTOOLCHAIN=local)`.
`x/vuln v1.8.0` hat die go-Direktive auf `1.26.0` gehoben; `setup-go` läuft mit
`GOTOOLCHAIN=local`, also darf die Toolchain nicht nachladen. Kein Abhängigkeitsfund —
ein kaputter Job. Alle Actions hängen an vollen SHAs, die drei Audit-Werkzeuge dagegen
nicht: neben diesem `@latest` stehen `pip install pip-audit` (Zeile 30) und
`cargo install cargo-audit --locked` (Zeile 47) ebenso ohne Version da. Rot geworden ist
zuerst govulncheck, weil nur dieser Bezug an eine **fest gepinnte** Toolchain gekoppelt
ist (`setup-go` setzt `GOTOOLCHAIN=local`); `cargo-audit` läuft unter rollendem
`rust-toolchain@stable`, `pip-audit` unter `python-version: "3.13"` — dieselbe Falle, nur
träger. Die beiden hier **nicht** mitgepinnt (Scope) → Roadmap-Zeile.
Änderung: `go install golang.org/x/vuln/cmd/govulncheck@v1.7.0` statt `@latest` — `v1.7.0`
ist die letzte Fassung mit go-Direktive `1.25.0`. **Nicht** stattdessen `go-version` auf
1.26 gehoben: `apps/agent/go.mod` sagt `go 1.25.0` und `release.yml` baut den Agent mit
1.25, ein Scan gegen eine 1.26-stdlib würde also über Binaries urteilen, die so nie
ausgeliefert werden. Die Advisory-DB bleibt davon unberührt (wird zur Laufzeit von
`vuln.go.dev` geholt) — die **Advisory-Daten** altern durch den Pin also nicht; die
Scanner-Logik von v1.8.0+ fehlt sehr wohl, was beim nächsten Anheben nachzuholen ist.
Dritte, verworfene Option: nur für den Install-Schritt `GOTOOLCHAIN=auto` setzen und
`go-version: "1.25"` behalten. Das ginge fachlich (die Build-Toolchain des Werkzeugs
bestimmt die gescannte stdlib nicht — ein mit go1.26 gebautes v1.8.0 meldet beim Scan
weiterhin `Go: go1.25.11`), zieht aber je Lauf eine komplette Toolchain nach und macht
den Job wieder von einem beweglichen Ziel abhängig.
Verify: `GOTOOLCHAIN=local go install golang.org/x/vuln/cmd/govulncheck@v1.7.0` unter go1.25.11
lokal → Exit 0, `Scanner: govulncheck@v1.7.0`, `DB updated: 2026-09-10`; `govulncheck ./...`
in `apps/agent` liefert **dieselben** 5 Symbol-Treffer wie `@latest` (alle `Standard library`
@ `go1.25.11`, Fix ≤ `go1.25.13`) — der Pin ändert die Erkennung nicht, nur die Baubarkeit.
Der eigentliche Beweis ist der Workflow-Lauf auf dem Branch (s. Abschluss-Notiz); CI läuft
auf go1.25.14 und ist von den stdlib-Treffern nicht betroffen.
Doku: keine (CI-Reparatur ohne nach außen sichtbare Wirkung; der Warum-Kommentar steht im Workflow)
