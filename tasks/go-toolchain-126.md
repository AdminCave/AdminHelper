<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Go-Toolchain 1.26: der Agent ohne die neun stdlib-Funde aus go1.25.14, govulncheck wieder grün (R-0348) — Task-Ledger
Status: aktiv · Branch: harness/go-toolchain-126 · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13: Go 1.26 als Naechstes; F1 1.26 wie in der Zeile, F2 go-Direktive bleibt 1.25.0, F3 check-latest mit T2, F4 tauscht die Aufsicht vor T3; Merge des Gate-PRs auf Kevins Wort; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0348 (Kurz-Ledger ohne Spec)
Heavy: scenario --agents 1 — der Wechsel ändert das ausgelieferte Agent-Binary (anderer Compiler, Runtime und stdlib bei gleicher Quelle und gleicher `go`-Direktive). Nur der Multibox-Lauf baut das .deb mit dem neuen Bootstrap-Go (T3) auf der Server-Box, installiert es über das signierte Repo (:8445) auf einer zweiten Box, provisioniert über :8444 mit mTLS gegen nginx, wartet auf den Monitoring-Push und startet das statische Binary in debian:9; und nur er ruft das neue Tarball-Pin samt SHA-256 in bootstrap_linux.sh wirklich ab. Die CI-Jobs `agent`/`agent-windows` testen gegen Go-eigene httptest-Server, nie gegen nginx/OpenSSL oder eine alte glibc. Kein `--rpm`/`--tunnel`: Paketformate und frpc ändern sich nicht. Läuft nach T3, ask-first, ein VM-Lauf.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/gofmt sauber, Doku DE+EN im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von einem Planungs-Worker für den Chef (adminhelper-ac). Kevin hat die Zeile am 2026-10-13
angenommen („als Nächstes, Gate-PR“). Zeilenangaben origin/main@c37d4198; beim Bau an Symbolen orientieren.

**Gate-PR:** T1 ändert `.github/workflows/` (ci.yml, release.yml, audit.yml), T2 den CI-Gate
`scripts/dev/toolchain-lockstep.sh`. Das sind Harness- und Gate-Pfade nach CLAUDE.md §2 „Merge“: gemergt wird von
Kevin oder auf sein ausdrückliches Wort. `scripts/vm/bootstrap_linux.sh` (T3) steht nicht in
`scripts/dev/harness-paths.txt`.

## Vorab geprüft

- **Der Befund.** Lauf 38269130931 (schedule, main@2ebdef55, 2026-10-12), Job „govulncheck (agent)“, Exit 3:
  setup-go `go-version: "1.25"` nahm go1.25.14 aus dem Toolcache, `govulncheck@v1.7.0` meldet neun aufgerufene
  stdlib-Funde: GO-2026-6617, -6613, -6612, -6611, -6610, -6605, -6603 (net/http), -6608 (net/textproto),
  -6607 (crypto/tls), je „Fixed in: …@go1.26.9“. pip-audit, npm audit und cargo audit sind grün.
