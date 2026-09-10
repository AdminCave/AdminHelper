<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 3 — Ausführung zuerst — Task-Ledger
Status: aktiv · Branch: feature/harness-stufe-3 · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/harness-stufe-3.md
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nach T14 zwei Läufe `tmux new -d -s ah-weekly 'bash scripts/tests/heavy.sh weekly'` (Session schließen, Report lesen) — ask-first, ≈ 17 VM-h je Lauf, acht VMs in der Spitze; vorher `crabbox list` leer, die Swap-Frage auf dem Proxmox-Host geklärt **und T7a entschieden** — sonst ist die Capstone-Ebene des Laufs per Konstruktion rot (Desktop-Etappe gegen ein enforced :443 ohne Client-Cert)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0003 (schließt R-0021, R-0022 ein) · Hängt ab von: R-0002 (gemergt, PR #11)
**Abweichung von `Commit-Granularität: pro Task` (T9–T13):** die fünf Tasks ändern dieselben zwei Dateien und sind ein Feature. Das Review von T9 hat den gemeinsamen Kern noch einmal deutlich bewegt (stale `last-all.json`, fail-open `crabbox list`, Infra-Marker der Wrapper, gebundener `doctor`, Artefakt-Sammlung); vier von Hand rekonstruierte Zwischenstände dieser Dateien synchron zu halten wäre danach mehr Fehlerquelle als Recovery-Gewinn — und ein Commit, dessen Suite ich in genau diesem Stand nicht real gefahren habe, wäre ein `[x]` ohne Beweis. Deshalb **ein** Commit für T9–T13. Reviewt wurde der T9-Schnitt; die späteren Anteile gehen in das Abschluss-`/code-review`.

Workflow-Änderungen an `release.yml` sind erst mit dem nächsten Tag real prüfbar; jede solche Task nennt deshalb eine lokale Probe (`act` ist nicht vorhanden) und die Stelle, an der der nächste Release-Lauf die Assertion zeigt.

### T1 — release.yml: Agent statisch, kein GLIBC-Symbol, .deb ohne zstd  [x] (Assert-Schritt + zstd-Guard in Collect artifacts; lokal grün/rot geprüft)
Komponente: .github · Dateien: .github/workflows/release.yml
Änderung: Job `agent`: Schritt „Assert static agent binary" nach dem Build (`file` enthält `statically linked`; `objdump -T` ohne `GLIBC_`; beide Ausgaben im Fehlerfall); in „Collect artifacts" `ar t dist/adminhelper-agent_*.deb` darf kein `.zst`-Member listen.
Verify: `python3 -c "import yaml;d=yaml.safe_load(open('.github/workflows/release.yml'));s=[x['name'] for x in d['jobs']['agent']['steps'] if 'name' in x];assert 'Assert static agent binary' in s"`; lokale Probe der Befehle gegen `make -C apps/agent build-linux` (`file`/`objdump`/`ar` auf dem Ergebnis, statisch ⇒ grün; `CGO_ENABLED=1 go build` ⇒ rot)
Doku: docs/developer/cicd.html DE+EN „Release-Assertionen" (T18)

### T2 — release.yml: Signatur gegen den gepinnten Public Key verifizieren  [x] (minisign -V gegen den Pin aus update.sh; Wegwerf-Key-Probe rot/grün/unarmed)
Komponente: .github · Dateien: .github/workflows/release.yml
Änderung: im Job `release` direkt nach `minisign -S`: `PUB=$(grep -m1 -o 'MINISIGN_PUBKEY="[^"]*"' scripts/update.sh | cut -d'"' -f2)`, `minisign -V -P "$PUB" -m release/SHA256SUMS` ⇒ Exit 1 bei Mismatch; Kommentar nennt den Grund (Secret ≠ gepinnter Key würde erst bei Nutzern auffallen).
Verify: lokale Probe: Wegwerf-Key, damit signieren, `minisign -V` gegen den Repo-Pubkey ⇒ rot; gegen den passenden Pubkey ⇒ grün; `python3 -c "import yaml;yaml.safe_load(open('.github/workflows/release.yml'))"`
Doku: docs/developer/cicd.html DE+EN „Release-Signatur" ein Satz (T18)

### T3 — release.yml: Job agent-windows-smoke (Tag-Version aus der .exe)  [x] (harter Job vor `release`; Shim-Probe match/mismatch/fehlende .exe rot-grün, `version`-Format gegen `make build-windows` gelesen)
Komponente: .github · Dateien: .github/workflows/release.yml
Änderung: neuer Job `agent-windows-smoke` (`windows-latest`, `needs: agent`, nur auf Tags, `timeout-minutes: 10`): Artefakt `agent` laden, `.\adminhelper-agent-windows-x86_64.exe version` ausführen, Ausgabe muss `${GITHUB_REF_NAME#v}` enthalten; hart; `release` bekommt ihn in `needs` und die `if`-Bedingung wie `agent`.
Verify: `python3 -c "import yaml;d=yaml.safe_load(open('.github/workflows/release.yml'));assert 'agent-windows-smoke' in d['jobs'] and 'agent-windows-smoke' in d['jobs']['release']['needs']"`; Probe: `GOOS=windows go build` lokal, `version`-Ausgabeformat aus `apps/agent/cmd` lesen und den Vergleich darauf ausrichten
Doku: docs/developer/cicd.html DE+EN Workflows-Tabelle (T18)

### T4 — release.yml: MSI installieren, prüfen, deinstallieren  [x] (Install/Assert/Uninstall nach „Collect artifacts", msi.log als eigenes Artefakt und aus `release/` ausgeschlossen; auf einem echten Runner unverifiziert — kein Windows/pwsh lokal)
Komponente: .github · Dateien: .github/workflows/release.yml
Änderung: Job `desktop-windows` nach „Build MSI": `msiexec /i <msi> /qn /norestart /l*v msi.log`; Assertion `Installation success or error status: 0` im Log und `adminhelper.exe` unter `%ProgramFiles%` (Pfad aus `tauri.conf.json` `productName` ableiten, im Kommentar als unverifiziert markieren); `msiexec /x <msi> /qn`; `msi.log` als Artefakt mit `if: always()`. `continue-on-error: true` bleibt (Spec Frage 5).
Verify: `python3 -c "import yaml;d=yaml.safe_load(open('.github/workflows/release.yml'));j=d['jobs']['desktop-windows'];assert j.get('continue-on-error') is True and any('msiexec' in str(x.get('run','')) for x in j['steps'])"`
Doku: docs/developer/cicd.html DE+EN (T18)

### T5 — go test -race im CI und in run.sh  [x] (Log-Zeile `race: on (-race)`/`race: off (no gcc)`; Evidenz: absichtliches Data-Race in internal/logging wird von `-race` als `WARNING: DATA RACE` gemeldet, ohne `-race` `ok` — Probe-Datei nicht committet)
Komponente: .github, scripts/tests · Dateien: .github/workflows/ci.yml, scripts/tests/run.sh
Änderung: Job `agent` in `ci.yml`: `go test -race -cover ./...`; `run.sh` Go-Step: `-race`, wenn `gcc` vorhanden (sonst wie heute plus Log-Zeile `race: off (kein gcc)`). Probe auf Wegwerf-Branch: ein absichtliches Data-Race in einem Test-Helfer wird von `-race` gemeldet (nicht committen, im Ledger als Evidenz notieren).
Verify: `bash scripts/dev/verify.sh agent --strict` grün; Log enthält `-race`; `python3 -c "import yaml;d=yaml.safe_load(open('.github/workflows/ci.yml'));assert any('-race' in str(x.get('run','')) for x in d['jobs']['agent']['steps'])"`
Doku: docs/developer/cicd.html DE+EN Test-Aggregator ein Satz (T18)

### T6 — check-versions.sh mit hermetischem Test, im Release-Workflow und in der Release-Rule  [x] (sechs Stellen, `ok`/`MISSING` — englisch statt `FEHLT`, Memory-Regel; Fund: die zwei mehrzeiligen Footer in docs/index.html + docs/en/index.html hingen seit 0.43.2 → Muster auf die Klasse umgestellt, Floor 38, Footer mitgebumpt, release.md Punkt 5 korrigiert; offene Frage T6a)
Komponente: scripts/release · Dateien: scripts/release/check-versions.sh (neu), scripts/tests/check_versions_test.sh (neu), .github/workflows/release.yml, .claude/rules/release.md
Änderung: Skript nach Spec (sechs Stellen, `ok`/`FEHLT` je Zeile, Exit 1); Test mit Fixture-Baum (alles richtig ⇒ 0; ein Footer alt ⇒ 1 mit Dateiname; CHANGELOG-Abschnitt fehlt ⇒ 1); `release.yml` Schritt „Verify the desktop version matches the tag" ruft `bash scripts/release/check-versions.sh "${GITHUB_REF_NAME#v}"`; `.claude/rules/release.md` nennt den Aufruf vor dem Tag; Test in die Liste des `scripts`-Blocks in `run.sh`. SPDX-Header.
Verify: `bash scripts/tests/check_versions_test.sh` → `N passed, 0 failed`; `bash scripts/release/check-versions.sh 0.45.0` → Exit 0 auf dem heutigen Stand; `bash scripts/release/check-versions.sh 0.46.0` → Exit 1 mit sechs `FEHLT`
Doku: .claude/rules/release.md (in der Task); DEVELOPMENT.md Release-Absatz (T18)
Abhängt von: —

### T6a — Prerelease-Tags und die sechs Versions-Stellen  [?]
Komponente: scripts/release · Dateien: scripts/release/check-versions.sh
Frage an Kevin: `check-versions.sh` vergleicht **verbatim**, ein Beta-Tag `v0.46.0-beta.1` verlangt diesen String also auch in 38 Doku-Footern, im CHANGELOG-Abschnitt `## [0.46.0-beta.1]` und in beiden News-Callouts. Der alte Inline-Schritt konnte bei einem Prerelease **nie** grün werden (`grep -o '[0-9][0-9.]*'` schnitt das Suffix ab, `$VER` behielt es) — das Gate wird also nicht gelockert, sondern Prereleases erstmals überhaupt möglich. Vorschlag: Stellen 1–3 (tauri/Cargo/Cargo.lock) bleiben verbatim, Stellen 4–6 (CHANGELOG, Footer, News) prüfen gegen `${VER%%-*}`. Vor dem ersten `beta`-Tag zu entscheiden (CLAUDE.md §2 sieht `beta` nach jedem grünen Wochenlauf vor).

### T7 — crabbox_multibox.sh: --capstone mit enforce, vier stille Skips gezählt, Null-Agents rot  [x] (`--capstone` setzt ENFORCE=1; vier Zweige über `skipped()`; Report-Erwartung mit Floor 1; realer Lauf steht in der Heavy-Zeile aus)
Komponente: scripts/tests · Dateien: scripts/tests/crabbox_multibox.sh, scripts/tests/crabbox_serverbox.sh, .claude/rules/release.md, .claude/rules/testing.md
Änderung: `--capstone` setzt `ENFORCE=1` (R-0022); die vier stillen Skips (Agent-Repo/CA-Flip ohne `REPO_FP`, Desktop-Lease, moncheck-Lease, `--enforce`-Zweig) laufen über `skipped()` und damit unter `--strict` rot (R-0021); die Monitoring-Assertion verlangt `erreichte Agents ≥ 1`, nicht `≥ 0`. Header und `/test`-Skill-Zeile zu `--capstone` nachziehen.
Verify: `shellcheck --severity=warning scripts/tests/crabbox_multibox.sh` leer; `grep -c 'skipped ' scripts/tests/crabbox_multibox.sh` ≥ 5; `grep -n 'ENFORCE=1' scripts/tests/crabbox_multibox.sh` zeigt den `--capstone`-Zweig; realer Lauf in der Heavy-Zeile
Doku: .claude/skills/test/SKILL.md (T16)

### T7a — `--capstone` erzwingt enforce, die Desktop-Etappe kann das nicht  [?]
Komponente: scripts/tests · Dateien: scripts/tests/crabbox_serverbox.sh, scripts/tests/crabbox_desktopbox.sh, scripts/tests/crabbox_multibox.sh
Befund (statisch belegt, kein Lauf nötig): `--capstone` setzt seit T7 `DESKTOP=1` **und** `ENFORCE=1`. `ENFORCE=1` → `crabbox_serverbox.sh:35` `MTLS_ENFORCE=true` → `apps/gateway/docker-entrypoint.sh:39` `ssl_verify_client on` auf :443. `crabbox_desktopbox.sh:16` fährt default `server-crud.live.js` + `monitoring-check.live.js`; beide beginnen mit `login()` über :443, die Box ist frisch (eigenes `XDG_DATA_HOME`, leerer Keyring) und enrollt nirgends — `enrollment::enroll` ist JWT-gated, also erst *nach* dem Login. Die S3-Etappe ist im Capstone damit **strukturell** rot, nicht „beim ersten Lauf vielleicht". Alle Desktop-Suiten laufen bis heute mit `e2e_init false`; Desktop + enforce ist nie gelaufen. Spec-Frage 4 deckt das nicht ab — freigegeben war „der Enforce-Guard kann beim ersten Lauf rot sein", nicht eine dauerhaft rote GUI-Etappe.
Frage an Kevin — eine von drei, vor dem ersten Capstone-Lauf (sonst kostet der Befund 17 VM-h):
(a) **enforce-tauglich machen:** serverbox mintet unter `DO_ENFORCE=1` ein zweites Enroll-Token und gibt es als Marker aus, `crabbox_desktopbox.sh` enrollt damit vor den Specs (Muster: `tunnel-connect.live.js:21-25`). Meiste Arbeit, deckt am meisten ab.
(b) **Capstone-Zusammensetzung ändern:** `--enforce` nicht zusammen mit `--desktop` (eine `.env`, ein Gateway — anders nicht trennbar); kostet S3 oder den Guard.
(c) **rote Desktop-Etappe bewusst hinnehmen** — dann muss `.claude/rules/release.md` das ausdrücklich sagen, sonst widerspricht sich das Gate selbst.
Bis dahin gilt: `crabbox_multibox.sh --capstone --strict` ist **nicht** grün erreichbar.

### T8 — desktop_e2e_misc.sh für die fünf verwaisten Specs  [x] (fünf verwaiste Specs, je eine `spec <name>: pass|fail`-Zeile, AH_SPEC wählt eine; run.sh brauchte nichts — layer_e2e globbt `desktop_e2e_*.sh`, desktop_e2e_skip_test zählt jetzt 8)
Komponente: scripts/tests · Dateien: scripts/tests/desktop_e2e_misc.sh (neu), scripts/tests/run.sh
Änderung: Aufbau wie `desktop_e2e_live.sh` (e2e-Stack, `e2e_require`, Exit 75); fährt `login-error`, `logout`, `monitoring-alerts`, `connection-editor`, `theme-toggle` nacheinander (`AH_SPEC` wählt einen), Zeile `spec <name>: pass|fail` je Spec, Exit 1 bei einem Fail; Aufnahme in die e2e-Liste von `run.sh`. Ein Spec, der eine im Stack fehlende Voraussetzung braucht, wird `[?]` im Ledger, nicht verbogen. SPDX-Header.
Verify: `shellcheck --severity=warning scripts/tests/desktop_e2e_misc.sh` leer; `bash scripts/tests/desktop_e2e_skip_test.sh` zählt jetzt 8 Skripte (Liste aus dem Verzeichnis) → `8 passed`; realer Lauf im Heavy-`all`
Doku: keine (intern)

### T9 — heavy.sh: all, capstone, weekly, Report, history.csv  [x] (Wrapper mit Vorab-Check, Report, history.csv, privatem Commit; heavy_test 32 passed, 0 failed)
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh (neu), scripts/tests/heavy_test.sh (neu)
Änderung: Entrypoint nach Spec: Vorab-Check (`crabbox doctor`, `crabbox list` ohne fremde Boxen, sonst 74), `all` über `crabbox_warm.sh desktop` + `crabbox_iter.sh all --strict`, `capstone` über `crabbox_multibox.sh --capstone --strict`, `weekly` seriell; `$AH_OUT_DIR/weekly/<stempel>/report.md` mit Kopfzeile `PASS|FAIL|UNVERIFIED (<grund>)`, Summary-Zeilen wörtlich, VM-Liste danach; `history.csv` (Schema aus der Spec) je Schritt aus `last-all.json` plus Ebenen-Zeile; Commit im privaten Repo, falls vorhanden; Exit 0/1/74. Test: Shims für `crabbox`, `crabbox_warm.sh`, `crabbox_iter.sh`, `crabbox_multibox.sh` (Fixtures liefern `last-all.json` und Summary-Zeilen), prüft Report-Kopf, wörtliche Summary, `history.csv`-Zeilen, Exit 74 bei fremder Box. SPDX-Header.
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed`; `bash scripts/tests/heavy.sh` ohne Argument → Usage, Exit 2; `shellcheck --severity=warning scripts/tests/heavy.sh` leer
Doku: DEVELOPMENT.md (T18)
Abhängt von: T7

### T10 — heavy.sh: Klassifikation INFRA und FLAKY (Wiederholung auf derselben Box)  [x] (INFRA endet die Ebene ohne Retry; bis 3 Wiederholungen mit AH_NO_SYNC=1, Desktop-Suiten spec-genau; heavy_test 48 passed, 0 failed — `kandidat` ist hier noch Endzustand, T11 löst ihn auf)
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: Exit 74 oder `strict-failed: <step> (SKIP)` ⇒ `infra` + Kopf `UNVERIFIED`; rote Schritte bis 3× per `crabbox_iter.sh all --strict --step <name>` mit `AH_NO_SYNC=1` (Desktop-Suiten spec-genau über `AH_SPEC`); ein grüner Rerun ⇒ `flaky` in `history.csv` + Zeile in `tasks/private/seen.md` (`quarantine · <schritt> · <datum> · <zähler> · Ablauf +30 d`); 3× identisch rot (gleicher erster Fehlermarker) ⇒ `kandidat`. Test: Fixture-Sequenzen rot/grün/…, rot/rot/rot, 74.
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed` (Fälle infra, flaky, kandidat enthalten)
Doku: keine (T18)
Abhängt von: T9

### T11 — heavy.sh: zweite VM und Gegenprobe gegen den letzten PASS  [x] (Worktree w2 in eigener Lane, Gegenprobe gegen den letzten PASS; unbestaetigt/reg/extern; heavy_test 62 passed, 0 failed)
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: für `kandidat`: Worktree `.crabbox-worktrees/w2` auf HEAD, `AH_LANE=w2 crabbox_warm.sh desktop`, Schritt dort einmal (`unbestätigt` bei grün); dann `--base <sha>` (Default: jüngste `history.csv`-Zeile `ebene=all,ergebnis=pass`; ohne PASS ⇒ `unbestätigt`) im Worktree auschecken, Schritt erneut: Basis grün ⇒ `reg`, Basis rot ⇒ `extern`; `--no-second-vm` überspringt (Kandidat bleibt `unbestätigt`); Aufräumen `crabbox_reap.sh --pond ah-warm-w2` + `git worktree remove`. Test: Fixtures für unbestätigt/reg/extern, Worktree-Anlage und -Abbau im Fixture-Repo.
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed` (Fälle unbestätigt, reg, extern, kein-PASS); `git worktree list` nach dem Test ohne `w2`
Doku: keine (T18)
Abhängt von: T10

### T12 — heavy.sh: REG-Ausgabe als Roadmap-Zeile und Kurz-Ledger, Dedup  [x] (Roadmap-Zeile + reg-Ledger + Dedup über seen.md, audit.yml-Zeile im Report; heavy_test 81 passed, 0 failed)
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: `reg` ⇒ Zeile unter „Neu" in `tasks/private/ROADMAP.md` (nächste freie `R-nnnn`, Klasse REG, Quelle `weekly <datum> · <commit> · Zweit-VM rot · Basis <sha> grün`, Ablauf `nie`; `.bak` vorher) und `tasks/reg-<datum>-<schritt>.md` (`Status: geplant`, `Komponente:`, Verify in Flag-Form, Beweis-Absatz); Dedup gleicher Schritt + gleiche Fehlerzeile in 30 Tagen ⇒ nur `history.csv`; `audit.yml`-Zeile per anonymer GitHub-API in den Report, `failure` ⇒ REL-Zeile `deps-audit` mit Run-Datum als Dedup. Test: Roadmap-Fixture, Zeilenzahl +1, Dedup schreibt nicht doppelt, Ledger-Datei existiert mit `Status: geplant`.
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed` (Fälle reg-Zeile, dedup, audit-failure)
Doku: tasks/README.md ein Satz zu `reg-*`-Ledgern
Abhängt von: T11

### T13 — heavy.sh: --notify (Default aus)  [x] (--notify an AH_NOTIFY_URL, Default aus, fehlgeschlagener POST ist kein Laufsfehler; heavy_test 89 passed, 0 failed)
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: `--notify` postet die Kopfzeile plus Pfad des Reports per `curl -m 10` an `AH_NOTIFY_URL` (aus `.devenv.sh`); ohne URL: Hinweis, kein Fehler. Test mit `curl`-Shim.
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed` (Fall notify)
Doku: DEVELOPMENT.md (T18)
Abhängt von: T9

### T14 — Hook: Wochenlauf-Zeile aus dem jüngsten Report  [x] (Zeile 4 aus dem jüngsten report.md, sonst `kein Report`; session_status_test 45 passed, 0 failed — Fallback auf den jüngsten Report MIT Urteil, nicht auf das jüngste Verzeichnis)
Komponente: scripts/dev · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh
Änderung: Zeile 4 `Wochenlauf: <datum> (<n> d): PASS|FAIL|UNVERIFIED` aus dem jüngsten `$AH_OUT_DIR/weekly/*/report.md`, sonst `kein Report`; Test-Fixture mit zwei Reports (jüngster zählt).
Verify: `bash scripts/tests/session_status_test.sh` → `N passed, 0 failed`; `bash scripts/dev/hooks/session-status.sh | grep -c 'Wochenlauf:'` → 1
Doku: DEVELOPMENT.md Hook-Absatz ein Satz (T18)

### T15 — upgrade_path_test.sh (Integration-Layer)  [ ]
Komponente: scripts/tests · Dateien: scripts/tests/upgrade_path_test.sh (neu), scripts/tests/run.sh
Änderung: nach Spec 3c: Vorgänger-Tag per anonymer API, Stack aus `ghcr.io/admincave/*:<tag>` mit Compose-Override, Seeds über `e2e_api.py`, Wechsel auf Checkout-Images (`adminhelper-test/*`, Bau wie `integration_stack_test.sh`), Assertion Seeds lesbar + neuer Agent-Report; Schritt 4 `scripts/update.sh --ref <tag>` gegen einen zweiten Stack im Vorgänger-Stand (eigene Marker, 75 ohne Runtime-Bundle). Dep-gated (Docker, Netz), Exit 75 ohne Voraussetzung; Aufnahme in `layer_integration`; Required-Menge: nur auf der Box (`AH_REQUIRED_DEFAULT` unverändert, Box-Profil setzt ihn). SPDX-Header.
Verify: `shellcheck --severity=warning scripts/tests/upgrade_path_test.sh` leer; `PATH=/usr/bin:/bin bash scripts/tests/upgrade_path_test.sh; echo $?` ohne Docker → `75`; realer Lauf im Heavy-`all` mit Marker `UPGRADE_OK` und `UPDATE_SH_OK|UPDATE_SH_SKIP`
Doku: docs/developer/cicd.html DE+EN Test-Aggregator (T18)

### T16 — /test-Skill neu geschrieben  [ ]
Komponente: .claude/skills · Dateien: .claude/skills/test/SKILL.md
Änderung: Struktur nach Spec: `quick` = `bash scripts/dev/verify.sh all --strict`; `all|capstone|weekly` drucken den `tmux`-Startbefehl (`tmux new -d -s ah-weekly 'bash scripts/tests/heavy.sh weekly'`) und enden; `status` liest den jüngsten Report; Klassifikations-Tabelle in Kurzform; Leak-Regel (`crabbox list` nach jedem Lauf), Zweit-VM-Regel, Rhythmus-Empfehlung; Warm-Loop und Pitfalls bleiben, `--capstone` inkl. enforce.
Verify: `grep -c 'heavy.sh' .claude/skills/test/SKILL.md` ≥ 3; `grep -n 'tmux new -d -s ah-weekly' .claude/skills/test/SKILL.md` → 1; keine Zeile empfiehlt `crabbox stop` nach jedem Lauf
Doku: ist der Skill
Abhängt von: T9

### T17 — CHANGELOG, DEVELOPMENT.md, tasks/README  [ ]
Komponente: Repo-Root · Dateien: CHANGELOG.md, DEVELOPMENT.md, tasks/README.md
Änderung: CHANGELOG Unreleased „Changed" (Release-Assertionen, `-race`, `check-versions.sh`, Wochenlauf mit Klassifikation, Upgrade-Pfad, fünf Specs); DEVELOPMENT.md Abschnitte „Wochenlauf (heavy.sh)" (Start, Report, history.csv, Exit-Codes, `AH_NOTIFY_URL`), Release-Absatz um `check-versions.sh`; tasks/README „Aktueller Stand" und `reg-*`-Ledger.
Verify: `grep -c 'heavy.sh' DEVELOPMENT.md` ≥ 2; `grep -c 'check-versions' DEVELOPMENT.md CHANGELOG.md` je ≥ 1
Doku: ist die Doku
Abhängt von: T9, T15

### T18 — Doku cicd.html DE+EN  [ ]
Komponente: docs · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: Abschnitte „Release-Assertionen" (statisch, zstd, Signatur-Verify, Windows-Smoke, MSI, Versions-Check) und „Wochenlauf (heavy.sh)" mit Klassifikationstabelle (INFRA, FLAKY, unbestätigt, extern, REG), Exit-Codes, `history.csv`, Report-Aufbau; Workflows-Tabelle um `agent-windows-smoke`; Test-Aggregator um `-race` und `upgrade_path_test.sh`; Release-Checkliste um `check-versions.sh`. Beide Sprachen gleichlautend.
Verify: `grep -c 'heavy.sh' docs/developer/cicd.html docs/en/developer/cicd.html` je ≥ 2; `grep -c 'check-versions' docs/developer/cicd.html docs/en/developer/cicd.html` je ≥ 1
Doku: ist die Doku
Abhängt von: T1, T2, T3, T4, T5, T6, T9, T15
