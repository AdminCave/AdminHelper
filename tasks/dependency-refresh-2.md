<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Dependency-Refresh 2 (audit.yml rot seit 2026-09-07) — Task-Ledger (Kurz)
Status: blockiert (T4 wartet auf Kevins Workflow-Lauf) · Branch: feature/dependency-refresh-2 · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
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

### T4 — Audit-Workflow als Beweis  [?] (Kevin löst aus — Befehl unten)
Komponente: .github · Dateien: keine Änderung
Änderung: Kevin startet `gh workflow run audit.yml --ref main` (Planfassung: `--ref feature/dependency-refresh-2`; hinfällig, weil dieser Branch keine Abhängigkeitsänderung trägt — der Builder nennt den Befehl, führt ihn laut dieser Task-Zeile ausdrücklich nicht aus); alle vier Jobs grün ⇒ Ledger `[x]` mit Run-Id. Der nächste Wochenlauf schließt den `deps-audit`-Eintrag in `seen.md` (nach harness-stufe-3b T3).
Verify: `gh run view <id> --json conclusion --jq .conclusion` → `success`
Doku: keine
Abhängt von: T1, T2, T3
Stand 2026-09-14: **der rote Lauf ist ein veraltetes Signal.** Lauf `34121945020` (2026-09-07, schedule) lief gegen `d4562067` — den Stand *vor* PR #8 (`790bf551`, 2026-09-08), der genau diese Funde geschlossen hat. Seither ist `audit.yml` nicht mehr gelaufen; der nächste planmäßige Lauf ist heute Mo 06:17 UTC gegen `main`. Lokal sind alle vier Dimensionen gegen den aktuellen Baum sauber: pip-audit 3×, cargo audit Exit 0, npm audit 3× Exit 0, govulncheck ohne Repo-Fund. Beweis-Befehl (Kevin, `main` reicht — dieser Branch trägt keine Abhängigkeitsänderung): `gh workflow run audit.yml --ref main`, dann `gh run watch <id> --exit-status`.
Nebenbefund `govulncheck`: lokal 5 „affected" + 4 informational, **alle aus der Standardbibliothek** der lokalen Toolchain `go1.25.11` (GO-2026-6218/6090/5972/5856/5026, Fix `go1.25.13`); kein Repo-Modul betroffen, `go.mod` pinnt nur `go 1.25.0` ohne `toolchain`, und CI zieht über `go-version: "1.25"` den neuesten Patch — der CI-Job war und bleibt davon grün. → Dev-Box: Go auf ≥ 1.25.13 heben.

## Abschluss-Notiz (2026-09-14)

**Ergebnis: nichts zu tun — das Vorhaben war beim Start schon erledigt.** Der Befund
dieses Ledgers stammt aus Audit-Lauf `34121945020` (2026-09-07), und der lief gegen
`d4562067` — den `main`-Stand *vor* PR #8 (`790bf551`, 2026-09-08), mit dem der
Vorgänger `tasks/dependency-refresh.md` genau diese Funde geschlossen hat. Seitdem hat
`audit.yml` nicht mehr getickt, deshalb steht das rote Signal noch. Kein einziger
Befund-Eintrag existiert heute noch; keine Lockfile wurde in diesem Lauf angefasst
(`git diff --stat` gegen `main`: nur diese Ledger-Datei).

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

**Offen für Kevin:** `gh workflow run audit.yml --ref main` (oder einfach den heutigen
06:17-UTC-Lauf abwarten) → `gh run watch <id> --exit-status`. Grün schließt R-0017.