- **Kein Fix für 1.25.** Die OSV-Einträge (etwa https://vuln.go.dev/ID/GO-2026-6617.json, veröffentlicht
  2026-10-08) nennen für die stdlib nur `introduced 0 → fixed 1.26.9` und `1.27.0-0 → fixed 1.27.2`. Go-Policy
  (https://go.dev/doc/devel/release): „Each major Go release is supported until there are two newer major
  releases.“ go1.27.0 kam am 2026-08-19; damit ist 1.25 aus dem Support. Neueste Stände dort: go1.25.14
  (2026-08-19), go1.26.9 (2026-10-08), go1.27.2 (2026-10-08).
- **Die Toolcache-Falle.** Das Runner-Image ubuntu-24.04 20261004.327.1 hält Go 1.24.13, 1.25.14 und **1.26.8**
  (https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md). setup-go@924ae3a1 (v6):
  `check-latest` ist per Default `false` (action.yml), aufgelöst wird zuerst aus dem lokalen Cache (README), und
  `GOTOOLCHAIN=local` wird immer gesetzt (src/main.ts, `setGoToolchain`). Ein bloßes `"1.26"` liefe also auf 1.26.8
  und bliebe rot. Mit `check-latest: true` holt setup-go den neuesten Patch aus dem Manifest
  (actions/go-versions, führt 1.26.9). Scheitert dieser Abruf, protokolliert es nur „Failed to resolve version …
  from manifest“ und nimmt den Cache (src/installer.ts, Zweig `checkLatest`).
- **govulncheck-Pin.** x/vuln v1.7.0 verlangt `go 1.25.0`, v1.8.0 und v1.9.0 (2026-10-11) verlangen `go 1.26.0`
  (proxy.golang.org `.mod`). v1.9.0 baut unter 1.26 mit `GOTOOLCHAIN=local`.
- **Lokale Probe** (origin/main@c37d4198, `apps/agent`, alle Go-Caches in einem eigenen Verzeichnis unter `~/.cache`,
  Toolchain per `GOTOOLCHAIN=<version>`):
  - go1.25.14 + govulncheck v1.7.0: dieselben neun Funde, rc 3 (CI-Befund nachgestellt);
  - go1.26.8 + v1.9.0: dieselben neun, „Found in: …@go1.26.8“, rc 3 (die Toolcache-Falle);
  - go1.26.9 + v1.7.0: „No vulnerabilities found.“, rc 0;
  - go1.26.9 + v1.9.0: „No vulnerabilities found.“, rc 0;
  - unter go1.26.9: `gofmt -l` (gofmt aus 1.26.9) leer, `go vet ./...` und `GOOS=windows go vet ./...` rc 0,
    `go test -race -cover ./...` rc 0 (neun Pakete ok), Cross-Build linux (`CGO_ENABLED=0`) und windows rc 0.
    Der Agent-Code braucht also keine Änderung.
- **GODEBUG und die `go`-Direktive** (https://go.dev/doc/godebug): „When compiling a work module or workspace that
  declares an older Go version, the Go toolchain amends its defaults to match that older Go version as closely as
  possible.“ Go 1.26 schaltet per GODEBUG unter anderem SecP256r1MLKEM768/SecP384r1MLKEM1024 ein (`tlssecpmlkem`),
  dazu `urlstrictcolons` und `cryptocustomrand`. Mit `go 1.25.0` in `apps/agent/go.mod:3` bleiben diese Defaults
  auf dem Stand von 1.25. Ohne GODEBUG ändert 1.26 (https://go.dev/doc/go1.26) die Cookie-Zuordnung des
  `http.Client` und die Redirects des `ServeMux`; der Agent hat weder Cookie-Jar noch `ServeMux` (grep über
  `apps/agent`, ohne Tests). Ports: für linux/amd64 und windows/amd64 nichts Neues.
- **Test-Boxen.** `bootstrap_linux.sh:19` pinnt `GO_VERSION` 1.25.0 mit SHA-256 (:22; stimmt mit
  https://go.dev/dl/?mode=json&include=all überein). Jede Box fährt den Bootstrap (`box_*.sh`), installiert dabei Go
  neu, wenn die Version nicht passt (:169–176), und baut den Agent mit `/usr/local/go`
  (`box_agentbox_rpm.sh:19` `make build-linux`, Server-Box über build-deb/build-rpm). Die schwere Ebene testet heute
  also einen Build mit 1.25.0, ausgeliefert wird mit 1.25.14. go1.26.9.linux-amd64.tar.gz: SHA-256
  `42d158b4d8f7b61ac0a830567c940a86098fb7aac52e467a5ebec03ef5cc2f8d` (go.dev-JSON, 66 935 201 Byte).
- **Nebenbefunde in derselben Doku.** DEVELOPMENT.md:1348–1349 sagt, govulncheck bewerte stdlib-Funde „gegen die
  Go-Version, mit der es gebaut wurde“. Die Doku (https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck) sagt: „For
  analyzing source code, that configuration is the Go version specified by the 'go' command found on the PATH.“
  oasdiff v1.32.0 verlangt `go 1.26.0`; die Sätze „die Workflows pinnen aber Go 1.25“ (ci.yml:727–731,
  DEVELOPMENT.md:326–328, cicd.html:396–398, EN :389–391) werden mit dem Bump falsch. Das Tarball bleibt (braucht
  keine Toolchain, SHA-Pin), nur die Begründung wird umformuliert.

## Go-Versionsstellen (frisch gegreppt, origin/main@c37d4198)

| Stelle | heute | Task |
|---|---|---|
| `.github/workflows/ci.yml:358` (Job `agent`) | `go-version: "1.25"` | T1 |
| `.github/workflows/ci.yml:398` (Job `agent-windows`) | `go-version: "1.25"` | T1 |
| `.github/workflows/release.yml:99` (Job `agent`) | `go-version: "1.25"` | T1 |
| `.github/workflows/audit.yml:72` | `go-version: "1.25"` | T1 |
| `.github/workflows/audit.yml:75–81` | Kommentar + `govulncheck@v1.7.0` | T1 |
| `.github/workflows/ci.yml:693–700` | Lockstep-Step (Text bleibt gültig) | — |
| `.github/workflows/ci.yml:727–731` | oasdiff-Kommentar „pin Go 1.25“ | T1 |
| `scripts/dev/toolchain-lockstep.sh:68–100`, `:85` | Prüfung 1, Meldung „today "1.25"“ | T2 |
| `scripts/tests/toolchain_lockstep_test.sh:43–66`, `:226–230` | Fixture (1.25, bleibt), Fall über den echten Baum | T2 |
| `apps/agent/go.mod:3` | `go 1.25.0` | bleibt (F2) |
| `scripts/vm/bootstrap_linux.sh:19`, `:22` | `GO_VERSION` 1.25.0 + SHA-256 | T3 |
| `scripts/tests/box_*.sh` (`PATH=…:/usr/local/go/bin`) | Verbraucher des Bootstrap-Go | — |
| `DEVELOPMENT.md:326–328` | oasdiff-Begründung „Go 1.25“ | T3 |
| `DEVELOPMENT.md:1272–1276` | „Go 1.25+ installieren“, `go1.25.x`-Tarball | T3 |
| `DEVELOPMENT.md:1322` | `govulncheck@v1.7.0` | T3 |
| `DEVELOPMENT.md:1348–1356` | „heute `1.25`“, Lockstep-Absatz | T3 (T2: Satz zu `check-latest`) |
| `docs/developer/cicd.html:40` + `docs/en/developer/cicd.html:40` | Lockstep-Beschreibung | T2 |
| `docs/developer/cicd.html:396–398` + `docs/en/developer/cicd.html:389–391` | oasdiff „Go 1.25“ | T1 |
| `docs/developer/index.html:56` + `docs/en/developer/index.html:41` | „Go 1.25, Cobra CLI …“ | T3 |
| `docs/developer/agent.html:55` + `docs/en/developer/agent.html:55` | „go.mod Go 1.25“ | bleibt (F2) |
| `~/sdk/go` der Dev-Box (`.devenv.sh` legt es vor das System-Go) | go1.25.14 | F4, vor T3 |
| `CHANGELOG.md:202–203`, `:934–940`, `docs/features/harness-stufe-8a.md:94` | Historie | — |

Ohne Go-Version: `apps/agent/Makefile`, `build-deb.sh`, `build-rpm.sh`, `build-common.sh`, `build-repo.sh`, alle
Dockerfiles (kein `golang:`-Image), `.claude/rules/release.md`, README.

## Offene Fragen (gesammelt, mit Empfehlung)

- **F1 (Kevin, Inhalt der Zeile): 1.26 wie angenommen oder gleich 1.27?** Empfehlung **1.26**: Das ist der
  kleinste Sprung. 1.27 entfernt GODEBUG-Schalter und leert HTTP/1-Bodies beim Schließen
  (https://go.dev/doc/go1.27). x/vuln v1.9.0 baut auf 1.26, der Fix steckt in go1.26.9. Trade-off: 1.26 fällt mit
  1.28 aus dem Support (Policy oben; wann 1.28 erscheint, ist nicht verifiziert), dann wird dieser Audit wieder rot.
  Dafür schlägt der Chef eine eigene REL-Zeile „Go 1.27“ vor.
- **F2 (Kevin, sichtbares Verhalten): die `go`-Direktive in `apps/agent/go.mod` anheben?** Empfehlung **nein,
  `go 1.25.0` bleibt.** Die Sicherheit kommt von der Toolchain, mit der CI und Release bauen. Mit 1.25.0 bleiben die
  GODEBUG-Defaults (TLS-Schlüsselaustausch, URL-Parser, crypto-Zufall) wie heute, gegenüber Gateway und Server
  ändert sich nichts. Wer den Agent selbst baut, braucht kein neueres Go. Trade-off: Ein Selbstbau mit Go 1.25.x
  trägt die neun Lücken weiter; T3 schreibt deshalb in die Doku, dass mit 1.26.9 oder neuer gebaut wird. Die
  Alternative `go 1.26.9` wäre eine harte Untergrenze: unter `GOTOOLCHAIN=local` bricht jeder CI-Build mit einem
  veralteten Toolcache-Go laut ab, das erledigte F3 gleich mit. Sie ändert aber die GODEBUG-Defaults und die
  Mindestversion für Selbstbauer. Nur auf Kevins Wort; dann bekäme T1 die go.mod-Zeile und agent.html:55 DE+EN.
- **F3 (Chef, Umsetzungsweg; Kevin sieht es beim Merge): wie kommt CI an 1.26.9 oder neuer, solange der Toolcache
  1.26.8 hält?** Plan: `check-latest: true` an allen vier setup-go-Stellen (T1), und der Lockstep verlangt es (T2).
  Restrisiko, oben belegt: Fällt der Manifest-Abruf aus, nimmt setup-go still den Cache. Alternative: Patch-Pin
  `go-version: "1.26.9"`. Der ist deterministisch, scheitert laut und passt zur Pin-Kultur (bootstrap pinnt Patch
  und SHA). Aber toolchain-lockstep.sh lehnt heute alles außer MAJOR.MINOR ab (:77–86, Test :149–156), und jeder
  Go-Sicherheits-Patch würde ein Gate-PR für Kevin. Empfehlung `check-latest`. T2 kann der Chef streichen (`[~]`),
  wenn ihm die Prüfung zu viel ist.
- **F4 (Handgriff Chef, vor T3): die Dev-Box-Go `~/sdk/go` von go1.25.14 auf go1.26.9 tauschen.** DEVELOPMENT.md
  :1349–1352 verlangt dieselbe Minor wie CI („Tarball-Swap unter `~/sdk/go`“). Das wirkt für jede Session unter
  Kevins UID. Andere Worktrees bauen weiter, weil go.mod bei 1.25.0 bleibt. Empfehlung: Der Chef tauscht direkt vor
  T3, wenn kein anderer Bau gerade Agent-Tasks fährt. Der alte Baum bleibt als `~/sdk/go-1.25.14` liegen
  (Rückweg). Danach `GOTOOLCHAIN=local go install golang.org/x/vuln/cmd/govulncheck@v1.9.0`. Im Builder-Profil
  (eigenes HOME) vorher `go version` dort prüfen, wo gebaut wird.

### T1 — Workflows auf Go 1.26 mit `check-latest`, govulncheck v1.9.0  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, .github/workflows/release.yml, .github/workflows/audit.yml, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 8 ok @551185df 2026-10-13T13:08:11+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `go-version: "1.25"` wird `"1.26"` an allen vier Stellen (ci.yml:358, :398, release.yml:99, audit.yml:72). Jede
  bekommt im selben `with:`-Block `check-latest: true`. Einmal je Datei sagt ein Kommentar warum: Der Toolcache des
  Images hält einen älteren Patch (20261004: 1.26.8), der Fix ist 1.26.9.
- audit.yml:81 `govulncheck@v1.7.0` wird `@v1.9.0`. Der Kommentar :75–80 wird neu gefasst: v1.9.0 verlangt
  `go 1.26.0`, baut also auf 1.26; gehoben wird es zusammen mit `go-version`.
- Der oasdiff-Kommentar ci.yml:727–731 und der oasdiff-Absatz cicd.html:396–398 / EN :389–391 behaupten nicht mehr,
  die Workflows pinnten Go 1.25. Das Tarball bleibt, weil es keine Toolchain braucht und die SHA-256 der Pin ist.
- CHANGELOG `[Unreleased]`, Abschnitt Security: Agent und Audit laufen auf Go 1.26 (1.26.9 oder neuer). Das schließt
  die neun stdlib-Funde aus go1.25.14 (GO-2026-6603 … -6617; net/http, net/textproto, crypto/tls). govulncheck v1.9.0.
Rot vorher: Lauf 38269130931 (s. Beweis). Auf main meldet `bash scripts/dev/toolchain-lockstep.sh` „go-version: ci=1.25
ci=1.25 release=1.25 audit=1.25“ — grün, aber auf einer Go-Version ohne Fix.
Beweis: main@2ebdef55, `gh run view 38269130931 --log-failed` → Job „govulncheck (agent)“: „Your code is affected by 9
vulnerabilities from the Go standard library.“, je „Fixed in: …@go1.26.9“, „Process completed with exit code 3.“;
lokal nachgestellt auf origin/main@c37d4198 unter go1.25.14 mit govulncheck v1.7.0: dieselben neun, rc 3.
Orakel: analyzer — govulncheck im Source-Modus, die stdlib zählt mit der Version des `go` im PATH
Dedup-Key: rel:agent:go-toolchain:1.26
HEAD: c37d4198
Semantik: DEVELOPMENT.md:1312 „`audit.yml` faehrt den woechentlichen CVE-Sweep in CI.“; docs/developer/cicd.html:40
„jede go-version-Stelle in ci.yml/release.yml/audit.yml muss dieselbe sein, und die go-Direktive des in audit.yml
gepinnten govulncheck-Release darf nicht darüber liegen“.
Verify: bash scripts/dev/verify.sh scripts --strict  und bash scripts/dev/toolchain-lockstep.sh → „toolchain-lockstep: ok (go 1.26 <= 1.26)“ (braucht den Modul-Proxy; 75 = nicht geprüft)
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (oasdiff-Absatz), CHANGELOG

### T2 — Lockstep verlangt `check-latest: true` an jeder `go-version`-Stelle  [ ]
Komponente: scripts · Dateien: scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md, CHANGELOG.md
Änderung:
- toolchain-lockstep.sh bekommt eine Offline-Prüfung neben Prüfung 1 (:68–100), vor dem Proxy-Abruf wie die
  ruff-Prüfung. Jeder `with:`-Block in ci.yml, release.yml und audit.yml, der `go-version:` setzt, trägt auch
  `check-latest: true`, Reihenfolge im Block egal. Sonst kommt eine `::error::`-Zeile mit Datei und Grund
  (ohne `check-latest` nimmt setup-go den Patch aus dem Toolcache, der Release kann einen anderen stdlib-Stand
  ausliefern, als der Audit prüft), Exit 1. Der Kopfkommentar nennt die Prüfung. Die Meldung :85 verliert ihr
  „today "1.25"“.
- toolchain_lockstep_test.sh:
  - `fixture` (:50–66) schreibt zu jeder `go-version:`-Zeile `check-latest: true`. Die Go-Versionen der Fixtures
    bleiben 1.25, kein bestehender Fall ändert seinen Sollwert.
  - Neue Fälle am Dateiende: release.yml ohne `check-latest` → Exit 1, die Meldung nennt release.yml; nur der zweite
    `go-version`-Block in ci.yml ohne `check-latest` (wie der Fall „one of ci.yml's two jobs bumped“) → Exit 1;
    `check-latest: false` → Exit 1.
  - Der bestehende Fall über den echten Baum (:226–230) prüft damit die echten Workflows aus T1 offline mit.
- cicd.html:40 DE+EN und DEVELOPMENT.md :1352–1356 (Lockstep-Absatz): ein Satz zu `check-latest`.
- CHANGELOG: der Eintrag aus T1 nennt die neue Prüfung.
Rot vorher: Auf main geht ein Fixture mit `go-version`, aber ohne `check-latest` mit Exit 0 durch. Der neue Fall
„release.yml ohne check-latest“ ist auf main rot.
Beweis: origin/main@c37d4198, toolchain-lockstep.sh :68–100 liest nur `go-version:`; `grep -n check-latest
.github/workflows/*.yml` ist leer.
Dedup-Key: rel:agent:go-toolchain:1.26
HEAD: c37d4198
Semantik: docs/developer/cicd.html:40 wie T1, dazu audit.yml:78–79 „the version release.yml ships the agent with, so
the scan keeps reporting against the stdlib we actually publish“ (Workflow-Kommentar, nicht docs/).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html, DEVELOPMENT.md, CHANGELOG
Abhängt von: T1

### T3 — Test-Boxen und Doku auf Go 1.26.9; Beweis: govulncheck sauber  [ ]
Komponente: agent · Dateien: scripts/vm/bootstrap_linux.sh, DEVELOPMENT.md, docs/developer/index.html, docs/en/developer/index.html, CHANGELOG.md
Vorbedingung: F4 erledigt. `go version` im Bau-Terminal (nach `source .devenv.sh`) meldet go1.26.9 oder neuer,
govulncheck v1.9.0 liegt in `~/go/bin`.
Änderung:
- bootstrap_linux.sh:19 `GO_VERSION` wird 1.26.9, :22 die SHA-256
  `42d158b4d8f7b61ac0a830567c940a86098fb7aac52e467a5ebec03ef5cc2f8d` (go.dev-JSON; beim Bau gegen
  https://go.dev/dl/?mode=json&include=all gegenprüfen). Der Kommentar :20–21 bleibt. Boxen aus einem Template mit
  1.25.0 installieren beim Bootstrap neu (:169–176); ein Rebake der Templates ist optional, nicht Teil des Ledgers.
- DEVELOPMENT.md:
  - :1272–1276: CI und Release bauen mit dem neuesten 1.26.x (mindestens 1.26.9), go.mod verlangt nur 1.25.
    Das Tarball-Beispiel wird `go1.26.x`. Die `apt install golang-go`-Zeile bleibt nur, wenn das Debian-Paket 1.26
    liefert (nicht verifiziert, beim Bau prüfen).
  - :326–328: die oasdiff-Begründung ohne „Go 1.25“.
  - :1322: `@v1.9.0`.
  - :1348–1351: „heute `1.26`“, lokal den neuesten Patch (1.26.9 oder neuer). Der Satz zur Bewertung wird richtig:
    govulncheck nimmt die Version des `go` im PATH (Zitat oben).
- docs/developer/index.html:56 und docs/en/developer/index.html:41: „Go 1.25“ wird „Go 1.26“. agent.html:55 bleibt
  (Direktive unverändert, F2).
- CHANGELOG: der Eintrag aus T1 nennt die Test-Boxen.
Rot vorher: Unter der Dev-Box-Go von main (go1.25.14) meldet `(cd apps/agent && govulncheck ./...)` die neun Funde,
rc 3. bootstrap_linux.sh installiert go1.25.0 auf jeder Box.
Beweis: origin/main@c37d4198, lokale Probe (Vorab geprüft): go1.26.9 + govulncheck v1.9.0 → „No vulnerabilities
found.“, rc 0. Nach dem Push (Chef) `gh workflow run audit.yml --ref harness/go-toolchain-126`: Job „govulncheck
(agent)“ `success`, im Log `go version go1.26.9` oder neuer. Lauf-ID in den PR-Text.
Dedup-Key: rel:agent:go-toolchain:1.26
HEAD: c37d4198
Semantik: DEVELOPMENT.md:1349–1351 „Die Dev-Box muss deshalb dieselbe Minor fahren wie `go-version` in den Workflows
(heute `1.25`), sonst weicht der lokale Befund von CI ab.“
Verify: bash scripts/dev/verify.sh agent scripts --strict  und (cd apps/agent && govulncheck ./...) → „No vulnerabilities found.“ unter go1.26.9 oder neuer
Doku: DEVELOPMENT.md, docs/developer/index.html + docs/en/developer/index.html, CHANGELOG
Abhängt von: T1
